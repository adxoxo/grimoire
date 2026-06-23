# ARCHITECTURE.md — Grimoire Planner

Technical shape of the two tabs. Builds on CLAUDE.md. Defines the data model,
the relations into the existing graph, the shared `core/` layer, the tool
surfaces, and the scheduling algorithm.

Stack: SurrealDB (data + graph relations), FastMCP Python backend, existing
Grimoire web UI. New: a Groq (Llama 3.3 70B) chat router for the in-tab agent.

---

## 1. Node types

Four new node types plus two supporting tables. New types *link into* the
existing project nodes rather than extending them — habits and tasks have
opposite lifecycles (a habit recurs and never permanently completes; a task is a
one-shot completion), so cramming them into existing nodes would mean a pile of
nullable fields and discriminator filtering on every query. Separate types keep
each query clean while the graph relations preserve the connections.

### life_area
Top tier of the goal hierarchy. A small, mostly-stable set defined once.
```
id            string
name          string        -- career | physical | spiritual | financial | craft | relationships ...
color         string        -- accent dot color
sort_order    int
```

### goal
Owns tasks; its deadline drives task urgency. Holds the user's "why" (spark filter).
```
id            string
title         string
why           string        -- the spark-filter reasoning; why this goal earns time
area          record<life_area>
parent_goal   option<record<goal>>   -- optional self-link; flat by default, allows nesting (4th tier) without schema change
target_date   datetime
priority      int            -- manual tiebreaker for the goal floor (higher = chased first)
status        string         -- active | done | paused
created_at    datetime
```

### task
Completable unit. Eisenhower-tagged. Carries a time estimate so the scheduler and
the in-tab agent can sum work.
```
id               string
title            string
notes            string
important        bool          -- MANUAL. Importance is a values judgment, never computed.
urgent_manual    option<bool>  -- override; when set, wins
urgent_computed  bool          -- derived from linked goal's target_date proximity
estimate_minutes option<int>   -- manual or proposed by the in-tab agent; null = untimed
status           string        -- open | done | dropped
due              option<datetime>
created_at       datetime
completed_at     option<datetime>
```
Effective urgency = `urgent_manual ?? urgent_computed`.
Quadrant = function of (`important`, effective urgency):
- important & urgent      -> Q1 DO NOW
- important & !urgent     -> Q2 SCHEDULE   (the goal-floor lane)
- !important & urgent     -> Q3 MINIMIZE
- !important & !urgent    -> Q4 SOMEDAY

### habit
Recurring non-negotiable. Daily or weekly cadence. Carries scheduler timing
metadata so the Flow tab can place it.
```
id                string
name              string
cadence_type      string        -- daily | weekly
weekly_target     option<int>   -- used only when cadence_type = weekly (e.g. 3)
target            string        -- human label, e.g. "20 min" / "5km"
duration_minutes  int           -- for scheduler placement
window_preference string        -- morning | midday | evening | anytime
hard_constraint   option<string>-- e.g. "before 09:00" | "after wake+120m"
flexibility       string        -- fixed | flexible
streak_current    int
streak_best       int
active            bool
created_at        datetime
```
Completion is NOT a field here — it lives in habit_log so history/streaks survive.

### anchor  (Flow tab primitive)
A fixed or soft point the day is built around. Per-day by default (the user's day
frame is dynamic); optional saved templates, not a recurring skeleton.
```
id                string
title             string
date              option<datetime>  -- null if part of a reusable template
kind              string            -- hard | soft        (hard = pinned; soft = preference/window)
start             option<datetime>  -- hard anchors
window_start      option<string>    -- soft anchors, e.g. "12:00"
window_end        option<string>    -- soft anchors, e.g. "14:00"
wake_relative     option<string>    -- e.g. "wake+120m" for body-clock items
duration_minutes  int
template_id       option<string>    -- if loaded from a saved day-shape
```

### Supporting tables

#### habit_log  (one row per completion per day)
```
id          string
habit       record<habit>
date        datetime       -- the day it counts for
completed_at datetime
```
Streaks and weekly progress are computed over this table, never stored as truth
on the habit.

#### day_plan  (a generated/stored schedule for one day)
```
id           string
date         datetime
wake_time    datetime
sleep_target datetime
blocks       array<block>   -- see below
generated_at datetime
```
`block` (embedded):
```
start      datetime
end        datetime
type       string      -- anchor | habit | task
ref_id     string      -- the source node id
title      string
locked     bool        -- completed/in-progress blocks survive reflow
goal_block bool         -- true if this is a goal-floor (Q2) block
```
Plans are stored (not just regenerated on the fly) so the user can mark blocks
done, see divergence, and so reflow can preserve locked/completed blocks.

---

## 2. Relations (the graph payoff)

SurrealDB graph edges, kept out of the node bodies so the existing project nodes
stay untouched:
```
task   -> belongs_to -> project        (existing node type)
task   -> feeds       -> goal
goal   -> in_area     -> life_area
goal   -> feeds       -> project        (optional, project-bound goals)
goal   -> parent      -> goal           (optional nesting)
```
This is what lets a project node surface its open tasks, and lets reflow walk
goals -> their next actionable task.

---

## 3. The `core/` layer (shared logic — load-bearing from Phase 1)

All business logic is plain Python functions in `core/`. Both the MCP server and
the Groq chat router are thin adapters that call these. No logic in adapters.
A third front door later (CLI, webhook, Telegram) becomes trivial.

```
core/
  tasks.py      create_task, modify_task, complete_task, list_tasks_by_quadrant,
                count_open_tasks, estimate_total_time
  habits.py     create_habit, modify_habit, toggle_habit (writes habit_log),
                compute_streak, weekly_progress, weekly_report
  goals.py      create_goal, modify_goal, list_goals (flat + by area),
                goals_by_priority, next_task_for_goal
  urgency.py    recompute_urgency           (the hybrid engine, see §5)
  schedule.py   generate_day, reflow_from_now, available_window,
                degrade_to_fit             (the greedy fitter, see §6)
  anchors.py    create_anchor, list_anchors, save_template, load_template

adapters/
  mcp_server.py     @mcp.tool() wrappers over core  (Claude Desktop — full)
  chat_router.py    Groq tool-calling -> core        (in-tab — capped surface)
```

---

## 4. Tool surfaces

### MCP (Claude Desktop) — full
Wraps essentially all of `core/`: full CRUD on every node type, weekly_report,
project-graph queries, generate_day / reflow_from_now, recompute_urgency, etc.

### In-tab Groq agent — capped (~8 tools)
Exposed to Llama for reliability. Each maps directly to one `core/` function:
```
WRITE        create_task, create_habit, create_goal
MODIFY       modify_task, modify_habit, modify_goal
LIGHT READ   count_open_tasks, estimate_total_time
(+ trigger)  reflow_from_now   -- goal-aware, see §7
```
Each tool call is schema-validated before execution. Ambiguous adds are echoed
for confirmation; unambiguous ones execute silently then confirm.

---

## 5. Hybrid urgency engine (`core/urgency.py`)

Importance is always manual. Only urgency is time-derived.

`recompute_urgency(task)`:
1. Find the task's linked goal (via `feeds` edge). No goal -> urgent_computed = false.
2. Days until goal.target_date:
   - `> 30 days`  -> urgent_computed = false
   - `<= 14 days` -> urgent_computed = true
   - (the 14–30 band can be tuned per goal later)
3. Effective urgency at read time = `urgent_manual ?? urgent_computed`.

Run on task create, on goal target_date change, and on a daily sweep. So firmware
tasks sit in Q2 through the summer and auto-promote into Q1 as Nov 29 approaches,
while a manual override can force any task urgent for a fire drill.

---

## 6. The scheduler (`core/schedule.py`) — greedy day-fitter

v1 is deliberately greedy, not a constraint solver. Greedy yields a usable
timetable immediately; optimization is a later refinement.

`generate_day(wake_time, sleep_target, date)`:
1. `window = sleep_target - wake_time`.
2. Place **hard anchors** at their fixed/wake-relative times.
3. Reserve the **goal floor**: pick the top goal via `goals_by_priority`, pull its
   `next_task_for_goal`, place that Q2 block first among the fillers. (Guarantees
   direction survives a short day — see CLAUDE.md.)
4. Place **habits** into preference-matching gaps; fixed/flexibility-fixed first.
5. Place **soft anchors** within their windows where they fit.
6. Fill remaining gaps with **tasks** pulled through the goal hierarchy in
   Eisenhower order (Q1 -> Q2 -> Q3), using `estimate_minutes`. Untimed tasks are
   placed with a default sentinel block or left out of auto-fill and shown as
   "untimed — drop in manually."
7. If overcommitted, run `degrade_to_fit`: shed Q4 -> Q3 -> trim flexible habits,
   never the goal floor, never past sleep_target. Return a gentle overcommit notice.

`reflow_from_now(now)`: same algorithm, but window = `sleep_target - now`, locked
and completed blocks preserved, everything after `now` re-fitted. This is the
primary interaction.

`estimate_total_time(tasks)`: sums `estimate_minutes`, excludes untimed and says
so ("~6h across 9 tasks, 5 untimed"). Labeled **focus time** in UI — raw work
time, not wall-clock; ignores breaks and context switching by design in v1.

---

## 7. Goal-aware reflow (the §"direction is fixed" mechanism)

Reflow is goal-aware *by construction*: the regeneration always carries active
goals as context and walks them in priority order to choose fillers. When invoked
through an agent (Groq or Claude Desktop), the prompt explicitly includes the
active goals + their next actionable tasks, instructing: fit the remaining window,
guarantee at least one goal-advancing block, prioritize by deadline+importance,
defer the rest. The schedule is disposable; the goals are the constant every
version is measured against.

---

## 8. Intermittent fasting overlay (toggleable, off by default)

Not a node behavior — a computed overlay on the Flow timeline.
- User logs `first_meal` time for the day.
- Eating window = `first_meal` .. `first_meal + eating_hours` (e.g. 8h).
- Fast = the rest. Window shifts automatically with wake time.
- The overlay only *shows* the window and can gently flag eating outside it. It
  never blocks, enforces, or guilts. Off until the user toggles it on.

---

## 9. Data integrity notes

- Streaks/weekly progress always computed from habit_log, never trusted as stored
  fields (the fields on `habit` are a cache, recomputed on write).
- `urgent_computed` is a cache; effective urgency is resolved at read time.
- day_plan is a snapshot; deleting it never deletes the underlying tasks/habits.
- The in-tab agent has the full task + scheduler surface, including hard delete
  (revised 2026-06-23: the local model is trusted to own the planner end to end).
  It is asked to confirm a delete when more than one item could match.
