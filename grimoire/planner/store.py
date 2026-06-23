"""The planner store: the ONLY module that touches the planner tables.

Same hard rule as the knowledge Repository — no planner SQL lives anywhere else.
The core/ logic modules (tasks, habits, goals, urgency, schedule, anchors) call
these intent-level methods; they never open a connection or write SQL.

This opens its own connection to the same SQLite file the knowledge store uses, so
a task can carry a project_id that points at an existing project node.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

GOAL_STATUSES = ("active", "done", "paused")
TASK_STATUSES = ("open", "done", "dropped")
CADENCES = ("daily", "weekly")
ANCHOR_KINDS = ("hard", "soft")
WINDOWS = ("morning", "midday", "evening", "anytime")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return uuid.uuid4().hex


def _b(v: Any) -> int | None:
    """Coerce a tri-state bool (True/False/None) to SQLite int/NULL."""
    return None if v is None else int(bool(v))


class PlannerRepository:
    """Intent-level access to the planner tables. One instance owns one connection."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        if str(self.db_path) != ":memory:":
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self.initialize()

    def initialize(self) -> None:
        self._conn.executescript(SCHEMA_PATH.read_text())

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "PlannerRepository":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- life areas -----------------------------------------------------

    def add_life_area(self, name: str, color: str | None = None, sort_order: int = 0) -> str:
        aid = _new_id()
        with self._conn:
            self._conn.execute(
                "INSERT INTO life_area(id,name,color,sort_order,created_at) VALUES (?,?,?,?,?)",
                (aid, name, color, sort_order, _now()),
            )
        return aid

    def get_or_create_life_area(self, name: str, color: str | None = None) -> str:
        row = self._conn.execute("SELECT id FROM life_area WHERE name = ?", (name,)).fetchone()
        if row:
            return row["id"]
        return self.add_life_area(name, color=color)

    def list_life_areas(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM life_area ORDER BY sort_order, name"
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- goals ----------------------------------------------------------

    def add_goal(
        self,
        title: str,
        *,
        why: str | None = None,
        area_id: str | None = None,
        parent_goal_id: str | None = None,
        target_date: str | None = None,
        priority: int = 0,
        status: str = "active",
        project_id: str | None = None,
    ) -> str:
        if status not in GOAL_STATUSES:
            raise ValueError(f"unknown goal status: {status!r}")
        gid = _new_id()
        now = _now()
        with self._conn:
            self._conn.execute(
                "INSERT INTO goal(id,title,why,area_id,parent_goal_id,target_date,priority,"
                "status,project_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (gid, title, why, area_id, parent_goal_id, target_date, priority,
                 status, project_id, now, now),
            )
        return gid

    def get_goal(self, goal_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM goal WHERE id = ?", (goal_id,)).fetchone()
        return dict(row) if row else None

    def update_goal(self, goal_id: str, fields: dict[str, Any]) -> None:
        allowed = {"title", "why", "area_id", "parent_goal_id", "target_date",
                   "priority", "status", "project_id"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        if not sets:
            return
        sets["updated_at"] = _now()
        cols = ", ".join(f"{k} = ?" for k in sets)
        with self._conn:
            self._conn.execute(f"UPDATE goal SET {cols} WHERE id = ?", (*sets.values(), goal_id))

    def list_goals(
        self, status: str | None = "active", area_id: str | None = None
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT g.*, a.name AS area_name, a.color AS area_color,"
            " (SELECT COUNT(*) FROM task t WHERE t.goal_id = g.id AND t.status = 'open') AS open_tasks,"
            " (SELECT COUNT(*) FROM task t WHERE t.goal_id = g.id AND t.status = 'done') AS done_tasks"
            " FROM goal g LEFT JOIN life_area a ON a.id = g.area_id WHERE 1=1"
        )
        params: list[Any] = []
        if status is not None:
            sql += " AND g.status = ?"
            params.append(status)
        if area_id is not None:
            sql += " AND g.area_id = ?"
            params.append(area_id)
        sql += " ORDER BY g.priority DESC, g.target_date IS NULL, g.target_date, g.created_at"
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def delete_goal(self, goal_id: str) -> int:
        """Hard-delete a goal. Detaches its tasks (goal_id -> NULL) and any child goals
        (parent_goal_id -> NULL) first so the foreign keys stay satisfied."""
        with self._conn:
            self._conn.execute("UPDATE task SET goal_id = NULL WHERE goal_id = ?", (goal_id,))
            self._conn.execute("UPDATE goal SET parent_goal_id = NULL WHERE parent_goal_id = ?", (goal_id,))
            cur = self._conn.execute("DELETE FROM goal WHERE id = ?", (goal_id,))
            return cur.rowcount

    def find_goal_by_title(self, title: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM goal WHERE title = ? COLLATE NOCASE ORDER BY created_at LIMIT 1",
            (title,),
        ).fetchone()
        return dict(row) if row else None

    # ---- tasks ----------------------------------------------------------

    def add_task(
        self,
        title: str,
        *,
        notes: str | None = None,
        important: bool = False,
        urgent_manual: bool | None = None,
        urgent_computed: bool = False,
        estimate_minutes: int | None = None,
        status: str = "open",
        due: str | None = None,
        goal_id: str | None = None,
        project_id: str | None = None,
    ) -> str:
        if status not in TASK_STATUSES:
            raise ValueError(f"unknown task status: {status!r}")
        tid = _new_id()
        with self._conn:
            self._conn.execute(
                "INSERT INTO task(id,title,notes,important,urgent_manual,urgent_computed,"
                "estimate_minutes,status,due,goal_id,project_id,created_at,completed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (tid, title, notes, _b(important), _b(urgent_manual), _b(urgent_computed),
                 estimate_minutes, status, due, goal_id, project_id, _now(), None),
            )
        return tid

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM task WHERE id = ?", (task_id,)).fetchone()
        return dict(row) if row else None

    def update_task(self, task_id: str, fields: dict[str, Any]) -> None:
        allowed = {"title", "notes", "important", "urgent_manual", "urgent_computed",
                   "estimate_minutes", "status", "due", "goal_id", "project_id", "completed_at"}
        sets: dict[str, Any] = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k in ("important", "urgent_manual", "urgent_computed"):
                v = _b(v)
            sets[k] = v
        if not sets:
            return
        cols = ", ".join(f"{k} = ?" for k in sets)
        with self._conn:
            self._conn.execute(f"UPDATE task SET {cols} WHERE id = ?", (*sets.values(), task_id))

    def delete_task(self, task_id: str) -> int:
        """Hard-delete a task. Returns rows deleted (0 if it did not exist)."""
        with self._conn:
            cur = self._conn.execute("DELETE FROM task WHERE id = ?", (task_id,))
            return cur.rowcount

    def list_tasks(
        self,
        status: str | None = "open",
        goal_id: str | None = None,
        project_id: str | None = None,
    ) -> list[dict[str, Any]]:
        sql = (
            "SELECT t.*, g.title AS goal_title, a.name AS area_name, a.color AS area_color"
            " FROM task t LEFT JOIN goal g ON g.id = t.goal_id"
            " LEFT JOIN life_area a ON a.id = g.area_id WHERE 1=1"
        )
        params: list[Any] = []
        if status is not None:
            sql += " AND t.status = ?"
            params.append(status)
        if goal_id is not None:
            sql += " AND t.goal_id = ?"
            params.append(goal_id)
        if project_id is not None:
            sql += " AND t.project_id = ?"
            params.append(project_id)
        sql += " ORDER BY t.created_at DESC"
        return [dict(r) for r in self._conn.execute(sql, params).fetchall()]

    def tasks_for_goals(self, goal_ids: list[str], status: str = "open") -> list[dict[str, Any]]:
        if not goal_ids:
            return []
        placeholders = ",".join("?" * len(goal_ids))
        rows = self._conn.execute(
            f"SELECT * FROM task WHERE status = ? AND goal_id IN ({placeholders})"
            " ORDER BY important DESC, urgent_computed DESC, created_at",
            (status, *goal_ids),
        ).fetchall()
        return [dict(r) for r in rows]

    def all_open_tasks(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM task WHERE status = 'open'"
        ).fetchall()
        return [dict(r) for r in rows]

    def find_task_by_title(self, title: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM task WHERE title = ? COLLATE NOCASE AND status = 'open'"
            " ORDER BY created_at DESC LIMIT 1",
            (title,),
        ).fetchone()
        return dict(row) if row else None

    # ---- habits ---------------------------------------------------------

    def add_habit(
        self,
        name: str,
        *,
        cadence_type: str = "daily",
        weekly_target: int | None = None,
        target: str | None = None,
        duration_minutes: int = 0,
        window_preference: str = "anytime",
        hard_constraint: str | None = None,
        flexibility: str = "flexible",
        active: bool = True,
    ) -> str:
        if cadence_type not in CADENCES:
            raise ValueError(f"unknown cadence: {cadence_type!r}")
        hid = _new_id()
        with self._conn:
            self._conn.execute(
                "INSERT INTO habit(id,name,cadence_type,weekly_target,target,duration_minutes,"
                "window_preference,hard_constraint,flexibility,streak_current,streak_best,"
                "active,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (hid, name, cadence_type, weekly_target, target, duration_minutes,
                 window_preference, hard_constraint, flexibility, 0, 0, _b(active), _now()),
            )
        return hid

    def get_habit(self, habit_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM habit WHERE id = ?", (habit_id,)).fetchone()
        return dict(row) if row else None

    def update_habit(self, habit_id: str, fields: dict[str, Any]) -> None:
        allowed = {"name", "cadence_type", "weekly_target", "target", "duration_minutes",
                   "window_preference", "hard_constraint", "flexibility", "active",
                   "streak_current", "streak_best"}
        sets: dict[str, Any] = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "active":
                v = _b(v)
            sets[k] = v
        if not sets:
            return
        cols = ", ".join(f"{k} = ?" for k in sets)
        with self._conn:
            self._conn.execute(f"UPDATE habit SET {cols} WHERE id = ?", (*sets.values(), habit_id))

    def list_habits(self, active_only: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM habit"
        if active_only:
            sql += " WHERE active = 1"
        sql += " ORDER BY created_at"
        return [dict(r) for r in self._conn.execute(sql).fetchall()]

    def delete_habit(self, habit_id: str) -> int:
        """Hard-delete a habit and its completion log (the log FK references the habit)."""
        with self._conn:
            self._conn.execute("DELETE FROM habit_log WHERE habit_id = ?", (habit_id,))
            cur = self._conn.execute("DELETE FROM habit WHERE id = ?", (habit_id,))
            return cur.rowcount

    def find_habit_by_name(self, name: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM habit WHERE name = ? COLLATE NOCASE ORDER BY created_at LIMIT 1",
            (name,),
        ).fetchone()
        return dict(row) if row else None

    # ---- habit log ------------------------------------------------------

    def log_habit(self, habit_id: str, date: str) -> bool:
        """Mark a habit complete for a day. Returns True if a new row was inserted."""
        with self._conn:
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO habit_log(id,habit_id,date,completed_at)"
                " VALUES (?,?,?,?)",
                (_new_id(), habit_id, date, _now()),
            )
            return cur.rowcount > 0

    def unlog_habit(self, habit_id: str, date: str) -> int:
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM habit_log WHERE habit_id = ? AND date = ?", (habit_id, date)
            )
            return cur.rowcount

    def habit_log_dates(self, habit_id: str) -> list[str]:
        """All dates a habit was completed, newest first."""
        rows = self._conn.execute(
            "SELECT date FROM habit_log WHERE habit_id = ? ORDER BY date DESC", (habit_id,)
        ).fetchall()
        return [r["date"] for r in rows]

    def habit_logs_between(self, habit_id: str, start: str, end: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT date FROM habit_log WHERE habit_id = ? AND date >= ? AND date <= ?",
            (habit_id, start, end),
        ).fetchall()
        return [r["date"] for r in rows]

    def is_habit_logged(self, habit_id: str, date: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM habit_log WHERE habit_id = ? AND date = ?", (habit_id, date)
        ).fetchone()
        return row is not None

    # ---- anchors --------------------------------------------------------

    def add_anchor(
        self,
        title: str,
        *,
        date: str | None = None,
        kind: str = "soft",
        start: str | None = None,
        window_start: str | None = None,
        window_end: str | None = None,
        wake_relative: str | None = None,
        duration_minutes: int = 0,
        template_id: str | None = None,
        template_name: str | None = None,
    ) -> str:
        if kind not in ANCHOR_KINDS:
            raise ValueError(f"unknown anchor kind: {kind!r}")
        aid = _new_id()
        with self._conn:
            self._conn.execute(
                "INSERT INTO anchor(id,title,date,kind,start,window_start,window_end,"
                "wake_relative,duration_minutes,template_id,template_name,created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid, title, date, kind, start, window_start, window_end,
                 wake_relative, duration_minutes, template_id, template_name, _now()),
            )
        return aid

    def get_anchor(self, anchor_id: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM anchor WHERE id = ?", (anchor_id,)).fetchone()
        return dict(row) if row else None

    def list_anchors(self, date: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM anchor WHERE date = ? ORDER BY kind, start, window_start",
            (date,),
        ).fetchall()
        return [dict(r) for r in rows]

    def delete_anchor(self, anchor_id: str) -> int:
        with self._conn:
            cur = self._conn.execute("DELETE FROM anchor WHERE id = ?", (anchor_id,))
            return cur.rowcount

    def list_templates(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT template_id, template_name, COUNT(*) AS n FROM anchor"
            " WHERE template_id IS NOT NULL GROUP BY template_id, template_name"
            " ORDER BY template_name"
        ).fetchall()
        return [dict(r) for r in rows]

    def template_anchors(self, template_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM anchor WHERE template_id = ?", (template_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---- day plans ------------------------------------------------------

    def save_day_plan(
        self,
        date: str,
        *,
        wake_time: str | None,
        sleep_target: str | None,
        blocks: list[dict[str, Any]],
        if_enabled: bool = False,
        first_meal: str | None = None,
        eating_hours: int = 8,
        generated_at: str | None = None,
    ) -> str:
        existing = self._conn.execute("SELECT id FROM day_plan WHERE date = ?", (date,)).fetchone()
        blob = json.dumps(blocks)
        gen = generated_at or _now()
        with self._conn:
            if existing:
                self._conn.execute(
                    "UPDATE day_plan SET wake_time=?,sleep_target=?,blocks=?,if_enabled=?,"
                    "first_meal=?,eating_hours=?,generated_at=? WHERE date=?",
                    (wake_time, sleep_target, blob, _b(if_enabled), first_meal,
                     eating_hours, gen, date),
                )
                return existing["id"]
            pid = _new_id()
            self._conn.execute(
                "INSERT INTO day_plan(id,date,wake_time,sleep_target,blocks,if_enabled,"
                "first_meal,eating_hours,generated_at) VALUES (?,?,?,?,?,?,?,?,?)",
                (pid, date, wake_time, sleep_target, blob, _b(if_enabled),
                 first_meal, eating_hours, gen),
            )
            return pid

    def get_day_plan(self, date: str) -> dict[str, Any] | None:
        row = self._conn.execute("SELECT * FROM day_plan WHERE date = ?", (date,)).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["blocks"] = json.loads(d["blocks"]) if d.get("blocks") else []
        d["if_enabled"] = bool(d["if_enabled"])
        return d

    def update_day_plan_meta(self, date: str, fields: dict[str, Any]) -> None:
        allowed = {"if_enabled", "first_meal", "eating_hours", "wake_time", "sleep_target"}
        sets: dict[str, Any] = {}
        for k, v in fields.items():
            if k not in allowed:
                continue
            if k == "if_enabled":
                v = _b(v)
            sets[k] = v
        if not sets:
            return
        cols = ", ".join(f"{k} = ?" for k in sets)
        with self._conn:
            self._conn.execute(f"UPDATE day_plan SET {cols} WHERE date = ?", (*sets.values(), date))
