"""Task logic: creation, modification, completion, the Eisenhower matrix, and the
time-estimate roll-up. All quadrant placement flows from (important, effective urgency).

Importance is a manual values judgment; urgency is `urgent_manual ?? urgent_computed`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from grimoire.planner.store import PlannerRepository
from grimoire.planner.urgency import recompute_urgency

# Quadrant ids match the design mockup (Q1 DO NOW ... Q4 SOMEDAY).
QUADRANTS = ("Q1", "Q2", "Q3", "Q4")


def effective_urgent(task: dict) -> bool:
    """Manual override wins; otherwise the computed (deadline-derived) value."""
    manual = task.get("urgent_manual")
    if manual is not None:
        return bool(manual)
    return bool(task.get("urgent_computed"))


def quadrant(task: dict) -> str:
    important = bool(task.get("important"))
    urgent = effective_urgent(task)
    if important and urgent:
        return "Q1"
    if important and not urgent:
        return "Q2"
    if not important and urgent:
        return "Q3"
    return "Q4"


def _annotate(task: dict) -> dict:
    return {**task, "quadrant": quadrant(task), "effective_urgent": effective_urgent(task)}


def create_task(
    repo: PlannerRepository,
    title: str,
    *,
    notes: str | None = None,
    important: bool = False,
    urgent_manual: bool | None = None,
    estimate_minutes: int | None = None,
    due: str | None = None,
    goal_id: str | None = None,
    goal_title: str | None = None,
    project_id: str | None = None,
) -> dict:
    """Create a task, link it to a goal (by id or title), and compute its urgency.

    goal_title is a convenience for the chat agent: it resolves to an existing goal,
    never creating one (goals carry a manual 'why', so they are an explicit act).
    """
    if goal_id is None and goal_title:
        match = repo.find_goal_by_title(goal_title)
        goal_id = match["id"] if match else None
    tid = repo.add_task(
        title,
        notes=notes,
        important=important,
        urgent_manual=urgent_manual,
        estimate_minutes=estimate_minutes,
        due=due,
        goal_id=goal_id,
        project_id=project_id,
    )
    task = repo.get_task(tid)
    recompute_urgency(repo, task)
    return _annotate(repo.get_task(tid))


def modify_task(repo: PlannerRepository, task_id: str, fields: dict) -> dict | None:
    """Update mutable task fields. Re-runs urgency if the goal link changed."""
    task = repo.get_task(task_id)
    if task is None:
        return None
    repo.update_task(task_id, fields)
    if "goal_id" in fields:
        recompute_urgency(repo, repo.get_task(task_id))
    return _annotate(repo.get_task(task_id))


def complete_task(repo: PlannerRepository, task_id: str, done: bool = True) -> dict | None:
    task = repo.get_task(task_id)
    if task is None:
        return None
    if done:
        repo.update_task(task_id, {"status": "done", "completed_at": datetime.now(timezone.utc).isoformat()})
    else:
        repo.update_task(task_id, {"status": "open", "completed_at": None})
    return _annotate(repo.get_task(task_id))


def delete_task(repo: PlannerRepository, task_id: str) -> bool:
    """Hard-delete a task. Returns True if a task was removed."""
    return repo.delete_task(task_id) > 0


def list_tasks_by_quadrant(repo: PlannerRepository) -> dict[str, list[dict]]:
    """Open tasks grouped into the four Eisenhower quadrants, annotated for the UI."""
    out: dict[str, list[dict]] = {q: [] for q in QUADRANTS}
    for t in repo.list_tasks(status="open"):
        a = _annotate(t)
        out[a["quadrant"]].append(a)
    return out


def count_open_tasks(repo: PlannerRepository) -> dict:
    """Light-read: open task count, with a per-quadrant breakdown."""
    by_q = list_tasks_by_quadrant(repo)
    counts = {q: len(by_q[q]) for q in QUADRANTS}
    return {"total": sum(counts.values()), "by_quadrant": counts}


def estimate_total_time(repo: PlannerRepository, tasks: list[dict] | None = None) -> dict:
    """Sum estimate_minutes across open tasks, excluding untimed ones and saying so.

    Labeled focus time in the UI: raw work time, not wall-clock (ignores breaks and
    context switching by design in v1).
    """
    tasks = tasks if tasks is not None else repo.list_tasks(status="open")
    timed = [t for t in tasks if t.get("estimate_minutes")]
    untimed = len(tasks) - len(timed)
    minutes = sum(int(t["estimate_minutes"]) for t in timed)
    hours = minutes / 60.0
    label = f"~{hours:.1f}h focus across {len(tasks)} tasks"
    if untimed:
        label += f", {untimed} untimed"
    return {"minutes": minutes, "hours": round(hours, 2), "counted": len(timed),
            "untimed": untimed, "total_tasks": len(tasks), "label": label}
