# BUILDPLAN.md

The Grimoire — phased build plan. Backend and a minimal dashboard advance in parallel so every milestone has something you can see.

## Stack decisions

Mostly locked. The store engine is the one open evaluation, settled in Phase 0.

- Store: decide in Phase 0. Recommended direction is SurrealDB for long-term fit (graph-native traversal, multi-model, real concurrency for an ever-growing and eventually multi-agent system), conditional on the Phase 0 backup routine being in place first. SQLite + sqlite-vec remains the safe-durability fallback. The repository layer (below) makes this reversible either way. Full tradeoff in ARCHITECTURE "Built to evolve."
- Repository layer (rule): all store access goes through one module of intent-level methods (get_project, link_nodes, search, write_memory). No query or engine call lives anywhere else. This is what makes the store engine swappable and the Phase 0 choice non-permanent. Same insurance pattern as the provider interface.
- Embeddings: 768-dim local model (e.g. nomic-embed-text or bge-base via Ollama). Cheapest on storage, good enough for retrieval. Changing dimensions later means re-embedding everything — supported as a planned routine (see Phase 0 and the re-embedding job), not improvised.
- Provider abstraction (rule): all LLM and embedding calls go through one thin provider interface, never hardcoded to a vendor or model. This is the cheap insurance against the embedding-dimension and model-choice decisions — swapping a provider becomes a config change, not a rewrite. Pattern borrowed from open-notebook's Esperanto layer; build a minimal version, do not take on the dependency.
- Backend: Python (FastAPI) or Node (Fastify). Pick whichever you ship faster in. The MCP gateway and the knowledge service live in the same process at this scale.
- Graph: edges stored in the store engine (edge tables in SQLite, or native graph edges in SurrealDB). No separate graph database either way. Traversal is joins or native graph queries.
- Ingestion automation: n8n, self-hosted (existing setup with Cloudflare Tunnel; Oracle Cloud Always Free VM as the permanent home).
- Dashboard: React + Vite. Force-directed graph via d3-force or cytoscape.js.
- Document conversion: PDF to markdown via a local converter (pymupdf4llm or marker). Never embed raw PDF bytes.
- Deployment: Docker Compose bundling the store, the API/gateway, and n8n as services. Pattern reference: open-notebook's compose setup. You already know Compose from GoatedTracking.

## Phase 0 — Foundations

Tasks:
- Initialize the repo with this file, CLAUDE.md, and ARCHITECTURE.md at the root.
- Decide the store engine. Recommended direction: SurrealDB for long-term graph-native fit (see ARCHITECTURE "Built to evolve"); SQLite + sqlite-vec is the safe-durability fallback. open-notebook (25k stars) uses SurrealDB for this exact graph-plus-vector shape. Write the choice and the reason at the top of ARCHITECTURE.md. This choice is reversible because of the repository layer, so do not over-agonize — pick, record, move.
- Build the repository layer first: one module of intent-level methods (get_project, link_nodes, search, write_memory, upsert_project). Everything else calls these; nothing else touches the store. This module is the only place that knows which engine is underneath.
- Build the provider interface: one thin module wrapping embed() and complete() so no other code references a vendor or model directly.
- Build the backup-and-restore routine and test it by actually restoring before any real data lands. Non-negotiable, especially if the engine is SurrealDB. Automated and scheduled.
- Create the store with the chosen engine and the schema below (behind the repository layer).
- Stand up Ollama (or chosen runtime) with the embedding model, behind the provider interface, and verify embed round-trip.
- Stub the re-embedding routine now (even if trivial): a documented job that walks every chunk and re-embeds through the provider interface. It becomes real the first time you change models; having the seam from day one means that day is routine.

Schema (SQLite-flavored; the same node/edge/chunk/vector model translates directly to SurrealDB tables and native edges if that engine is chosen):

```sql
-- Nodes
CREATE TABLE nodes (
  id TEXT PRIMARY KEY,            -- uuid
  type TEXT NOT NULL,             -- 'document' | 'memory' | 'project' | 'entity'
  title TEXT NOT NULL,
  status TEXT,                    -- projects: idea|active|shipped|archived
                                  -- memory/docs: unreviewed|reviewed|error
  meta JSON,                      -- type-specific metadata (client, stack, source url, etc.)
  context_summary TEXT,           -- projects: the living summary. others: optional
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

-- Edges (typed links)
CREATE TABLE edges (
  src TEXT NOT NULL REFERENCES nodes(id),
  dst TEXT NOT NULL REFERENCES nodes(id),
  rel TEXT NOT NULL,              -- 'belongs_to' | 'references' | 'mentions' | 'derived_from'
  created_at TEXT NOT NULL,
  PRIMARY KEY (src, dst, rel)
);

-- Raw memory layer (cheap, never embedded)
CREATE TABLE memory_raw (
  id TEXT PRIMARY KEY,
  node_id TEXT NOT NULL REFERENCES nodes(id),
  turn_index INTEGER,
  role TEXT,
  content TEXT,
  created_at TEXT NOT NULL
);

-- Chunks (the embedded layer for documents and memory summaries)
CREATE TABLE chunks (
  id TEXT PRIMARY KEY,
  node_id TEXT NOT NULL REFERENCES nodes(id),
  seq INTEGER,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

-- Vector index (sqlite-vec virtual table)
CREATE VIRTUAL TABLE chunk_vectors USING vec0(
  chunk_id TEXT PRIMARY KEY,
  embedding float[768]
);
```

Acceptance: insert a node, an edge, a chunk, and a vector through the repository layer (not raw queries); query nearest-neighbor and get it back; run a backup, wipe, and restore successfully.

## Phase 1 — Document pipeline + retrieval

Tasks:
- Build ingest_document(path or url): convert PDF/HTML to markdown, chunk at ~500 tokens with small overlap, embed each chunk, write node + chunks + vectors.
- Build the read path as one function the gateway will later expose:

```
retrieve(query, project_id=None, k=10):
  1. if project_id: candidate_chunks = chunks of nodes linked to project (1-2 hops)
     else: candidate_chunks = all chunks
  2. vector search query embedding against candidates
  3. score = similarity * recency_decay(updated_at)
  4. return top k with node metadata
```

- Recency decay: simple exponential, half-life ~90 days. Tune later.
- Minimal dashboard milestone: document list + search box returning ranked results. Ugly is fine.

Acceptance: ingest 10 real PDFs (GHL docs, Django docs), ask 5 real questions, get relevant chunks back. If retrieval is bad here, fix it before moving on — everything downstream depends on it.

## Phase 2 — MCP gateway

Tasks:
- Wrap the knowledge service in an MCP server exposing:
  - kb_retrieve(query, project?, k?) — the read path
  - kb_write_memory(project, summary, decisions[], entities[]) — distilled session write
  - kb_get_project(name) — project node + context summary + linked node list
  - kb_upsert_project(name, meta, context_patch) — create or update a project hub
  - kb_ingest_document(path, project?) — document pipeline trigger
- Connect Claude Code first. Prove: pull context at session start, write a memory node at session end.
- Then connect Codex CLI and Antigravity — each is just another MCP client pointing at the same gateway.

Acceptance: a Claude Code session retrieves prior context about a project without you re-explaining it, and its session summary appears in the store afterward.

## Phase 3 — Memory + project context

Tasks:
- Conversation capture: one cheap LLM call distills a session into decisions, code/config produced, open questions, entities mentioned. Write summary as a memory node; write raw turns to memory_raw; auto-link to the touched project; mark status unreviewed.
- Project hubs: create project nodes for current real projects (ROAR, FTV Mushrooms, GoatedTracking) and backfill links.
- Ideas path: a project with status idea, title + paragraph only. Graduation to active preserves the node id so lineage holds.
- Dashboard milestone: project view — click a project, see context summary, linked conversations, linked docs. This becomes the most-used screen.

### Phase 3b — History backfill (one-time)

Seed the store with all past Claude conversations so the base starts populated, not empty.

- Export: claude.ai Settings -> Privacy -> Export data. The emailed download contains conversations.json: every conversation, every turn, timestamps.
- Backfill script: iterate conversations.json; for each conversation run the same distillation call as live capture (decisions, code/config, open questions, entities); write summary as a memory node with the original conversation date as created_at; write raw turns to memory_raw; link to a project when one is identifiable from content (ROAR, FTV, GoatedTracking, Grimoire, etc.), otherwise leave unlinked for manual triage in the review queue.
- Mark all backfilled nodes unreviewed. Skim the review queue afterward; fix mislinked projects there.
- Cost control: distillation is one cheap LLM call per conversation. A few hundred conversations is a few dollars and an afternoon, not a project. Run compaction once after backfill to merge near-duplicate topics from the start.
- Do not put conversation history in CLAUDE.md. That file is loaded every session; history belongs in the store, retrieved only when relevant.

Acceptance: search the dashboard for a topic you know you discussed months ago and get the distilled memory back, linked to the right project.

Acceptance: open the ROAR project in the dashboard and see its real accumulated context.

## Phase 4 — n8n capture endpoint + automation

Tasks:
- One ingestion webhook in n8n accepting two payload types: conversation_capture and project_context. Both call the gateway's write tools.
- Wire conversation capture to fire after sessions (manual trigger first, automation second).
- Optional: scheduled GHL and Zapier API pollers pulling build structure (pipelines, workflows, forms) into project context so it stays current as you edit, not only when you log it.

Acceptance: finish a working session, and within a minute the distilled memory shows in the dashboard flagged unreviewed.

## Phase 5 — Compaction

Tasks:
- Scheduled job (cron or n8n): for each project, find memory summaries older than N days on overlapping topics, merge into one consolidated summary, archive the originals (keep raw), re-embed the merged result.
- Consolidate each project's context_summary from its recent memory.
- Promote the re-embedding routine stubbed in Phase 0 to a working job: walk every chunk, re-embed through the provider interface, swap in the new vectors transactionally. This is the maintenance path for changing embedding models over the years; it lives next to compaction because both are scheduled store-maintenance jobs. Test it by re-embedding the whole store with the same model and confirming retrieval is unchanged.

This is load-bearing, not polish. Build it now. Memory and project nodes start rotting the moment they accumulate, and compaction is also what keeps the vector count — and therefore storage — flat.

Acceptance: after compaction, a query that previously returned near-duplicate fragments returns one consolidated summary.

## Phase 6 — The grimoire UI

Now the data model is real and the UI has something true to draw.

Tasks:
- Constellation home view: force-directed graph (d3-force or cytoscape), nodes colored by type per the design system in CLAUDE.md, edges carrying the parent color, drag/zoom/pan. Hand-placed coordinates do not scale; physics layout from the start. SVG is fine to low hundreds of nodes; plan to switch to canvas/WebGL (cytoscape canvas renderer or sigma.js) when the base reaches thousands. This is an expected upgrade, not a rewrite — keep rendering behind a component boundary so the switch is local.
- Skill-tree reveal: nodes dim until traversed, brighten on visit. Status-as-glow: steady = reviewed, faint pulse = unreviewed, red rim = error.
- Node detail panels: grimoire chrome, plain legible content.
- Review queue: list unreviewed memory and project updates, mark reviewed, prune.
- Typography and palette exactly as specified in CLAUDE.md (Cinzel + Spectral, dark arcane palette, four rune colors).

Acceptance: open the dashboard, see your actual knowledge base as the lit constellation, click into a project, read its context comfortably.

## Scope discipline

- Keep: dashboard polish (you live in it), UI/UX quality on the constellation and project views.
- Drop: agent-to-agent messaging, multi-user anything, cloud sync, a dedicated vector database. One store, one gateway, four node types.
- If tempted to start at Phase 6 because it is the fun one: a beautiful grimoire over an unproven store is wasted work. The constellation is only worth looking at when it draws real nodes from a real graph.
