"""The hybrid urgency engine (ARCHITECTURE §5).

Importance is always manual. Only urgency is time-derived, from the linked goal's
target_date. `urgent_computed` is a cache; effective urgency is resolved at read
time as `urgent_manual ?? urgent_computed`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from grimoire.planner.store import PlannerRepository

# Tuning bands (days until the linked goal's deadline).
URGENT_WITHIN_DAYS = 14   # <= this -> urgent
NOT_URGENT_BEYOND_DAYS = 30  # > this -> not urgent; the 14-30 band stays not-urgent in v1


def _parse(dt: str) -> datetime | None:
    try:
        d = datetime.fromisoformat(dt)
    except (ValueError, TypeError):
        return None
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def compute_urgent(target_date: str | None, now: datetime | None = None) -> bool:
    """Pure: is a deadline close enough to make its tasks urgent?"""
    if not target_date:
        return False
    parsed = _parse(target_date)
    if parsed is None:
        return False
    now = now or datetime.now(timezone.utc)
    days = (parsed - now).total_seconds() / 86400.0
    return days <= URGENT_WITHIN_DAYS


def recompute_urgency(repo: PlannerRepository, task: dict, now: datetime | None = None) -> bool:
    """Recompute and persist urgent_computed for one task. Returns the new value.

    No linked goal -> not urgent. Manual override is untouched (it wins at read time).
    """
    urgent = False
    goal_id = task.get("goal_id")
    if goal_id:
        goal = repo.get_goal(goal_id)
        if goal:
            urgent = compute_urgent(goal.get("target_date"), now=now)
    if bool(task.get("urgent_computed")) != urgent:
        repo.update_task(task["id"], {"urgent_computed": urgent})
    return urgent


def recompute_for_goal(repo: PlannerRepository, goal_id: str, now: datetime | None = None) -> int:
    """Recompute urgency for every open task feeding a goal (on deadline change). Count touched."""
    tasks = repo.list_tasks(status="open", goal_id=goal_id)
    for t in tasks:
        recompute_urgency(repo, t, now=now)
    return len(tasks)


def daily_sweep(repo: PlannerRepository, now: datetime | None = None) -> int:
    """Recompute urgency across all open tasks (the daily auto-promote pass)."""
    tasks = repo.all_open_tasks()
    for t in tasks:
        recompute_urgency(repo, t, now=now)
    return len(tasks)
