"""Hybrid retrieval acceptance tests.

The key claim: an exact identifier that appears once (an env var name, a port) lands
in the top results in hybrid mode even when the vector leg misses it. FakeProvider's
hash-based embeddings guarantee the vector leg carries no real semantics, which makes
it the perfect stand-in for "vector search missed the identifier".
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grimoire.providers import get_provider
from grimoire.service import KnowledgeService
from grimoire.store import Repository


def _ingest_text(service: KnowledgeService, tmp_path: Path, title: str, text: str, project: str):
    p = tmp_path / f"{title.replace(' ', '-')}.md"
    p.write_text(text)
    service.ingest_document(str(p), project=project, title=title)


@pytest.fixture
def svc(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    provider = get_provider("fake")
    service = KnowledgeService(repo, provider)
    repo.upsert_project("Demo")
    # a haystack of filler chunks plus one carrying a unique identifier
    for i in range(8):
        _ingest_text(service, tmp_path, f"filler {i}",
                     f"General notes about the project, part {i}. Nothing special here.", "Demo")
    _ingest_text(service, tmp_path, "deploy notes",
                 "Deployment uses the GRIMOIRE_SPECIAL_TOKEN_XYZ environment variable on port 8731.",
                 "Demo")
    yield service
    repo.close()


def test_exact_identifier_hits_top3_in_hybrid(svc: KnowledgeService):
    hits = svc.retrieve("GRIMOIRE_SPECIAL_TOKEN_XYZ", k=10, mode="hybrid")
    top3 = [h["title"] for h in hits[:3]]
    assert "deploy notes" in top3


def test_keyword_mode_needs_no_embeddings(svc: KnowledgeService):
    svc.provider = None  # embedding provider gone entirely
    hits = svc.retrieve("GRIMOIRE_SPECIAL_TOKEN_XYZ", k=5, mode="keyword")
    assert hits and hits[0]["title"] == "deploy notes"


def test_vector_mode_reproduces_old_behaviour(svc: KnowledgeService):
    """Old path: similarity x recency over all candidate chunks, sorted desc."""
    from datetime import datetime, timezone

    from grimoire.service import recency_decay

    q_emb = svc.provider.embed_query("anything at all")
    rows = svc.repo.scored_chunks(q_emb, node_ids=None)
    now = datetime.now(timezone.utc)
    expected = sorted(
        ((1.0 - float(r["distance"])) * recency_decay(r["updated_at"], now), r["chunk_id"])
        for r in rows
    )
    expected_ids = [cid for _, cid in sorted(expected, reverse=True)][:5]
    got = [h["chunk_id"] for h in svc.retrieve("anything at all", k=5, mode="vector")]
    assert got == expected_ids


def test_hybrid_respects_project_scope(svc: KnowledgeService, tmp_path: Path):
    svc.repo.upsert_project("Other")
    _ingest_text(svc, tmp_path, "other notes",
                 "GRIMOIRE_SPECIAL_TOKEN_XYZ also appears in another realm.", "Other")
    hits = svc.retrieve("GRIMOIRE_SPECIAL_TOKEN_XYZ", project="Other", k=10, mode="hybrid")
    assert {h["title"] for h in hits} <= {"other notes", "Other"}


def test_unknown_mode_rejected(svc: KnowledgeService):
    with pytest.raises(ValueError):
        svc.retrieve("query", mode="psychic")


def test_fts_backfill_for_existing_store(tmp_path: Path):
    """A store whose chunks predate the FTS table gets rebuilt on open."""
    db = tmp_path / "g.db"
    repo = Repository(db)
    provider = get_provider("fake")
    service = KnowledgeService(repo, provider)
    repo.upsert_project("Demo")
    _ingest_text(service, tmp_path, "doc", "The UNIQUE_BACKFILL_MARKER lives here.", "Demo")
    # simulate a pre-FTS store: drop the index and its triggers outright
    repo._conn.executescript(
        "DROP TRIGGER chunks_fts_insert; DROP TRIGGER chunks_fts_delete;"
        " DROP TRIGGER chunks_fts_update; DROP TABLE chunk_fts;"
    )
    repo.close()

    repo = Repository(db)  # reopen: schema recreates the table, migration rebuilds it
    try:
        rows = repo.keyword_chunks("UNIQUE_BACKFILL_MARKER")
        assert rows and rows[0]["title"] == "doc"
    finally:
        repo.close()
