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
    ) -> str:
        """Write a distilled session record, linked to its project.

        Creates a memory node (status unreviewed), links belongs_to the project,
        get-or-creates each mentioned entity and links it, stores raw turns in the
        raw layer, and embeds the distilled summary when an embedding is supplied.
        Embeddings come from the caller via the provider interface, never from here.
        """
        proj = self._get_by_type_title("project", project)
        if proj is None:
            raise ValueError(f"project not found: {project!r}; call upsert_project first")
        decisions = decisions or []
        entities = entities or []
        mem_id = _new_id()
        now = _now()
        meta = json.dumps({"decisions": decisions, "entities": entities})
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
