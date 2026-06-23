"""The Grimoire Planner: Today (task matrix, habits, goals) + Flow (day scheduler).

A separate subsystem layered on the same SQLite store as the knowledge graph. The
store module owns all planner SQL; the core logic modules (tasks, habits, goals,
urgency, anchors, schedule) are plain functions over the repository; the API, MCP,
and Groq chat are thin adapters over those functions. Logic never lives in an adapter.
"""

from __future__ import annotations

from grimoire.planner.store import PlannerRepository

__all__ = ["PlannerRepository"]
