"""Ops hardening tests: Ollama URL auto-resolution and backup retention.

No network, no live Ollama or store needed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from grimoire import config as config_module
from grimoire.backup import prune_backups
from grimoire.config import Settings


def test_ollama_url_auto_resolves(monkeypatch):
    monkeypatch.setattr(config_module, "_resolve_wsl_ollama_url", lambda: "http://172.20.0.1:11434")
    s = Settings(ollama_url="auto")
    assert s.ollama_url == "http://172.20.0.1:11434"


def test_ollama_url_empty_resolves(monkeypatch):
    monkeypatch.setattr(config_module, "_resolve_wsl_ollama_url", lambda: "http://172.20.0.1:11434")
    s = Settings(ollama_url="")
    assert s.ollama_url == "http://172.20.0.1:11434"


def test_ollama_url_explicit_passthrough(monkeypatch):
    def boom():
        raise AssertionError("resolver should not be called for an explicit URL")

    monkeypatch.setattr(config_module, "_resolve_wsl_ollama_url", boom)
    s = Settings(ollama_url="http://example.com:11434")
    assert s.ollama_url == "http://example.com:11434"


def test_resolve_wsl_ollama_url_falls_back_on_missing_command(monkeypatch):
    def fake_run(*args, **kwargs):
        raise FileNotFoundError("ip: command not found")

    monkeypatch.setattr(config_module.subprocess, "run", fake_run)
    assert config_module._resolve_wsl_ollama_url() == config_module._DEFAULT_OLLAMA_URL


def test_resolve_wsl_ollama_url_falls_back_on_no_match(monkeypatch):
    class FakeResult:
        stdout = "some unrelated output\n"

    monkeypatch.setattr(config_module.subprocess, "run", lambda *a, **k: FakeResult())
    assert config_module._resolve_wsl_ollama_url() == config_module._DEFAULT_OLLAMA_URL


def _touch_backup(backup_dir: Path, ts: str) -> Path:
    path = backup_dir / f"grimoire-{ts}.db"
    path.write_text("fake db")
    return path


def test_prune_backups_keeps_newest_n(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    timestamps = [f"2026070{i}T000000Z" for i in range(1, 10)]  # 9 fake backups
    for ts in timestamps:
        _touch_backup(backup_dir, ts)

    deleted = prune_backups(backup_dir, retain=5)

    remaining = sorted(p.name for p in backup_dir.glob("grimoire-*.db"))
    assert len(remaining) == 5
    # the 5 newest (last 5 timestamps) survive
    assert remaining == [f"grimoire-{ts}.db" for ts in timestamps[-5:]]
    assert len(deleted) == 4
    assert all(not p.exists() for p in deleted)


def test_prune_backups_noop_when_under_limit(tmp_path):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    for ts in ["20260701T000000Z", "20260702T000000Z"]:
        _touch_backup(backup_dir, ts)

    deleted = prune_backups(backup_dir, retain=14)

    assert deleted == []
    assert len(list(backup_dir.glob("grimoire-*.db"))) == 2
