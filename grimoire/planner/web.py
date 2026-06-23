"""HTTP adapter for the planner (Today + Flow tabs). A thin FastAPI router over core/.

Mounted by grimoire.api under /api/planner. Like the knowledge API, it calls core
functions / repository intent-methods only; no business logic lives here.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from grimoire.config import settings
from grimoire.planner import anchors as anchors_mod
from grimoire.planner import chat_router
from grimoire.planner import goals as goals_mod
from grimoire.planner import habits as habits_mod
from grimoire.planner import schedule as schedule_mod
from grimoire.planner import tasks as tasks_mod
from grimoire.planner.store import PlannerRepository
from grimoire.planner.urgency import daily_sweep
from grimoire.providers import get_provider
from grimoire.providers.groq import GroqProvider

router = APIRouter(prefix="/api/planner", tags=["planner"])


@contextmanager
def _repo() -> Iterator[PlannerRepository]:
    repo = PlannerRepository(settings.db_path)
    try:
        yield repo
    finally:
        repo.close()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


# ---- Today ------------------------------------------------------------------


@router.get("/today")
def today(date: str | None = None) -> dict:
    """Everything the Today tab draws: habits strip, the four quadrants, goals rail,
    the weekly headline percent, and the open-task focus estimate."""
    d = date or _today()
    with _repo() as repo:
        goals_mod.ensure_default_areas(repo)
        return {
            "date": d,
            "habits": habits_mod.habit_view(repo, today=datetime.fromisoformat(d).date()),
            "quadrants": tasks_mod.list_tasks_by_quadrant(repo),
            "goals": goals_mod.goals_by_area(repo),
            "weekly": habits_mod.weekly_report(repo, today=datetime.fromisoformat(d).date()),
            "estimate": tasks_mod.estimate_total_time(repo),
        }


@router.get("/weekly-report")
def weekly_report(date: str | None = None) -> dict:
    with _repo() as repo:
        d = datetime.fromisoformat(date).date() if date else datetime.now(timezone.utc).date()
        return habits_mod.weekly_report(repo, today=d)


class NewTask(BaseModel):
    title: str
    notes: str | None = None
    important: bool = False
    urgent_manual: bool | None = None
    estimate_minutes: int | None = None
    due: str | None = None
    goal_id: str | None = None
    project_id: str | None = None


@router.post("/tasks")
def create_task(body: NewTask) -> dict:
    with _repo() as repo:
        return tasks_mod.create_task(repo, body.title, notes=body.notes, important=body.important,
                                     urgent_manual=body.urgent_manual, estimate_minutes=body.estimate_minutes,
                                     due=body.due, goal_id=body.goal_id, project_id=body.project_id)


class TaskPatch(BaseModel):
    title: str | None = None
    notes: str | None = None
    important: bool | None = None
    urgent_manual: bool | None = None
    estimate_minutes: int | None = None
    due: str | None = None
    goal_id: str | None = None
    project_id: str | None = None


@router.patch("/tasks/{task_id}")
def modify_task(task_id: str, body: TaskPatch) -> dict:
    with _repo() as repo:
        out = tasks_mod.modify_task(repo, task_id, body.model_dump(exclude_none=True))
        if out is None:
            raise HTTPException(404, "task not found")
        return out


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: str, done: bool = True) -> dict:
    with _repo() as repo:
        out = tasks_mod.complete_task(repo, task_id, done=done)
        if out is None:
            raise HTTPException(404, "task not found")
        return out


@router.delete("/tasks/{task_id}")
def delete_task(task_id: str) -> dict:
    with _repo() as repo:
        return {"deleted": tasks_mod.delete_task(repo, task_id)}


# ---- Habits -----------------------------------------------------------------


class NewHabit(BaseModel):
    name: str
    cadence_type: str = "daily"
    weekly_target: int | None = None
    target: str | None = None
    duration_minutes: int = 0
    window_preference: str = "anytime"
    hard_constraint: str | None = None
    flexibility: str = "flexible"


@router.post("/habits")
def create_habit(body: NewHabit) -> dict:
    with _repo() as repo:
        return habits_mod.create_habit(repo, body.name, cadence_type=body.cadence_type,
                                       weekly_target=body.weekly_target, target=body.target,
                                       duration_minutes=body.duration_minutes,
                                       window_preference=body.window_preference,
                                       hard_constraint=body.hard_constraint, flexibility=body.flexibility)


class HabitPatch(BaseModel):
    name: str | None = None
    weekly_target: int | None = None
    target: str | None = None
    duration_minutes: int | None = None
    window_preference: str | None = None
    hard_constraint: str | None = None
    flexibility: str | None = None
    active: bool | None = None


@router.patch("/habits/{habit_id}")
def modify_habit(habit_id: str, body: HabitPatch) -> dict:
    with _repo() as repo:
        out = habits_mod.modify_habit(repo, habit_id, body.model_dump(exclude_none=True))
        if out is None:
            raise HTTPException(404, "habit not found")
        return out


@router.post("/habits/{habit_id}/toggle")
def toggle_habit(habit_id: str, date: str | None = None) -> dict:
    with _repo() as repo:
        out = habits_mod.toggle_habit(repo, habit_id, date)
        if out is None:
            raise HTTPException(404, "habit not found")
        return out


@router.delete("/habits/{habit_id}")
def delete_habit(habit_id: str) -> dict:
    with _repo() as repo:
        return {"deleted": habits_mod.delete_habit(repo, habit_id)}


# ---- Goals + areas ----------------------------------------------------------


@router.get("/areas")
def areas() -> dict:
    with _repo() as repo:
        goals_mod.ensure_default_areas(repo)
        return {"areas": repo.list_life_areas()}


@router.get("/goals")
def goals(status: str | None = "active") -> dict:
    with _repo() as repo:
        return {"goals": goals_mod.list_goals(repo, status=status),
                "by_area": goals_mod.goals_by_area(repo, status=status)}


class NewGoal(BaseModel):
    title: str
    why: str | None = None
    area: str | None = None
    target_date: str | None = None
    priority: int = 0
    project_id: str | None = None


@router.post("/goals")
def create_goal(body: NewGoal) -> dict:
    with _repo() as repo:
        return goals_mod.create_goal(repo, body.title, why=body.why, area=body.area,
                                     target_date=body.target_date, priority=body.priority,
                                     project_id=body.project_id)


class GoalPatch(BaseModel):
    title: str | None = None
    why: str | None = None
    area: str | None = None
    target_date: str | None = None
    priority: int | None = None
    status: str | None = None
    project_id: str | None = None


@router.patch("/goals/{goal_id}")
def modify_goal(goal_id: str, body: GoalPatch) -> dict:
    with _repo() as repo:
        out = goals_mod.modify_goal(repo, goal_id, body.model_dump(exclude_none=True))
        if out is None:
            raise HTTPException(404, "goal not found")
        return out


@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: str) -> dict:
    with _repo() as repo:
        return {"deleted": goals_mod.delete_goal(repo, goal_id)}


# ---- Project bridge (Phase 4) ----------------------------------------------


@router.get("/projects/{project_id}/tasks")
def project_tasks(project_id: str, status: str = "open") -> dict:
    """Open tasks linked to an existing project node (the graph payoff)."""
    with _repo() as repo:
        return {"tasks": repo.list_tasks(status=status, project_id=project_id)}


# ---- urgency sweep ----------------------------------------------------------


@router.post("/sweep")
def sweep() -> dict:
    """Daily urgency recompute (deadline-driven Q2->Q1 drift). Idempotent."""
    with _repo() as repo:
        return {"recomputed": daily_sweep(repo)}


# ---- Flow -------------------------------------------------------------------


@router.get("/flow")
def flow(date: str | None = None) -> dict:
    """The Flow tab state for a day: the stored plan (if any), its anchors, the fasting
    overlay, and the saved templates."""
    d = date or _today()
    with _repo() as repo:
        plan = repo.get_day_plan(d)
        return {
            "date": d,
            "plan": plan,
            "anchors": repo.list_anchors(d),
            "overlay": schedule_mod.fasting_overlay(plan) if plan else None,
            "templates": repo.list_templates(),
        }


class GenerateDay(BaseModel):
    date: str | None = None
    wake_time: str
    sleep_target: str
    now: str | None = None
    if_enabled: bool = False
    first_meal: str | None = None
    eating_hours: int = 8


@router.post("/flow/generate")
def generate_day(body: GenerateDay) -> dict:
    d = body.date or _today()
    with _repo() as repo:
        return schedule_mod.generate_day(repo, body.wake_time, body.sleep_target, d,
                                         now=body.now, if_enabled=body.if_enabled,
                                         first_meal=body.first_meal, eating_hours=body.eating_hours)


class Reflow(BaseModel):
    date: str | None = None
    now: str | None = None


@router.post("/flow/reflow")
def reflow(body: Reflow) -> dict:
    d = body.date or _today()
    now = body.now or datetime.now(timezone.utc).isoformat()
    with _repo() as repo:
        out = schedule_mod.reflow_from_now(repo, now, d)
        if out is None:
            raise HTTPException(404, "no day plan to reflow — generate one first")
        return out


class FlowMeta(BaseModel):
    if_enabled: bool | None = None
    first_meal: str | None = None
    eating_hours: int | None = None


@router.patch("/flow/{date}/meta")
def flow_meta(date: str, body: FlowMeta) -> dict:
    with _repo() as repo:
        if repo.get_day_plan(date) is None:
            raise HTTPException(404, "no day plan for that date")
        repo.update_day_plan_meta(date, body.model_dump(exclude_none=True))
        plan = repo.get_day_plan(date)
        return {"plan": plan, "overlay": schedule_mod.fasting_overlay(plan)}


class BlockLock(BaseModel):
    ref_id: str | None = None
    start: str | None = None
    locked: bool = True


class SaveBlocks(BaseModel):
    blocks: list[dict]


@router.put("/flow/{date}/blocks")
def save_blocks(date: str, body: SaveBlocks) -> dict:
    """Replace a day's blocks wholesale (the Flow tab's drag / rename / delete path).
    Wake/sleep/fasting metadata are preserved; only the block layout changes."""
    with _repo() as repo:
        plan = repo.get_day_plan(date)
        if plan is None:
            raise HTTPException(404, "no day plan for that date")
        repo.save_day_plan(date, wake_time=plan["wake_time"], sleep_target=plan["sleep_target"],
                           blocks=body.blocks, if_enabled=plan["if_enabled"],
                           first_meal=plan.get("first_meal"), eating_hours=plan.get("eating_hours") or 8,
                           generated_at=plan.get("generated_at"))
        return {"blocks": body.blocks}


@router.patch("/flow/{date}/block")
def lock_block(date: str, body: BlockLock) -> dict:
    """Mark a block locked/done (survives reflow). Matches by ref_id or start time."""
    with _repo() as repo:
        plan = repo.get_day_plan(date)
        if plan is None:
            raise HTTPException(404, "no day plan for that date")
        for b in plan["blocks"]:
            if (body.ref_id and b.get("ref_id") == body.ref_id) or (body.start and b["start"] == body.start):
                b["locked"] = body.locked
        repo.save_day_plan(date, wake_time=plan["wake_time"], sleep_target=plan["sleep_target"],
                           blocks=plan["blocks"], if_enabled=plan["if_enabled"],
                           first_meal=plan.get("first_meal"), eating_hours=plan.get("eating_hours") or 8,
                           generated_at=plan.get("generated_at"))
        return {"blocks": plan["blocks"]}


# ---- Anchors + templates ----------------------------------------------------


class NewAnchor(BaseModel):
    title: str
    date: str | None = None
    kind: str = "soft"
    start: str | None = None
    window_start: str | None = None
    window_end: str | None = None
    wake_relative: str | None = None
    duration_minutes: int = 0


@router.post("/anchors")
def create_anchor(body: NewAnchor) -> dict:
    with _repo() as repo:
        return anchors_mod.create_anchor(repo, body.title, date=body.date or _today(), kind=body.kind,
                                         start=body.start, window_start=body.window_start,
                                         window_end=body.window_end, wake_relative=body.wake_relative,
                                         duration_minutes=body.duration_minutes)


@router.delete("/anchors/{anchor_id}")
def delete_anchor(anchor_id: str) -> dict:
    with _repo() as repo:
        return {"deleted": anchors_mod.delete_anchor(repo, anchor_id)}


class SaveTemplate(BaseModel):
    name: str
    date: str | None = None


@router.post("/flow/templates")
def save_template(body: SaveTemplate) -> dict:
    with _repo() as repo:
        return anchors_mod.save_template(repo, body.name, body.date or _today())


class LoadTemplate(BaseModel):
    date: str | None = None


@router.post("/flow/templates/{template_id}/load")
def load_template(template_id: str, body: LoadTemplate) -> dict:
    with _repo() as repo:
        created = anchors_mod.load_template(repo, template_id, body.date or _today())
        return {"created": created}


# ---- In-tab chat agent ------------------------------------------------------

_provider = get_provider()


def _groq() -> GroqProvider | None:
    """The chat agent needs Groq tool-calling. Surface a clear error if unconfigured."""
    if isinstance(_provider, GroqProvider):
        return _provider
    completers = getattr(_provider, "_completers", None)
    if completers:
        for c in completers:
            if isinstance(c, GroqProvider):
                return c
    if settings.groq_api_key:
        return GroqProvider(api_key=settings.groq_api_key, url=settings.groq_url,
                            model=settings.groq_model, embed_dim=settings.embed_dim)
    return None


class ChatMessage(BaseModel):
    message: str
    history: list[dict] | None = None
    context: dict | None = None


@router.post("/chat")
def chat(body: ChatMessage) -> dict:
    groq = _groq()
    if groq is None:
        return {"reply": "the in-tab agent needs a Groq key configured. you can still add "
                         "items with the + button, or use Claude Desktop.", "actions": [], "error": True}
    with _repo() as repo:
        return chat_router.chat(repo, groq, body.message, history=body.history, context=body.context)
