-- The Grimoire Planner store schema (lives in the same SQLite file as the knowledge
-- graph, but in its own tables). Owned exclusively by PlannerRepository — no other
-- module issues SQL, same rule as the knowledge store.
--
-- The planner is a separate subsystem from the four knowledge node types. Tasks,
-- habits, and goals have their own lifecycles, so they get their own tables rather
-- than being crammed into `nodes`. The single bridge into the knowledge graph is
-- task.project_id / goal.project_id, which reference an existing project node.

-- Life areas: the small, stable top tier of the goal hierarchy.
CREATE TABLE IF NOT EXISTS life_area (
  id          TEXT PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  color       TEXT,                       -- accent dot color
  sort_order  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL
);

-- Goals: own tasks; deadline drives task urgency; hold the user's "why".
CREATE TABLE IF NOT EXISTS goal (
  id              TEXT PRIMARY KEY,
  title           TEXT NOT NULL,
  why             TEXT,                    -- the spark-filter reasoning
  area_id         TEXT REFERENCES life_area(id),
  parent_goal_id  TEXT REFERENCES goal(id),  -- optional nesting (flat by default)
  target_date     TEXT,                    -- ISO datetime
  priority        INTEGER NOT NULL DEFAULT 0,  -- manual tiebreaker (higher = chased first)
  status          TEXT NOT NULL DEFAULT 'active',  -- active|done|paused
  project_id      TEXT,                        -- optional bridge to a project node id (not FK-enforced; cross-subsystem)
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL
);

-- Tasks: completable, Eisenhower-tagged units carrying a time estimate.
CREATE TABLE IF NOT EXISTS task (
  id               TEXT PRIMARY KEY,
  title            TEXT NOT NULL,
  notes            TEXT,
  important        INTEGER NOT NULL DEFAULT 0,   -- MANUAL bool, never computed
  urgent_manual    INTEGER,                      -- nullable bool override; when set, wins
  urgent_computed  INTEGER NOT NULL DEFAULT 0,   -- cache from linked goal's deadline
  estimate_minutes INTEGER,                      -- nullable; null = untimed
  status           TEXT NOT NULL DEFAULT 'open', -- open|done|dropped
  due              TEXT,                          -- optional ISO datetime
  goal_id          TEXT REFERENCES goal(id),      -- feeds edge
  project_id       TEXT,                          -- belongs_to a project node id (not FK-enforced; cross-subsystem)
  created_at       TEXT NOT NULL,
  completed_at     TEXT
);

-- Habits: recurring non-negotiables. Completion is NOT stored here (see habit_log).
CREATE TABLE IF NOT EXISTS habit (
  id                TEXT PRIMARY KEY,
  name              TEXT NOT NULL,
  cadence_type      TEXT NOT NULL DEFAULT 'daily',   -- daily|weekly
  weekly_target     INTEGER,                          -- used only for weekly cadence
  target            TEXT,                             -- human label, e.g. "20 min" / "5km"
  duration_minutes  INTEGER NOT NULL DEFAULT 0,       -- for scheduler placement
  window_preference TEXT NOT NULL DEFAULT 'anytime',  -- morning|midday|evening|anytime
  hard_constraint   TEXT,                             -- e.g. "before 09:00"
  flexibility       TEXT NOT NULL DEFAULT 'flexible', -- fixed|flexible
  streak_current    INTEGER NOT NULL DEFAULT 0,       -- cache, recomputed from habit_log
  streak_best       INTEGER NOT NULL DEFAULT 0,       -- cache
  active            INTEGER NOT NULL DEFAULT 1,
  created_at        TEXT NOT NULL
);

-- Habit log: one row per completion per day. Streaks/weekly progress computed here.
CREATE TABLE IF NOT EXISTS habit_log (
  id           TEXT PRIMARY KEY,
  habit_id     TEXT NOT NULL REFERENCES habit(id),
  date         TEXT NOT NULL,            -- the day it counts for (YYYY-MM-DD)
  completed_at TEXT NOT NULL,
  UNIQUE (habit_id, date)
);

-- Anchors: fixed/soft points the day is built around. Per-day, or saved templates.
CREATE TABLE IF NOT EXISTS anchor (
  id                TEXT PRIMARY KEY,
  title             TEXT NOT NULL,
  date              TEXT,                 -- null if part of a reusable template
  kind              TEXT NOT NULL DEFAULT 'soft',  -- hard|soft
  start             TEXT,                 -- hard anchors: ISO datetime
  window_start      TEXT,                 -- soft anchors: "HH:MM"
  window_end        TEXT,                 -- soft anchors: "HH:MM"
  wake_relative     TEXT,                 -- e.g. "wake+120m"
  duration_minutes  INTEGER NOT NULL DEFAULT 0,
  template_id       TEXT,                 -- groups anchors into a named saved day-shape
  template_name     TEXT,                 -- the saved shape's label
  created_at        TEXT NOT NULL
);

-- Day plans: a generated/stored schedule for one day. blocks is JSON (see schedule.py).
CREATE TABLE IF NOT EXISTS day_plan (
  id           TEXT PRIMARY KEY,
  date         TEXT NOT NULL UNIQUE,      -- YYYY-MM-DD
  wake_time    TEXT,                      -- ISO datetime
  sleep_target TEXT,                      -- ISO datetime
  blocks       TEXT,                      -- JSON array of block objects
  if_enabled   INTEGER NOT NULL DEFAULT 0,
  first_meal   TEXT,                      -- ISO datetime of first logged meal
  eating_hours INTEGER NOT NULL DEFAULT 8,
  generated_at TEXT
);

-- Lookup indexes for the read paths.
CREATE INDEX IF NOT EXISTS idx_task_status   ON task(status);
CREATE INDEX IF NOT EXISTS idx_task_goal     ON task(goal_id);
CREATE INDEX IF NOT EXISTS idx_task_project  ON task(project_id);
CREATE INDEX IF NOT EXISTS idx_goal_area     ON goal(area_id);
CREATE INDEX IF NOT EXISTS idx_goal_status   ON goal(status);
CREATE INDEX IF NOT EXISTS idx_habit_log_h   ON habit_log(habit_id, date);
CREATE INDEX IF NOT EXISTS idx_anchor_date   ON anchor(date);
CREATE INDEX IF NOT EXISTS idx_anchor_tmpl   ON anchor(template_id);
