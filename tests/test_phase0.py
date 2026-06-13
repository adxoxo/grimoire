"""Phase 0 acceptance.

BUILDPLAN: "insert a node, an edge, a chunk, and a vector through the repository layer
(not raw queries); query nearest-neighbor and get it back; run a backup, wipe, and
restore successfully."

Everything goes through the repository layer and the provider interface. No test
issues raw SQL. Embeddings are the offline FakeProvider so the suite runs without
Ollama; it exercises the store's KNN mechanics, not retrieval quality.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grimoire.backup import make_backup, restore_backup
from grimoire.providers import get_provider
from grimoire.reembed import reembed_all
from grimoire.store import Repository


@pytest.fixture
def provider():
    return get_provider("fake")


@pytest.fixture
def repo(tmp_path: Path):
    r = Repository(tmp_path / "grimoire.db")
    yield r
    r.close()


def test_node_edge_chunk_vector_and_knn(repo: Repository, provider):
    # node + edge through the repository layer
    project_id = repo.upsert_project("ROAR", meta={"stack": "GHL"}, context_patch="initial context")
    doc_id = repo.add_node("document", "GHL pipeline reference", status="unreviewed")
    repo.link_nodes(doc_id, project_id, "belongs_to")

    # chunk + vector through the repository layer
    target = "Setting up the sales pipeline stages in GoHighLevel."
    other = "Completely unrelated text about mushroom cultivation."
    target_chunk = repo.add_chunk(doc_id, 0, target, provider.embed(target))
    repo.add_chunk(doc_id, 1, other, provider.embed(other))

    counts = repo.counts()
    assert counts == {"nodes": 2, "edges": 1, "memory_raw": 0, "chunks": 2, "chunk_vectors": 2}

    # nearest-neighbour: querying the target text returns the target chunk first
    hits = repo.search(provider.embed(target), k=2)
    assert hits, "expected KNN hits"
    assert hits[0]["chunk_id"] == target_chunk
    assert hits[0]["content"] == target
    assert hits[0]["node_id"] == doc_id


def test_get_project_shows_linked_nodes(repo: Repository, provider):
    pid = repo.upsert_project("FTV Mushrooms", context_patch="grow logs and SOPs")
    doc_id = repo.add_node("document", "Substrate recipe")
    repo.link_nodes(doc_id, pid, "belongs_to")

    proj = repo.get_project("FTV Mushrooms")
    assert proj is not None
    assert proj["type"] == "project"
    assert proj["context_summary"] == "grow logs and SOPs"
    linked_ids = {n["id"] for n in proj["linked"]}
    assert doc_id in linked_ids


def test_upsert_project_updates_in_place(repo: Repository):
    pid1 = repo.upsert_project("GoatedTracking", meta={"stack": "n8n"}, status="idea")
    pid2 = repo.upsert_project("GoatedTracking", meta={"client": "self"}, context_patch="now active")
    assert pid1 == pid2  # same node id preserved (idea -> active lineage)

    proj = repo.get_project("GoatedTracking")
    assert proj["status"] == "idea"  # status untouched when not provided
    assert proj["meta"] == {"stack": "n8n", "client": "self"}  # meta merged
    assert proj["context_summary"] == "now active"


def test_write_memory_links_project_entities_and_raw(repo: Repository, provider):
    repo.upsert_project("Grimoire", context_patch="building the knowledge base")
    summary = "Decided SQLite + sqlite-vec for the store. Built the repository layer."
    mem_id = repo.write_memory(
        project="Grimoire",
        summary=summary,
        decisions=["store = sqlite-vec", "python only"],
        entities=["sqlite-vec", "FastMCP"],
        raw_turns=[{"role": "user", "content": "build it"}, {"role": "assistant", "content": "done"}],
        summary_embedding=provider.embed(summary),
    )

    # memory belongs_to the project (1 hop); entities are mentioned BY the memory (2 hops out)
    proj = repo.get_project("Grimoire")
    assert any(n["id"] == mem_id and n["rel"] == "belongs_to" for n in proj["linked"])

    mem = repo.get_node(mem_id)
    assert mem["status"] == "unreviewed"
    assert mem["meta"]["decisions"] == ["store = sqlite-vec", "python only"]

    # project + memory + 2 entity nodes; belongs_to + 2 mentions edges; 2 raw turns;
    # only the distilled summary embedded (1 chunk/vector), never the raw turns
    assert repo.counts() == {"nodes": 4, "edges": 3, "memory_raw": 2, "chunks": 1, "chunk_vectors": 1}

    # the distilled summary is retrievable
    hits = repo.search(provider.embed(summary), k=1)
    assert hits[0]["node_id"] == mem_id


def test_write_memory_requires_existing_project(repo: Repository, provider):
    with pytest.raises(ValueError, match="project not found"):
        repo.write_memory("DoesNotExist", "orphan summary")


def test_embedding_dimension_is_enforced(repo: Repository):
    with pytest.raises(ValueError, match="expected 768"):
        repo.add_chunk(repo.add_node("document", "bad"), 0, "x", [0.1, 0.2, 0.3])


def test_backup_wipe_restore(tmp_path: Path, provider):
    db_path = tmp_path / "data" / "grimoire.db"
    backup_dir = tmp_path / "backups"

    # populate a live store
    repo = Repository(db_path)
    pid = repo.upsert_project("ROAR", context_patch="real context")
    doc_id = repo.add_node("document", "pipeline doc")
    repo.link_nodes(doc_id, pid, "belongs_to")
    text = "How recency decay scoring works in the read path."
    repo.add_chunk(doc_id, 0, text, provider.embed(text))
    counts_before = repo.counts()

    # back up the LIVE store (separate connection), verified internally
    backup_path = make_backup(db_path=db_path, backup_dir=backup_dir)
    assert backup_path.exists()

    # disaster: close and wipe the store and its WAL sidecars
    repo.close()
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    assert not db_path.exists()

    # restore (verified internally) and prove the data — including vectors — survived
    restore_backup(backup_path, db_path=db_path)
    repo2 = Repository(db_path)
    try:
        assert repo2.counts() == counts_before
        hits = repo2.search(provider.embed(text), k=1)
        assert hits[0]["content"] == text  # KNN works on the restored store
        assert repo2.get_project("ROAR")["context_summary"] == "real context"
    finally:
        repo2.close()


def test_reembed_all_rebuilds_vectors(repo: Repository, provider):
    pid = repo.upsert_project("ROAR")
    doc_id = repo.add_node("document", "doc")
    repo.link_nodes(doc_id, pid, "belongs_to")
    text = "chunk to be re-embedded"
    repo.add_chunk(doc_id, 0, text, provider.embed(text))

    n = reembed_all(repo, provider)
    assert n == 1
    hits = repo.search(provider.embed(text), k=1)
    assert hits[0]["content"] == text  # still retrievable after re-embed


def test_fake_provider_is_deterministic_and_correct_dim(provider):
    v1 = provider.embed("same text")
    v2 = provider.embed("same text")
    assert v1 == v2  # deterministic
    assert len(v1) == 768
    norm = sum(x * x for x in v1) ** 0.5
    assert abs(norm - 1.0) < 1e-6  # unit vector
