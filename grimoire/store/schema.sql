-- The Grimoire store schema (SQLite + sqlite-vec).
-- Owned exclusively by the repository layer. No other module issues SQL.

-- Nodes: the four types are 'document' | 'memory' | 'project' | 'entity'.
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY,            -- uuid
  type TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT,                    -- projects: idea|active|shipped|archived
                                  -- memory/docs: unreviewed|reviewed|error
  meta TEXT,                      -- JSON, type-specific metadata
  context_summary TEXT,          -- projects: the living summary; others: optional
  community_id INTEGER,          -- Louvain community (kb_recluster); NULL = unclustered
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Edges: typed links. rel is 'belongs_to' | 'references' | 'mentions' | 'derived_from'.
-- provenance: 'explicit' (a user/agent tool call) | 'inferred' (auto-linking logic) |
-- 'ambiguous'. confidence rides alongside (1.0 for explicit) for future auto-linkers.
CREATE TABLE IF NOT EXISTS edges (
  src TEXT NOT NULL REFERENCES nodes(id),
  dst TEXT NOT NULL REFERENCES nodes(id),
  rel TEXT NOT NULL,
  provenance TEXT NOT NULL DEFAULT 'explicit',
  confidence REAL NOT NULL DEFAULT 1.0,
  created_at TEXT NOT NULL,
  PRIMARY KEY (src, dst, rel)
);

-- Raw memory layer: cheap, never embedded. Audit and replay only.
CREATE TABLE IF NOT EXISTS memory_raw (
  id TEXT PRIMARY KEY,
  node_id TEXT NOT NULL REFERENCES nodes(id),
  turn_index INTEGER,
  role TEXT,
  content TEXT,
  created_at TEXT NOT NULL
);

-- Chunks: the embedded layer for documents and distilled memory summaries.
CREATE TABLE IF NOT EXISTS chunks (
  id TEXT PRIMARY KEY,
  node_id TEXT NOT NULL REFERENCES nodes(id),
  seq INTEGER,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- Vector index. Dimension is fixed at 768; changing it is a re-embedding operation.
CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vectors USING vec0(
  chunk_id TEXT PRIMARY KEY,
  embedding float[768]
);

-- Persisted constellation layout (fixed anchors + settled, frozen leaves).
-- One row per node that has a placed position. `pinned` = the user (or the anchor rule)
-- fixed it; the force simulation must never move it. Absent row = not yet laid out.
CREATE TABLE IF NOT EXISTS node_layout (
  node_id TEXT PRIMARY KEY REFERENCES nodes(id),
  x REAL NOT NULL,
  y REAL NOT NULL,
  pinned INTEGER NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL
);

-- Traversal and lookup indexes (the read path leans on these).
CREATE INDEX IF NOT EXISTS idx_edges_dst ON edges(dst, rel);
CREATE INDEX IF NOT EXISTS idx_edges_src ON edges(src, rel);
CREATE INDEX IF NOT EXISTS idx_chunks_node ON chunks(node_id);
CREATE INDEX IF NOT EXISTS idx_nodes_type_title ON nodes(type, title);
CREATE INDEX IF NOT EXISTS idx_memory_raw_node ON memory_raw(node_id);
