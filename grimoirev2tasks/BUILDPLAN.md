# BUILDPLAN.md — Grimoire Planner

Phased build. Strict rule (per methodology): every phase front-loads a shippable
deliverable. Phase 1 alone must let the user run a day. No pure-plumbing phases.

Each phase lists: **Ships** (the usable thing), **Schema**, **core/**, **UI**,
**Done when**.

---

## Phase 1 — Task matrix + Today tab
**Ships:** a working daily view you can run your day off — tasks in four quadrants,
manual flags, check things done.

- **Schema:** `task` node (with `important`, `urgent_manual`, `estimate_minutes`,
  `status`). No goals/habits/urgency-engine yet — `urgent_computed` defaults false,
  so quadrant comes from manual flags only.
- **core/:** `tasks.py` — create_task, modify_task, complete_task,
  list_tasks_by_quadrant, count_open_tasks, estimate_total_time. **Establish the
  `core/` + thin-adapter discipline here** so later phases are wiring, not rewrites.
- **UI:** "Today" tab. 2×2 Eisenhower grid (DO NOW / SCHEDULE / MINIMIZE /
  SOMEDAY), task chips with checkbox + title + time estimate, add/edit task.
- **Done when:** you can add tasks, flag important/urgent, see them sorted into
  quadrants, complete them, and this replaces whatever you use now.

---

## Phase 2 — Habits + streaks + weekly report
**Ships:** streak-aware habit strip and a weekly consistency report.

- **Schema:** `habit` node (daily + weekly cadence, weekly_target) and `habit_log`
  table. Timing metadata fields (duration, window_preference, hard_constraint,
  flexibility) added now but only *consumed* in Phase 7.
- **core/:** `habits.py` — create_habit, modify_habit, toggle_habit (writes
  habit_log), compute_streak, weekly_progress, weekly_report.
- **UI:** habits strip at top of Today — daily habits as glowing checkboxes,
  weekly habits as progress pills ("cardio 2/3"), ember streak badges, "this week
  · 83%" summary. A weekly report card/sub-view.
- **Done when:** you check off meditation/PT/cardio/reading daily, weekly habits
  track toward their target, streaks compute correctly from habit_log, and the
  weekly report reads right on a Sunday.

---

## Phase 3 — Goals, hierarchy, and the hybrid urgency engine
**Ships:** the goal system + smart urgency that auto-promotes tasks as deadlines
approach.

- **Schema:** `life_area` and `goal` nodes (with `area`, optional `parent_goal`,
  `target_date`, `priority`, `why`). Relations: `task->feeds->goal`,
  `goal->in_area->life_area`, optional `goal->parent->goal`.
- **core/:** `goals.py` — create_goal, modify_goal, list_goals (flat + by area),
  goals_by_priority, next_task_for_goal. `urgency.py` — recompute_urgency (hybrid
  engine, §5 of ARCHITECTURE). Wire recompute on create / deadline-change / daily
  sweep.
- **UI:** goals rail at bottom of Today, grouped by life area with accent dots,
  progress bars, target dates, subtle hierarchy indentation. Flat goal list view.
- **Done when:** goals live under life areas, tasks link to goals, and a firmware
  task visibly slides from Q2 toward Q1 as Nov 29 nears — with manual override
  still winning.

---

## Phase 4 — Link tasks to existing project nodes (graph payoff)
**Ships:** "open tasks per project," tasks connected to the project nodes already
in your Grimoire.

- **Schema:** relation `task->belongs_to->project` (existing node type); optional
  `goal->feeds->project`.
- **core/:** extend `tasks.py`/`goals.py` with project-scoped queries.
- **UI:** on a project node view, surface its open tasks; on a task chip, the faint
  project tag becomes a real link.
- **Done when:** opening Baker Brothers (or any project node) shows its open tasks,
  and tasks carry their project context.

---

## Phase 5 — In-tab Groq agent (add / modify / light read)
**Ships:** a chat box in the UI that captures and edits tasks/habits/goals by
sentence, proposes time estimates, and answers open-count + total-time.

- **Schema:** none new (`estimate_minutes` already exists from Phase 1).
- **core/:** none new — this phase is *adapter only*, proving the Phase-1
  discipline paid off.
- **adapters:** `chat_router.py` — Groq (Llama 3.3 70B) tool-calling over the
  capped ~8-tool surface (create/modify task|habit|goal, count_open_tasks,
  estimate_total_time). Schema-validate every call; echo ambiguous adds for
  confirmation; execute unambiguous adds silently. Llama proposes estimates at
  capture time (accept/override). No destructive tools exposed.
- **UI:** chat box in the Today tab. Confirmation chips for ambiguous adds.
- **Done when:** "add a daily habit journaling and a task to finish the i2c driver
  for the firmware goal" creates both correctly, "how many tasks left and how long"
  answers, and anything analytical is redirected to Claude Desktop. The existing
  MCP/Claude Desktop path is untouched throughout.

---

## Phase 6 — Scheduler data model + anchors + IF overlay
**Ships:** you can describe a day's fixed pieces and toggle a fasting window.

- **Schema:** `anchor` node (hard/soft, per-day, wake_relative, template_id) and
  `day_plan` node (date, wake_time, sleep_target, blocks, generated_at). Habit
  timing metadata (from Phase 2) now becomes live input.
- **core/:** `anchors.py` — create_anchor, list_anchors, save_template,
  load_template. Skeleton of `schedule.py` (available_window).
- **UI:** "Flow" tab shell. Day-setup bar (woke at / sleeping around / computed
  window). Add hard + soft anchors. Toggleable IF overlay band (off by default,
  anchored to first logged meal, pressure-free).
- **Done when:** you can set today's window, add a confirmed call as a hard anchor
  and "lunch midday" as a soft one, and flip the fasting overlay on/off.

---

## Phase 7 — The greedy day-fitter (with goal floor)
**Ships:** enter wake/sleep -> get a real generated timetable that always includes
a goal-advancing block. The headline "maximize my day" feature.

- **Schema:** none new.
- **core/:** `schedule.py` — generate_day (greedy: hard anchors -> goal floor ->
  habits -> soft anchors -> tasks by Eisenhower through the goal hierarchy),
  degrade_to_fit (Q4->Q3->trim flexible habits, never the goal floor, never past
  sleep). Works fine with zero anchors.
- **UI:** vertical timeline ribbon, three block-card variants (anchor/habit/task),
  current-time marker, proportional block heights, goal-floor block visibly marked.
  Gentle overcommit notice. "Generate my day" button.
- **Done when:** "woke at 10, sleeping at 1" produces a sensible packed day, a
  short day degrades gracefully with a calm warning, and *every* generated day
  contains at least one goal block — or nudges you to add one.

---

## Phase 8 — Reflow + energy windows + templates (the smart version)
**Ships:** mid-day "reflow from now," energy-aware placement, saved day-shapes.

- **Schema:** optional energy-window tagging (config, not necessarily a node).
- **core/:** `reflow_from_now` (preserve locked/completed, re-fit remaining,
  goal-aware by construction — carries active goals + next tasks in context).
  Energy mapping so Q2 deep-work prefers high-energy windows, admin gets low-energy.
- **UI:** prominent "Reflow from now" (the main repeat interaction), energy-window
  shading on the timeline, save/load template day-shapes ("deep work day",
  "client-heavy day", "recovery day"), draggable intention chips.
- **Done when:** a blown-up 2pm re-fits the rest of the day in one tap while
  keeping the goal floor, deep-work lands in your high-energy hours, and you can
  start a chaotic day blank or load a template.

---

## Cross-cutting (every phase)

- Honor both governing principles: **reference not ultimatum**, **day fluid /
  direction fixed**. No locking, no guilt-tracking, gentle notices only.
- Maintain `core/` + thin-adapter separation. Logic never in an adapter.
- Streaks/urgency are caches recomputed from source (habit_log / goal deadlines).
- In-tab agent has full task + scheduler control including delete (revised
  2026-06-23); it confirms a delete when the target is ambiguous.
- Each phase ends with something genuinely usable on its own.

## Suggested sequencing note
Phases 1–5 deliver the full Today experience + capture. Phases 6–8 deliver Flow.
If time is tight, Phases 1–3 alone are a complete, useful planner; Flow can wait.
