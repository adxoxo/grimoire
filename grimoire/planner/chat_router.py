"""The in-tab planner agent: a Groq (Llama 3.3 70B) tool-calling adapter over the FULL
task + scheduler surface of core/.

Originally a capped, non-destructive slice; opened up per the user's call that the local
model is capable enough to own the planner end to end. It now has full read/write
including delete. (Hard deletes here are the same operations as the Claude Desktop MCP
surface — see grimoire.gateway.) Reflects the updated decision in grimoirev2tasks docs.

This is an adapter: it contains no business logic, only the wiring from a natural
sentence to the core functions and back.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from grimoire.planner import anchors as anchors_mod
from grimoire.planner import goals as goals_mod
from grimoire.planner import habits as habits_mod
from grimoire.planner import schedule as schedule_mod
from grimoire.planner import tasks as tasks_mod
from grimoire.planner.store import PlannerRepository
from grimoire.providers.groq import GroqError, GroqProvider

SYSTEM_PROMPT = """You are the in-tab assistant for the Grimoire planner, a calm reference \
tool (never a nag). You have full read/write over the user's tasks, habits, goals, and the \
day scheduler, and you are trusted to use it.

Rules:
- Importance is the user's manual values judgment. Only set `important: true` if they \
clearly signal it. Never infer urgency; leave urgency to deadlines unless they say "urgent".
- Propose a time estimate (estimate_minutes) for new tasks when you can infer a sensible one; \
keep it modest. The user can override.
- If a request is genuinely ambiguous (which item they mean, or a habit's cadence), ASK one \
short clarifying question instead of guessing. This matters most for deletes: if more than \
one item could match, confirm before deleting.
- For unambiguous requests, just call the tool(s), then confirm in one short sentence. Always \
say plainly what you deleted.
- Goals carry a "why" — create one only when the user gives a real reason.
- You can read the full state (today view, tasks, goals, habits, counts, time) and write \
freely: create / modify / complete / delete tasks, habits, goals; toggle habit completions; \
add or remove anchors; generate or reflow the day's schedule.
- Keep replies short, plain, lowercase-friendly, no em-dashes."""


def _tools() -> list[dict]:
    def fn(name, desc, props, required=None):
        return {"type": "function", "function": {
            "name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required or []},
        }}

    return [
        # ---- reads ----
        fn("get_today", "Read the full Today view: habits with streaks, the four Eisenhower "
           "quadrants, goals by area, the weekly percent, and the focus-time estimate.", {}),
        fn("list_tasks", "List open tasks grouped by Eisenhower quadrant (Q1-Q4).", {}),
        fn("list_goals", "List active goals (priority + deadline ordered).", {}),
        fn("list_habits", "List active habits with their current streaks and weekly progress.", {}),
        fn("count_open_tasks", "How many open tasks, by quadrant.", {}),
        fn("estimate_total_time", "Total focus time across open tasks.", {}),
        # ---- tasks ----
        fn("create_task", "Create a task. Importance is manual; only set urgent if the user says so.",
           {"title": {"type": "string"},
            "important": {"type": "boolean"},
            "urgent": {"type": "boolean", "description": "manual urgency override"},
            "estimate_minutes": {"type": "integer", "description": "proposed focus minutes"},
            "goal_title": {"type": "string", "description": "link to an existing goal by title"}},
           ["title"]),
        fn("modify_task", "Modify an existing open task found by its title.",
           {"title": {"type": "string"}, "important": {"type": "boolean"},
            "urgent": {"type": "boolean"}, "estimate_minutes": {"type": "integer"},
            "done": {"type": "boolean"}}, ["title"]),
        fn("complete_task", "Mark a task done (or reopen it) by title.",
           {"title": {"type": "string"}, "done": {"type": "boolean"}}, ["title"]),
        fn("delete_task", "Permanently delete a task by title. Confirm first if ambiguous.",
           {"title": {"type": "string"}}, ["title"]),
        # ---- habits ----
        fn("create_habit", "Create a recurring habit. Ask if cadence is unclear.",
           {"name": {"type": "string"},
            "cadence_type": {"type": "string", "enum": ["daily", "weekly"]},
            "weekly_target": {"type": "integer"},
            "duration_minutes": {"type": "integer"},
            "window_preference": {"type": "string", "enum": ["morning", "midday", "evening", "anytime"]}},
           ["name", "cadence_type"]),
        fn("modify_habit", "Modify an existing habit found by its name.",
           {"name": {"type": "string"}, "duration_minutes": {"type": "integer"},
            "weekly_target": {"type": "integer"}, "active": {"type": "boolean"}}, ["name"]),
        fn("toggle_habit", "Toggle today's completion for a habit by name.",
           {"name": {"type": "string"}}, ["name"]),
        fn("delete_habit", "Permanently delete a habit (and its log) by name.",
           {"name": {"type": "string"}}, ["name"]),
        # ---- goals ----
        fn("create_goal", "Create a goal under a life area. Requires a 'why'.",
           {"title": {"type": "string"}, "why": {"type": "string"},
            "area": {"type": "string"}, "target_date": {"type": "string", "description": "ISO date"}},
           ["title", "why"]),
        fn("modify_goal", "Modify an existing goal found by its title.",
           {"title": {"type": "string"}, "target_date": {"type": "string"},
            "priority": {"type": "integer"}, "status": {"type": "string", "enum": ["active", "done", "paused"]}},
           ["title"]),
        fn("delete_goal", "Permanently delete a goal by title (its tasks are detached, not deleted).",
           {"title": {"type": "string"}}, ["title"]),
        # ---- scheduler ----
        fn("generate_day", "Generate today's schedule from wake and sleep times (ISO datetimes).",
           {"wake_time": {"type": "string"}, "sleep_target": {"type": "string"}}, ["wake_time", "sleep_target"]),
        fn("reflow_from_now", "Regenerate today's schedule from now, keeping the goal floor.",
           {"woke_at": {"type": "string", "description": "optional ISO wake time if no plan exists yet"}}),
        fn("add_anchor", "Add a hard (pinned, with start) or soft (windowed) anchor to today.",
           {"title": {"type": "string"}, "kind": {"type": "string", "enum": ["hard", "soft"]},
            "start": {"type": "string", "description": "ISO datetime for hard anchors"},
            "window_start": {"type": "string", "description": "HH:MM for soft anchors"},
            "window_end": {"type": "string", "description": "HH:MM for soft anchors"},
            "duration_minutes": {"type": "integer"}}, ["title", "kind"]),
        fn("delete_anchor", "Remove an anchor from today by its title.",
           {"title": {"type": "string"}}, ["title"]),
    ]


def _execute(repo: PlannerRepository, name: str, args: dict, ctx: dict) -> dict:
    """Dispatch one validated tool call to core/. Returns a compact result for the model."""
    date_str = ctx.get("date") or datetime.now(timezone.utc).date().isoformat()
    try:
        # ---- reads ----
        if name == "get_today":
            goals_mod.ensure_default_areas(repo)
            day = datetime.fromisoformat(date_str).date()
            return {"ok": True,
                    "quadrant_counts": {k: len(v) for k, v in tasks_mod.list_tasks_by_quadrant(repo).items()},
                    "habits": [{"name": h["name"], "streak": h["streak"]["current"],
                                "done_today": h["progress"].get("done_today"),
                                "progress": h["progress"]} for h in habits_mod.habit_view(repo, today=day)],
                    "goals": [{"title": g["title"], "target_date": g.get("target_date")}
                              for g in goals_mod.list_goals(repo)],
                    "weekly_percent": habits_mod.weekly_report(repo, today=day)["overall_percent"],
                    "estimate": tasks_mod.estimate_total_time(repo)["label"]}
        if name == "list_tasks":
            by_q = tasks_mod.list_tasks_by_quadrant(repo)
            return {"ok": True, "tasks": {q: [{"title": t["title"], "estimate_minutes": t.get("estimate_minutes")}
                                              for t in ts] for q, ts in by_q.items()}}
        if name == "list_goals":
            return {"ok": True, "goals": [{"title": g["title"], "area": g.get("area_name"),
                                           "target_date": g.get("target_date"), "priority": g["priority"]}
                                          for g in goals_mod.list_goals(repo)]}
        if name == "list_habits":
            day = datetime.fromisoformat(date_str).date()
            return {"ok": True, "habits": [{"name": h["name"], "cadence": h["cadence_type"],
                                            "streak": h["streak"]["current"], "progress": h["progress"]}
                                           for h in habits_mod.habit_view(repo, today=day)]}
        # ---- writes ----
        if name == "create_task":
            t = tasks_mod.create_task(
                repo, args["title"], important=bool(args.get("important")),
                urgent_manual=args.get("urgent"), estimate_minutes=args.get("estimate_minutes"),
                goal_title=args.get("goal_title"))
            return {"ok": True, "created": "task", "title": t["title"], "quadrant": t["quadrant"]}
        if name == "create_habit":
            h = habits_mod.create_habit(
                repo, args["name"], cadence_type=args.get("cadence_type", "daily"),
                weekly_target=args.get("weekly_target"),
                duration_minutes=args.get("duration_minutes") or 0,
                window_preference=args.get("window_preference", "anytime"))
            return {"ok": True, "created": "habit", "name": h["name"], "cadence": h["cadence_type"]}
        if name == "create_goal":
            g = goals_mod.create_goal(
                repo, args["title"], why=args.get("why"), area=args.get("area"),
                target_date=args.get("target_date"))
            return {"ok": True, "created": "goal", "title": g["title"]}
        if name == "modify_task":
            task = repo.find_task_by_title(args["title"])
            if not task:
                return {"ok": False, "error": f"no open task titled {args['title']!r}"}
            if args.get("done"):
                tasks_mod.complete_task(repo, task["id"])
                return {"ok": True, "modified": "task", "title": task["title"], "status": "done"}
            fields = {k: v for k, v in {
                "important": args.get("important"),
                "urgent_manual": args.get("urgent"),
                "estimate_minutes": args.get("estimate_minutes")}.items() if v is not None}
            tasks_mod.modify_task(repo, task["id"], fields)
            return {"ok": True, "modified": "task", "title": task["title"]}
        if name == "complete_task":
            task = repo.find_task_by_title(args["title"])
            if not task:
                return {"ok": False, "error": f"no open task titled {args['title']!r}"}
            tasks_mod.complete_task(repo, task["id"], done=args.get("done", True))
            return {"ok": True, "task": task["title"], "status": "done" if args.get("done", True) else "open"}
        if name == "delete_task":
            task = repo.find_task_by_title(args["title"])
            if not task:
                return {"ok": False, "error": f"no open task titled {args['title']!r}"}
            tasks_mod.delete_task(repo, task["id"])
            return {"ok": True, "deleted": "task", "title": task["title"]}
        if name == "modify_habit":
            habit = repo.find_habit_by_name(args["name"])
            if not habit:
                return {"ok": False, "error": f"no habit named {args['name']!r}"}
            fields = {k: v for k, v in {
                "duration_minutes": args.get("duration_minutes"),
                "weekly_target": args.get("weekly_target"),
                "active": args.get("active")}.items() if v is not None}
            habits_mod.modify_habit(repo, habit["id"], fields)
            return {"ok": True, "modified": "habit", "name": habit["name"]}
        if name == "toggle_habit":
            habit = repo.find_habit_by_name(args["name"])
            if not habit:
                return {"ok": False, "error": f"no habit named {args['name']!r}"}
            out = habits_mod.toggle_habit(repo, habit["id"], date_str)
            return {"ok": True, "habit": habit["name"], "done_today": out["done_today"],
                    "streak": out["streak_current"]}
        if name == "delete_habit":
            habit = repo.find_habit_by_name(args["name"])
            if not habit:
                return {"ok": False, "error": f"no habit named {args['name']!r}"}
            habits_mod.delete_habit(repo, habit["id"])
            return {"ok": True, "deleted": "habit", "name": habit["name"]}
        if name == "modify_goal":
            goal = repo.find_goal_by_title(args["title"])
            if not goal:
                return {"ok": False, "error": f"no goal titled {args['title']!r}"}
            fields = {k: v for k, v in {
                "target_date": args.get("target_date"),
                "priority": args.get("priority"),
                "status": args.get("status")}.items() if v is not None}
            goals_mod.modify_goal(repo, goal["id"], fields)
            return {"ok": True, "modified": "goal", "title": goal["title"]}
        if name == "delete_goal":
            goal = repo.find_goal_by_title(args["title"])
            if not goal:
                return {"ok": False, "error": f"no goal titled {args['title']!r}"}
            goals_mod.delete_goal(repo, goal["id"])
            return {"ok": True, "deleted": "goal", "title": goal["title"]}
        if name == "count_open_tasks":
            return {"ok": True, **tasks_mod.count_open_tasks(repo)}
        if name == "estimate_total_time":
            return {"ok": True, **tasks_mod.estimate_total_time(repo)}
        if name == "generate_day":
            res = schedule_mod.generate_day(repo, args["wake_time"], args["sleep_target"], date_str,
                                            now=ctx.get("now"))
            return {"ok": True, "generated": True, "notice": res.get("notice"),
                    "blocks": len(res["blocks"]), "goal_block": res["goal_block_present"],
                    "deferred": len(res.get("deferred", []))}
        if name == "reflow_from_now":
            now = ctx.get("now") or datetime.now(timezone.utc).isoformat()
            woke = args.get("woke_at")
            plan = repo.get_day_plan(date_str)
            if plan is None and woke:
                res = schedule_mod.generate_day(repo, woke, ctx.get("sleep_target") or now, date_str)
            else:
                res = schedule_mod.reflow_from_now(repo, now, date_str)
            if res is None:
                return {"ok": False, "error": "no day plan yet — set today's wake/sleep in Flow first"}
            return {"ok": True, "reflowed": True, "notice": res.get("notice"),
                    "blocks": len(res["blocks"]), "goal_block": res["goal_block_present"]}
        if name == "add_anchor":
            a = anchors_mod.create_anchor(
                repo, args["title"], date=date_str, kind=args.get("kind", "soft"),
                start=args.get("start"), window_start=args.get("window_start"),
                window_end=args.get("window_end"), duration_minutes=args.get("duration_minutes") or 30)
            return {"ok": True, "created": "anchor", "title": a["title"], "kind": a["kind"]}
        if name == "delete_anchor":
            match = next((a for a in repo.list_anchors(date_str)
                          if a["title"].lower() == args["title"].lower()), None)
            if not match:
                return {"ok": False, "error": f"no anchor titled {args['title']!r} today"}
            anchors_mod.delete_anchor(repo, match["id"])
            return {"ok": True, "deleted": "anchor", "title": match["title"]}
        return {"ok": False, "error": f"unknown tool {name}"}
    except Exception as exc:  # noqa: BLE001 - report tool failures back to the model, don't crash
        return {"ok": False, "error": str(exc)}


def chat(
    repo: PlannerRepository,
    provider: GroqProvider,
    message: str,
    *,
    history: list[dict] | None = None,
    context: dict | None = None,
    max_rounds: int = 3,
) -> dict:
    """Run one user turn through the capped agent. Returns reply text + executed actions."""
    ctx = context or {}
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": message})
    tools = _tools()
    actions: list[dict] = []

    for _ in range(max_rounds):
        try:
            assistant = provider.chat(messages, tools=tools)
        except GroqError as exc:
            return {"reply": f"the in-tab agent is unavailable right now ({exc}). "
                             "try again, or use Claude Desktop.", "actions": actions, "error": True}
        messages.append(assistant)
        tool_calls = assistant.get("tool_calls") or []
        if not tool_calls:
            return {"reply": assistant.get("content") or "", "actions": actions}
        for call in tool_calls:
            fname = call["function"]["name"]
            try:
                fargs = json.loads(call["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                fargs = {}
            result = _execute(repo, fname, fargs, ctx)
            actions.append({"tool": fname, "args": fargs, "result": result})
            messages.append({"role": "tool", "tool_call_id": call["id"],
                             "name": fname, "content": json.dumps(result)})
    # Out of rounds: summarize what was done.
    return {"reply": "done.", "actions": actions}
