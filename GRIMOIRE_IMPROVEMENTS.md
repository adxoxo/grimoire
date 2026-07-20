# Grimoire Improvement Plan

Execution spec for Claude Code. Work through phases in order. Each phase is independently shippable — commit after each one. Do not start a phase until the previous phase's acceptance criteria pass.

**Stack context:** FastMCP server + SQLite/sqlite-vec backend, React constellation UI (force-directed graph). Node types include: project, goal, task, habit, memory, document/chunk, quest line, tome, chronicle, rune. Edge types include: belongs_to, references, related_to, and project↔memory links.

---

## Phase 1 — Kill the drifting graph (fixed anchors + settled layout)

**Problem:** All nodes are in one force simulation. Everything moves, nothing settles, the graph looks chaotic compared to Obsidian-style views.

### 1.1 Pin anchor nodes

- Classify nodes into **anchors** (projects, goals) and **leaves** (tasks, memories, habits, document chunks).
- Anchors get **fixed positions** (`fx`, `fy` in d3-force, or the equivalent in whatever force lib the constellation UI uses). Compute their initial positions once with a deterministic layout — a simple circular or grid arrangement of projects is fine for v1 — and persist those coordinates.
- **Persist positions to SQLite.** Add a `node_layout` table: `node_id, x, y, pinned (bool), updated_at`. On load, restore saved positions. Never re-randomize an anchor that already has coordinates.
- Allow drag-to-reposition on anchors in the UI; on drag end, write the new position back to `node_layout`.

### 1.2 Settle, then freeze

- Run the force simulation for leaves only, for a **fixed tick budget** (e.g. 300 ticks) on first layout, then **stop the simulation entirely** (`simulation.stop()`). No perpetual wiggling.
- On subsequent loads, restore leaf positions from `node_layout` too and skip simulation unless nodes were added/removed since last save.
- New nodes since last layout: spawn them near their parent anchor (small random offset), run a short local re-simulation (50–100 ticks) touching only the new nodes and their immediate neighbors, then freeze and persist.

### 1.3 Edge stiffness by relationship type

Different link distances/strengths per edge type so clusters visually form:

| Edge type | Link distance | Strength |
|---|---|---|
| belongs_to (task→project, task→goal) | short (~40) | high (0.9) |
| habit→goal, memory→project | medium (~80) | medium (0.5) |
| references / related_to | long (~160) | low (0.1) |

Tune values by eye after first render; the ratios matter more than absolutes.

**Acceptance criteria (Phase 1):**
- Opening the graph twice in a row shows the identical layout.
- Nothing moves on screen unless the user drags a node.
- Tasks visibly cluster around their project/goal anchors.
- Dragging a project and reloading preserves the new position.

---

## Phase 2 — Default to local view, not the hairball

**Problem:** Rendering the entire graph at once is the main source of "messy." Obsidian's clean look is mostly its *local graph* (1-hop from current note), not the global view.

- Add a **focus mode**: default view is one project hub + its 1-hop neighborhood (this is exactly what `kb_get_project` already returns — reuse that query).
- Global "everything" view stays available behind a toggle, but is not the default.
- In focus mode, add a **depth slider** (1–3 hops).
- Node click → refocus the view on that node's neighborhood (Obsidian local-graph behavior).
- Fade, don't hide: when refocusing, out-of-scope nodes fade to ~10% opacity for 300ms before removal, so navigation feels spatial rather than jumpy.

**Acceptance criteria (Phase 2):**
- Opening the graph lands on the most recently active project's local view, not the full graph.
- Clicking any node recenters on it within one interaction.
- The full-graph toggle still works.

---

## Phase 3 — Community detection + visual grouping (the Graphify trick)

**Problem:** Clean-looking graphs (Graphify, Obsidian with plugins) cluster nodes into communities and color by community. Grimoire renders raw topology with no grouping.

- Add a clustering pass server-side (Python): run **Leiden** (via `leidenalg` + `igraph`, or `networkx` Louvain as a fallback if Leiden deps are a hassle on the VPS) over the full node/edge graph.
- Persist results: add `community_id` column to nodes (or a `node_community` table). Recompute on demand via a new MCP tool `kb_recluster` — not on every write.
- UI: color nodes by community using the aquryu palette family (derive shades from leaf green #4F7A52 / glow green #7BB77E plus 4–6 additional distinguishable hues; keep it muted, no rainbow).
- Optional v1.1: draw a soft convex hull or blur blob behind each community in the global view.
- Label communities: for each community, pick the highest-degree node's title as the label. No LLM call needed for v1.

**Acceptance criteria (Phase 3):**
- Global view shows visibly distinct colored clusters.
- `kb_recluster` runs in under ~5s on the current graph size and persists community assignments.
- Communities are stable across reruns when the graph hasn't changed.

---

## Phase 4 — Edge provenance tags (EXTRACTED vs INFERRED)

**Problem:** No way to tell which relationships were explicitly created vs derived. This blocks trust in the graph and blocks future auto-linking features.

- Add `provenance` column to the edges table: `explicit` (created by user or agent via a tool call) | `inferred` (created by resolution/auto-linking logic) | `ambiguous`.
- Backfill all existing edges as `explicit`.
- All current MCP write tools set `explicit` by default. Any future auto-linker must set `inferred`.
- UI: inferred edges render dashed and lighter; explicit edges solid.
- Add `confidence REAL` alongside (default 1.0 for explicit) for future use.

**Acceptance criteria (Phase 4):**
- Schema migrated with no data loss; all existing edges tagged `explicit`.
- A manually created edge renders solid; a test-inserted `inferred` edge renders dashed.

---

## Phase 5 — Temporal validity (lightweight Graphiti idea, not the stack)

**Problem:** Edits destroy history. "What did I decide before I changed my mind" is unanswerable — and it's the one capability markdown-in-a-folder can never have.

- Add `valid_from` (datetime, default now) and `invalidated_at` (datetime, nullable) to edges and to the memory table.
- Change semantics of updates: modifying a relationship or superseding a memory sets `invalidated_at` on the old row and inserts a new row, instead of UPDATE-in-place. Deletes of nodes can stay hard deletes for now.
- Default all read queries to `WHERE invalidated_at IS NULL`.
- Add MCP tool `kb_history(node_id)` returning the invalidated timeline for a node's edges/memories.
- Do **not** adopt Neo4j/Graphiti itself. This is a two-column schema change on SQLite.

**Acceptance criteria (Phase 5):**
- All existing reads behave identically (nothing is invalidated yet).
- Superseding a memory keeps the old one queryable via `kb_history`.

---

## Phase 6 — Obsidian/markdown export (the pretty-view escape hatch)

**Problem:** Competing with Obsidian's graph renderer is a losing game. Export to it instead; keep the custom UI for what Obsidian can't do (today view, urgency, habits, computed state).

- New MCP tool + CLI script `kb_export_markdown(output_dir)`:
  - One `.md` file per node, filename = slugified title, frontmatter = `type, community, created, tags`.
  - Every edge becomes a `[[wikilink]]` in the body, grouped under headings by edge type (`## Belongs to`, `## References`, `## Memories`).
  - Only export currently-valid edges (respects Phase 5).
  - Folder structure: `export/<node_type>/<slug>.md`.
- Idempotent: re-export overwrites the export dir cleanly. Export dir is disposable — Grimoire's SQLite stays the source of truth. One-way sync only; do not build markdown→SQLite import in this phase.

**Acceptance criteria (Phase 6):**
- Opening the export folder as an Obsidian vault shows a connected, navigable graph with working wikilinks.
- Re-running export after adding a node updates the vault without duplicates.

---

---

## Phase 7 — Hybrid retrieval (FTS5 + vectors)

**Problem:** `kb_retrieve` is pure vector similarity × recency decay. Vector search is weak on exact identifiers — env var names, ports, people's names, project codenames — which is a large share of real personal-KB queries.

- Add an **FTS5 virtual table** over chunk/memory text in the store layer (SQLite built-in, no new deps). Keep it in sync via triggers or in the repository write path — repository layer stays the only module issuing SQL.
- Retrieval becomes two-leg: BM25 keyword search + existing vector search, fused with **reciprocal rank fusion** (RRF, k=60). Apply the existing recency decay after fusion.
- Keep the 1–2 hop graph traversal and supernode cap on top of the fused result set, unchanged.
- Add a `mode` param to `kb_retrieve`: `hybrid` (new default) | `vector` | `keyword`, so the benchmark (Phase 8) can compare legs.
- Backfill: index all existing chunks/memories into FTS5 in the migration.

**Acceptance criteria (Phase 7):**
- Query for an exact string that appears once (e.g. an env var name) returns that chunk in top-3 in `hybrid` mode even when `vector` mode misses it.
- Existing tests still pass; `vector` mode reproduces old behavior.

---

## Phase 8 — Benchmark harness (prove the thesis)

**Problem:** The "why is this better than a folder of markdown Claude can grep" question is currently answered with vibes. Answer it with numbers, Graphify-BENCHMARKS.md style. This is also the portfolio artifact.

- Build `scripts/benchmark.py` + a `benchmarks/` dir:
  - `benchmarks/questions.jsonl`: 30–50 real questions with expected-answer keys (gold chunk IDs or answer strings). Write these by hand from real usage — decisions, config values, people, project facts.
  - Three retrieval backends to compare: (a) Grimoire `kb_retrieve` hybrid, (b) Grimoire vector-only, (c) baseline: ripgrep over the Phase 6 markdown export (simulates "folder of md files").
  - Metrics: recall@5, recall@10, MRR. Optional LLM-judged answer accuracy as v2.
  - Output a markdown results table to `BENCHMARKS.md`, committed to the repo.
- Wire it to run against a snapshot copy of the DB, never the live store.

**Acceptance criteria (Phase 8):**
- `python scripts/benchmark.py` runs offline (FakeProvider embeddings acceptable for CI; real run uses Ollama) and regenerates `BENCHMARKS.md`.
- README links to the results table.
- Honest reporting: if the grep baseline wins a category, it goes in the table anyway — that's signal for Phase 7 tuning, not something to hide.

---

## Phase 9 — Ops hardening

**Problem:** Several silent-failure landmines and untested operational paths.

### 9.1 Ollama connectivity (current WSL2 setup)
- Replace the hardcoded gateway IP in `.env` with startup resolution: if `GRIMOIRE_OLLAMA_URL` is unset or set to `auto`, resolve the Windows host IP via `ip route show default` in `config.py`.
- Add a startup health check (both gateway and API): ping Ollama, **fail loudly** with a clear message if unreachable — never degrade silently to broken embeddings.
- Note: this becomes moot for the server once Phase 11 (VPS) lands, but the resolver still helps local dev.

### 9.2 Test coverage for Phases 2–5 features
- Gateway: smoke test that each registered `kb_*` tool dispatches and returns a well-formed payload (FakeProvider).
- Distillation: given a fixed fake session, distilled chronicle contains expected entities.
- **Compaction (priority): assert nothing is ever lost** — originals archived, not deleted; node/edge counts reconcile before vs after; running compaction twice is idempotent.
- Capture endpoint: auth required (see 9.3), both payload types validated, malformed payload rejected with 4xx.

### 9.3 API auth
- `/api/capture` and any write-capable HTTP route require a bearer token (`GRIMOIRE_API_TOKEN` env). Reject with 401 when missing/wrong. Read-only dashboard routes may stay open on localhost but must also require the token once exposed publicly (Phase 11).

### 9.4 Scheduled maintenance
- Ship `deploy/grimoire-compact.timer` + `.service` (systemd user units): weekly `scripts/compact.py`, monthly `--reembed`, plus a daily `grimoire.backup backup` timer with retention (keep last 14).
- Log outcomes to a file; compaction failure should be visible, not silent.

**Acceptance criteria (Phase 9):**
- Killing Ollama and starting the gateway produces an immediate, explicit error.
- Compaction test suite passes; capture without token returns 401.
- `systemctl --user list-timers` shows the three timers after running the install script.

---

## Phase 10 — README + positioning rewrite

**Problem:** The README documents 5 MCP tools; the live server exposes ~25. The planner/OS layer (tasks, goals, habits, Eisenhower quadrants, day generation, urgency recompute, weekly reports) — the actual differentiator vs Obsidian — is invisible. This repo doubles as a portfolio piece.

- Rewrite README to lead with the thesis: **an agent-native operating layer with computed state**, not a note-taking app. One paragraph on "why not Obsidian / a folder of markdown" (Obsidian = static text + human UI; Grimoire = computed state + agent-writable tools + semantic retrieval; link to BENCHMARKS.md for evidence).
- Document ALL MCP tools in a table: name, one-line purpose, grouped by layer (knowledge / planner / maintenance).
- Add an architecture diagram (Mermaid in the README is fine): agents → MCP gateway → service → store (SQLite+FTS5+sqlite-vec) → providers (Ollama), plus API → dashboard.
- Add a short "design decisions" section: why SQLite over Neo4j, why bitemporal edges, why hybrid retrieval, provenance tags. These are interview talking points.
- Keep setup/deploy sections accurate to whatever Phase 11 ships.

**Acceptance criteria (Phase 10):**
- A stranger reading only the README can state what Grimoire does differently from Obsidian and can find every MCP tool.

---

## Phase 11 — VPS deployment [DEFERRED — DO NOT EXECUTE YET]

> **STATUS: BLOCKED.** VPS not yet purchased. Do not implement anything in this phase until the owner explicitly says the VPS is available. This section is planning reference only — transport (11.1), packaging (11.3), and migration (11.4) all wait. Phases 1–10 are fully executable now and none of them depend on this phase.

**Problem:** Everything currently assumes the WSL2 laptop: stdio gateway launched per-agent, Ollama on the Windows host, Cloudflare Tunnel off the dev machine. Target: run Grimoire as a proper service on the VPS alongside other projects (n8n etc. handled separately — out of scope here).

### 11.1 Transport: stdio → streamable HTTP
- The stdio gateway can't serve a remote VPS. Run FastMCP with the **streamable HTTP transport** as a long-lived service on the VPS (FastMCP supports this natively). Keep stdio mode working for local dev — transport selected via env/flag.
- Auth: bearer token on the MCP endpoint (already the pattern used with the Cloudflare Tunnel setup — carry it over).

### 11.2 Embeddings without the Windows GPU
The VPS won't have the RTX GPU. Pick one, in order of preference:
1. **CPU Ollama on the VPS** with a small embed model (`nomic-embed-text` runs fine on CPU; the LLM used for distillation is the heavier part — test `llama3.2` CPU latency, and if too slow, distill via the Claude/API path instead of local LLM).
2. Keep Ollama on the home machine and point the VPS at it over Tailscale — works but reintroduces the home machine as a dependency; only as a stopgap.
3. A hosted embeddings API — conflicts with the free/self-hosted philosophy; last resort.
The provider interface already isolates this — implement/choose per env config, no service-layer changes.

### 11.3 Packaging
- Fix and actually run the Docker compose (it's currently authored-but-never-built): API + dashboard behind one container, volume-mounted `./data` for SQLite, backups volume. The MCP HTTP service is either a second process in the same container or its own service — pick one and test it.
- Alternative acceptable v1: no Docker, just two systemd services (API, MCP gateway) + the Phase 9.4 timers. Whichever is verified working wins; do not ship an untested compose file as the documented path.
- Reverse proxy: Caddy or the existing Cloudflare Tunnel pattern terminating TLS in front of both the dashboard and the MCP endpoint. Dashboard gets basic auth or token; MCP keeps bearer auth.

### 11.4 Data migration + safety
- Migrate the SQLite file with `grimoire.backup backup` → copy → `restore` on the VPS (integrity-verified both ends, already built).
- SQLite is fine at this scale on a VPS — do not migrate to Postgres just because it's a server now.
- Enable WAL mode if not already; single-writer discipline (API and MCP service share the store — verify the repository layer serializes writes or add a write lock).
- Backups: daily timer from 9.4, plus a weekly off-VPS copy (e.g. rclone to object storage or even the home machine) — a VPS is not a backup.

**Acceptance criteria (Phase 11):**
- Claude Code on the laptop, with zero local Grimoire install, connects to the VPS MCP endpoint and runs `kb_today` + `kb_write_memory` successfully.
- Dashboard reachable over HTTPS with auth.
- Ollama-off-at-home has zero effect on the VPS service.
- Restore drill performed once: backup pulled from VPS, restored locally, integrity check passes.

---

## Phase 12 — Codebase knowledge + session bootstrap ("one fetch" context)

**Problem:** Switching terminals/sessions means Claude Code re-explores the repo from scratch every time (10–15 tool calls to rebuild orientation). Goal: a new session starts already knowing the project — architecture, decisions, current state — via one automatic fetch.

**Design rule: Grimoire stores the map, not the territory.** Do NOT embed raw source files — code chunks embed poorly, go stale by the hour, and Claude Code can already read files on disk. What Grimoire holds is the distilled orientation layer: architecture summaries, module responsibilities, key decisions, gotchas.

### 12.1 Codebase ingestion pipeline (via Graphify, don't rebuild it)

- Use Graphify as the extraction engine: `graphify extract <repo> --wiki` (tree-sitter AST, local, no API cost for code) produces `GRAPH_REPORT.md` + wiki markdown pages.
- New script `scripts/ingest_codebase.py <repo_path> <project_name>`:
  1. Runs graphify (or accepts an existing `graphify-out/`).
  2. Ingests `GRAPH_REPORT.md` + wiki pages through the existing `kb_ingest_document` path, linked to the project node.
  3. Tags these chunks with `source=codebase` and the repo's current git commit hash in metadata.
- Re-ingestion replaces prior `source=codebase` chunks for that project (delete-then-insert keyed on project + source tag) — no duplicate stale copies. Respect Phase 5 semantics if landed: invalidate, don't hard-delete.
- Manual sections survive: anything written via `kb_write_memory` is untouched by re-ingestion.

### 12.2 Freshness via git hook

- `deploy/hooks/post-commit` (installable via a small `scripts/install_git_hooks.sh`): after each commit, if files changed since last ingest (compare stored commit hash), re-run `ingest_codebase.py` in the background. Debounce: skip if last ingest < 10 min ago.
- Log each auto-ingest (timestamp, repo, commit) to a local file for sanity checks.

### 12.3 SessionStart bootstrap hook (the actual "one fetch")

- Add to the global `~/.claude/settings.json` a `SessionStart` hook (alongside the existing marker-clear) that runs `scripts/session_context.py`:
  1. Derives project name from `basename $CLAUDE_PROJECT_DIR` (same convention as the Stop hook).
  2. Calls the Grimoire API for `kb_get_project` + top-N recent memories + the codebase `GRAPH_REPORT` summary chunk.
  3. Prints a compact context block (target: under ~1500 tokens) to stdout — SessionStart hook output is injected into Claude's context automatically.
- Graceful degradation: if Grimoire is unreachable or the project is unknown, print nothing and exit 0 — never block or delay session start. Hard timeout of 3s on the API call.
- Include a one-line footer in the injected block telling Claude the full KB is available via `kb_retrieve` for anything deeper.

**Acceptance criteria (Phase 12):**
- Opening `claude` in a repo that's been ingested: Claude can answer "what's the architecture of this project and what did we last decide?" with zero exploratory tool calls.
- Committing a change and starting a new session reflects the change after the post-commit re-ingest.
- Starting a session with Grimoire stopped adds no delay and no error noise.
- Raw source files are NOT stored as embedded chunks (only distilled artifacts).

- Neo4j, FalkorDB, or Graphiti adoption
- LLM-based community labeling
- Markdown→Grimoire import / two-way sync
- Real-time collaborative anything
- Rewriting the constellation UI framework
- n8n setup/migration (handled separately as its own VPS project; Grimoire's `/api/capture` endpoint just needs to exist and be authed — 9.3)
- Postgres migration

## Suggested order of commits

1. `feat(graph): persist node layout, pin anchors, freeze simulation`
2. `feat(graph): typed edge stiffness`
3. `feat(ui): local focus mode with depth slider`
4. `feat(cluster): leiden community detection + kb_recluster tool`
5. `feat(schema): edge provenance + confidence`
6. `feat(schema): bitemporal validity + kb_history`
7. `feat(export): kb_export_markdown obsidian vault export`
8. `feat(retrieval): fts5 + rrf hybrid search`
9. `feat(bench): benchmark harness + BENCHMARKS.md`
10. `fix(ops): ollama auto-resolve + startup health check`
11. `test: gateway, distill, compaction, capture coverage`
12. `feat(api): bearer auth on write routes`
13. `feat(deploy): systemd timers for compact/backup`
14. `docs: README rewrite — agent OS positioning + full tool table`
15. `feat(mcp): streamable http transport for vps`
16. `feat(deploy): vps packaging (compose or systemd) + reverse proxy`
17. `feat(ingest): codebase ingestion via graphify outputs`
18. `feat(hooks): post-commit re-ingest + sessionstart context bootstrap`

Note: commits 17–18 (Phase 12) do NOT depend on the deferred Phase 11 — they run against the current WSL2 setup and can be built any time after Phase 1.

## Priority note

If time-boxed, the highest-leverage sequence is: **Phase 1 → Phase 7 → Phase 8**. Phase 1 fixes the daily-visible annoyance, Phase 7 fixes retrieval quality, Phase 8 produces the evidence (and portfolio artifact) that settles the "why not just Obsidian" question. Phase 11 is deferred until the VPS is purchased — and when it unblocks, it must still come after Phase 9, since deploying before auth + tests + backups are in place multiplies every existing risk.