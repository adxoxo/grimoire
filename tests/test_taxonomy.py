"""V2 acceptance tests: hierarchical scoped retrieval + human-in-the-loop classification.

All tests use FakeProvider (offline, deterministic) and per-test temp databases. Fake
embeddings are not semantically meaningful, so routing tests make the match explicit by
embedding a scope summary from the SAME text the query uses (similarity ~ 1.0) and an
unrelated summary for the negative case (near-orthogonal -> below threshold). The store
mechanics and control flow are what these prove; retrieval quality needs real Ollama.
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


# ---------------------------------------------------------------------------
# 1. Schema migration is additive and backward compatible
# ---------------------------------------------------------------------------

def test_schema_has_taxonomy_columns(repo):
    cols = {r[1] for r in repo._conn.execute("PRAGMA table_info(nodes)")}
    assert {"node_kind", "domain_id", "index_id", "summary", "summary_updated_at"} <= cols
    exists = repo._conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = 'scope_vectors'"
    ).fetchone()
    assert exists is not None


def test_existing_nodes_default_to_node_kind(repo):
    repo.upsert_project("Demo")
    nid = repo.add_node("memory", "a note", context_summary="hello")
    assert repo.get_node(nid)["node_kind"] == "node"


# ---------------------------------------------------------------------------
# 2. Scope integrity rules
# ---------------------------------------------------------------------------

def test_domain_and_index_integrity(repo):
    dom = repo.add_scope("domain", "Content automation")
    d = repo.get_node(dom)
    assert d["node_kind"] == "domain" and d["domain_id"] is None and d["index_id"] is None

    idx = repo.add_scope("index", "YouTube", domain_id=dom)
    i = repo.get_node(idx)
    assert i["node_kind"] == "index" and i["domain_id"] == dom and i["index_id"] is None


def test_index_requires_a_real_domain(repo):
    with pytest.raises(ValueError):
        repo.add_scope("index", "Orphan")  # no domain_id
    node = repo.add_node("memory", "not a domain")
    with pytest.raises(ValueError):
        repo.add_scope("index", "Bad", domain_id=node)  # points at a content node


# ---------------------------------------------------------------------------
# 3. Classify / move / inbox round trip
# ---------------------------------------------------------------------------

def test_classify_sets_both_ids_and_clears_inbox(repo):
    dom = repo.add_scope("domain", "Content automation")
    idx = repo.add_scope("index", "YouTube", domain_id=dom)
    nid = repo.add_node("memory", "thumbnail tips", context_summary="use bold faces")

    assert any(n["id"] == nid for n in repo.unclassified_nodes())
    placed = repo.classify_node(nid, idx)
    assert placed["index_id"] == idx and placed["domain_id"] == dom
    assert not any(n["id"] == nid for n in repo.unclassified_nodes())
    assert repo.node_breadcrumb(nid)["index"] == "YouTube"


def test_move_node_is_classify_alias(repo):
    dom = repo.add_scope("domain", "D")
    a = repo.add_scope("index", "A", domain_id=dom)
    b = repo.add_scope("index", "B", domain_id=dom)
    nid = repo.add_node("memory", "note")
    repo.classify_node(nid, a)
    repo.move_node(nid, b)
    assert repo.get_node(nid)["index_id"] == b


# ---------------------------------------------------------------------------
# 4. Deleting a scope detaches members, never deletes them
# ---------------------------------------------------------------------------

def test_delete_index_detaches_nodes(repo):
    dom = repo.add_scope("domain", "D")
    idx = repo.add_scope("index", "I", domain_id=dom)
    nid = repo.add_node("memory", "keep me")
    repo.classify_node(nid, idx)

    out = repo.delete_scope(idx)
    assert out["detached"] == 1
    assert repo.get_node(nid) is not None  # node survived
    assert repo.get_node(nid)["index_id"] is None  # back in the inbox
    assert repo.get_scope(idx) is None


def test_delete_domain_removes_indexes_and_detaches(repo):
    dom = repo.add_scope("domain", "D")
    idx = repo.add_scope("index", "I", domain_id=dom)
    nid = repo.add_node("memory", "keep me")
    repo.classify_node(nid, idx)

    repo.delete_scope(dom)
    assert repo.get_scope(dom) is None and repo.get_scope(idx) is None
    node = repo.get_node(nid)
    assert node is not None and node["index_id"] is None and node["domain_id"] is None


# ---------------------------------------------------------------------------
# 5. Summary refresh embeds, stamps, and clears staleness
# ---------------------------------------------------------------------------

def test_refresh_summary_embeds_and_unstales(repo, provider):
    svc = KnowledgeService(repo, provider)
    dom = repo.add_scope("domain", "D")
    idx = repo.add_scope("index", "YouTube", domain_id=dom)

    scopes = repo.list_scopes()
    assert scopes["domains"][0]["indexes"][0]["stale"] is True  # no summary yet

    out = svc.refresh_summary(idx, summary_text="YouTube growth: thumbnails, titles.")
    assert out["embedded"] is True
    i = repo.get_node(idx)
    assert i["summary"] and i["summary_updated_at"]
    assert repo.list_scopes()["domains"][0]["indexes"][0]["stale"] is False


def test_staleness_after_n_classifications(repo, provider):
    svc = KnowledgeService(repo, provider)
    dom = repo.add_scope("domain", "D")
    idx = repo.add_scope("index", "I", domain_id=dom)
    svc.refresh_summary(idx, summary_text="a summary")
    for n in range(3):
        repo.classify_node(repo.add_node("memory", f"n{n}"), idx)
    # threshold 3 -> stale; threshold 10 -> not yet
    assert repo.list_scopes(stale_after=3)["domains"][0]["indexes"][0]["stale"] is True
    assert repo.list_scopes(stale_after=10)["domains"][0]["indexes"][0]["stale"] is False


# ---------------------------------------------------------------------------
# 6. Routing: scoped when an index matches, global fallback when none do
# ---------------------------------------------------------------------------

def _seed_youtube_index(repo, provider):
    dom = repo.add_scope("domain", "Content automation")
    idx = repo.add_scope("index", "YouTube", domain_id=dom)
    # summary embedding == the query text below, so cosine similarity ~ 1.0
    repo.set_scope_summary(idx, "youtube thumbnails", provider.embed("youtube thumbnails"))
    nid = repo.add_node("memory", "thumbnail note", context_summary="bold faces win")
    repo.add_chunk(nid, 0, "how to design youtube thumbnails that get clicks",
                   provider.embed("how to design youtube thumbnails that get clicks"))
    repo.classify_node(nid, idx)
    return idx, nid


def test_routing_scoped_hit(repo, provider):
    svc = KnowledgeService(repo, provider)
    idx, nid = _seed_youtube_index(repo, provider)
    # a matching index plus enough members to clear k_min
    for i in range(3):
        m = repo.add_node("memory", f"yt {i}")
        repo.add_chunk(m, 0, f"youtube thumbnails variant {i}", provider.embed(f"youtube thumbnails variant {i}"))
        repo.classify_node(m, idx)

    out = svc.retrieve_scoped("youtube thumbnails", k=5, k_min=1)
    assert out["routing"]["mode"] == "scoped"
    assert out["routing"]["matched_indexes"][0]["index_id"] == idx
    assert out["results"] and all(r["scope"]["index_id"] == idx for r in out["results"])


def test_routing_global_fallback_when_no_scope_matches(repo, provider):
    svc = KnowledgeService(repo, provider)
    _seed_youtube_index(repo, provider)
    # an unrelated node so global search has something to return
    other = repo.add_node("memory", "tax filing", context_summary="quarterly taxes")
    repo.add_chunk(other, 0, "quarterly estimated tax payment deadlines",
                   provider.embed("quarterly estimated tax payment deadlines"))

    out = svc.retrieve_scoped("quarterly estimated tax payment deadlines", k=5)
    assert out["routing"]["mode"] == "global_fallback"
    assert out["results"]  # never silently empty


def test_backward_compatible_global_when_no_scopes(repo, provider):
    """Acceptance #8: with no taxonomy at all, retrieval behaves like global search."""
    svc = KnowledgeService(repo, provider)
    nid = repo.add_node("memory", "note", context_summary="a plain note")
    repo.add_chunk(nid, 0, "a plain note about deployment", provider.embed("a plain note about deployment"))
    out = svc.retrieve_scoped("deployment", k=5)
    assert out["routing"]["mode"] in ("global", "global_fallback")
    assert any(r["node_id"] == nid for r in out["results"])


# ---------------------------------------------------------------------------
# 7. Ingest classification: auto-file vs inbox proposal
# ---------------------------------------------------------------------------

def test_ingest_autofiles_above_threshold(repo, provider, tmp_path):
    svc = KnowledgeService(repo, provider)
    dom = repo.add_scope("domain", "Content automation")
    idx = repo.add_scope("index", "YouTube", domain_id=dom)
    repo.set_scope_summary(idx, "youtube thumbnails guide",
                           provider.embed("youtube thumbnails guide"))
    doc = tmp_path / "d.md"
    doc.write_text("youtube thumbnails guide\n\nHow to design thumbnails.")
    # threshold below any similarity -> forced auto-file
    res = svc.ingest_document(str(doc), autofile_threshold=-1.0)
    assert res["classification"]["status"] == "filed"
    assert repo.get_node(res["node_id"])["index_id"] == idx


def test_ingest_proposes_to_inbox_below_threshold(repo, provider, tmp_path):
    svc = KnowledgeService(repo, provider)
    dom = repo.add_scope("domain", "Content automation")
    idx = repo.add_scope("index", "YouTube", domain_id=dom)
    repo.set_scope_summary(idx, "youtube", provider.embed("youtube"))
    doc = tmp_path / "d.md"
    doc.write_text("some unrelated content about firmware drivers")
    res = svc.ingest_document(str(doc), autofile_threshold=2.0)  # impossible -> inbox
    assert res["classification"]["status"] == "proposed"
    node = repo.get_node(res["node_id"])
    assert node["index_id"] is None
    assert node["meta"].get("classification") is not None  # proposal stashed for the inbox


# ---------------------------------------------------------------------------
# 8. Bootstrap: communities -> taxonomy backfill
# ---------------------------------------------------------------------------

def test_bootstrap_applies_taxonomy(repo, provider):
    from grimoire.taxonomy import apply_taxonomy, propose_taxonomy

    svc = KnowledgeService(repo, provider)
    a = repo.add_node("memory", "yt a")
    b = repo.add_node("memory", "yt b")
    # propose_taxonomy reclusters first, so give the two nodes a real edge and let Louvain
    # group them into one community rather than relying on hand-set community ids.
    repo.link_nodes(a, b, "references")
    proposal = propose_taxonomy(repo)
    cid = proposal["communities"][0]["community_id"]
    assert proposal["communities"][0]["size"] == 2

    plan = {"domains": [{"title": "Content automation", "indexes": [
        {"title": "YouTube", "community_ids": [cid]}]}]}
    stats = apply_taxonomy(svc, plan)
    assert stats["nodes_filed"] == 2
    assert repo.get_node(a)["index_id"] is not None
    assert repo.unclassified_count() == 0


# ---------------------------------------------------------------------------
# 9. Migration against the real store (only when a copy is present)
# ---------------------------------------------------------------------------

def test_migration_against_real_db_if_present(tmp_path):
    import shutil

    src = Path(__file__).resolve().parent.parent / "grimoire.db"
    if not src.exists():
        pytest.skip("no real grimoire.db copy present")
    copy = tmp_path / "real.db"
    shutil.copy(src, copy)

    before_total = _raw_node_count(copy)
    repo = Repository(copy)
    try:
        cols = {r[1] for r in repo._conn.execute("PRAGMA table_info(nodes)")}
        assert {"node_kind", "domain_id", "index_id"} <= cols
        # every pre-existing node is unclassified content, nothing lost or reclassified
        assert repo.unclassified_count() == len(repo.list_nodes())
        assert len(repo.list_nodes()) == before_total
        # and the taxonomy works on real data
        dom = repo.add_scope("domain", "Test domain")
        idx = repo.add_scope("index", "Test index", domain_id=dom)
        nid = next(n["id"] for n in repo.list_nodes() if n.get("node_kind") == "node")
        repo.classify_node(nid, idx)
        assert repo.node_breadcrumb(nid)["index"] == "Test index"
        repo.delete_scope(dom)
        assert repo.get_node(nid) is not None  # detach, not delete
    finally:
        repo.close()


def _raw_node_count(db_path: Path) -> int:
    import sqlite3

    import sqlite_vec

    c = sqlite3.connect(str(db_path))
    c.enable_load_extension(True)
    sqlite_vec.load(c)
    c.enable_load_extension(False)
    try:
        return c.execute("SELECT count(*) FROM nodes WHERE invalidated_at IS NULL").fetchone()[0]
    finally:
        c.close()


# ---------------------------------------------------------------------------
# 10. Auto-classification of inbox items (LLM over vector routing)
# ---------------------------------------------------------------------------

def test_auto_classify_files_on_strong_vector(repo, provider):
    # Force the vector path (use_llm=False). FakeProvider gives identical text an
    # identical vector, so the node routes to the index with similarity ~ 1.0.
    svc = KnowledgeService(repo, provider)
    dom = repo.add_scope("domain", "Content")
    idx = repo.add_scope("index", "YouTube", domain_id=dom)
    repo.set_scope_summary(idx, "YouTube thumbnails guide",
                           provider.embed("YouTube thumbnails guide"))
    node_id = repo.add_node("document", "YouTube thumbnails guide", status="unreviewed")

    out = svc.auto_classify_node(node_id, use_llm=False)
    assert out == {"node_id": node_id, "filed": True, "index_id": idx,
                   "index": "YouTube", "domain": "Content",
                   "score": out["score"], "reason": "high vector confidence"}
    assert out["score"] >= 0.75
    assert repo.get_node(node_id)["index_id"] == idx


def test_auto_classify_no_indexes(repo, provider):
    svc = KnowledgeService(repo, provider)
    node_id = repo.add_node("document", "orphan note")
    out = svc.auto_classify_node(node_id, use_llm=False)
    assert out["filed"] is False
    assert out["index_id"] is None
    assert out["reason"] == "no indexes exist yet"


def test_auto_classify_inbox_splits_filed_and_skipped(repo, provider):
    svc = KnowledgeService(repo, provider)
    dom = repo.add_scope("domain", "Content")
    idx = repo.add_scope("index", "YouTube", domain_id=dom)
    repo.set_scope_summary(idx, "YouTube thumbnails guide",
                           provider.embed("YouTube thumbnails guide"))
    match = repo.add_node("document", "YouTube thumbnails guide")
    nomatch = repo.add_node("document", "unrelated firmware driver notes")

    out = svc.auto_classify_inbox(use_llm=False)
    assert out["filed_count"] == 1 and out["skipped_count"] == 1
    assert {r["node_id"] for r in out["filed"]} == {match}
    assert {r["node_id"] for r in out["skipped"]} == {nomatch}
    assert out["skipped"][0]["reason"] == "no confident match, needs review"
