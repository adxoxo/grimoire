"""Ops-hardening acceptance tests (Phase 9.2/9.3).

Covers: gateway kb_* tools dispatch and return well-formed payloads (FakeProvider),
distillation writes the expected entities, compaction never loses data (originals
archived not deleted, counts reconcile, idempotent), and the bearer guard on
write-capable API routes.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from grimoire.compaction import compact_project
from grimoire.config import settings
from grimoire.distill import capture_session
from grimoire.providers import get_provider
from grimoire.providers.fake import FakeProvider
from grimoire.service import KnowledgeService
from grimoire.store import Repository


# ---------------------------------------------------------------------------
# gateway smoke: every wrapped surface dispatches and returns a well-formed payload
# ---------------------------------------------------------------------------


def test_gateway_tools_dispatch(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "g.db")
    from grimoire import gateway

    proj = gateway.kb_upsert_project("Smoke", context_patch="a testing realm")
    assert proj["project_id"]

    got = gateway.kb_get_project("Smoke")
    assert got["title"] == "Smoke" and "linked" in got

    hits = gateway.kb_retrieve("anything", k=3)
    assert isinstance(hits, list)
    hits_kw = gateway.kb_retrieve("anything", k=3, mode="keyword")
    assert isinstance(hits_kw, list)

    mem = gateway.kb_write_memory("Smoke", "we decided things", decisions=["ship it"])
    assert mem["node_id"]

    hist = gateway.kb_history(mem["node_id"])
    assert hist["node"]["id"] == mem["node_id"] and isinstance(hist["edges"], list)

    clustered = gateway.kb_recluster()
    assert set(clustered) == {"communities", "nodes"}

    exported = gateway.kb_export_markdown(str(tmp_path / "vault"))
    assert exported["nodes"] >= 2

    today = gateway.kb_today()
    assert {"habits", "quadrants", "goals", "weekly", "estimate"} <= set(today)

    task = gateway.kb_create_task("smoke task", important=True)
    assert task["id"]
    done = gateway.kb_complete_task(task["id"])
    assert done["status"] == "done"

    missing = gateway.kb_delete_node("no-such-node")
    assert "error" in missing


# ---------------------------------------------------------------------------
# distillation: the distilled chronicle carries the expected entities
# ---------------------------------------------------------------------------


class _EntityProvider(FakeProvider):
    """FakeProvider whose completion names fixed entities, like a real distillation."""

    def complete(self, prompt: str, system: str | None = None, json_mode: bool = False) -> str:
        return json.dumps({
            "summary": "Chose sqlite-vec for storage after comparing options.",
            "decisions": ["use sqlite-vec"],
            "open_questions": ["when to revisit pgvector?"],
            "entities": ["sqlite-vec", "Adam"],
        })


def test_distillation_writes_expected_entities(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        svc = KnowledgeService(repo, _EntityProvider())
        repo.upsert_project("Demo")
        turns = [{"role": "user", "content": "let's pick a vector store"},
                 {"role": "assistant", "content": "sqlite-vec fits"}]
        result = capture_session(svc, "Demo", turns)

        node = repo.get_node(result["node_id"])
        assert node["meta"]["entities"] == ["sqlite-vec", "Adam"]
        assert node["meta"]["decisions"] == ["use sqlite-vec"]
        assert node["meta"]["open_questions"] == ["when to revisit pgvector?"]
        # entity runes exist and are linked via mentions
        titles = {n["title"] for n in repo.list_nodes(type="entity")}
        assert {"sqlite-vec", "Adam"} <= titles
        rels = [e for e in repo.list_edges() if e["rel"] == "mentions" and e["src"] == result["node_id"]]
        assert len(rels) == 2
        # raw turns preserved in the raw layer
        assert repo.counts()["memory_raw"] == 2
    finally:
        repo.close()


# ---------------------------------------------------------------------------
# compaction: nothing is ever lost
# ---------------------------------------------------------------------------


def _old(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def test_compaction_archives_without_losing_anything(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        provider = get_provider("fake")
        svc = KnowledgeService(repo, provider)
        repo.upsert_project("Demo")
        # two identical old summaries (cosine distance 0 -> one cluster) + one distinct
        same = "We picked the arcane blue palette for tomes."
        ids = [
            repo.write_memory("Demo", same, title="palette a",
                              summary_embedding=provider.embed(same), created_at=_old(60),
                              raw_turns=[{"role": "user", "content": "blue?"}]),
            repo.write_memory("Demo", same, title="palette b",
                              summary_embedding=provider.embed(same), created_at=_old(45)),
        ]
        other = "Completely unrelated deployment note about tunnels."
        repo.write_memory("Demo", other, title="deploy",
                          summary_embedding=provider.embed(other), created_at=_old(50))

        before = repo.counts()
        stats = compact_project(svc, "Demo")
        assert stats["clusters_merged"] == 1
        assert stats["originals_archived"] == 2

        after = repo.counts()
        # originals archived, never deleted: node count grows by the consolidated one
        assert after["nodes"] == before["nodes"] + 1
        assert after["memory_raw"] == before["memory_raw"]  # raw layer untouched
        for mid in ids:
            node = repo.get_node(mid)
            assert node is not None and node["status"] == "archived"
        # lineage: consolidated derived_from each original
        derived = [e for e in repo.list_edges() if e["rel"] == "derived_from"]
        assert {e["dst"] for e in derived} == set(ids)

        # idempotent: a second run finds nothing left to merge and changes nothing
        again = compact_project(svc, "Demo")
        assert again["clusters_merged"] == 0 and again["originals_archived"] == 0
        assert repo.counts() == after
    finally:
        repo.close()


# ---------------------------------------------------------------------------
# API auth: write routes 401 without the bearer once a token is set
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(settings, "db_path", tmp_path / "api.db")
    from fastapi.testclient import TestClient

    from grimoire import api

    return TestClient(api.app)


def test_capture_requires_token(client, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "sekrit")
    payload = {"type": "project_context", "project": "Demo", "context_patch": "ctx"}

    assert client.post("/api/capture", json=payload).status_code == 401
    bad = client.post("/api/capture", json=payload, headers={"authorization": "Bearer wrong"})
    assert bad.status_code == 401
    ok = client.post("/api/capture", json=payload, headers={"authorization": "Bearer sekrit"})
    assert ok.status_code == 200 and ok.json()["kind"] == "project_context"


def test_all_write_routes_guarded_reads_open(client, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "sekrit")
    assert client.put("/api/layout", json=[]).status_code == 401
    assert client.post("/api/maintenance/recluster").status_code == 401
    assert client.get("/api/graph").status_code == 200  # reads stay open


def test_capture_rejects_malformed_payload(client, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "")
    assert client.post("/api/capture", json={"type": "nonsense"}).status_code == 422
    assert client.post("/api/capture", json={"project": "x"}).status_code == 422


def test_no_token_configured_means_open(client, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "")
    payload = {"type": "project_context", "project": "Open", "context_patch": None}
    assert client.post("/api/capture", json=payload).status_code == 200
