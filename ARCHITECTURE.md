# ARCHITECTURE.md

The Grimoire — a local AI agent operating system with one shared knowledge base underneath multiple coding agents.

## Store engine decision (Phase 0, 2026-06-13)

**Decided: SQLite + sqlite-vec** (768-dim vectors), Python in-process. Backend is Python only (FastMCP gateway + FastAPI in one process).

Reason. The current scope is a single agent at a time, retrieval that traverses 1-2 hops out from a project hub, and a heavy-year ceiling around 25k vectors. SQLite covers all of that with zero ops, single-file durability, and a backup that is a verified file copy. sqlite-vec is verified in this environment: a `vec0` virtual table with a TEXT primary key and `float[768]` embeddings returns correct KNN results. SurrealDB stays the stronger long-term fit once traversal gets richer or the system goes genuinely multi-agent (see "Built to evolve" below), and it stays open as a future migration because the repository layer is the only module that touches the store engine. Per the build plan: pick, record, move.

## The core idea

Do not wire the agents together. Build one knowledge service underneath them. Claude Code, Codex CLI, and Google Antigravity stay fully independent; each speaks MCP to a single gateway, and the gateway reads and writes one local store. Adding a fourth agent later means pointing it at the gateway, nothing more.

The store is a single local engine on the machine — either SQLite + sqlite-vec (one file, zero ops, bulletproof durability) or SurrealDB (multi-model: document, graph, and vector in one engine, native traversal, real concurrency). The choice is made in Phase 0 and recorded here; the four-node + edges + vectors model is identical either way. Critically, all store access goes through a repository layer (see below), so the engine is swappable and the decision is not permanent. No cloud subscription, scalable to the machine. All LLM and embedding calls run through one thin provider interface, so the model or vendor behind retrieval and distillation can change by config without touching the rest of the system.

This is a long-term system: the knowledge base grows continuously, gets more connected, and is expected to gain complexity over years. Two abstraction layers — the repository layer and the provider interface — exist specifically so the two hardest-to-reverse decisions (store engine, embedding model) stay reversible. They are not optional polish; they are what keep a years-long project from calcifying.

## System layout

```
Claude Code     Codex CLI     Google Antigravity
      \              |              /
       \             |             /
            MCP gateway (one read/write interface)
                     |
            Knowledge service
        (retrieval, ranking, traversal)
                     |
          Shared store (SQLite + sqlite-vec)
        four node types, edges, chunks, vectors
            /                          \
   Document pipeline            n8n capture endpoint
  (convert, chunk, embed)   (conversations, project sync)

   Compaction job (scheduled)      Web dashboard (grimoire UI)
```

## The four node types

1. Documents (tomes) — reference material. PDFs and HTML are converted to markdown on ingestion to cut token cost, then chunked (~500 tokens) and embedded.

2. Memory (chronicles) — conversation records in two layers. Raw turns are kept cheap and unindexed for audit and replay. A distilled summary (decisions made, code/config produced, open questions, entities mentioned — one cheap LLM call) is what gets embedded and retrieved.

3. Projects (quest lines) — the hub everything links to. Every GHL build, n8n/Zapier flow, web app, dashboard, and idea is a project node holding structured metadata (type, status, client, stack) and a living context summary. Status: idea, active, shipped, archived. An idea is a project with a title and a paragraph; if it becomes real it graduates to active under the same node id, preserving idea-to-project lineage.

4. Entities (runes) — reusable things referenced across projects: APIs, skills, tools, people. A shared entity can link two otherwise separate projects, which is what the graph buys over flat folders.

## Write paths (two, landing in one store)

Document pipeline: convert to markdown, chunk, embed, write node + chunks + vectors.

n8n capture endpoint: one webhook, two payload types.
- conversation_capture — after each session, the distilled summary is written as a memory node, raw turns to the raw layer, auto-linked to the project it touched. Project context partly populates itself this way: every session about a project adds to that project for free.
- project_context — structured snapshots that do not come from chat: a GHL build's pipeline structure, an n8n flow's trigger/action map, a web app's schema. Pushed manually or via optional scheduled GHL/Zapier API pollers so context stays current as builds are edited.

## Read path

1. Agent identifies the relevant project.
2. Traverse from the project node to linked memory, documents, and entities (1-2 hops).
3. Vector search runs only against that narrowed candidate set.
4. Score = similarity x recency decay (exponential, ~90-day half-life). Return top k.

The graph narrows before any embedding search runs. That is the token and processing win: agents pull distilled, relevant context instead of rescanning everything each session.

## Compaction (load-bearing)

A scheduled job merges old memory fragments on overlapping topics into consolidated summaries (originals archived, raw kept), and refreshes each project's living context summary. Without it, retrieval surfaces near-duplicate fragments, project hubs become unreadable piles, and the vector count grows without bound. With it, both retrieval quality and storage stay flat. It is built in Phase 5, not bolted on later.

## Built to evolve (long-term design)

This system is meant to run and grow for years. Five decisions exist specifically to absorb that growth.

Repository layer (hard rule). All store reads and writes go through one module exposing intent-level methods — get_project, link_nodes, search, write_memory, and so on. No other code issues a query or touches the store engine directly. This is the same insurance as the provider interface, applied to the database: the store engine becomes swappable, so the Phase 0 choice is reversible. If traversal queries get painful in year two, you migrate this one module, not the application. For a long-evolving project this abstraction matters more than which engine is chosen first.

Store engine — the long-term tradeoff, stated honestly. The data model is fundamentally a graph: nodes, typed edges, traversal-first retrieval. SQLite models that as join tables — proven and bulletproof, but every traversal is hand-written recursive SQL that grows painful as relational queries get richer (e.g. entities shared across recently-touched projects linking to unreviewed memory). SurrealDB does graph traversal natively, holds documents and vectors in one engine, and has a real concurrency story for when more than one process reads and writes. Under a multi-year, increasingly-connected, eventually-multi-agent lens, SurrealDB has the stronger fit. The countervailing risk is maturity: SQLite is the most battle-tested database in existence; SurrealDB is younger, so its stability and backup story carry more weight when years of knowledge depend on them. Resolution: SurrealDB is the recommended direction for this use case, conditional on the backup routine below being in place before any real data lands. The repository layer means neither choice is a trap.

Re-embedding as a first-class routine. Better embedding models will ship over the years, and changing models (or dimensions) requires re-embedding the whole store. This is a planned, supported, documented operation — a repeatable job — not a crisis to improvise later. The provider interface keeps the calling code stable; the re-embedding routine handles the data migration. Changing models should be a scheduled afternoon, not a rewrite.

Backup and restore (non-negotiable). A system holding years of accumulated knowledge needs an automated, tested backup-and-restore routine built before real data goes in — especially if the store engine is SurrealDB. Backups are verified by actually restoring them, not assumed. This is a Phase 0 deliverable.

Graph rendering scales in steps. The force-directed constellation is smooth at dozens to low hundreds of nodes in SVG. At thousands of nodes SVG stops being viable and rendering moves to canvas/WebGL (cytoscape's canvas renderer, or a library like sigma.js built for large graphs). This is an expected future upgrade, not a stack change — noted now so the lag, when it comes, is a planned switch rather than a surprise.

## Storage and sizing

Raw text is tiny: a long conversation is 20-50 KB, a converted PDF 10-100 KB. Thousands sum to hundreds of MB, not GB.

Embeddings are the real cost and scale with model dimensions: 768-dim ≈ 3 KB/chunk, 1024-dim ≈ 4 KB, 3072-dim ≈ 12 KB — a 4x swing on model choice. The locked choice is 768-dim local.

Worked heavy-year estimate: 2,000 documents → ~20,000 chunks; 1,000 conversations → ~5,000 chunks (summaries only — the two-layer design paying off); project/entity nodes negligible. ~25,000 vectors x 3 KB ≈ 75 MB raw, ~150 MB with the HNSW-style index. Total system: a few hundred MB for a heavy year; single-digit GB worst case over multiple years.

The guard against ballooning is architectural, not disciplinary: only summaries are embedded, and compaction plateaus the vector count.

The real local constraint is RAM (embedding model loaded + MCP server serving), not disk.

Database: at this data size either engine is comfortable — sizing is not the deciding factor. The engine choice is made on the long-term fit grounds laid out in "Built to evolve" above (graph-native traversal and concurrency vs. proven durability), not on storage volume. A dedicated standalone vector database only earns its place at millions of vectors — years away at this usage, if ever.

Provider abstraction and re-embedding: LLM and embedding calls go through one thin interface (the pattern open-notebook factors into its Esperanto layer). This isolates the embedding model/dimension decision behind a config boundary, so swapping models is a setting change, not application rewrite. The data-side cost — re-embedding the store — is handled by the dedicated re-embedding routine described in "Built to evolve," treated as a planned operation rather than a warned-about hazard.

## Borrowed patterns

From open-notebook (MIT, lfnovo/open-notebook), studied as a mature reference for this class of system:
- Notebook-as-hub confirms the project-hub model: a unit grouping sources, notes, and chats maps onto a project grouping documents, memory, and entities.
- Provider abstraction (Esperanto) — adopted as the provider-interface rule above.
- Content transformations: user-definable extract/summarize actions over sources, a generalization of the distillation step worth adopting so memory and project-context summaries are configurable rather than one hardcoded prompt.
- Docker Compose deployment bundling store + API + automation as services.
Not borrowed: podcast generation, multi-speaker TTS, multi-language UI — NotebookLM-parity features irrelevant to an agent OS.

## Design direction

The dashboard is a dark arcane grimoire: the knowledge base renders as a glowing constellation / skill tree (force-directed layout), four rune colors map exactly to the four node types, status is encoded as glow intensity, and Cinzel + Spectral carry the FFXV feel. Atmosphere on the chrome, plain legibility on content. Full specification lives in CLAUDE.md; build order in BUILDPLAN.md.

## Future directions (out of scope — parking lot)

Not being built now. The current scope is the knowledge base, used by a single agent at a time. These are recorded so the research is not lost, explicitly deferred until the knowledge layer ships and proves out. None of this changes the build order in BUILDPLAN.md.

Multi-agent runtime. A possible later layer: one "Chief" coordinator dispatching to specialist agents (coder, researcher, planner), each with its own memory and skills. Reference pattern: allen-hsu/agent-os (Claude Code-based, closest to this goal). Caution: adds real orchestration complexity; build only after the knowledge base is solid, or the agents have nothing proven to read from.

Two planes, kept distinct. If a runtime is ever added, "agent" means two different things and must not be conflated:
- External coding tools (Claude Code, Codex, Antigravity) — stay independent, coordinate only through the gateway. This is the current meaning.
- Internal runtime agents (Chief + specialists) — orchestrated, do talk to each other.
The knowledge base is the shared substrate at the bottom; external tools sit independently on top; any Chief/specialist runtime is a separate orchestration layer that also reads and writes through the gateway. Both "stay independent" and "Chief dispatches to specialists" are true only because they describe different planes.

Spec & workflow layer. Markdown specs, standards, and workflow definitions agents follow. Reference: buildermethods/agent-os. Lowest-risk of the references — this project already does a version of it (CLAUDE.md, BUILDPLAN.md are spec-driven agent docs). Adopt directly if formalizing.

Skill ecosystem. Build any custom skills to the Agent Skills open standard so they stay portable across Claude Code, Codex, Cursor, etc. — matches the existing swappable-tools principle. Pattern catalogs (not dependencies): VoltAgent/awesome-agent-skills, VoltAgent/awesome-claude-code-subagents.

Control plane. If multiple agents ever run, a dashboard with cost/token tracking is worth having — none of the other references emphasize spend tracking. Reference: modimihir07/agentic-os.

Set aside for now: OpenFang (Rust, sandboxed, security-focused) and Agent Zero (self-building autonomous framework) — more systems- and autonomy-heavy than needed; revisit only if agents execute untrusted code or autonomy becomes a goal.

Note: these references are summarized from a landscape scan, not from reading their source. Verify each against its actual code before building on it.
