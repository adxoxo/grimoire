# CLAUDE.md — Grimoire Planner

The working contract. Read this before touching ARCHITECTURE.md or BUILDPLAN.md.
Everything downstream answers to the principles stated here.

---

## What this is

Two new tabs in the Grimoire web UI:

1. **Today** — a daily action surface. Habits (top), tasks arranged by Eisenhower
   quadrant (center), goals grouped by life area (bottom). This is the source of
   truth for *what* to do.
2. **Flow** — a dynamic daily scheduler. Takes today's actual wake/sleep window
   as input and fits habits, anchors, and goal-advancing tasks into it. This
   answers *when* to do things, given a day that starts and ends at unpredictable
   hours.

These sit on the existing Grimoire foundation: FastMCP Python backend, SurrealDB,
the established four node types, the dark arcane design system, and the Claude
Desktop MCP wiring already in place.

---

## Two governing principles

These are not features. They are the lens every design and code decision passes
through. If a choice violates one of these, it is the wrong choice regardless of
how clever it is.

### 1. Reference, not ultimatum

The planner is something the user *consults*, never something that *commands*.
It suggests; the user disposes. Nothing locks. A generated schedule is disposable.
There is no guilt-tracking, no streak-shaming, no alarms when the real day
diverges from the plan. A day that goes off-plan is normal, not a failure. The
tool earns its place by being useful when looked at — not by demanding compliance.

Practical consequences:
- Generated schedules are *proposals*, freely editable, droppable, ignorable.
- Input cost stays minimal. Chaotic days are exactly when the user will skip
  fiddly logging, so logging a day is two fields plus optional taps.
- Reflow ("regenerate from now") is the primary interaction, not an edge case.
- Notices are gentle ("~2h over your window — consider trimming"), never alarming.

### 2. The day is fluid, the direction is fixed

The schedule changes constantly. The *goals* do not. Every regeneration of the
day must re-anchor to the user's active goals, so that no matter how the day
morphs, the user keeps chasing what matters. Chaos must not be allowed to quietly
starve the important-but-not-urgent work (firmware roadmap, Grimoire itself) by
filling every hour with reactive urgency.

This is enforced by the **daily goal floor** (see below).

---

## The daily goal floor

The single rule that ties the two tabs together.

Every generated/reflowed day MUST reserve at least one block for goal-advancing
(Q2: important, not urgent) work before filling the remainder with reactive work.
When the scheduler fills time, it pulls tasks *through the goal hierarchy in
priority order* — not from a flat list — so the highest-leverage progress toward
the most important goals always gets a seat, even on a short day.

If a generated day contains no goal-advancing block, the tool surfaces a gentle
nudge: "nothing toward your goals today — want to fit one in?"

When the day shrinks, peripheral tasks are *deferred, not forgotten*. The
scheduler sheds Q4 → Q3 → flexible habits, and protects the goal floor last.

---

## How the user works (design must fit this, not the reverse)

- Days are genuinely dynamic: wake anywhere from 7am to 12pm, sleep anywhere from
  12am to 4am. The *frame itself* moves daily. "Fixed" is the rare exception.
- Few true anchors. Most "anchors" are soft/flexible (loose meetings, "lunch
  sometime midday"). Hard anchors (a confirmed call) are occasional, added per-day.
- Non-negotiable habits: meditation, PT exercise, cardio, reading. These must get
  a lane that reactive work can't crowd out.
- Intermittent fasting is *aspirational* — wanted, not yet practiced. It must be a
  toggleable, pressure-free overlay, never an enforced rule, never on by default.
- Importance is a values judgment (the user's "spark filter"), set manually.
  Urgency is mostly time-derived from goal deadlines, with manual override.

---

## Scope of the two front doors

The same underlying logic is reachable two ways. Both are thin adapters over a
shared `core/` layer (see ARCHITECTURE.md). Business logic never lives in an
adapter.

### Claude Desktop (external agent, via existing MCP) — FULL power
Full read/write/reasoning over the whole graph. The serious interface for
planning, weekly review, anything analytical.

### In-tab chat box (Groq + Llama 3.3 70B) — FULL task + scheduler control
A quick lane inside the UI. Originally a capped capture-only slice; revised
2026-06-23 to the full task + scheduler surface (the local model is trusted to own
the planner end to end):
- **Read:** today view, list tasks/goals/habits, count_open_tasks, estimate_total_time
- **Write:** create / modify / complete / delete tasks, habits, goals
- **Scheduler:** generate_day, reflow_from_now, add/remove anchors, toggle habits
- Knowledge-base / full-graph analysis still belongs in Claude Desktop's MCP surface.

Guardrails for the in-tab agent: validate every tool call against schema before
executing; ask one clarifying question for ambiguous requests (cadence, or which
item a delete refers to); execute unambiguous requests and confirm plainly,
always stating what was deleted.

---

## Aesthetic

Inherits the existing Grimoire dark arcane system. Deep near-black background,
violet accent (#7c5cff), ember-amber for streaks/highlights (#ffb347), refined
serif/display headers (spellbook feel) over clean sans body, thin glowing borders,
hairline dividers, soft inner glows, generous spacing. Atmospheric but calm and
precise — a spellbook crossed with a sleek terminal dashboard. The Flow tab
specifically must *feel* fluid and forgiving: soft edges, easy drag-and-drop.

---

## Build methodology (non-negotiable, per existing practice)

- Document-first, strict order: **CLAUDE.md → ARCHITECTURE.md → BUILDPLAN.md.**
- Every phase front-loads a shippable deliverable. Phase 1 alone must be usable
  to run a day. No phase is a pure-plumbing phase with nothing to show.
- `core/` discipline from Phase 1: logic in plain functions; MCP and the Groq
  chat are thin adapters. This makes the in-tab agent (later phase) mostly wiring.

---

## Definition of done for the whole feature

The user can, on any given day — including a chaotic one — open Today to see what
matters arranged by priority, open Flow, enter "woke at / sleeping around," and
get a sensible suggested day that always includes at least one block advancing a
real goal. They can capture and tweak items by sentence in-tab, do the heavy
thinking through Claude Desktop, and never once feel the tool is nagging them.
The day is fluid; the direction holds.
