"""Phase 1 acceptance tests.

Covers: ingest_document, retrieve (project scoping), the entity supernode cap,
recency_decay, and chunk_text. All tests use FakeProvider (offline, deterministic)
and per-test temp databases via pytest's tmp_path fixture.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from grimoire.providers import get_provider
from grimoire.service import KnowledgeService, chunk_text, recency_decay
from grimoire.store import Repository


@pytest.fixture
def provider():
    return get_provider("fake")


# ---------------------------------------------------------------------------
# 1. ingest_document
# ---------------------------------------------------------------------------

def test_ingest_document(tmp_path: Path, provider):
    doc_path = tmp_path / "notes.md"
    doc_path.write_text(
        "# Introduction\n\nThis is the first paragraph about the project.\n\n"
        "## Details\n\nHere is some more information in the second paragraph.\n\n"
        "## Conclusion\n\nFinal thoughts wrap up the document nicely.\n"
    )

    repo = Repository(tmp_path / "g.db")
    try:
        repo.upsert_project("Demo")
        svc = KnowledgeService(repo, provider)
        result = svc.ingest_document(str(doc_path), project="Demo")

        # a document node was created
        node = repo.get_node(result["node_id"])
        assert node is not None
        assert node["type"] == "document"

        # at least one chunk was stored
        assert repo.counts()["chunks"] > 0

        # the document appears in the project's linked nodes
        proj = repo.get_project("Demo")
        linked_ids = {n["id"] for n in proj["linked"]}
        assert result["node_id"] in linked_ids
    finally:
        repo.close()


# ---------------------------------------------------------------------------
# 2. retrieve is project-scoped
# ---------------------------------------------------------------------------

def test_retrieve_is_project_scoped(tmp_path: Path, provider):
    doc_a = tmp_path / "doc_a.md"
    doc_a.write_text(
        "# Alpha content\n\nThis document belongs exclusively to project A.\n\n"
        "More alpha details here.\n"
    )
    doc_b = tmp_path / "doc_b.md"
    doc_b.write_text(
        "# Beta content\n\nThis document belongs exclusively to project B.\n\n"
        "More beta details here.\n"
    )

    repo = Repository(tmp_path / "g.db")
    try:
        repo.upsert_project("A")
        repo.upsert_project("B")
        svc = KnowledgeService(repo, provider)

        result_a = svc.ingest_document(str(doc_a), project="A")
        result_b = svc.ingest_document(str(doc_b), project="B")

        b_node_id = result_b["node_id"]

        hits = svc.retrieve("anything", project="A")
        hit_node_ids = {h["node_id"] for h in hits}
        assert b_node_id not in hit_node_ids, "project B's node must not appear in project A's results"
    finally:
        repo.close()


# ---------------------------------------------------------------------------
# 3. entity supernode cap
# ---------------------------------------------------------------------------

def test_entity_supernode_cap(tmp_path: Path, provider):
    repo = Repository(tmp_path / "g.db")
    try:
        repo.upsert_project("Alpha")
        repo.upsert_project("Beta")
        svc = KnowledgeService(repo, provider)

        alpha_mem_id = repo.write_memory(
            project="Alpha",
            summary="alpha work",
            entities=["Shared API"],
            summary_embedding=provider.embed("alpha work"),
        )
        beta_mem_id = repo.write_memory(
            project="Beta",
            summary="beta work",
            entities=["Shared API"],
            summary_embedding=provider.embed("beta work"),
        )

        # exactly one entity node named "Shared API"
        entities = repo.list_nodes(type="entity")
        assert len(entities) == 1
        entity_id = entities[0]["id"]

        alpha_proj = repo.get_project("Alpha")
        alpha_id = alpha_proj["id"]

        cand = repo.candidate_node_ids(alpha_id)

        # alpha's own memory and the shared entity are reachable
        assert alpha_mem_id in cand, "alpha's memory must be in candidates"
        assert entity_id in cand, "shared entity must be in candidates"

        # traversal must not cross through the entity into Beta's memory
        assert beta_mem_id not in cand, "beta's memory must NOT be reachable from alpha"

        # service-level: retrieve from Alpha must not surface Beta's chunk
        hits = svc.retrieve("work", project="Alpha")
        hit_node_ids = {h["node_id"] for h in hits}
        assert beta_mem_id not in hit_node_ids, "beta memory node must not appear in alpha retrieve"
    finally:
        repo.close()


# ---------------------------------------------------------------------------
# 4. recency_decay
# ---------------------------------------------------------------------------

def test_recency_decay():
    now = datetime.now(timezone.utc)
    recent = now.isoformat()
    old = (now - timedelta(days=200)).isoformat()
    ninety_days_ago = (now - timedelta(days=90)).isoformat()

    assert recency_decay(recent) > recency_decay(old)
    assert abs(recency_decay(recent) - 1.0) < 0.01  # effectively 1.0 for age~0

    # 90-day half-life: decay at 90 days should be ~0.5
    assert abs(recency_decay(ninety_days_ago) - 0.5) < 0.05


# ---------------------------------------------------------------------------
# 5. chunk_text
# ---------------------------------------------------------------------------

def test_chunk_text():
    # build a long text of many paragraphs well above the default target
    paragraphs = [f"Paragraph number {i}. " + ("Word " * 80) for i in range(30)]
    text = "\n\n".join(paragraphs)

    from grimoire.service import CHUNK_CHARS

    chunks = chunk_text(text)
    assert len(chunks) > 1, "long text must produce multiple chunks"
    # allow a small margin for the overlap carry-over
    for chunk in chunks:
        assert len(chunk) <= CHUNK_CHARS + 300, f"chunk too long: {len(chunk)}"


# ---------------------------------------------------------------------------
# 6. delete_node (cascade)
# ---------------------------------------------------------------------------

def test_delete_node_cascades(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        pid = repo.upsert_project("Proj")
        mem = repo.add_node("memory", "a chronicle", status="unreviewed")
        repo.link_nodes(mem, pid, "belongs_to")
        repo.add_chunk(mem, 0, "body", [0.0] * repo.embed_dim)

        before = repo.counts()
        assert before["nodes"] >= 2 and before["chunks"] == 1 and before["edges"] == 1

        assert repo.delete_node(mem) == 1
        assert repo.get_node(mem) is None

        after = repo.counts()
        assert after["chunks"] == 0          # chunks gone
        assert after["chunk_vectors"] == 0   # vectors gone
        assert after["edges"] == 0           # the belongs_to edge gone
        assert repo.get_project("Proj") is not None  # the project survives

        assert repo.delete_node(mem) == 0    # idempotent: already gone
    finally:
        repo.close()
