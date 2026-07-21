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
EDGE_PROVENANCE = ("explicit", "inferred", "ambiguous")
# Scope kinds: the two taxonomy levels above content nodes. Stored in `nodes` with
# type mirroring node_kind; node_kind is the authoritative discriminator.
SCOPE_KINDS = ("domain", "index")


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
        self._conn.execute("PRAGMA busy_timeout = 5000")
        self.initialize()

    # ---- lifecycle -------------------------------------------------------

    def _table_exists(self, table: str) -> bool:
        return self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone() is not None

    def initialize(self) -> None:
        """Create the schema if absent, then apply additive migrations. Idempotent."""
        self._recover_edges_rebuild()
        self._conn.executescript(SCHEMA_PATH.read_text())
        self._migrate()

    def _recover_edges_rebuild(self) -> None:
        """Heal a crash mid-rebuild of the edges table (see _migrate). sqlite3
        autocommits DDL, so a process that dies partway through the edges rebuild
        can leave the store between steps: `edges` renamed away with no
        replacement, or a `edges_new` build that never got swapped in. This must
        run before the schema script below, whose `CREATE TABLE IF NOT EXISTS
        edges` would otherwise paper over a missing table with an empty one and
        silently strand the real data in edges_old/edges_new.
        """
        with self._conn:
            if not self._table_exists("edges") and self._table_exists("edges_old"):
                # crashed before the rebuilt table was ever put in place: resume from scratch
                self._conn.execute("ALTER TABLE edges_old RENAME TO edges")
            if self._table_exists("edges_new"):
                if self._table_exists("edges"):
                    # crashed before DROP TABLE edges ran: the new build is stale
                    self._conn.execute("DROP TABLE edges_new")
                else:
                    # crashed between DROP TABLE edges and the final RENAME
                    self._conn.execute("ALTER TABLE edges_new RENAME TO edges")

    def _migrate(self) -> None:
        """Additive column migrations for stores created before a schema change
        (CREATE TABLE IF NOT EXISTS never alters an existing table)."""
        def cols(table: str) -> set[str]:
            return {r["name"] for r in self._conn.execute(f"PRAGMA table_info({table})")}

        with self._conn:
            node_cols = cols("nodes")
            if "community_id" not in node_cols:
                self._conn.execute("ALTER TABLE nodes ADD COLUMN community_id INTEGER")
            if "valid_from" not in node_cols:
                self._conn.execute("ALTER TABLE nodes ADD COLUMN valid_from TEXT")
                self._conn.execute("ALTER TABLE nodes ADD COLUMN invalidated_at TEXT")
            # nodes created before (or between) migrations start their validity at creation
            self._conn.execute(
                "UPDATE nodes SET valid_from = created_at WHERE valid_from IS NULL"
            )
            # V2 hierarchical taxonomy: scope kind + partition pointers + routing summary.
            # Added here (not in schema.sql) because executescript runs before this and
            # CREATE TABLE IF NOT EXISTS never alters an existing table; pre-existing rows
            # default to node_kind='node' (unclassified content), which is the intended
            # backward-compatible state.
            if "node_kind" not in node_cols:
                self._conn.execute(
                    "ALTER TABLE nodes ADD COLUMN node_kind TEXT NOT NULL DEFAULT 'node'"
                )
            if "domain_id" not in node_cols:
                self._conn.execute("ALTER TABLE nodes ADD COLUMN domain_id TEXT")
            if "index_id" not in node_cols:
                self._conn.execute("ALTER TABLE nodes ADD COLUMN index_id TEXT")
            if "summary" not in node_cols:
                self._conn.execute("ALTER TABLE nodes ADD COLUMN summary TEXT")
            if "summary_updated_at" not in node_cols:
                self._conn.execute("ALTER TABLE nodes ADD COLUMN summary_updated_at TEXT")
            # Scope indexes live here so they are created only after the columns exist
            # (a CREATE INDEX in schema.sql would run against the not-yet-migrated table).
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_kind ON nodes(node_kind)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_index ON nodes(index_id)")
            self._conn.execute("CREATE INDEX IF NOT EXISTS idx_nodes_domain ON nodes(domain_id)")
            edge_cols = cols("edges")
            if "provenance" not in edge_cols:
                # existing edges were all created by explicit tool calls; the default backfills them
                self._conn.execute(
                    "ALTER TABLE edges ADD COLUMN provenance TEXT NOT NULL DEFAULT 'explicit'"
                )
            if "confidence" not in edge_cols:
                self._conn.execute(
                    "ALTER TABLE edges ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0"
                )
            if "valid_from" not in edge_cols:
                # Bitemporal validity needs valid_from in the primary key (a severed link
                # must be re-creatable), and SQLite cannot alter a PK: rebuild the table.
                # Built forward (edges_new alongside the live edges table, then swapped
                # in) rather than renaming edges out of the way first, so a crash never
                # leaves the store without an edges table at all. The only vulnerable
                # window is between DROP TABLE edges and the RENAME below, and
                # _recover_edges_rebuild heals exactly that state on next open.
                self._conn.execute(
                    "CREATE TABLE edges_new ("
                    " src TEXT NOT NULL REFERENCES nodes(id),"
                    " dst TEXT NOT NULL REFERENCES nodes(id),"
                    " rel TEXT NOT NULL,"
                    " provenance TEXT NOT NULL DEFAULT 'explicit',"
                    " confidence REAL NOT NULL DEFAULT 1.0,"
                    " created_at TEXT NOT NULL,"
                    " valid_from TEXT NOT NULL,"
                    " invalidated_at TEXT,"
                    " PRIMARY KEY (src, dst, rel, valid_from))"
                )
                self._conn.execute(
                    "INSERT INTO edges_new(src,dst,rel,provenance,confidence,created_at,valid_from,invalidated_at)"
                    " SELECT src,dst,rel,provenance,confidence,created_at,created_at,NULL FROM edges"
                )
                self._conn.execute("DROP TABLE edges")
                self._conn.execute("ALTER TABLE edges_new RENAME TO edges")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst, rel)")
                self._conn.execute("CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src, rel)")
            # FTS backfill: stores that predate the keyword index (its triggers only see
            # writes made after they exist) get a one-time rebuild from the chunks table.
            # count(*) on an external-content fts5 table scans the CONTENT table, so the
            # indexed-row count must come from the docsize shadow table instead.
            fts_count = self._conn.execute("SELECT count(*) FROM chunk_fts_docsize").fetchone()[0]
            chunk_count = self._conn.execute("SELECT count(*) FROM chunks").fetchone()[0]
            if fts_count != chunk_count:
                self._conn.execute("INSERT INTO chunk_fts(chunk_fts) VALUES ('rebuild')")

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
        """All currently-valid nodes, optionally filtered by type. Used by the
        constellation graph, the Obsidian export, and Louvain clustering. Carries the
        taxonomy fields (node_kind/domain_id/index_id) so the constellation can render
        the domain -> index -> node level-of-detail without a second query."""
        cols = ("id, type, title, status, community_id,"
                " node_kind, domain_id, index_id, updated_at")
        if type is not None:
            rows = self._conn.execute(
                f"SELECT {cols} FROM nodes"
                " WHERE type = ? AND invalidated_at IS NULL ORDER BY updated_at DESC",
                (type,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                f"SELECT {cols} FROM nodes"
                " WHERE invalidated_at IS NULL ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def list_edges(self) -> list[dict[str, Any]]:
        """All currently-valid edges. Used by the constellation graph."""
        rows = self._conn.execute(
            "SELECT src, dst, rel, provenance, confidence FROM edges"
            " WHERE invalidated_at IS NULL"
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- constellation layout --------------------------------------------

    def get_layout(self) -> dict[str, dict[str, Any]]:
        """Persisted node positions, keyed by node id. The constellation restores these
        on load so the graph opens settled instead of re-simulating from scratch."""
        rows = self._conn.execute("SELECT node_id, x, y, pinned FROM node_layout").fetchall()
        return {
            r["node_id"]: {"x": r["x"], "y": r["y"], "pinned": bool(r["pinned"])}
            for r in rows
        }

    def node_history(self, node_id: str) -> dict[str, Any] | None:
        """The bitemporal timeline of a node: every edge it ever had (invalidated rows
        included, oldest first), its own validity window, and what superseded it
        (compaction summaries link derived_from back to their originals)."""
        node = self.get_node(node_id)
        if node is None:
            return None
        edges = self._conn.execute(
            "SELECT src, dst, rel, provenance, confidence, valid_from, invalidated_at"
            " FROM edges WHERE src = ? OR dst = ? ORDER BY valid_from",
            (node_id, node_id),
        ).fetchall()
        superseded_by = self._conn.execute(
            "SELECT n.id, n.title, n.created_at FROM edges e JOIN nodes n ON n.id = e.src"
            " WHERE e.dst = ? AND e.rel = 'derived_from'",
            (node_id,),
        ).fetchall()
        return {
            "node": {
                "id": node["id"],
                "title": node["title"],
                "type": node["type"],
                "status": node["status"],
                "valid_from": node.get("valid_from") or node["created_at"],
                "invalidated_at": node.get("invalidated_at"),
            },
            "edges": [dict(r) for r in edges],
            "superseded_by": [dict(r) for r in superseded_by],
        }

    def set_communities(self, assignment: dict[str, int]) -> int:
        """Persist community ids (node_id -> community). Nodes absent from the
        assignment keep their previous value. Returns rows updated."""
        with self._conn:
            for node_id, cid in assignment.items():
                self._conn.execute(
                    "UPDATE nodes SET community_id = ? WHERE id = ?", (cid, node_id)
                )
        return len(assignment)

    def save_layout(self, positions: list[dict[str, Any]]) -> int:
        """Upsert a batch of node positions. Each item: {node_id, x, y, pinned?}.
        Called after the simulation settles and on drag end. Returns rows written."""
        now = _now()
        with self._conn:
            for p in positions:
                self._conn.execute(
                    "INSERT INTO node_layout(node_id, x, y, pinned, updated_at)"
                    " VALUES (?,?,?,?,?)"
                    " ON CONFLICT(node_id) DO UPDATE SET x=excluded.x, y=excluded.y,"
                    " pinned=excluded.pinned, updated_at=excluded.updated_at",
                    (p["node_id"], float(p["x"]), float(p["y"]),
                     1 if p.get("pinned") else 0, now),
                )
        return len(positions)

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

    def update_node_meta(self, node_id: str, patch: dict[str, Any]) -> None:
        """Shallow-merge `patch` into a node's JSON meta (used to stash an ingest-time
        classification proposal). Keys set to None are removed."""
        row = self._conn.execute("SELECT meta FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            return
        meta = json.loads(row["meta"] or "{}")
        for key, value in patch.items():
            if value is None:
                meta.pop(key, None)
            else:
                meta[key] = value
        with self._conn:
            self._conn.execute(
                "UPDATE nodes SET meta = ?, updated_at = ? WHERE id = ?",
                (json.dumps(meta), _now(), node_id),
            )

    def node_scopes(self, node_ids: list[str]) -> dict[str, dict[str, Any]]:
        """Batch breadcrumb lookup: node_id -> {index_id, index, domain_id, domain} for a
        set of content nodes (used to annotate retrieval hits with their partition)."""
        if not node_ids:
            return {}
        placeholders = ",".join("?" * len(node_ids))
        rows = self._conn.execute(
            f"SELECT n.id, n.index_id, n.domain_id, i.title AS index_title,"
            f" d.title AS domain_title FROM nodes n"
            f" LEFT JOIN nodes i ON i.id = n.index_id"
            f" LEFT JOIN nodes d ON d.id = n.domain_id"
            f" WHERE n.id IN ({placeholders})",
            node_ids,
        ).fetchall()
        return {
            r["id"]: {
                "index_id": r["index_id"], "index": r["index_title"],
                "domain_id": r["domain_id"], "domain": r["domain_title"],
            }
            for r in rows
        }

    def node_chunk_texts(self, node_id: str) -> list[str]:
        """A node's chunk contents in order (fallback document body if no full text)."""
        rows = self._conn.execute(
            "SELECT content FROM chunks WHERE node_id = ? ORDER BY seq", (node_id,)
        ).fetchall()
        return [r["content"] for r in rows]

    def link_nodes(
        self, src: str, dst: str, rel: str,
        provenance: str = "explicit", confidence: float = 1.0,
    ) -> None:
        """Create a typed edge. Tool-call writes stay 'explicit' (the default); any
        future auto-linker must pass provenance='inferred' with its confidence."""
        if rel not in EDGE_RELS:
            raise ValueError(f"unknown edge relation: {rel!r}")
        if provenance not in EDGE_PROVENANCE:
            raise ValueError(f"unknown edge provenance: {provenance!r}")
        with self._conn:
            # One valid row per (src, dst, rel); invalidated history rows may coexist.
            exists = self._conn.execute(
                "SELECT 1 FROM edges WHERE src=? AND dst=? AND rel=? AND invalidated_at IS NULL",
                (src, dst, rel),
            ).fetchone()
            if exists:
                return
            now = _now()
            self._conn.execute(
                "INSERT OR IGNORE INTO edges(src,dst,rel,provenance,confidence,created_at,valid_from)"
                " VALUES (?,?,?,?,?,?,?)",
                (src, dst, rel, provenance, float(confidence), now, now),
            )

    def unlink_nodes(self, src: str, dst: str, rel: str) -> int:
        """Sever an edge: invalidate it rather than delete, so history stays queryable
        via node_history. Returns rows invalidated (0 if no valid edge existed)."""
        with self._conn:
            cur = self._conn.execute(
                "UPDATE edges SET invalidated_at = ? WHERE src = ? AND dst = ? AND rel = ?"
                " AND invalidated_at IS NULL",
                (_now(), src, dst, rel),
            )
            return cur.rowcount

    def delete_node(self, node_id: str) -> int:
        """Hard-delete a node and everything that depends on it: its vectors, chunks,
        raw turns, and every edge it touches (as src or dst). Returns 1 if the node
        existed, else 0.

        Note: planner tasks/goals reference a project node by a non-FK project_id; those
        links are intentionally not touched here (cross-subsystem), so a deleted project
        simply stops resolving to a title.
        """
        with self._conn:
            self._conn.execute(
                "DELETE FROM chunk_vectors WHERE chunk_id IN (SELECT id FROM chunks WHERE node_id = ?)",
                (node_id,),
            )
            self._conn.execute("DELETE FROM chunks WHERE node_id = ?", (node_id,))
            self._conn.execute("DELETE FROM memory_raw WHERE node_id = ?", (node_id,))
            self._conn.execute("DELETE FROM edges WHERE src = ? OR dst = ?", (node_id, node_id))
            self._conn.execute("DELETE FROM node_layout WHERE node_id = ?", (node_id,))
            self._conn.execute("DELETE FROM scope_vectors WHERE scope_id = ?", (node_id,))
            # If this node was a scope, detach any members that pointed at it so no
            # content node is left with a dangling domain_id/index_id (delete_scope is
            # the graceful path; this keeps the invariant even on a raw hard-delete).
            self._conn.execute(
                "UPDATE nodes SET domain_id = NULL, index_id = NULL, updated_at = ?"
                " WHERE domain_id = ? OR index_id = ?",
                (_now(), node_id, node_id),
            )
            cur = self._conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
            return cur.rowcount

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

    def keyword_chunks(
        self, query: str, node_ids: list[str] | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        """BM25 keyword search over chunk text (the FTS5 leg of hybrid retrieval),
        best match first. node_ids restricts to those nodes' chunks, mirroring
        scored_chunks. Free-form input is quoted term-by-term so FTS5 operators in a
        natural-language query cannot break the match expression."""
        terms = ['"' + t.replace('"', '') + '"' for t in query.split() if t.replace('"', '')]
        if not terms:
            return []
        base = (
            "SELECT c.id AS chunk_id, c.node_id, c.content,"
            " n.title, n.type, n.status, n.updated_at, bm25(chunk_fts) AS keyword_rank"
            " FROM chunk_fts f"
            " JOIN chunks c ON c.rowid = f.rowid"
            " JOIN nodes n ON n.id = c.node_id"
            " WHERE chunk_fts MATCH ?"
        )
        params: list[Any] = [" OR ".join(terms)]
        if node_ids is not None:
            if not node_ids:
                return []
            base += f" AND c.node_id IN ({','.join('?' * len(node_ids))})"
            params.extend(node_ids)
        base += " ORDER BY rank LIMIT ?"
        params.append(limit)
        return [dict(r) for r in self._conn.execute(base, params).fetchall()]

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
                    "SELECT dst AS other FROM edges WHERE src = ? AND invalidated_at IS NULL"
                    " UNION SELECT src AS other FROM edges WHERE dst = ? AND invalidated_at IS NULL",
                    (nid, nid),
                ).fetchall()
                for r in neighbours:
                    if r["other"] not in visited:
                        visited.add(r["other"])
                        nxt.add(r["other"])
            frontier = nxt
        return list(visited)

    def neighbors(
        self,
        node_ids: list[str],
        per_node: int = 6,
        min_confidence: float = 0.0,
        exclude: set[str] | None = None,
    ) -> dict[str, list[dict]]:
        """1-hop undirected neighbors for each seed node id, with edge metadata.
        Returns {seed_id: [{node_id, title, type, rel, confidence, provenance}, ...]}.
        Skips invalidated edges and invalidated neighbor nodes. Drops neighbors in
        `exclude` and any that equal the seed. Caps each seed's list to `per_node`,
        highest confidence first.
        """
        exclude = exclude or set()
        out: dict[str, list[dict]] = {}
        for seed in node_ids:
            rows = self._conn.execute(
                "SELECT e.rel, e.confidence, e.provenance,"
                " n.id AS node_id, n.title AS title, n.type AS type"
                " FROM edges e"
                " JOIN nodes n ON n.id = (CASE WHEN e.src = ? THEN e.dst ELSE e.src END)"
                " WHERE (e.src = ? OR e.dst = ?)"
                "   AND e.invalidated_at IS NULL"
                "   AND n.invalidated_at IS NULL"
                "   AND e.confidence >= ?",
                (seed, seed, seed, min_confidence),
            ).fetchall()
            items: list[dict] = []
            for r in rows:
                nid = r["node_id"]
                if nid == seed or nid in exclude:
                    continue
                items.append({
                    "node_id": nid, "title": r["title"], "type": r["type"],
                    "rel": r["rel"], "confidence": r["confidence"],
                    "provenance": r["provenance"],
                })
            items.sort(key=lambda x: x["confidence"], reverse=True)
            # A neighbor reached by more than one edge appears once, at its best edge.
            seen: set[str] = set()
            deduped: list[dict] = []
            for it in items:
                if it["node_id"] in seen:
                    continue
                seen.add(it["node_id"])
                deduped.append(it)
            out[seed] = deduped[:per_node]
        return out

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

    def rank_projects_by_similarity(
        self, query_embedding: list[float], k: int = 5
    ) -> list[dict[str, Any]]:
        """Rank quest lines (projects) by how closely their linked content matches a
        query vector. Each project is scored by its single nearest chunk (min cosine
        distance over everything that belongs_to it). Used to auto-route a new note or
        document to the quest line it is most related to, instead of a flat catch-all.
        """
        if len(query_embedding) != self.embed_dim:
            raise ValueError(f"query has {len(query_embedding)} dims, expected {self.embed_dim}")
        qv = serialize_float32(query_embedding)
        rows = self._conn.execute(
            "SELECT p.id, p.title, MIN(vec_distance_cosine(cv.embedding, ?)) AS distance"
            " FROM chunk_vectors cv"
            " JOIN chunks c ON c.id = cv.chunk_id"
            " JOIN nodes n ON n.id = c.node_id"
            " JOIN edges e ON e.src = n.id AND e.rel = 'belongs_to' AND e.invalidated_at IS NULL"
            " JOIN nodes p ON p.id = e.dst AND p.type = 'project'"
            " GROUP BY p.id ORDER BY distance LIMIT ?",
            (qv, k),
        ).fetchall()
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
            " WHERE e.dst = ? AND e.invalidated_at IS NULL AND n.invalidated_at IS NULL"
            " ORDER BY n.updated_at DESC",
            (proj["id"],),
        ).fetchall()
        out = self._node_row_to_dict(proj)
        out["linked"] = [dict(r) for r in linked]
        return out

    # ---- scopes: the V2 hierarchical taxonomy (domain -> index -> node) ---
    #
    # Domains and indexes are rows in `nodes` with node_kind in ('domain','index')
    # and type mirroring node_kind. The hierarchy is expressed by the domain_id /
    # index_id columns, NOT by edges: edges stay the association layer, the taxonomy
    # is the scoping layer. Integrity is enforced here, in application code:
    #   domain -> domain_id NULL, index_id NULL
    #   index  -> domain_id = its domain, index_id NULL
    #   node   -> both NULL (inbox) OR both set with index_id's domain == domain_id

    def add_scope(
        self, node_kind: str, title: str, *, domain_id: str | None = None, why: str | None = None
    ) -> str:
        """Create a domain or an index. An index must name an existing domain."""
        if node_kind not in SCOPE_KINDS:
            raise ValueError(f"unknown scope kind: {node_kind!r}")
        if node_kind == "index":
            if not domain_id:
                raise ValueError("an index requires a domain_id")
            parent = self.get_node(domain_id)
            if parent is None or parent.get("node_kind") != "domain":
                raise ValueError(f"domain_id does not point to a domain: {domain_id!r}")
        else:
            domain_id = None
        sid = _new_id()
        now = _now()
        meta = json.dumps({"why": why} if why else {})
        with self._conn:
            self._conn.execute(
                "INSERT INTO nodes(id,type,title,status,meta,node_kind,domain_id,"
                " valid_from,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (sid, node_kind, title, None, meta, node_kind, domain_id, now, now, now),
            )
        return sid

    def get_scope(self, scope_id: str) -> dict[str, Any] | None:
        """A domain or index node by id, or None if it is not a scope."""
        node = self.get_node(scope_id)
        if node is None or node.get("node_kind") not in SCOPE_KINDS:
            return None
        return node

    def list_scopes(self, stale_after: int = 10) -> dict[str, Any]:
        """Domains with their indexes, member-node counts, and summary freshness.
        A scope is stale when it has no summary yet, or when at least `stale_after`
        nodes have been filed into it since its last refresh."""
        domains = [
            self._node_row_to_dict(r)
            for r in self._conn.execute(
                "SELECT * FROM nodes WHERE node_kind = 'domain' AND invalidated_at IS NULL"
                " ORDER BY title"
            ).fetchall()
        ]
        indexes = [
            self._node_row_to_dict(r)
            for r in self._conn.execute(
                "SELECT * FROM nodes WHERE node_kind = 'index' AND invalidated_at IS NULL"
                " ORDER BY title"
            ).fetchall()
        ]
        idx_counts = {
            r["index_id"]: r["c"]
            for r in self._conn.execute(
                "SELECT index_id, count(*) AS c FROM nodes"
                " WHERE node_kind = 'node' AND index_id IS NOT NULL AND invalidated_at IS NULL"
                " GROUP BY index_id"
            ).fetchall()
        }
        dom_counts = {
            r["domain_id"]: r["c"]
            for r in self._conn.execute(
                "SELECT domain_id, count(*) AS c FROM nodes"
                " WHERE node_kind = 'node' AND domain_id IS NOT NULL AND invalidated_at IS NULL"
                " GROUP BY domain_id"
            ).fetchall()
        }

        def _stale(scope: dict[str, Any]) -> bool:
            if not scope.get("summary"):
                return True
            return int((scope.get("meta") or {}).get("pending_since_refresh", 0)) >= stale_after

        idx_by_domain: dict[str, list[dict[str, Any]]] = {}
        for idx in indexes:
            idx_by_domain.setdefault(idx.get("domain_id"), []).append({
                "id": idx["id"],
                "title": idx["title"],
                "summary": idx.get("summary"),
                "summary_updated_at": idx.get("summary_updated_at"),
                "node_count": idx_counts.get(idx["id"], 0),
                "stale": _stale(idx),
            })
        out_domains = [
            {
                "id": d["id"],
                "title": d["title"],
                "summary": d.get("summary"),
                "summary_updated_at": d.get("summary_updated_at"),
                "node_count": dom_counts.get(d["id"], 0),
                "stale": _stale(d),
                "indexes": idx_by_domain.get(d["id"], []),
            }
            for d in domains
        ]
        return {
            "domains": out_domains,
            "unclassified": self.unclassified_count(),
            "stale_count": sum(
                1 for d in domains if _stale(d)
            ) + sum(1 for i in indexes if _stale(i)),
        }

    def classify_node(self, node_id: str, index_id: str) -> dict[str, Any] | None:
        """File a content node into an index (sets index_id + its domain consistently).
        Clears any stored classification proposal and nudges the index toward a summary
        refresh. Returns the placement, or None if the node does not exist."""
        node = self.get_node(node_id)
        if node is None:
            return None
        if node.get("node_kind") not in (None, "node"):
            raise ValueError("only content nodes can be classified")
        idx = self.get_node(index_id)
        if idx is None or idx.get("node_kind") != "index":
            raise ValueError(f"index_id must point to an index: {index_id!r}")
        domain_id = idx.get("domain_id")
        meta = node.get("meta") or {}
        meta.pop("classification", None)
        now = _now()
        with self._conn:
            self._conn.execute(
                "UPDATE nodes SET index_id = ?, domain_id = ?, meta = ?, updated_at = ?"
                " WHERE id = ?",
                (index_id, domain_id, json.dumps(meta), now, node_id),
            )
            self._bump_pending(index_id)
            if domain_id:
                self._bump_pending(domain_id)
        return {"node_id": node_id, "index_id": index_id, "domain_id": domain_id}

    # kb_move_node is an alias of classify: re-filing is the same operation.
    move_node = classify_node

    def classify_community_nodes(self, community_ids: list[int], index_id: str) -> int:
        """Bulk-file every content node in the given Louvain communities into an index
        (the migration backfill, §7). Returns the number of nodes filed."""
        idx = self.get_node(index_id)
        if idx is None or idx.get("node_kind") != "index":
            raise ValueError(f"index_id must point to an index: {index_id!r}")
        if not community_ids:
            return 0
        domain_id = idx.get("domain_id")
        placeholders = ",".join("?" * len(community_ids))
        with self._conn:
            cur = self._conn.execute(
                "UPDATE nodes SET index_id = ?, domain_id = ?, updated_at = ?"
                " WHERE node_kind = 'node' AND invalidated_at IS NULL"
                f" AND community_id IN ({placeholders})",
                (index_id, domain_id, _now(), *community_ids),
            )
            return cur.rowcount

    def unclassify_node(self, node_id: str) -> bool:
        """Detach a content node back to the inbox (both scope pointers NULL)."""
        with self._conn:
            cur = self._conn.execute(
                "UPDATE nodes SET index_id = NULL, domain_id = NULL, updated_at = ?"
                " WHERE id = ? AND node_kind = 'node'",
                (_now(), node_id),
            )
            return cur.rowcount > 0

    def _bump_pending(self, scope_id: str) -> None:
        """Increment a scope's since-refresh counter (staleness nag). Open txn only."""
        row = self._conn.execute("SELECT meta FROM nodes WHERE id = ?", (scope_id,)).fetchone()
        if row is None:
            return
        meta = json.loads(row["meta"] or "{}")
        meta["pending_since_refresh"] = int(meta.get("pending_since_refresh", 0)) + 1
        self._conn.execute("UPDATE nodes SET meta = ? WHERE id = ?", (json.dumps(meta), scope_id))

    def unclassified_count(self) -> int:
        return self._conn.execute(
            "SELECT count(*) FROM nodes WHERE node_kind = 'node' AND index_id IS NULL"
            " AND invalidated_at IS NULL"
        ).fetchone()[0]

    def unclassified_nodes(self, limit: int = 50) -> list[dict[str, Any]]:
        """The inbox: content nodes not yet filed into an index, newest first. Each row
        carries its stored classification proposal (if ingest left one) for the UI."""
        rows = self._conn.execute(
            "SELECT id, type, title, status, context_summary, meta, updated_at FROM nodes"
            " WHERE node_kind = 'node' AND index_id IS NULL AND invalidated_at IS NULL"
            " ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            d = dict(r)
            meta = json.loads(d.pop("meta") or "{}")
            d["proposal"] = meta.get("classification")
            out.append(d)
        return out

    def node_breadcrumb(self, node_id: str) -> dict[str, Any]:
        """A content node's domain/index placement (titles + ids), for the payload
        breadcrumb. Empty dict fields when unclassified."""
        row = self._conn.execute(
            "SELECT domain_id, index_id FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        if row is None:
            return {}
        out = {"domain_id": row["domain_id"], "index_id": row["index_id"],
               "domain": None, "index": None}
        if row["domain_id"]:
            d = self._conn.execute("SELECT title FROM nodes WHERE id = ?", (row["domain_id"],)).fetchone()
            out["domain"] = d["title"] if d else None
        if row["index_id"]:
            i = self._conn.execute("SELECT title FROM nodes WHERE id = ?", (row["index_id"],)).fetchone()
            out["index"] = i["title"] if i else None
        return out

    def scope_member_ids(
        self, index_ids: list[str] | None = None, domain_ids: list[str] | None = None
    ) -> list[str]:
        """Content node ids inside the given indexes and/or domains (currently valid).
        The candidate set for scoped retrieval."""
        clauses, params = [], []
        if index_ids:
            clauses.append(f"index_id IN ({','.join('?' * len(index_ids))})")
            params.extend(index_ids)
        if domain_ids:
            clauses.append(f"domain_id IN ({','.join('?' * len(domain_ids))})")
            params.extend(domain_ids)
        if not clauses:
            return []
        sql = (
            "SELECT id FROM nodes WHERE node_kind = 'node' AND invalidated_at IS NULL"
            f" AND ({' OR '.join(clauses)})"
        )
        return [r["id"] for r in self._conn.execute(sql, params).fetchall()]

    def scope_sample(self, scope_id: str, node_limit: int = 20, chunk_limit: int = 10) -> dict[str, Any]:
        """Material for generating a scope summary: the scope's own title, a sample of
        member titles, and a few representative chunk texts. Works for a domain (all its
        members) or an index (its members)."""
        scope = self.get_scope(scope_id)
        if scope is None:
            return {}
        col = "domain_id" if scope["node_kind"] == "domain" else "index_id"
        titles = [
            r["title"]
            for r in self._conn.execute(
                f"SELECT title FROM nodes WHERE node_kind = 'node' AND {col} = ?"
                " AND invalidated_at IS NULL ORDER BY updated_at DESC LIMIT ?",
                (scope_id, node_limit),
            ).fetchall()
        ]
        chunks = [
            r["content"]
            for r in self._conn.execute(
                f"SELECT c.content FROM chunks c JOIN nodes n ON n.id = c.node_id"
                f" WHERE n.node_kind = 'node' AND n.{col} = ? AND n.invalidated_at IS NULL"
                " ORDER BY c.created_at DESC LIMIT ?",
                (scope_id, chunk_limit),
            ).fetchall()
        ]
        return {"title": scope["title"], "kind": scope["node_kind"],
                "titles": titles, "chunks": chunks}

    def set_scope_summary(
        self, scope_id: str, summary_text: str, embedding: list[float] | None = None
    ) -> bool:
        """Store a scope's routing summary, embed it into scope_vectors, stamp the
        refresh time, and reset the staleness counter. Returns False if not a scope."""
        scope = self.get_scope(scope_id)
        if scope is None:
            return False
        meta = scope.get("meta") or {}
        meta["pending_since_refresh"] = 0
        now = _now()
        with self._conn:
            self._conn.execute(
                "UPDATE nodes SET summary = ?, summary_updated_at = ?, meta = ?, updated_at = ?"
                " WHERE id = ?",
                (summary_text, now, json.dumps(meta), now, scope_id),
            )
            if embedding is not None:
                if len(embedding) != self.embed_dim:
                    raise ValueError(
                        f"embedding has {len(embedding)} dims, expected {self.embed_dim}"
                    )
                self._conn.execute("DELETE FROM scope_vectors WHERE scope_id = ?", (scope_id,))
                self._conn.execute(
                    "INSERT INTO scope_vectors(scope_id, embedding) VALUES (?, ?)",
                    (scope_id, serialize_float32(embedding)),
                )
        return True

    def rank_scopes(
        self, query_embedding: list[float], kind: str = "index", limit: int = 2
    ) -> list[dict[str, Any]]:
        """Rank domains or indexes by cosine similarity of their summary embedding to a
        query. The routing step: cheap (tens of vectors). Returns best first with a
        `similarity` in [0, 1]. Only scopes that have an embedded summary participate."""
        if kind not in SCOPE_KINDS:
            raise ValueError(f"unknown scope kind: {kind!r}")
        if len(query_embedding) != self.embed_dim:
            raise ValueError(f"query has {len(query_embedding)} dims, expected {self.embed_dim}")
        rows = self._conn.execute(
            "SELECT sv.scope_id, n.title, n.domain_id,"
            " vec_distance_cosine(sv.embedding, ?) AS distance"
            " FROM scope_vectors sv JOIN nodes n ON n.id = sv.scope_id"
            " WHERE n.node_kind = ? AND n.invalidated_at IS NULL"
            " ORDER BY distance LIMIT ?",
            (serialize_float32(query_embedding), kind, limit),
        ).fetchall()
        return [
            {"scope_id": r["scope_id"], "title": r["title"], "domain_id": r["domain_id"],
             "similarity": 1.0 - float(r["distance"])}
            for r in rows
        ]

    def delete_scope(self, scope_id: str) -> dict[str, Any] | None:
        """Delete a domain or index, detaching its member nodes back to the inbox. Never
        cascades node deletion. Deleting a domain also removes its indexes. Returns
        {detached, removed_scopes} or None if the id is not a scope."""
        scope = self.get_scope(scope_id)
        if scope is None:
            return None
        now = _now()
        with self._conn:
            if scope["node_kind"] == "index":
                detached = self._conn.execute(
                    "UPDATE nodes SET index_id = NULL, domain_id = NULL, updated_at = ?"
                    " WHERE index_id = ? AND node_kind = 'node'",
                    (now, scope_id),
                ).rowcount
                removed = [scope_id]
            else:  # domain: detach all members, then drop its indexes and itself
                detached = self._conn.execute(
                    "UPDATE nodes SET index_id = NULL, domain_id = NULL, updated_at = ?"
                    " WHERE domain_id = ? AND node_kind = 'node'",
                    (now, scope_id),
                ).rowcount
                index_ids = [
                    r["id"] for r in self._conn.execute(
                        "SELECT id FROM nodes WHERE node_kind = 'index' AND domain_id = ?",
                        (scope_id,),
                    ).fetchall()
                ]
                removed = index_ids + [scope_id]
            placeholders = ",".join("?" * len(removed))
            self._conn.execute(
                f"DELETE FROM scope_vectors WHERE scope_id IN ({placeholders})", removed
            )
            self._conn.execute(
                f"DELETE FROM node_layout WHERE node_id IN ({placeholders})", removed
            )
            self._conn.execute(
                f"DELETE FROM nodes WHERE id IN ({placeholders})", removed
            )
        return {"detached": detached, "removed_scopes": len(removed)}

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
                "INSERT OR IGNORE INTO edges(src,dst,rel,created_at,valid_from) VALUES (?,?,?,?,?)",
                (mem_id, proj["id"], "belongs_to", now, now),
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
                    "INSERT OR IGNORE INTO edges(src,dst,rel,created_at,valid_from) VALUES (?,?,?,?,?)",
                    (mem_id, ent_id, "mentions", now, now),
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

    # ---- full-fidelity read (drill-down-to-raw) -------------------------

    def node_chunks(self, node_id: str) -> list[dict[str, Any]]:
        """A node's stored chunk texts in sequence order: the full embedded text,
        un-truncated (retrieval elsewhere clips context_summary to a snippet)."""
        rows = self._conn.execute(
            "SELECT seq, content FROM chunks WHERE node_id = ? ORDER BY seq",
            (node_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_raw_turns(self, node_id: str) -> list[dict[str, Any]]:
        """The raw conversation turns stored for a memory node, in order. The raw layer is
        write-through and unindexed by design (only distilled summaries are embedded); this
        is its read path, used by drill-down-to-raw when a summary is too thin."""
        rows = self._conn.execute(
            "SELECT turn_index, role, content, created_at FROM memory_raw"
            " WHERE node_id = ? ORDER BY turn_index",
            (node_id,),
        ).fetchall()
        return [dict(r) for r in rows]

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
            " WHERE e.dst = ? AND e.rel = 'belongs_to' AND e.invalidated_at IS NULL"
            " AND n.type = 'memory'"
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
        Its edges are invalidated too - except derived_from lineage, which documents
        the supersede event itself and must stay current for kb_history.
        """
        with self._conn:
            now = _now()
            self._conn.execute(
                "UPDATE nodes SET status = 'archived', updated_at = ?,"
                " invalidated_at = COALESCE(invalidated_at, ?) WHERE id = ?",
                (now, now, node_id),
            )
            self._conn.execute(
                "UPDATE edges SET invalidated_at = ? WHERE (src = ? OR dst = ?)"
                " AND rel != 'derived_from' AND invalidated_at IS NULL",
                (now, node_id, node_id),
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
