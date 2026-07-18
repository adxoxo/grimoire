"""Bitemporal validity acceptance tests.

Covers: sever = invalidate (not delete), re-link after sever, reads default to
currently-valid rows, archive marks a memory invalidated, and node_history exposes
the full timeline including superseded rows.
"""

from __future__ import annotations

from pathlib import Path

from grimoire.store import Repository


def test_unlink_invalidates_and_relink_works(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        pid = repo.upsert_project("Demo")
        mid = repo.add_node("memory", "m")
        repo.link_nodes(mid, pid, "belongs_to")

        assert repo.unlink_nodes(mid, pid, "belongs_to") == 1
        assert repo.list_edges() == []  # reads see only valid rows

        history = repo.node_history(mid)
        assert len(history["edges"]) == 1
        assert history["edges"][0]["invalidated_at"] is not None

        # a severed link can be re-created; one valid row, one invalidated row
        repo.link_nodes(mid, pid, "belongs_to")
        assert len(repo.list_edges()) == 1
        assert len(repo.node_history(mid)["edges"]) == 2
    finally:
        repo.close()


def test_link_nodes_is_idempotent_per_valid_edge(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        pid = repo.upsert_project("Demo")
        mid = repo.add_node("memory", "m")
        repo.link_nodes(mid, pid, "belongs_to")
        repo.link_nodes(mid, pid, "belongs_to")  # no duplicate valid row
        assert len(repo.node_history(mid)["edges"]) == 1
    finally:
        repo.close()


def test_reads_exclude_invalidated(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        pid = repo.upsert_project("Demo")
        mid = repo.add_node("memory", "m")
        did = repo.add_node("document", "d")
        repo.link_nodes(mid, pid, "belongs_to")
        repo.link_nodes(did, pid, "belongs_to")
        repo.unlink_nodes(did, pid, "belongs_to")

        proj = repo.get_project("Demo")
        assert [n["id"] for n in proj["linked"]] == [mid]
        assert set(repo.candidate_node_ids(pid)) == {pid, mid}
    finally:
        repo.close()


def test_archive_marks_memory_invalidated_but_history_keeps_it(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        repo.upsert_project("Demo")
        mem_id = repo.write_memory("Demo", "the original decision")
        repo.archive_node(mem_id)

        history = repo.node_history(mem_id)
        assert history["node"]["invalidated_at"] is not None
        assert history["node"]["valid_from"]  # backfilled from created_at
        # the original stays queryable even though normal reads skip archived memories
        proj = repo.get_project("Demo")
        pid = proj["id"]
        assert repo.project_memories(pid) == []
    finally:
        repo.close()
