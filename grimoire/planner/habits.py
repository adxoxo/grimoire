"""Habit logic: creation, daily/weekly completion via the log, streaks, and the
weekly consistency report.

Streaks and weekly progress are ALWAYS computed from habit_log; the fields stored on
`habit` are a cache, recomputed on every toggle (ARCHITECTURE §9).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from grimoire.planner.store import PlannerRepository


def today_str(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.date().isoformat()


def week_start(d: date) -> date:
    """Monday of the week containing d."""
    return d - timedelta(days=d.weekday())


def _parse_d(s: str) -> date:
    return date.fromisoformat(s[:10])


# ---- pure streak math --------------------------------------------------


def compute_daily_streak(dates: list[str], today: date) -> dict:
    """Current + best run of consecutive days from a set of completion dates.

    Current counts back from today; if today is not logged but yesterday is, the run
    ending yesterday still counts (the streak does not collapse until a full day is
    missed). Best is the longest consecutive run ever recorded.
    """
    s = {_parse_d(x) for x in dates}
    if not s:
        return {"current": 0, "best": 0}

    # current
    current = 0
    anchor = today if today in s else (today - timedelta(days=1))
    cur = anchor
    while cur in s:
        current += 1
        cur -= timedelta(days=1)
    if today not in s and (today - timedelta(days=1)) not in s:
        current = 0

    # best
    best = 0
    for d in s:
        if (d - timedelta(days=1)) in s:
            continue  # not a run start
        run, cur = 0, d
        while cur in s:
            run += 1
            cur += timedelta(days=1)
        best = max(best, run)
    return {"current": current, "best": max(best, current)}


def compute_weekly_streak(dates: list[str], today: date, target: int) -> dict:
    """Current + best run of consecutive weeks that hit the weekly target."""
    if target <= 0:
        return {"current": 0, "best": 0}
    weeks: dict[date, int] = {}
    for x in dates:
        ws = week_start(_parse_d(x))
        weeks[ws] = weeks.get(ws, 0) + 1
    hit = {w for w, n in weeks.items() if n >= target}
    if not hit:
        return {"current": 0, "best": 0}

    this_week = week_start(today)
    current = 0
    anchor = this_week if this_week in hit else (this_week - timedelta(days=7))
    cur = anchor
    while cur in hit:
        current += 1
        cur -= timedelta(days=7)
    if this_week not in hit and (this_week - timedelta(days=7)) not in hit:
        current = 0

    best = 0
    for w in hit:
        if (w - timedelta(days=7)) in hit:
            continue
        run, cur = 0, w
        while cur in hit:
            run += 1
            cur += timedelta(days=7)
        best = max(best, run)
    return {"current": current, "best": max(best, current)}


def compute_streak(repo: PlannerRepository, habit: dict, today: date | None = None) -> dict:
    today = today or datetime.now(timezone.utc).date()
    dates = repo.habit_log_dates(habit["id"])
    if habit["cadence_type"] == "weekly":
        return compute_weekly_streak(dates, today, habit.get("weekly_target") or 1)
    return compute_daily_streak(dates, today)


# ---- mutations ---------------------------------------------------------


def create_habit(repo: PlannerRepository, name: str, **kw) -> dict:
    hid = repo.add_habit(name, **kw)
    return repo.get_habit(hid)


def modify_habit(repo: PlannerRepository, habit_id: str, fields: dict) -> dict | None:
    if repo.get_habit(habit_id) is None:
        return None
    repo.update_habit(habit_id, fields)
    return repo.get_habit(habit_id)


def delete_habit(repo: PlannerRepository, habit_id: str) -> bool:
    """Hard-delete a habit and its completion log."""
    return repo.delete_habit(habit_id) > 0


def toggle_habit(repo: PlannerRepository, habit_id: str, date_str: str | None = None) -> dict | None:
    """Flip a habit's completion for a day, then refresh its cached streak fields."""
    habit = repo.get_habit(habit_id)
    if habit is None:
        return None
    date_str = date_str or today_str()
    if repo.is_habit_logged(habit_id, date_str):
        repo.unlog_habit(habit_id, date_str)
        done = False
    else:
        repo.log_habit(habit_id, date_str)
        done = True
    streak = compute_streak(repo, habit, today=_parse_d(date_str))
    repo.update_habit(habit_id, {"streak_current": streak["current"], "streak_best": streak["best"]})
    return {**repo.get_habit(habit_id), "done_today": done}


# ---- reads -------------------------------------------------------------


def weekly_progress(repo: PlannerRepository, habit: dict, today: date | None = None) -> dict:
    """For weekly habits: count this week vs target. For daily: done-today flag."""
    today = today or datetime.now(timezone.utc).date()
    ws = week_start(today)
    we = ws + timedelta(days=6)
    logs = repo.habit_logs_between(habit["id"], ws.isoformat(), we.isoformat())
    if habit["cadence_type"] == "weekly":
        target = habit.get("weekly_target") or 1
        return {"count": len(logs), "target": target, "met": len(logs) >= target}
    return {"count": len(logs), "done_today": repo.is_habit_logged(habit["id"], today.isoformat())}


def habit_view(repo: PlannerRepository, today: date | None = None) -> list[dict]:
    """Every active habit with its live streak + this-week progress, for the Today strip."""
    today = today or datetime.now(timezone.utc).date()
    out = []
    for h in repo.list_habits(active_only=True):
        streak = compute_streak(repo, h, today=today)
        out.append({**h, "streak": streak, "progress": weekly_progress(repo, h, today=today)})
    return out


def weekly_report(repo: PlannerRepository, today: date | None = None) -> dict:
    """Consistency report for the current week: per-habit hit rate + overall percent."""
    today = today or datetime.now(timezone.utc).date()
    ws = week_start(today)
    we = ws + timedelta(days=6)
    days_elapsed = (min(today, we) - ws).days + 1
    items, expected_total, done_total = [], 0, 0
    for h in repo.list_habits(active_only=True):
        logs = repo.habit_logs_between(h["id"], ws.isoformat(), we.isoformat())
        done = len(logs)
        if h["cadence_type"] == "weekly":
            expected = h.get("weekly_target") or 1
        else:
            expected = days_elapsed
        expected_total += expected
        done_total += min(done, expected)
        items.append({
            "habit_id": h["id"], "name": h["name"], "cadence_type": h["cadence_type"],
            "done": done, "expected": expected,
            "percent": round(100 * min(done, expected) / expected) if expected else 0,
            "streak": compute_streak(repo, h, today=today),
        })
    overall = round(100 * done_total / expected_total) if expected_total else 0
    return {"week_start": ws.isoformat(), "overall_percent": overall, "habits": items}
