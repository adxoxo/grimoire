"""Community detection acceptance tests.

Covers: kb_recluster persistence, stability across reruns on an unchanged graph,
distinct communities for disconnected clusters, and community labels.
"""

from __future__ import annotations

from pathlib import Path

from grimoire.cluster import community_labels, recluster
from grimoire.store import Repository


def _two_cluster_store(db: Path) -> Repository:
    """Two quest lines, each with its own little constellation, no cross links."""
    repo = Repository(db)
    for name in ("Alpha", "Beta"):
        pid = repo.upsert_project(name)
        for i in range(3):
            mid = repo.add_node("memory", f"{name} memory {i}")
            repo.link_nodes(mid, pid, "belongs_to")
        did = repo.add_node("document", f"{name} doc")
        repo.link_nodes(did, pid, "belongs_to")
    return repo


def test_recluster_persists_and_separates(tmp_path: Path):
    repo = _two_cluster_store(tmp_path / "g.db")
    try:
        result = recluster(repo)
        assert result["nodes"] == 10
        assert result["communities"] >= 2

        nodes = repo.list_nodes()
        assert all(n["community_id"] is not None for n in nodes)

        # the two disconnected clusters land in different communities
        by_title = {n["title"]: n["community_id"] for n in nodes}
        assert by_title["Alpha"] != by_title["Beta"]
        assert by_title["Alpha memory 0"] == by_title["Alpha"]
        assert by_title["Beta doc"] == by_title["Beta"]
    finally:
        repo.close()


def test_recluster_stable_across_reruns(tmp_path: Path):
    repo = _two_cluster_store(tmp_path / "g.db")
    try:
        recluster(repo)
        first = {n["id"]: n["community_id"] for n in repo.list_nodes()}
        recluster(repo)
        second = {n["id"]: n["community_id"] for n in repo.list_nodes()}
        assert first == second
    finally:
        repo.close()


def test_community_labels_pick_highest_degree(tmp_path: Path):
    repo = _two_cluster_store(tmp_path / "g.db")
    try:
        recluster(repo)
        nodes = repo.list_nodes()
        labels = community_labels(nodes, repo.list_edges())
        # each project hub has degree 4 (its linked nodes), the highest in its cluster
        assert set(labels.values()) == {"Alpha", "Beta"}
    finally:
        repo.close()
