"""The MCP gateway: the one read/write interface every coding agent speaks to.

Exposes the knowledge service as MCP tools (kb_*). Each tool is wrapped in an
OpenTelemetry span capturing duration, project, and the count of candidate chunks
retrieved or written, so traversal paths and usage are traceable. Per the request,
this is the minimum tracing to map these gateway operations, no extra configurability.

Tracing note: an MCP stdio server uses stdout for the protocol, so spans are exported
to stderr, never stdout.

Run as an MCP server (stdio):
    .venv/bin/python -m grimoire.gateway
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Iterator

from fastmcp import FastMCP
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor

from grimoire.config import settings
from grimoire.providers import get_provider
from grimoire.service import KnowledgeService
from grimoire.store import Repository

# --- tracing (spans -> stderr) ---
_tp = TracerProvider()
_tp.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter(out=sys.stderr)))
trace.set_tracer_provider(_tp)
tracer = trace.get_tracer("grimoire.gateway")

# Provider is reused across calls; the store connection is per-call (SQLite is happiest
# with one connection per unit of work).
_provider = get_provider()

mcp = FastMCP("Grimoire")


@contextmanager
def _service() -> Iterator[KnowledgeService]:
    repo = Repository(settings.db_path)
    try:
        yield KnowledgeService(repo, _provider)
    finally:
        repo.close()


@mcp.tool
def kb_retrieve(query: str, project: str | None = None, k: int = 10) -> list[dict]:
    """Retrieve the most relevant chunks for a query, optionally narrowed to a project."""
    with tracer.start_as_current_span("kb_retrieve") as span:
        span.set_attribute("grimoire.project", project or "")
        span.set_attribute("grimoire.k", k)
        with _service() as svc:
            hits = svc.retrieve(query, project=project, k=k)
        span.set_attribute("grimoire.candidate_chunks", len(hits))
        return [
            {
                "title": h["title"],
                "type": h["type"],
                "node_id": h["node_id"],
                "score": round(h["score"], 4),
                "content": h["content"],
            }
            for h in hits
        ]


@mcp.tool
def kb_write_memory(
    project: str,
    summary: str,
    decisions: list[str] | None = None,
    entities: list[str] | None = None,
) -> dict:
    """Write a distilled session memory, embedded and linked to its project."""
    with tracer.start_as_current_span("kb_write_memory") as span:
        span.set_attribute("grimoire.project", project)
        with _service() as svc:
            emb = svc.provider.embed(summary)
            mem_id = svc.repo.write_memory(
                project=project,
                summary=summary,
                decisions=decisions or [],
                entities=entities or [],
                summary_embedding=emb,
            )
        span.set_attribute("grimoire.chunks_written", 1)
        return {"node_id": mem_id, "chunks_written": 1}


@mcp.tool
def kb_get_project(name: str) -> dict:
    """Return a project hub: its node, living context, and one hop of linked nodes."""
    with tracer.start_as_current_span("kb_get_project") as span:
        span.set_attribute("grimoire.project", name)
        with _service() as svc:
            proj = svc.repo.get_project(name)
        if proj is None:
            return {"error": f"project not found: {name}"}
        span.set_attribute("grimoire.candidate_chunks", len(proj["linked"]))
        return proj


@mcp.tool
def kb_upsert_project(
    name: str,
    meta: dict | None = None,
    context_patch: str | None = None,
    status: str | None = None,
) -> dict:
    """Create a project hub or update it in place (preserving its id)."""
    with tracer.start_as_current_span("kb_upsert_project") as span:
        span.set_attribute("grimoire.project", name)
        with _service() as svc:
            pid = svc.repo.upsert_project(name, meta=meta, context_patch=context_patch, status=status)
        return {"project_id": pid, "name": name}


@mcp.tool
def kb_delete_node(node_id: str) -> dict:
    """Hard-delete a node (quest line, tome, chronicle, or rune) and everything that
    depends on it: its edges, chunks, vectors, and raw turns. Irreversible."""
    with tracer.start_as_current_span("kb_delete_node") as span:
        span.set_attribute("grimoire.node_id", node_id)
        with _service() as svc:
            if svc.repo.get_node(node_id) is None:
                return {"error": f"node not found: {node_id}"}
            return {"deleted": svc.repo.delete_node(node_id), "node_id": node_id}


@mcp.tool
def kb_ingest_document(path: str, project: str | None = None) -> dict:
    """Ingest a document (PDF/HTML/markdown) into the store, linked to a project."""
    with tracer.start_as_current_span("kb_ingest_document") as span:
        span.set_attribute("grimoire.project", project or "")
        with _service() as svc:
            result = svc.ingest_document(path, project=project)
        span.set_attribute("grimoire.chunks_written", result["chunks"])
        return result


# ---------------------------------------------------------------------------
# Planner tools (the Today + Flow subsystem). Claude Desktop gets the FULL surface:
# CRUD on every type, the weekly report, project-task queries, day generation/reflow,
# and the urgency sweep. (The in-tab Groq agent gets only a capped slice; see
# grimoire.planner.chat_router.) Each tool is a thin wrapper over core/.
# ---------------------------------------------------------------------------

from contextlib import contextmanager as _contextmanager  # noqa: E402

from grimoire.planner import anchors as _anchors  # noqa: E402
from grimoire.planner import goals as _goals  # noqa: E402
from grimoire.planner import habits as _habits  # noqa: E402
from grimoire.planner import schedule as _schedule  # noqa: E402
from grimoire.planner import tasks as _tasks  # noqa: E402
from grimoire.planner.store import PlannerRepository  # noqa: E402
from grimoire.planner.urgency import daily_sweep as _daily_sweep  # noqa: E402


@_contextmanager
def _planner() -> Iterator[PlannerRepository]:
    repo = PlannerRepository(settings.db_path)
    try:
        yield repo
    finally:
        repo.close()


@mcp.tool
def kb_today(date: str | None = None) -> dict:
    """The full Today view: habits with streaks, the four Eisenhower quadrants, goals by
    area, the weekly consistency report, and the open-task focus estimate."""
    from datetime import datetime, timezone
    d = date or datetime.now(timezone.utc).date().isoformat()
    with tracer.start_as_current_span("kb_today"):
        with _planner() as repo:
            _goals.ensure_default_areas(repo)
            day = datetime.fromisoformat(d).date()
            return {
                "date": d,
                "habits": _habits.habit_view(repo, today=day),
                "quadrants": _tasks.list_tasks_by_quadrant(repo),
                "goals": _goals.goals_by_area(repo),
                "weekly": _habits.weekly_report(repo, today=day),
                "estimate": _tasks.estimate_total_time(repo),
            }


@mcp.tool
def kb_create_task(
    title: str,
    important: bool = False,
    urgent: bool | None = None,
    estimate_minutes: int | None = None,
    due: str | None = None,
    goal_title: str | None = None,
    project: str | None = None,
) -> dict:
    """Create a task. Importance is a manual values call; urgency derives from the linked
    goal's deadline unless overridden. `project` links it to an existing project node."""
    with tracer.start_as_current_span("kb_create_task"):
        with _service() as svc:
            project_id = None
            if project:
                proj = svc.repo.get_project(project)
                project_id = proj["id"] if proj else None
        with _planner() as repo:
            return _tasks.create_task(repo, title, important=important, urgent_manual=urgent,
                                      estimate_minutes=estimate_minutes, due=due,
                                      goal_title=goal_title, project_id=project_id)


@mcp.tool
def kb_modify_task(task_id: str, fields: dict) -> dict:
    """Modify a task by id (title, notes, important, urgent_manual, estimate_minutes,
    due, goal_id, status)."""
    with tracer.start_as_current_span("kb_modify_task"):
        with _planner() as repo:
            out = _tasks.modify_task(repo, task_id, fields)
            return out or {"error": f"task not found: {task_id}"}


@mcp.tool
def kb_complete_task(task_id: str, done: bool = True) -> dict:
    """Mark a task done (or reopen it)."""
    with tracer.start_as_current_span("kb_complete_task"):
        with _planner() as repo:
            out = _tasks.complete_task(repo, task_id, done=done)
            return out or {"error": f"task not found: {task_id}"}


@mcp.tool
def kb_delete_task(task_id: str) -> dict:
    """Permanently delete a task by id."""
    with tracer.start_as_current_span("kb_delete_task"):
        with _planner() as repo:
            return {"deleted": _tasks.delete_task(repo, task_id)}


@mcp.tool
def kb_create_habit(
    name: str,
    cadence_type: str = "daily",
    weekly_target: int | None = None,
    target: str | None = None,
    duration_minutes: int = 0,
    window_preference: str = "anytime",
    hard_constraint: str | None = None,
    flexibility: str = "flexible",
) -> dict:
    """Create a recurring habit (daily or weekly). Timing fields feed the Flow scheduler."""
    with tracer.start_as_current_span("kb_create_habit"):
        with _planner() as repo:
            return _habits.create_habit(repo, name, cadence_type=cadence_type,
                                        weekly_target=weekly_target, target=target,
                                        duration_minutes=duration_minutes,
                                        window_preference=window_preference,
                                        hard_constraint=hard_constraint, flexibility=flexibility)


@mcp.tool
def kb_toggle_habit(habit_id: str, date: str | None = None) -> dict:
    """Toggle a habit's completion for a day; recomputes its streak from the log."""
    with tracer.start_as_current_span("kb_toggle_habit"):
        with _planner() as repo:
            out = _habits.toggle_habit(repo, habit_id, date)
            return out or {"error": f"habit not found: {habit_id}"}


@mcp.tool
def kb_delete_habit(habit_id: str) -> dict:
    """Permanently delete a habit and its completion log by id."""
    with tracer.start_as_current_span("kb_delete_habit"):
        with _planner() as repo:
            return {"deleted": _habits.delete_habit(repo, habit_id)}


@mcp.tool
def kb_weekly_report(date: str | None = None) -> dict:
    """The weekly habit-consistency report (per-habit hit rate + overall percent)."""
    from datetime import datetime
    with tracer.start_as_current_span("kb_weekly_report"):
        with _planner() as repo:
            d = datetime.fromisoformat(date).date() if date else None
            return _habits.weekly_report(repo, today=d)


@mcp.tool
def kb_create_goal(
    title: str,
    why: str | None = None,
    area: str | None = None,
    target_date: str | None = None,
    priority: int = 0,
    project: str | None = None,
) -> dict:
    """Create a goal under a life area. `why` is the spark-filter reasoning; `target_date`
    drives task urgency. `project` optionally binds it to a project node."""
    with tracer.start_as_current_span("kb_create_goal"):
        project_id = None
        if project:
            with _service() as svc:
                proj = svc.repo.get_project(project)
                project_id = proj["id"] if proj else None
        with _planner() as repo:
            return _goals.create_goal(repo, title, why=why, area=area, target_date=target_date,
                                      priority=priority, project_id=project_id)


@mcp.tool
def kb_modify_goal(goal_id: str, fields: dict) -> dict:
    """Modify a goal by id (title, why, area, target_date, priority, status). Changing
    target_date re-runs urgency for its tasks."""
    with tracer.start_as_current_span("kb_modify_goal"):
        with _planner() as repo:
            out = _goals.modify_goal(repo, goal_id, fields)
            return out or {"error": f"goal not found: {goal_id}"}


@mcp.tool
def kb_delete_goal(goal_id: str) -> dict:
    """Permanently delete a goal by id (its tasks are detached, not deleted)."""
    with tracer.start_as_current_span("kb_delete_goal"):
        with _planner() as repo:
            return {"deleted": _goals.delete_goal(repo, goal_id)}


@mcp.tool
def kb_list_goals(status: str | None = "active") -> dict:
    """Active goals, priority+deadline ordered, plus the grouped-by-area view."""
    with tracer.start_as_current_span("kb_list_goals"):
        with _planner() as repo:
            return {"goals": _goals.list_goals(repo, status=status),
                    "by_area": _goals.goals_by_area(repo, status=status)}


@mcp.tool
def kb_project_tasks(project: str, status: str = "open") -> dict:
    """Open tasks linked to a project node (the graph payoff: 'open tasks per project')."""
    with tracer.start_as_current_span("kb_project_tasks"):
        with _service() as svc:
            proj = svc.repo.get_project(project)
            if proj is None:
                return {"error": f"project not found: {project}"}
            pid = proj["id"]
        with _planner() as repo:
            return {"project": project, "tasks": repo.list_tasks(status=status, project_id=pid)}


@mcp.tool
def kb_generate_day(
    wake_time: str,
    sleep_target: str,
    date: str | None = None,
    now: str | None = None,
    if_enabled: bool = False,
    first_meal: str | None = None,
    eating_hours: int = 8,
) -> dict:
    """Generate today's greedy schedule (ISO wake/sleep). Always reserves a goal-floor
    block; returns blocks, deferred items, and any overcommit notice. Pass `now` (ISO) to
    clamp placement to the present so elapsed hours are not scheduled."""
    from datetime import datetime, timezone
    d = date or datetime.now(timezone.utc).date().isoformat()
    with tracer.start_as_current_span("kb_generate_day"):
        with _planner() as repo:
            return _schedule.generate_day(repo, wake_time, sleep_target, d, now=now,
                                          if_enabled=if_enabled, first_meal=first_meal,
                                          eating_hours=eating_hours)


@mcp.tool
def kb_reflow_day(now: str | None = None, date: str | None = None) -> dict:
    """Reflow the rest of today from `now`, preserving locked/completed blocks and the
    goal floor (the primary repeat interaction)."""
    from datetime import datetime, timezone
    d = date or datetime.now(timezone.utc).date().isoformat()
    n = now or datetime.now(timezone.utc).isoformat()
    with tracer.start_as_current_span("kb_reflow_day"):
        with _planner() as repo:
            out = _schedule.reflow_from_now(repo, n, d)
            return out or {"error": "no day plan to reflow; generate one first"}


@mcp.tool
def kb_add_anchor(
    title: str,
    date: str | None = None,
    kind: str = "soft",
    start: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    wake_relative: str | None = None,
    duration_minutes: int = 0,
) -> dict:
    """Add a hard (pinned) or soft (windowed) anchor to a day."""
    from datetime import datetime, timezone
    d = date or datetime.now(timezone.utc).date().isoformat()
    with tracer.start_as_current_span("kb_add_anchor"):
        with _planner() as repo:
            return _anchors.create_anchor(repo, title, date=d, kind=kind, start=start,
                                          window_start=window_start, window_end=window_end,
                                          wake_relative=wake_relative, duration_minutes=duration_minutes)


@mcp.tool
def kb_delete_anchor(anchor_id: str) -> dict:
    """Remove an anchor by id."""
    with tracer.start_as_current_span("kb_delete_anchor"):
        with _planner() as repo:
            return {"deleted": _anchors.delete_anchor(repo, anchor_id)}


@mcp.tool
def kb_recompute_urgency() -> dict:
    """Run the daily urgency sweep (deadline-driven Q2->Q1 promotion across open tasks)."""
    with tracer.start_as_current_span("kb_recompute_urgency"):
        with _planner() as repo:
            return {"recomputed": _daily_sweep(repo)}


if __name__ == "__main__":
    mcp.run()
