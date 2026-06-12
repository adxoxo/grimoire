# CLAUDE.md

Operating instructions for any agent working in the Grimoire. ARCHITECTURE.md explains the system. BUILDPLAN.md is the build order. This file is how you behave inside it.

## What this project is

A local shared knowledge base that multiple coding agents (Claude Code, Codex CLI, Google Antigravity) read from and write to through one MCP gateway. You are one of those agents. The store is the single source of truth. Use it instead of asking the user to repeat themselves.

## Session protocol

At session start:
1. Identify the project this task belongs to (ask once if genuinely ambiguous).
2. Call kb_get_project(name) and kb_retrieve(query, project) before doing work.
3. Work from the returned context. Do not request the whole base.

During the session:
- If you produce a decision, code/config, an open question, or discover a new entity, note it for the end-of-session write.
- If the project's stored context contradicts what the user says now, trust the user and flag the stale context for update.

At session end:
- Call kb_write_memory(project, summary, decisions[], entities[]). Distill — decisions and outcomes, not transcript.
- If project structure changed (new pipeline, new workflow, schema change), patch the project hub via kb_upsert_project.

## Rules for the knowledge base

- Traverse, do not scan. Retrieval goes through the project node first. Never embed or fetch "everything."
- Convert before ingesting. PDFs and HTML become markdown before chunking. Never embed raw PDF bytes.
- Respect the two layers. Raw conversation turns go to memory_raw, cheap and unindexed. Only distilled summaries are embedded. Do not embed raw turns.
- Every write links to a project. An unlinked node is a bug.
- New writes are status unreviewed. Only the user (via the review queue) marks things reviewed.
- Do not fight compaction. If a project's context summary already states something, do not append a duplicate note. If compaction merged fragments, do not re-create them.

## Node types

| Type | Grimoire name | What it holds |
|---|---|---|
| document | tome | reference material, converted to markdown |
| memory | chronicle | distilled session records, two-layer |
| project | quest line | the hub; status idea / active / shipped / archived |
| entity | rune | reusable APIs, skills, tools, people; can link projects |

Edge relations: belongs_to (node to project), references (node to document), mentions (node to entity), derived_from (compacted summary to originals).

## Design system — dark arcane grimoire

The interface is a grimoire. Atmosphere lives on the chrome and the graph; legibility lives on the content. Hold both — this is the rule that keeps the app usable for 8-hour sessions.

The split: grimoire styling on navigation, headers, the constellation, empty states, loading text. Content panels (open documents, chat summaries, project context being edited) stay clean and plainly readable. Never stylize body content into illegibility.

Palette:
- Base: near-black with violet undertone — #0c0b14 page, #0e0d16 panels, #16142b raised surfaces
- Borders: #29263f default, #1d1a2e subtle dividers
- Gold (headers, primary accent): #e3d3a0 display text, #c9a13b / #d4a93f accents
- Muted text: #9b96b8 secondary, #6b6789 tertiary

Node-type rune colors (one glowing color per type, four total — four is the ceiling):
- Quest line (project): gold #d4a93f
- Tome (document): arcane blue #5b8dd9
- Chronicle (memory): ember orange #d98b4a
- Rune (entity/API): violet #9d6bd9

Edges carry the parent node's color so lineage reads by following the thread.

Status is glow, not hue. Do not spend new colors on status:
- Reviewed / live: steady glow
- Unreviewed: faint pulse
- Error: red rim

Typography (FFXV-adjacent):
- Display/headers: Cinzel (carved-capital serif, the FFXV-logo feel). Locally, Cormorant or a licensed Trajan-family face get closer; the proprietary FFXV fonts are not freely licensed — do not use them.
- Body: Spectral, light weights. Keep body in Spectral regardless of display face. Readability wins every conflict.

The home view is a constellation / skill tree:
- Force-directed layout (d3-force or cytoscape.js). Hand-placed coordinates do not scale.
- Quest-line nodes form the spine; tomes, chronicles, and runes radiate from them.
- Drag, zoom, pan. Nodes dim until traversed and brighten on visit — the skill-tree reveal.
- Glow effects only on the dark base; they do not read on light backgrounds.

General UI rules: sentence case everywhere; gold and rune detailing on edges and headers, not flooding surfaces; loading text may be thematic ("inscribing the grimoire") but error messages stay plain and actionable.

## Karpathy rules (always active)

Adapted from forrestchang/andrej-karpathy-skills (MIT), derived from Andrej Karpathy's January 2026 observations on LLM coding failures. These bias toward caution over speed; use judgment on trivial tasks.

1. Think before coding. Do not assume silently. State assumptions explicitly; if multiple interpretations exist, present them instead of picking one. If something is unclear, stop and ask. If a simpler approach exists, say so and push back.

2. Simplicity first. Minimum code that solves the problem. No features beyond what was asked, no abstractions for single-use code, no speculative configurability, no error handling for impossible scenarios. If 200 lines could be 50, rewrite. Test: would a senior engineer call this overcomplicated?

3. Surgical changes. Touch only what the request requires. Do not improve adjacent code, refactor what is not broken, or restyle to personal preference; match existing style. Mention unrelated dead code, do not delete it. Do remove imports/variables your own changes orphaned. Test: every changed line traces directly to the request.

4. Goal-driven execution. Turn tasks into verifiable goals with success criteria, then loop until verified. "Fix the bug" becomes "write a test that reproduces it, then make it pass." For multi-step work, state a brief plan where each step has its own verify check. This is the same philosophy as the phase acceptance criteria in BUILDPLAN.md; apply it inside sessions too.

Working signal: fewer unnecessary lines in diffs, fewer overcomplication rewrites, clarifying questions arriving before implementation instead of after mistakes.

## Author conventions

When producing written output for the user (notes, copy, docs): no em-dashes anywhere. Short and scannable beats narrative-heavy. Sign-off name when needed: Adam Scott Peguit.

## Scope discipline

Agents stay independent. The gateway is the only coordination point. No agent-to-agent messaging. No multi-user features. No cloud sync. No dedicated vector database until millions of vectors. One store, one gateway, four node types.
