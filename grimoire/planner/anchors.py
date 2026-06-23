"""Anchor logic: the fixed/soft points the Flow day is built around, plus saving and
loading reusable day-shape templates.
"""

from __future__ import annotations

import uuid

from grimoire.planner.store import PlannerRepository


def create_anchor(repo: PlannerRepository, title: str, **kw) -> dict:
    aid = repo.add_anchor(title, **kw)
    return repo.get_anchor(aid)


def list_anchors(repo: PlannerRepository, date: str) -> list[dict]:
    return repo.list_anchors(date)


def delete_anchor(repo: PlannerRepository, anchor_id: str) -> int:
    return repo.delete_anchor(anchor_id)


def save_template(repo: PlannerRepository, name: str, date: str) -> dict:
    """Snapshot a day's anchors into a named template (stripped of the date/start)."""
    template_id = uuid.uuid4().hex
    saved = 0
    for a in repo.list_anchors(date):
        repo.add_anchor(
            a["title"], date=None, kind=a["kind"],
            start=None,  # absolute starts are day-specific; templates keep windows/offsets
            window_start=a.get("window_start"), window_end=a.get("window_end"),
            wake_relative=a.get("wake_relative"), duration_minutes=a.get("duration_minutes") or 0,
            template_id=template_id, template_name=name,
        )
        saved += 1
    return {"template_id": template_id, "name": name, "anchors": saved}


def list_templates(repo: PlannerRepository) -> list[dict]:
    return repo.list_templates()


def load_template(repo: PlannerRepository, template_id: str, date: str) -> list[dict]:
    """Instantiate a template's anchors onto a given date. Returns the created anchors."""
    created = []
    for a in repo.template_anchors(template_id):
        nid = repo.add_anchor(
            a["title"], date=date, kind=a["kind"], start=None,
            window_start=a.get("window_start"), window_end=a.get("window_end"),
            wake_relative=a.get("wake_relative"), duration_minutes=a.get("duration_minutes") or 0,
        )
        created.append(repo.get_anchor(nid))
    return created
