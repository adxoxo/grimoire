"""The repository layer: the ONLY module that touches the store engine.

Hard rule (ARCHITECTURE / CLAUDE.md): no SQL, no sqlite connection, and no
sqlite-vec call lives anywhere else in the codebase. Everything else calls these
intent-level methods. This is what keeps the SQLite choice reversible: to move to
SurrealDB you rewrite this one module, not the application.

The repository stores; it does not embed. Embeddings are produced by the provider
interface and passed in as plain float lists. Keeping the two seams separate is
deliberate.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import sqlite_vec
from sqlite_vec import serialize_float32

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

# Node types and edge relations, kept here so callers reference names, not literals.
NODE_TYPES = ("document", "memory", "project", "entity")
EDGE_RELS = ("belongs_to", "references", "mentions", "derived_from")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _derive_title(summary: str) -> str:
    first = (summary or "").strip().splitlines()[0] if (summary or "").strip() else ""
    first = first.strip()
    if not first:
        return "Untitled memory"
    return first[:80]


class Repository:
    """Intent-level access to the Grimoire store. One instance owns one connection."""

    def __init__(self, db_path: str | Path, embed_dim: int = 768) -> None:
        self.db_path = Path(db_path)
        self.embed_dim = embed_dim
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self.initialize()

    # ---- lifecycle -------------------------------------------------------

    def initialize(self) -> None:
        """Create the schema if absent. Idempotent."""
        self._conn.executescript(SCHEMA_PATH.read_text())

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "Repository":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- node + edge primitives -----------------------------------------

    def add_node(
        self,
        type: str,
        title: str,
        *,
        status: str | None = None,
        meta: dict[str, Any] | None = None,
        context_summary: str | None = None,
    ) -> str:
        if type not in NODE_TYPES:
            raise ValueError(f"unknown node type: {type!r}")
        node_id = _new_id()
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO nodes(id,type,title,status,meta,context_summary,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (node_id, type, title, status, json.dumps(meta) if meta is not None else None,
                 context_summary, now, now),
            )
        return node_id

    def get_node(self, node_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        return self._node_row_to_dict(row) if row else None

    def list_nodes(self, type: str | None = None) -> list[dict[str, Any]]:
        """All nodes, optionally filtered by type. Used by the constellation graph."""
        if type is not None:
            rows = self._conn.execute(
                "SELECT id, type, title, status, updated_at FROM nodes WHERE type = ?"
                " ORDER BY updated_at DESC",
                (type,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT id, type, title, status, updated_at FROM nodes ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def list_edges(self) -> list[dict[str, Any]]:
        """All edges. Used by the constellation graph."""
        rows = self._conn.execute("SELECT src, dst, rel FROM edges").fetchall()
        return [dict(r) for r in rows]

    def nodes_by_status(self, status: str) -> list[dict[str, Any]]:
        """Nodes in a given status (e.g. 'unreviewed'), newest first. The review queue."""
        rows = self._conn.execute(
            "SELECT id, type, title, status, context_summary, updated_at FROM nodes"
            " WHERE status = ? ORDER BY updated_at DESC",
            (status,),
        ).fetchall()
        return [dict(r) for r in rows]

    def set_status(self, node_id: str, status: str) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE nodes SET status = ?, updated_at = ? WHERE id = ?",
                (status, _now(), node_id),
            )

    def node_chunk_texts(self, node_id: str) -> list[str]:
        """A node's chunk contents in order (fallback document body if no full text)."""
        rows = self._conn.execute(
            "SELECT content FROM chunks WHERE node_id = ? ORDER BY seq", (node_id,)
        ).fetchall()
        return [r["content"] for r in rows]

    def link_nodes(self, src: str, dst: str, rel: str) -> None:
        if rel not in EDGE_RELS:
            raise ValueError(f"unknown edge relation: {rel!r}")
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO edges(src,dst,rel,created_at) VALUES (?,?,?,?)",
                (src, dst, rel, _now()),
            )

    # ---- chunks + vectors -----------------------------------------------

    def add_chunk(self, node_id: str, seq: int, content: str, embedding: list[float]) -> str:
        with self._conn:
            return self._insert_chunk(node_id, seq, content, embedding)

    def _insert_chunk(self, node_id: str, seq: int, content: str, embedding: list[float]) -> str:
        """Insert a chunk + its vector. Must run inside an open transaction."""
        if len(embedding) != self.embed_dim:
            raise ValueError(f"embedding has {len(embedding)} dims, expected {self.embed_dim}")
        chunk_id = _new_id()
        self._conn.execute(
            "INSERT INTO chunks(id,node_id,seq,content,created_at) VALUES (?,?,?,?,?)",
            (chunk_id, node_id, seq, content, _now()),
        )
        self._conn.execute(
            "INSERT INTO chunk_vectors(chunk_id, embedding) VALUES (?, ?)",
            (chunk_id, serialize_float32(embedding)),
        )
        return chunk_id

    def search(self, query_embedding: list[float], k: int = 10) -> list[dict[str, Any]]:
        """Vector nearest-neighbour over all chunks.

        Phase 0 scope: global KNN. Phase 1 adds project-scoped candidate narrowing
        (1-2 hops) and recency-decay scoring before this is the real read path.
        """
        if len(query_embedding) != self.embed_dim:
            raise ValueError(f"query has {len(query_embedding)} dims, expected {self.embed_dim}")
        knn = self._conn.execute(
            "SELECT chunk_id, distance FROM chunk_vectors"
            " WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (serialize_float32(query_embedding), k),
        ).fetchall()
        results: list[dict[str, Any]] = []
        for row in knn:
            meta = self._conn.execute(
                "SELECT c.node_id, c.content, n.title, n.type, n.status, n.updated_at"
                " FROM chunks c JOIN nodes n ON n.id = c.node_id WHERE c.id = ?",
                (row["chunk_id"],),
            ).fetchone()
            if meta is None:
                continue
            results.append({
                "chunk_id": row["chunk_id"],
                "distance": row["distance"],
                "node_id": meta["node_id"],
                "content": meta["content"],
                "title": meta["title"],
                "type": meta["type"],
                "status": meta["status"],
                "updated_at": meta["updated_at"],
            })
        return results

    # ---- traversal for the read path ------------------------------------

    def candidate_node_ids(self, project_id: str, max_hops: int = 2) -> list[str]:
        """Nodes reachable from a project within max_hops, treated undirected,
        with the supernode rule: traversal never expands OUTWARD from an entity
        node. Entities are included as candidates when reached, but a shared entity
        (e.g. a common API rune) cannot bridge to unrelated projects' nodes.
        """
        visited = {project_id}
        frontier = {project_id}
        for _ in range(max_hops):
            if not frontier:
                break
            nxt: set[str] = set()
            for nid in frontier:
                row = self._conn.execute("SELECT type FROM nodes WHERE id = ?", (nid,)).fetchone()
                if row is None or row["type"] == "entity":
                    continue  # entity cap: do not traverse out of an entity
                neighbours = self._conn.execute(
                    "SELECT dst AS other FROM edges WHERE src = ?"
                    " UNION SELECT src AS other FROM edges WHERE dst = ?",
                    (nid, nid),
                ).fetchall()
                for r in neighbours:
                    if r["other"] not in visited:
                        visited.add(r["other"])
                        nxt.add(r["other"])
            frontier = nxt
        return list(visited)

    def scored_chunks(
        self, query_embedding: list[float], node_ids: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Cosine distance of every candidate chunk to the query, with node metadata.

        node_ids=None scores all chunks (global). A list restricts to chunks of those
        nodes (the narrowed candidate set). Recency weighting and top-k are applied by
        the caller, so this returns the full scored candidate set, not a truncated KNN.
        """
        if len(query_embedding) != self.embed_dim:
            raise ValueError(f"query has {len(query_embedding)} dims, expected {self.embed_dim}")
        qv = serialize_float32(query_embedding)
        base = (
            "SELECT cv.chunk_id, c.node_id, c.content, n.title, n.type, n.status, n.updated_at,"
            " vec_distance_cosine(cv.embedding, ?) AS distance"
            " FROM chunk_vectors cv"
            " JOIN chunks c ON c.id = cv.chunk_id"
            " JOIN nodes n ON n.id = c.node_id"
        )
        if node_ids is not None:
            if not node_ids:
                return []
            placeholders = ",".join("?" * len(node_ids))
            rows = self._conn.execute(
                f"{base} WHERE c.node_id IN ({placeholders}) ORDER BY distance",
                (qv, *node_ids),
            ).fetchall()
        else:
            rows = self._conn.execute(f"{base} ORDER BY distance", (qv,)).fetchall()
        return [dict(r) for r in rows]

    # ---- projects -------------------------------------------------------

    def upsert_project(
        self,
        name: str,
        meta: dict[str, Any] | None = None,
        context_patch: str | None = None,
        status: str | None = None,
    ) -> str:
        """Create a project hub, or update an existing one by name.

        status=None leaves an existing project's status untouched and defaults a new
        project to 'active'. context_patch replaces the living summary when provided
        (consolidation across notes is compaction's job, not this method's).
        """
        existing = self._get_by_type_title("project", name)
        now = _now()
        with self._conn:
            if existing is None:
                pid = _new_id()
                self._conn.execute(
                    "INSERT INTO nodes(id,type,title,status,meta,context_summary,created_at,updated_at)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (pid, "project", name, status or "active",
                     json.dumps(meta or {}), context_patch, now, now),
                )
                return pid
            pid = existing["id"]
            merged = {**json.loads(existing["meta"] or "{}"), **(meta or {})}
            new_summary = context_patch if context_patch is not None else existing["context_summary"]
            new_status = status if status is not None else existing["status"]
            self._conn.execute(
                "UPDATE nodes SET meta=?, context_summary=?, status=?, updated_at=? WHERE id=?",
                (json.dumps(merged), new_summary, new_status, now, pid),
            )
            return pid

    def get_project(self, name: str) -> dict[str, Any] | None:
        """Project hub + its directly linked nodes (one hop in)."""
        proj = self._get_by_type_title("project", name)
        if proj is None:
            return None
        linked = self._conn.execute(
            "SELECT n.id, n.type, n.title, n.status, e.rel"
            " FROM edges e JOIN nodes n ON n.id = e.src"
            " WHERE e.dst = ? ORDER BY n.updated_at DESC",
            (proj["id"],),
        ).fetchall()
        out = self._node_row_to_dict(proj)
        out["linked"] = [dict(r) for r in linked]
        return out

    # ---- memory ---------------------------------------------------------

    def write_memory(
        self,
        project: str,
        summary: str,
        decisions: list[str] | None = None,
        entities: list[str] | None = None,
        raw_turns: list[dict[str, Any]] | None = None,
        summary_embedding: list[float] | None = None,
        title: str | None = None,
        created_at: str | None = None,
        extra_meta: dict[str, Any] | None = None,
    ) -> str:
        """Write a distilled session record, linked to its project.

        Creates a memory node (status unreviewed), links belongs_to the project,
        get-or-creates each mentioned entity and links it, stores raw turns in the
        raw layer, and embeds the distilled summary when an embedding is supplied.
        Embeddings come from the caller via the provider interface, never from here.

        created_at backdates the node (used by the history backfill). extra_meta is
        merged into the node meta (e.g. open_questions from distillation).
        """
        proj = self._get_by_type_title("project", project)
        if proj is None:
            raise ValueError(f"project not found: {project!r}; call upsert_project first")
        decisions = decisions or []
        entities = entities or []
        mem_id = _new_id()
        now = created_at or _now()
        meta = json.dumps({"decisions": decisions, "entities": entities, **(extra_meta or {})})
        with self._conn:
            self._conn.execute(
                "INSERT INTO nodes(id,type,title,status,meta,context_summary,created_at,updated_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (mem_id, "memory", title or _derive_title(summary), "unreviewed",
                 meta, summary, now, now),
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO edges(src,dst,rel,created_at) VALUES (?,?,?,?)",
                (mem_id, proj["id"], "belongs_to", now),
            )
            for name in entities:
                ent = self._get_by_type_title("entity", name)
                if ent is None:
                    ent_id = _new_id()
                    self._conn.execute(
                        "INSERT INTO nodes(id,type,title,status,meta,context_summary,created_at,updated_at)"
                        " VALUES (?,?,?,?,?,?,?,?)",
                        (ent_id, "entity", name, "unreviewed", None, None, now, now),
                    )
                else:
                    ent_id = ent["id"]
                self._conn.execute(
                    "INSERT OR IGNORE INTO edges(src,dst,rel,created_at) VALUES (?,?,?,?)",
                    (mem_id, ent_id, "mentions", now),
                )
            if raw_turns:
                for i, turn in enumerate(raw_turns):
                    self._conn.execute(
                        "INSERT INTO memory_raw(id,node_id,turn_index,role,content,created_at)"
                        " VALUES (?,?,?,?,?,?)",
                        (_new_id(), mem_id, i, turn.get("role"), turn.get("content"), now),
                    )
            if summary_embedding is not None:
                self._insert_chunk(mem_id, 0, summary, summary_embedding)
        return mem_id

    # ---- re-embedding support (used by the re-embed routine) ------------

    def iter_chunks(self) -> Iterator[dict[str, Any]]:
        cur = self._conn.execute("SELECT id, node_id, seq, content FROM chunks ORDER BY node_id, seq")
        for row in cur:
            yield dict(row)

    def update_vector(self, chunk_id: str, embedding: list[float]) -> None:
        if len(embedding) != self.embed_dim:
            raise ValueError(f"embedding has {len(embedding)} dims, expected {self.embed_dim}")
        with self._conn:
            self._conn.execute("DELETE FROM chunk_vectors WHERE chunk_id = ?", (chunk_id,))
            self._conn.execute(
                "INSERT INTO chunk_vectors(chunk_id, embedding) VALUES (?, ?)",
                (chunk_id, serialize_float32(embedding)),
            )

    # ---- compaction support ---------------------------------------------

    def project_memories(self, project_id: str, include_archived: bool = False) -> list[dict[str, Any]]:
        """Memory nodes belonging to a project, each with its summary chunk id (seq 0)."""
        sql = (
            "SELECT n.id, n.title, n.status, n.created_at, n.context_summary,"
            " (SELECT c.id FROM chunks c WHERE c.node_id = n.id ORDER BY c.seq LIMIT 1) AS chunk_id"
            " FROM edges e JOIN nodes n ON n.id = e.src"
            " WHERE e.dst = ? AND e.rel = 'belongs_to' AND n.type = 'memory'"
        )
        if not include_archived:
            sql += " AND (n.status IS NULL OR n.status != 'archived')"
        return [dict(r) for r in self._conn.execute(sql, (project_id,)).fetchall()]

    def vector_distance(self, chunk_a: str, chunk_b: str) -> float | None:
        """Cosine distance between two stored chunk vectors (for topic clustering)."""
        row = self._conn.execute(
            "SELECT vec_distance_cosine("
            " (SELECT embedding FROM chunk_vectors WHERE chunk_id = ?),"
            " (SELECT embedding FROM chunk_vectors WHERE chunk_id = ?)) AS d",
            (chunk_a, chunk_b),
        ).fetchone()
        return None if row is None or row["d"] is None else float(row["d"])

    def archive_node(self, node_id: str) -> None:
        """Archive a node: mark it archived and drop it from the embedded layer (so it
        no longer surfaces in retrieval), keeping the node and its raw turns for audit.
        """
        with self._conn:
            self._conn.execute(
                "UPDATE nodes SET status = 'archived', updated_at = ? WHERE id = ?",
                (_now(), node_id),
            )
            self._conn.execute(
                "DELETE FROM chunk_vectors WHERE chunk_id IN (SELECT id FROM chunks WHERE node_id = ?)",
                (node_id,),
            )
            self._conn.execute("DELETE FROM chunks WHERE node_id = ?", (node_id,))

    # ---- maintenance ----------------------------------------------------

    def backup(self, dest: str | Path) -> Path:
        """Online-backup the whole store to dest (safe under WAL)."""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        target = sqlite3.connect(str(dest))
        try:
            with target:
                self._conn.backup(target)
        finally:
            target.close()
        return dest

    def integrity_check(self) -> bool:
        row = self._conn.execute("PRAGMA integrity_check").fetchone()
        return row[0] == "ok"

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for table in ("nodes", "edges", "memory_raw", "chunks", "chunk_vectors"):
            out[table] = self._conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        return out

    # ---- internals ------------------------------------------------------

    def _get_by_type_title(self, type: str, title: str) -> sqlite3.Row | None:
        return self._conn.execute(
            "SELECT * FROM nodes WHERE type = ? AND title = ?", (type, title)
        ).fetchone()

    @staticmethod
    def _node_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        d["meta"] = json.loads(d["meta"]) if d.get("meta") else {}
        return d


def verify_store(path: str | Path) -> bool:
    """Open a store file read-only and integrity-check it. Used to verify backups
    without mutating them. Kept here so the engine is touched only by this module.
    """
    uri = f"file:{Path(path)}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        return conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        conn.close()


def restore(src: str | Path, db_path: str | Path) -> None:
    """Replace the store at db_path with the backup at src.

    No Repository may hold db_path open when this runs. Stale WAL sidecars are
    cleared so the restored file is authoritative.
    """
    src = Path(src)
    db_path = Path(db_path)
    if not src.exists():
        raise FileNotFoundError(f"backup not found: {src}")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    shutil.copy(src, db_path)
