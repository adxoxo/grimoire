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


def test_get_project_excludes_archived_linked_node(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        repo.upsert_project("Demo")
        mem_id = repo.write_memory("Demo", "keep me")
        repo.archive_node(mem_id)

        proj = repo.get_project("Demo")
        assert mem_id not in [n["id"] for n in proj["linked"]]
    finally:
        repo.close()


def test_archive_node_invalidates_its_edges(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        pid = repo.upsert_project("Demo")
        mid = repo.add_node("memory", "m")
        repo.link_nodes(mid, pid, "belongs_to")

        repo.archive_node(mid)

        assert repo.list_edges() == []
        history = repo.node_history(mid)
        assert len(history["edges"]) == 1
        assert history["edges"][0]["invalidated_at"] is not None
    finally:
        repo.close()


def test_list_nodes_excludes_archived_node(tmp_path: Path):
    repo = Repository(tmp_path / "g.db")
    try:
        repo.upsert_project("Demo")
        mem_id = repo.write_memory("Demo", "archive me")

        repo.archive_node(mem_id)

        assert mem_id not in [n["id"] for n in repo.list_nodes()]
        assert mem_id not in [n["id"] for n in repo.list_nodes(type="memory")]
        # nodes_by_status and get_node are untouched by the archived filter
        assert mem_id in [n["id"] for n in repo.nodes_by_status("archived")]
        assert repo.get_node(mem_id) is not None
    finally:
        repo.close()


def test_migration_recovers_from_crash_after_edges_renamed_away(tmp_path: Path):
    """Simulates a crash between renaming edges out of the way and rebuilding it
    (the old RENAME-first approach's failure mode). On reopen, the recovery
    preamble must rename edges_old back to edges before anything else runs."""
    path = tmp_path / "g.db"
    repo = Repository(path)
    pid = repo.upsert_project("Demo")
    mid = repo.add_node("memory", "m")
    repo.link_nodes(mid, pid, "belongs_to")
    with repo._conn:
        repo._conn.execute("ALTER TABLE edges RENAME TO edges_old")
    repo.close()

    repo2 = Repository(path)
    try:
        edges = repo2.list_edges()
        assert len(edges) == 1
        assert edges[0]["src"] == mid and edges[0]["dst"] == pid
    finally:
        repo2.close()


def test_migration_recovers_from_crash_between_drop_and_rename(tmp_path: Path):
    """Simulates a crash between DROP TABLE edges and ALTER TABLE edges_new RENAME
    TO edges. On reopen, the recovery preamble must rename edges_new back to
    edges since it is the only copy of the data left."""
    path = tmp_path / "g.db"
    repo = Repository(path)
    pid = repo.upsert_project("Demo")
    mid = repo.add_node("memory", "m")
    repo.link_nodes(mid, pid, "belongs_to")
    with repo._conn:
        repo._conn.execute("CREATE TABLE edges_new AS SELECT * FROM edges")
        repo._conn.execute("DROP TABLE edges")
    repo.close()

    repo2 = Repository(path)
    try:
        edges = repo2.list_edges()
        assert len(edges) == 1
        assert edges[0]["src"] == mid and edges[0]["dst"] == pid
    finally:
        repo2.close()
