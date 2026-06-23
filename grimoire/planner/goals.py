"""Goal logic: the hierarchy (life area -> goal -> task), priority ordering, and the
'next actionable task' lookup the scheduler uses to reserve the daily goal floor.

Changing a goal's target_date re-runs urgency for its tasks (deadline -> Q2->Q1 drift).
"""

from __future__ import annotations

from grimoire.planner.store import PlannerRepository
from grimoire.planner.tasks import effective_urgent, quadrant
from grimoire.planner.urgency import recompute_for_goal

# A small, stable default set, seeded on first use so goals always have an area.
DEFAULT_AREAS = [
    ("career", "#d4a93f"),
    ("physical", "#d98b4a"),
    ("spiritual", "#9d6bd9"),
    ("financial", "#5b8dd9"),
    ("craft", "#eec054"),
    ("relationships", "#e08aa8"),
]


def ensure_default_areas(repo: PlannerRepository) -> None:
    if repo.list_life_areas():
        return
    for i, (name, color) in enumerate(DEFAULT_AREAS):
        repo.add_life_area(name, color=color, sort_order=i)


def create_goal(
    repo: PlannerRepository,
    title: str,
    *,
    why: str | None = None,
    area: str | None = None,
    area_id: str | None = None,
    parent_goal_id: str | None = None,
    target_date: str | None = None,
    priority: int = 0,
    project_id: str | None = None,
) -> dict:
    """Create a goal under a life area (resolved/created by name when given)."""
    if area_id is None and area:
        area_id = repo.get_or_create_life_area(area)
    gid = repo.add_goal(
        title, why=why, area_id=area_id, parent_goal_id=parent_goal_id,
        target_date=target_date, priority=priority, project_id=project_id,
    )
    return repo.get_goal(gid)


def modify_goal(repo: PlannerRepository, goal_id: str, fields: dict) -> dict | None:
    goal = repo.get_goal(goal_id)
    if goal is None:
        return None
    if "area" in fields and "area_id" not in fields:
        fields = {**fields, "area_id": repo.get_or_create_life_area(fields.pop("area"))}
    repo.update_goal(goal_id, fields)
    if "target_date" in fields:
        recompute_for_goal(repo, goal_id)
    return repo.get_goal(goal_id)


def delete_goal(repo: PlannerRepository, goal_id: str) -> bool:
    """Hard-delete a goal (its tasks are detached, not deleted)."""
    return repo.delete_goal(goal_id) > 0


def list_goals(repo: PlannerRepository, status: str | None = "active") -> list[dict]:
    """Flat goal list (already priority/deadline ordered by the store)."""
    return repo.list_goals(status=status)


def goals_by_area(repo: PlannerRepository, status: str | None = "active") -> list[dict]:
    """Goals grouped under their life areas, for the Today goals rail."""
    areas = repo.list_life_areas()
    goals = repo.list_goals(status=status)
    by_area: dict[str | None, list[dict]] = {}
    for g in goals:
        by_area.setdefault(g.get("area_id"), []).append(g)
    out = []
    for a in areas:
        out.append({**a, "goals": by_area.get(a["id"], [])})
    if None in by_area:  # goals with no area
        out.append({"id": None, "name": "unsorted", "color": None, "goals": by_area[None]})
    return out


def goals_by_priority(repo: PlannerRepository) -> list[dict]:
    """Active goals, highest priority then soonest deadline first (the goal floor order)."""
    return repo.list_goals(status="active")


def next_task_for_goal(repo: PlannerRepository, goal_id: str) -> dict | None:
    """The single most important open task feeding a goal: the goal-floor candidate.

    Prefers Q2 (important, not urgent) work — the goal floor's whole purpose — then
    Q1, then anything open, breaking ties by a present time estimate.
    """
    tasks = repo.list_tasks(status="open", goal_id=goal_id)
    if not tasks:
        return None

    def rank(t: dict) -> tuple:
        q = quadrant(t)
        q_rank = {"Q2": 0, "Q1": 1, "Q3": 2, "Q4": 3}[q]
        return (q_rank, 0 if t.get("estimate_minutes") else 1, t.get("created_at") or "")

    tasks.sort(key=rank)
    return tasks[0]
