"""Full-fidelity read path (drill-down-to-raw).

The two-layer memory design embeds only the distilled summary; raw conversation turns go
to memory_raw, unindexed. Until now that raw layer was write-only. These tests cover its
read path: read_node_full returns a node's complete chunk text plus its raw turns, and the
GET /api/nodes/{id}/full endpoint exposes the same. All offline (fake provider, temp db).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grimoire.providers import get_provider
from grimoire.service import KnowledgeService
from grimoire.store import Repository


@pytest.fixture
def provider():
    return get_provider("fake")


@pytest.fixture
def repo(tmp_path: Path):
    r = Repository(tmp_path / "g.db")
    yield r
    r.close()


def test_read_node_full_returns_chunks_and_raw_turns(repo, provider):
    svc = KnowledgeService(repo, provider)
    repo.upsert_project("Demo")
    mem_id = repo.write_memory(
        project="Demo",
        summary="distilled: shipped the fix",
        raw_turns=[
            {"role": "user", "content": "exact cmd: docker compose up -d --build"},
            {"role": "assistant", "content": "container healthy on :8731"},
        ],
        summary_embedding=provider.embed("distilled: shipped the fix"),
    )
    full = svc.read_node_full(mem_id)
    assert full is not None
    assert full["node"]["id"] == mem_id
    # the full embedded chunk text is present, un-truncated. Exactly one chunk (the
    # distilled summary): this actively guards the two-layer invariant, since raw turns
    # leaking into the embedding store would show up here as extra chunks.
    assert len(full["chunks"]) == 1
    assert full["chunks"][0]["content"] == "distilled: shipped the fix"
    # the raw layer is readable now, in turn order, verbatim
    assert [t["content"] for t in full["raw_turns"]] == [
        "exact cmd: docker compose up -d --build",
        "container healthy on :8731",
    ]
    assert [t["role"] for t in full["raw_turns"]] == ["user", "assistant"]


def test_read_node_full_missing_node_is_none(repo, provider):
    svc = KnowledgeService(repo, provider)
    assert svc.read_node_full("does-not-exist") is None


def test_memory_without_raw_turns_reads_empty(repo, provider):
    svc = KnowledgeService(repo, provider)
    repo.upsert_project("Demo")
    mem_id = repo.write_memory(
        project="Demo", summary="no raw turns here",
        summary_embedding=provider.embed("no raw turns here"),
    )
    full = svc.read_node_full(mem_id)
    assert full["raw_turns"] == []
    assert full["chunks"][0]["content"] == "no raw turns here"


def test_node_full_endpoint(tmp_path, monkeypatch):
    import grimoire.api as apimod
    from fastapi.testclient import TestClient

    monkeypatch.setattr(apimod.settings, "db_path", tmp_path / "g.db")
    monkeypatch.setattr(apimod, "_provider", get_provider("fake"))
    client = TestClient(apimod.app)

    # Seed via a repo on the same db the app points at, then close so WAL is flushed.
    repo = Repository(tmp_path / "g.db")
    try:
        repo.upsert_project("Demo")
        mem_id = repo.write_memory(
            project="Demo", summary="endpoint chronicle",
            raw_turns=[{"role": "user", "content": "verbatim detail worth keeping"}],
            summary_embedding=apimod._provider.embed("endpoint chronicle"),
        )
    finally:
        repo.close()

    res = client.get(f"/api/nodes/{mem_id}/full")
    assert res.status_code == 200
    body = res.json()
    assert body["node"]["id"] == mem_id
    assert body["raw_turns"][0]["content"] == "verbatim detail worth keeping"
    assert client.get("/api/nodes/does-not-exist/full").status_code == 404
