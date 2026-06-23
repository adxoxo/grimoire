"""The scheduler (ARCHITECTURE §6-7): a greedy day-fitter with a protected goal floor.

v1 is deliberately greedy, not a constraint solver. Items are placed in priority
order, so when the day is too short the lowest-priority work simply does not get a
slot (Q4 is never auto-placed; Q3 yields before flexible habits; the goal floor and
Q1 are protected). The schedule is a disposable proposal; the goals are the constant.

The fitting core (`fit_day`) is pure: it takes plain lists and returns blocks +
deferred items, so it is unit-testable without a database. `generate_day` and
`reflow_from_now` gather from the repository and persist.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timedelta, timezone

from grimoire.planner.store import PlannerRepository
from grimoire.planner import goals as goals_mod
from grimoire.planner import habits as habits_mod
from grimoire.planner.tasks import list_tasks_by_quadrant

DEFAULT_GOAL_BLOCK_MIN = 60
DEFAULT_TASK_MIN = 30  # used only when an auto-placed item lacks an estimate but must be placed

# Clock windows (local-naive HH ranges) for habit/anchor window preferences.
WINDOW_CLOCK = {
    "morning": (time(5, 0), time(12, 0)),
    "midday": (time(11, 0), time(15, 0)),
    "evening": (time(17, 0), time(23, 30)),
}
# High-energy windows: where deep-work (goal floor / Q2) prefers to land (Phase 8).
DEFAULT_ENERGY_HIGH = [(time(9, 0), time(12, 30)), (time(15, 0), time(18, 0))]


def _parse(dt: str | datetime) -> datetime:
    if isinstance(dt, datetime):
        d = dt
    else:
        d = datetime.fromisoformat(dt)
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _mins(a: datetime, b: datetime) -> int:
    return int((b - a).total_seconds() // 60)


def available_window(wake_time: str | datetime, sleep_target: str | datetime) -> int:
    """Minutes between waking and the sleep target (0 if inverted)."""
    return max(0, _mins(_parse(wake_time), _parse(sleep_target)))


def _on_date(base: datetime, t: time) -> datetime:
    return datetime.combine(base.date(), t, tzinfo=base.tzinfo)


def _window_bounds(pref: str | None, wake: datetime, sleep: datetime) -> tuple[datetime, datetime]:
    if pref in WINDOW_CLOCK:
        lo, hi = WINDOW_CLOCK[pref]
        return max(wake, _on_date(wake, lo)), min(sleep, _on_date(wake, hi))
    return wake, sleep


def _constraint_bounds(constraint: str | None, wake: datetime, sleep: datetime) -> tuple[datetime, datetime]:
    """Parse a hard_constraint like 'before 09:00' / 'after 18:00' into a clip range."""
    lo, hi = wake, sleep
    if not constraint:
        return lo, hi
    m = re.search(r"(before|after)\s+(\d{1,2}):(\d{2})", constraint.lower())
    if m:
        kind, h, mm = m.group(1), int(m.group(2)), int(m.group(3))
        t = _on_date(wake, time(h, mm))
        if kind == "before":
            hi = min(hi, t)
        else:
            lo = max(lo, t)
    return lo, hi


# ---- free-gap arithmetic ----------------------------------------------


def _carve(gaps: list[list[datetime]], start: datetime, end: datetime) -> None:
    """Remove [start, end] from the free gaps, splitting any gap it overlaps."""
    out: list[list[datetime]] = []
    for g0, g1 in gaps:
        if end <= g0 or start >= g1:
            out.append([g0, g1])
            continue
        if start > g0:
            out.append([g0, min(start, g1)])
        if end < g1:
            out.append([max(end, g0), g1])
    gaps[:] = [g for g in out if _mins(g[0], g[1]) > 0]


def _place_fixed(gaps: list[list[datetime]], start: datetime, dur: int) -> tuple[datetime, datetime] | None:
    end = start + timedelta(minutes=dur)
    for g0, g1 in gaps:
        if g0 <= start and end <= g1:
            _carve(gaps, start, end)
            return start, end
    return None


def _place_flex(
    gaps: list[list[datetime]], dur: int, lo: datetime, hi: datetime,
    prefer: list[tuple[datetime, datetime]] | None = None,
) -> tuple[datetime, datetime] | None:
    """Place dur minutes in the earliest gap within [lo, hi]. If `prefer` ranges are
    given, try those first (energy-aware placement), then fall back to the window."""
    for ranges in ([prefer] if prefer else []) + [None]:
        for g0, g1 in gaps:
            s = max(g0, lo)
            e = min(g1, hi)
            if ranges:
                for r0, r1 in ranges:
                    rs, re_ = max(s, r0), min(e, r1)
                    if _mins(rs, re_) >= dur:
                        _carve(gaps, rs, rs + timedelta(minutes=dur))
                        return rs, rs + timedelta(minutes=dur)
            elif _mins(s, e) >= dur:
                _carve(gaps, s, s + timedelta(minutes=dur))
                return s, s + timedelta(minutes=dur)
    return None


def _block(start: datetime, end: datetime, type_: str, title: str, ref_id: str | None = None,
           *, goal_block: bool = False, locked: bool = False, kind: str | None = None) -> dict:
    return {"start": _iso(start), "end": _iso(end), "type": type_, "title": title,
            "ref_id": ref_id, "goal_block": goal_block, "locked": locked, "kind": kind}


# ---- the pure fitting core --------------------------------------------


def fit_day(
    wake: datetime,
    sleep: datetime,
    *,
    hard_anchors: list[dict],
    soft_anchors: list[dict],
    habits: list[dict],
    goal_floor: dict | None,
    tasks_by_quadrant: dict[str, list[dict]],
    locked_blocks: list[dict] | None = None,
    energy_high: list[tuple[time, time]] | None = None,
) -> dict:
    """Greedily fit a day. Returns blocks, deferred items, and overcommit info.

    Placement priority (higher protection = placed first): hard anchors -> goal floor
    -> Q1 -> fixed/constrained habits -> Q2 -> flexible habits -> soft anchors -> Q3.
    Q4 is never auto-placed. Untimed tasks are surfaced, not auto-placed.
    """
    gaps: list[list[datetime]] = [[wake, sleep]]
    blocks: list[dict] = []
    deferred: list[dict] = []
    requested = 0
    energy_ranges = [(_on_date(wake, a), _on_date(wake, b)) for a, b in (energy_high or DEFAULT_ENERGY_HIGH)]

    # 0. Preserve locked/completed blocks (reflow): carve them out, keep them. A goal
    #    block already done earlier today still satisfies the floor.
    placed_refs: set[str] = set()
    goal_block_present = False
    for b in (locked_blocks or []):
        bs, be = _parse(b["start"]), _parse(b["end"])
        _carve(gaps, bs, be)
        blocks.append({**b, "locked": True})
        if b.get("ref_id"):
            placed_refs.add(b["ref_id"])
        if b.get("goal_block"):
            goal_block_present = True

    def remaining(item_id: str | None) -> bool:
        return not (item_id and item_id in placed_refs)

    # 1. Hard anchors at fixed times (start, or wake+wake_relative).
    for a in hard_anchors:
        if not remaining(a.get("id")):
            continue
        dur = a.get("duration_minutes") or DEFAULT_TASK_MIN
        requested += dur
        if a.get("start"):
            start = _parse(a["start"])
        elif a.get("wake_relative"):
            m = re.search(r"wake\+(\d+)m", a["wake_relative"])
            start = wake + timedelta(minutes=int(m.group(1))) if m else wake
        else:
            start = wake
        placed = _place_fixed(gaps, start, dur)
        if placed:
            blocks.append(_block(*placed, "anchor", a["title"], a.get("id"), kind="hard"))
        else:
            deferred.append({"type": "anchor", "title": a["title"], "ref_id": a.get("id"),
                             "reason": "no room at its fixed time"})

    # 2. Goal floor — protected Q2 block, energy-preferred.
    if goal_floor and remaining((goal_floor.get("task") or {}).get("id")):
        task = goal_floor.get("task")
        title = task["title"] if task else f"Advance: {goal_floor['goal']['title']}"
        dur = (task.get("estimate_minutes") if task else None) or DEFAULT_GOAL_BLOCK_MIN
        requested += dur
        placed = _place_flex(gaps, dur, wake, sleep, prefer=energy_ranges)
        if placed:
            blocks.append(_block(*placed, "goal", title, task.get("id") if task else goal_floor["goal"]["id"],
                                 goal_block=True))
            goal_block_present = True
            if task:
                placed_refs.add(task["id"])
        else:
            deferred.append({"type": "goal", "title": title, "reason": "day too short for a goal block"})

    def place_task(t: dict, prefer: list | None = None) -> None:
        if not remaining(t.get("id")):
            return
        if not t.get("estimate_minutes"):
            deferred.append({"type": "task", "title": t["title"], "ref_id": t.get("id"),
                             "reason": "untimed — drop in manually"})
            return
        nonlocal requested
        dur = int(t["estimate_minutes"])
        requested += dur
        placed = _place_flex(gaps, dur, wake, sleep, prefer=prefer)
        if placed:
            blocks.append(_block(*placed, "task", t["title"], t.get("id")))
        else:
            deferred.append({"type": "task", "title": t["title"], "ref_id": t.get("id"),
                             "reason": "deferred — no room"})

    q = tasks_by_quadrant
    # 3. Q1 do-now.
    for t in q.get("Q1", []):
        place_task(t)

    # 4. Fixed / hard-constrained habits.
    flexible_habits = []
    for h in habits:
        if not remaining(h.get("id")):
            continue
        if h.get("flexibility") == "fixed" or h.get("hard_constraint"):
            _place_habit(h, gaps, wake, sleep, blocks, deferred)
            requested += h.get("duration_minutes") or DEFAULT_TASK_MIN
        else:
            flexible_habits.append(h)

    # 5. Q2 schedule (goal-advancing), energy-preferred.
    for t in q.get("Q2", []):
        place_task(t, prefer=energy_ranges)

    # 6. Flexible habits.
    for h in flexible_habits:
        _place_habit(h, gaps, wake, sleep, blocks, deferred)
        requested += h.get("duration_minutes") or DEFAULT_TASK_MIN

    # 7. Soft anchors within their windows.
    for a in soft_anchors:
        if not remaining(a.get("id")):
            continue
        dur = a.get("duration_minutes") or DEFAULT_TASK_MIN
        requested += dur
        lo, hi = wake, sleep
        if a.get("window_start"):
            lo = max(lo, _on_date(wake, _time(a["window_start"])))
        if a.get("window_end"):
            hi = min(hi, _on_date(wake, _time(a["window_end"])))
        placed = _place_flex(gaps, dur, lo, hi)
        if placed:
            blocks.append(_block(*placed, "anchor", a["title"], a.get("id"), kind="soft"))
        else:
            deferred.append({"type": "anchor", "title": a["title"], "ref_id": a.get("id"),
                             "reason": "no room in its window"})

    # 8. Q3 minimize (lowest auto-placed priority). Q4 is never auto-placed.
    for t in q.get("Q3", []):
        place_task(t)
    for t in q.get("Q4", []):
        if t.get("estimate_minutes"):
            deferred.append({"type": "task", "title": t["title"], "ref_id": t.get("id"),
                             "reason": "someday — left for you to pull in"})

    blocks.sort(key=lambda b: b["start"])
    window = _mins(wake, sleep)
    overcommit = max(0, requested - window)
    notice = None
    if not goal_block_present and goal_floor is None:
        notice = "nothing toward your goals today — want to fit one in?"
    elif not goal_block_present:
        notice = "couldn't fit a goal block — the day may be too short."
    elif overcommit > 0:
        notice = f"~{overcommit // 60}h {overcommit % 60}m over your window — consider trimming."

    return {
        "blocks": blocks,
        "deferred": deferred,
        "window_minutes": window,
        "requested_minutes": requested,
        "overcommit_minutes": overcommit,
        "goal_block_present": goal_block_present,
        "notice": notice,
    }


def _time(hhmm: str) -> time:
    h, m = hhmm.split(":")[:2] if ":" in hhmm else (hhmm, "0")
    return time(int(h), int(m))


def _place_habit(h: dict, gaps, wake, sleep, blocks, deferred) -> None:
    dur = h.get("duration_minutes") or DEFAULT_TASK_MIN
    lo, hi = _window_bounds(h.get("window_preference"), wake, sleep)
    lo, hi = _constraint_bounds(h.get("hard_constraint"), lo, hi)
    placed = _place_flex(gaps, dur, lo, hi)
    if placed is None:  # fall back to anytime if its preferred window is full
        placed = _place_flex(gaps, dur, wake, sleep)
    if placed:
        blocks.append(_block(*placed, "habit", h["name"], h.get("id")))
    else:
        deferred.append({"type": "habit", "title": h["name"], "ref_id": h.get("id"),
                         "reason": "no room — consider trimming"})


# ---- repository-backed entry points -----------------------------------


def _gather(repo: PlannerRepository, date_str: str) -> dict:
    goals_mod.ensure_default_areas(repo)
    anchors = repo.list_anchors(date_str)
    hard = [a for a in anchors if a["kind"] == "hard"]
    soft = [a for a in anchors if a["kind"] == "soft"]
    today = datetime.fromisoformat(date_str[:10]).date()
    habit_list = [h for h in habits_mod.habit_view(repo, today=today)
                  if not _habit_done(h, date_str)]
    by_q = list_tasks_by_quadrant(repo)
    goal_floor = _pick_goal_floor(repo)
    return {"hard": hard, "soft": soft, "habits": habit_list, "by_q": by_q, "goal_floor": goal_floor}


def _habit_done(h: dict, date_str: str) -> bool:
    prog = h.get("progress", {})
    if h["cadence_type"] == "daily":
        return bool(prog.get("done_today"))
    return bool(prog.get("met"))


def _pick_goal_floor(repo: PlannerRepository) -> dict | None:
    for g in goals_mod.goals_by_priority(repo):
        task = goals_mod.next_task_for_goal(repo, g["id"])
        if task:
            return {"goal": g, "task": task}
    actives = goals_mod.goals_by_priority(repo)
    return {"goal": actives[0], "task": None} if actives else None


def generate_day(
    repo: PlannerRepository,
    wake_time: str,
    sleep_target: str,
    date_str: str,
    *,
    now: str | None = None,
    if_enabled: bool = False,
    first_meal: str | None = None,
    eating_hours: int = 8,
    persist: bool = True,
) -> dict:
    """Generate a fresh greedy day plan and (by default) store it.

    `now` clamps placement to the present: if the current time is already inside the
    day's window, nothing is scheduled in the elapsed part of the day. Generating at
    5:40pm fills 5:40pm -> sleep, not the whole morning that is already gone.
    """
    wake, sleep = _parse(wake_time), _parse(sleep_target)
    start = wake
    if now:
        n = _parse(now)
        if wake <= n < sleep:  # we are mid-window today -> start from now
            start = n
    g = _gather(repo, date_str)
    result = fit_day(
        start, sleep,
        hard_anchors=g["hard"], soft_anchors=g["soft"], habits=g["habits"],
        goal_floor=g["goal_floor"], tasks_by_quadrant=g["by_q"],
    )
    plan = {"date": date_str, "wake_time": wake_time, "sleep_target": sleep_target,
            "if_enabled": if_enabled, "first_meal": first_meal, "eating_hours": eating_hours,
            **result}
    if persist:
        repo.save_day_plan(
            date_str, wake_time=wake_time, sleep_target=sleep_target, blocks=result["blocks"],
            if_enabled=if_enabled, first_meal=first_meal, eating_hours=eating_hours,
        )
    return plan


def reflow_from_now(
    repo: PlannerRepository, now: str, date_str: str, *, persist: bool = True
) -> dict | None:
    """Re-fit the rest of today from `now`, preserving locked/completed/past blocks.

    Goal-aware by construction: the regeneration re-pulls active goals and their next
    tasks, so the goal floor is re-guaranteed even after the day blew up.
    """
    plan = repo.get_day_plan(date_str)
    if plan is None:
        return None
    now_dt = _parse(now)
    sleep = _parse(plan["sleep_target"]) if plan.get("sleep_target") else None
    if sleep is None or sleep <= now_dt:
        return generate_day(repo, now, plan.get("sleep_target") or now, date_str,
                            if_enabled=plan["if_enabled"], first_meal=plan.get("first_meal"),
                            eating_hours=plan.get("eating_hours") or 8, persist=persist)

    # Locked: anything explicitly locked, completed, or already started/past.
    locked = [b for b in plan["blocks"]
              if b.get("locked") or _parse(b["end"]) <= now_dt or _parse(b["start"]) <= now_dt]
    g = _gather(repo, date_str)
    result = fit_day(
        now_dt, sleep,
        hard_anchors=g["hard"], soft_anchors=g["soft"], habits=g["habits"],
        goal_floor=g["goal_floor"], tasks_by_quadrant=g["by_q"], locked_blocks=locked,
    )
    out = {"date": date_str, "wake_time": plan.get("wake_time"), "sleep_target": plan["sleep_target"],
           "reflowed_from": now, "if_enabled": plan["if_enabled"],
           "first_meal": plan.get("first_meal"), "eating_hours": plan.get("eating_hours") or 8,
           **result}
    if persist:
        repo.save_day_plan(
            date_str, wake_time=plan.get("wake_time"), sleep_target=plan["sleep_target"],
            blocks=result["blocks"], if_enabled=plan["if_enabled"],
            first_meal=plan.get("first_meal"), eating_hours=plan.get("eating_hours") or 8,
        )
    return out


def fasting_overlay(plan: dict) -> dict | None:
    """Compute the intermittent-fasting eating window for a day (ARCHITECTURE §8).

    Pure display overlay: eating = first_meal .. first_meal + eating_hours; the rest is
    the fast. Never blocks or enforces. Returns None when off or no meal logged.
    """
    if not plan.get("if_enabled") or not plan.get("first_meal"):
        return None
    start = _parse(plan["first_meal"])
    end = start + timedelta(hours=plan.get("eating_hours") or 8)
    return {"eating_start": _iso(start), "eating_end": _iso(end),
            "eating_hours": plan.get("eating_hours") or 8}
