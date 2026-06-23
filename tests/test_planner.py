"""Planner acceptance tests (the grimoire-v2 task/habit/goal/scheduler subsystem).

Covers the core logic: the hybrid urgency engine + quadrant placement, habit streaks
and the weekly report, goal-floor selection, and the greedy day-fitter (goal floor
guaranteed, graceful degradation, hard-anchor placement, reflow preserving locks).

All tests use a per-test temp database via pytest's tmp_path fixture. No provider or
network is needed — the planner core is pure logic over the store.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from grimoire.planner import habits as H
from grimoire.planner import goals as G
from grimoire.planner import schedule as S
from grimoire.planner import tasks as T
from grimoire.planner.store import PlannerRepository
from grimoire.planner.urgency import compute_urgent, daily_sweep


@pytest.fixture
def repo(tmp_path: Path):
    r = PlannerRepository(tmp_path / "planner.db")
    yield r
    r.close()


def _iso(dt: datetime) -> str:
    return dt.isoformat()


# ---------------------------------------------------------------------------
# Urgency engine + quadrants
# ---------------------------------------------------------------------------

def test_compute_urgent_bands():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    assert compute_urgent(_iso(now + timedelta(days=10)), now) is True   # <=14d urgent
    assert compute_urgent(_iso(now + timedelta(days=45)), now) is False  # >30d not urgent
    assert compute_urgent(None, now) is False


def test_task_quadrants_from_flags(repo):
    t = T.create_task(repo, "manual urgent+important", important=True, urgent_manual=True)
    assert t["quadrant"] == "Q1"
    t2 = T.create_task(repo, "important not urgent", important=True)
    assert t2["quadrant"] == "Q2"
    t3 = T.create_task(repo, "urgent not important", urgent_manual=True)
    assert t3["quadrant"] == "Q3"
    t4 = T.create_task(repo, "neither")
    assert t4["quadrant"] == "Q4"


def test_deadline_auto_promotes_q2_to_q1(repo):
    """A firmware-style task slides Q2 -> Q1 as its goal's deadline nears (manual
    override still wins)."""
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    far = G.create_goal(repo, "Firmware roadmap", area="craft",
                        target_date=_iso(now + timedelta(days=60)))
    task = T.create_task(repo, "i2c driver", important=True, goal_id=far["id"])
    assert T.quadrant(task) == "Q2"  # deadline far -> not urgent

    # Move the deadline inside the urgent band and re-sweep.
    G.modify_goal(repo, far["id"], {"target_date": _iso(now + timedelta(days=10))})
    daily_sweep(repo, now=now)
    promoted = repo.get_task(task["id"])
    assert T.quadrant(promoted) == "Q1"


def test_delete_task(repo):
    t = T.create_task(repo, "scrap this")
    assert T.delete_task(repo, t["id"]) is True
    assert repo.get_task(t["id"]) is None
    assert T.delete_task(repo, t["id"]) is False  # already gone


def test_delete_goal_detaches_its_tasks(repo):
    g = G.create_goal(repo, "Doomed goal", area="career")
    t = T.create_task(repo, "orphan me", goal_id=g["id"])
    assert G.delete_goal(repo, g["id"]) is True
    assert repo.get_goal(g["id"]) is None
    # the task survives, just detached (foreign key stays satisfied)
    assert repo.get_task(t["id"])["goal_id"] is None


def test_delete_habit_clears_log(repo):
    h = H.create_habit(repo, "fleeting")
    repo.log_habit(h["id"], "2026-06-23")
    assert H.delete_habit(repo, h["id"]) is True
    assert repo.get_habit(h["id"]) is None
    assert repo.habit_log_dates(h["id"]) == []


def test_estimate_total_time_excludes_untimed(repo):
    T.create_task(repo, "a", estimate_minutes=60)
    T.create_task(repo, "b", estimate_minutes=120)
    T.create_task(repo, "c")  # untimed
    summary = T.estimate_total_time(repo)
    assert summary["minutes"] == 180
    assert summary["untimed"] == 1
    assert "untimed" in summary["label"]


# ---------------------------------------------------------------------------
# Habits + streaks
# ---------------------------------------------------------------------------

def test_daily_streak_counts_consecutive():
    today = date(2026, 6, 10)
    dates = [(today - timedelta(days=i)).isoformat() for i in range(5)]  # today..-4
    s = H.compute_daily_streak(dates, today)
    assert s["current"] == 5

    # A gap two days ago breaks the current run but not the best.
    gappy = [today.isoformat(), (today - timedelta(days=3)).isoformat(),
             (today - timedelta(days=4)).isoformat(), (today - timedelta(days=5)).isoformat()]
    s2 = H.compute_daily_streak(gappy, today)
    assert s2["current"] == 1
    assert s2["best"] == 3


def test_weekly_progress_and_report(repo):
    today = date(2026, 6, 10)  # a Wednesday
    cardio = H.create_habit(repo, "cardio", cadence_type="weekly", weekly_target=3)
    ws = H.week_start(today)
    for i in range(2):
        repo.log_habit(cardio["id"], (ws + timedelta(days=i)).isoformat())
    prog = H.weekly_progress(repo, repo.get_habit(cardio["id"]), today=today)
    assert prog == {"count": 2, "target": 3, "met": False}

    report = H.weekly_report(repo, today=today)
    assert 0 <= report["overall_percent"] <= 100
    assert report["habits"][0]["name"] == "cardio"


def test_toggle_habit_roundtrip(repo):
    h = H.create_habit(repo, "meditation")
    d = "2026-06-10"
    on = H.toggle_habit(repo, h["id"], d)
    assert on["done_today"] is True and on["streak_current"] == 1
    off = H.toggle_habit(repo, h["id"], d)
    assert off["done_today"] is False


# ---------------------------------------------------------------------------
# Goals
# ---------------------------------------------------------------------------

def test_next_task_for_goal_prefers_q2(repo):
    g = G.create_goal(repo, "Ship beta", area="career")
    T.create_task(repo, "urgent fire", important=True, urgent_manual=True, goal_id=g["id"])  # Q1
    q2 = T.create_task(repo, "deep work", important=True, goal_id=g["id"])  # Q2
    pick = G.next_task_for_goal(repo, g["id"])
    assert pick["id"] == q2["id"]


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def _setup_day(repo):
    g = G.create_goal(repo, "Ship beta", area="career", priority=10)
    T.create_task(repo, "architecture deep work", important=True,
                  estimate_minutes=120, goal_id=g["id"])  # Q2 goal-floor candidate
    T.create_task(repo, "reply to vendor", urgent_manual=True, estimate_minutes=30)  # Q3
    H.create_habit(repo, "meditation", duration_minutes=20, window_preference="morning")
    return g


def test_generate_day_guarantees_goal_floor(repo):
    _setup_day(repo)
    wake = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)
    sleep = datetime(2026, 6, 11, 1, 0, tzinfo=timezone.utc)  # "woke at 10, sleeping at 1"
    plan = S.generate_day(repo, _iso(wake), _iso(sleep), "2026-06-10")
    assert plan["goal_block_present"] is True
    assert any(b["goal_block"] for b in plan["blocks"])
    assert any(b["type"] == "habit" for b in plan["blocks"])


def test_generate_from_now_skips_elapsed_hours(repo):
    """Generating mid-day starts from `now`, never scheduling the morning that is gone."""
    _setup_day(repo)
    wake = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)
    sleep = datetime(2026, 6, 10, 23, 0, tzinfo=timezone.utc)
    now = datetime(2026, 6, 10, 18, 0, tzinfo=timezone.utc)  # "it's 6pm"
    plan = S.generate_day(repo, _iso(wake), _iso(sleep), "2026-06-10", now=_iso(now))
    assert plan["blocks"], "should still fill the evening"
    for b in plan["blocks"]:
        assert S._parse(b["start"]) >= now  # nothing before 6pm
    assert plan["goal_block_present"]


def test_short_day_degrades_but_keeps_goal_floor(repo):
    _setup_day(repo)
    # Add lots of low-priority timed tasks to force overcommit on a tiny window.
    for i in range(8):
        T.create_task(repo, f"busywork {i}", urgent_manual=True, estimate_minutes=60)  # Q3
    wake = datetime(2026, 6, 10, 22, 0, tzinfo=timezone.utc)
    sleep = datetime(2026, 6, 11, 1, 0, tzinfo=timezone.utc)  # only 3h
    plan = S.generate_day(repo, _iso(wake), _iso(sleep), "2026-06-10")
    assert plan["goal_block_present"] is True              # floor protected
    assert plan["overcommit_minutes"] > 0                  # honest about the squeeze
    assert plan["notice"]


def test_hard_anchor_is_pinned(repo):
    _setup_day(repo)
    wake = datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc)
    sleep = datetime(2026, 6, 10, 23, 0, tzinfo=timezone.utc)
    repo.add_anchor("dentist", date="2026-06-10", kind="hard",
                    start=_iso(datetime(2026, 6, 10, 14, 0, tzinfo=timezone.utc)),
                    duration_minutes=60)
    plan = S.generate_day(repo, _iso(wake), _iso(sleep), "2026-06-10")
    anchor = next(b for b in plan["blocks"] if b["title"] == "dentist")
    assert anchor["start"].startswith("2026-06-10T14:00")


def test_reflow_preserves_locked_blocks(repo):
    _setup_day(repo)
    wake = datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc)
    sleep = datetime(2026, 6, 10, 23, 0, tzinfo=timezone.utc)
    S.generate_day(repo, _iso(wake), _iso(sleep), "2026-06-10")
    # Reflow at 2pm: morning blocks become locked/past and survive.
    now = datetime(2026, 6, 10, 14, 0, tzinfo=timezone.utc)
    reflow = S.reflow_from_now(repo, _iso(now), "2026-06-10")
    assert reflow is not None
    assert reflow["goal_block_present"] is True
    # Every non-locked block must start at/after the reflow point.
    for b in reflow["blocks"]:
        if not b["locked"]:
            assert S._parse(b["start"]) >= now


def test_fasting_overlay_off_by_default(repo):
    plan = {"if_enabled": False, "first_meal": None}
    assert S.fasting_overlay(plan) is None
    plan2 = {"if_enabled": True, "first_meal": _iso(datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)),
             "eating_hours": 8}
    overlay = S.fasting_overlay(plan2)
    assert overlay["eating_end"].startswith("2026-06-10T20:00")
