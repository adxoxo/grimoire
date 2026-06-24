"""Scribe-from-text tests: the LLM is monkeypatched to a fixed JSON reply, so these
verify the node-creation logic only (no network/model needed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from grimoire.providers import get_provider
from grimoire.scribe import scribe_from_text
from grimoire.service import KnowledgeService
from grimoire.store import Repository


def _svc(tmp_path: Path, reply: str):
    prov = get_provider("fake")
    prov.complete = lambda *a, **k: reply  # type: ignore[assignment]
    repo = Repository(tmp_path / "g.db")
    return KnowledgeService(repo, prov), repo


def test_scribe_memory_links_to_project(tmp_path: Path):
    svc, repo = _svc(tmp_path, '{"type":"memory","title":"i2c pinout","content":"SDA on PB7","project":"Firmware"}')
    out = scribe_from_text(svc, "remember the i2c pinout, SDA on PB7")
    assert out["type"] == "memory" and out["title"] == "i2c pinout" and out["project"] == "Firmware"
    proj = repo.get_project("Firmware")
    assert proj is not None and any(l["type"] == "memory" for l in proj["linked"])


def test_scribe_entity(tmp_path: Path):
    svc, repo = _svc(tmp_path, '{"type":"entity","title":"STM32","content":"ARM MCU family","project":"Firmware"}')
    out = scribe_from_text(svc, "track STM32 as an entity")
    assert out["type"] == "entity"
    assert any(l["title"] == "STM32" for l in repo.get_project("Firmware")["linked"])


def test_scribe_new_project(tmp_path: Path):
    svc, repo = _svc(tmp_path, '{"type":"project","title":"Australia migration","content":"visa + job plan"}')
    out = scribe_from_text(svc, "start a quest line for migrating to Australia")
    assert out["type"] == "project"
    assert repo.get_project("Australia migration") is not None


def test_scribe_tolerates_code_fences_and_defaults_project(tmp_path: Path):
    svc, repo = _svc(tmp_path, '```json\n{"type":"memory","title":"random idea","content":"a thought"}\n```')
    out = scribe_from_text(svc, "a thought")
    assert out["type"] == "memory" and out["project"] == "Inbox"  # default catch-all
    assert repo.get_project("Inbox") is not None
