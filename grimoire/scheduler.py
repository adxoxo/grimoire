"""In-process maintenance scheduler for the local (terminal-lived) server.

The Grimoire runs on a local box, not a VPS, so the process comes and goes with the
terminal. This runs compaction + backup on BOOT, once DAILY, and on SHUTDOWN, all
inside the API process via the FastAPI lifespan. A staleness guard keeps frequent
boots from recompacting redundantly; backups are cheap and always taken.

All Ollama/DB work runs inside asyncio.to_thread so the event loop is never blocked.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from grimoire.backup import make_backup, prune_backups
from grimoire.compaction import compact_project, consolidate_context
from grimoire.config import settings
from grimoire.providers import get_provider
from grimoire.service import KnowledgeService
from grimoire.store import Repository

logger = logging.getLogger(__name__)

# The local hour the daily maintenance pass fires at (server local time).
DAILY_HOUR = 3

# Serialises boot and daily passes so they never overlap.
_lock = asyncio.Lock()


# ---- last-run marker (lives next to the db) --------------------------------


def _marker_path() -> Path:
    return settings.db_path.parent / "last_maintenance.txt"


def _last_run() -> datetime | None:
    """The last recorded maintenance run (UTC), or None if never / unreadable."""
    try:
        text = _marker_path().read_text().strip()
    except OSError:
        return None
    try:
        ts = datetime.fromisoformat(text)
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def _mark_run() -> None:
    """Stamp the marker with the current UTC time."""
    path = _marker_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(datetime.now(timezone.utc).isoformat())
    except OSError as exc:
        logger.warning("maintenance: could not write marker %s: %s", path, exc)


# ---- the synchronous work (safe to call in a worker thread) ----------------


def run_maintenance(reason: str, force: bool = False) -> dict:
    """Backup (always) + compaction (guarded). Synchronous; safe in a worker thread.

    Never raises: a provider/LLM/DB outage during maintenance must not crash the server
    it runs inside. Returns a small summary dict.
    """
    summary = {"reason": reason, "backed_up": False, "compacted": False, "skipped": False}

    # 1. Backup is cheap and independent; always attempt it.
    try:
        dest = make_backup(db_path=settings.db_path)
        prune_backups(retain=settings.backup_retain)
        summary["backed_up"] = True
        logger.info("maintenance(%s): backed up to %s", reason, dest)
    except Exception as exc:  # noqa: BLE001 - backup failure must not crash the caller
        logger.warning("maintenance(%s): backup failed: %s", reason, exc)

    # 2. Staleness guard: skip compaction if we ran recently (unless forced).
    last = _last_run()
    if not force and last is not None:
        age_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
        if age_hours < settings.maintenance_min_interval_hours:
            summary["skipped"] = True
            logger.info("maintenance(%s): compaction skipped, ran %.1fh ago", reason, age_hours)
            return summary

    # 3. Compaction across all projects (mirrors api.run_compaction).
    try:
        provider = get_provider()
        repo = Repository(settings.db_path)
        try:
            svc = KnowledgeService(repo, provider)
            for project in [n["title"] for n in repo.list_nodes(type="project")]:
                compact_project(svc, project)
                consolidate_context(svc, project)
        finally:
            repo.close()
        _mark_run()
        summary["compacted"] = True
        logger.info("maintenance(%s): compaction complete", reason)
    except Exception as exc:  # noqa: BLE001 - LLM/DB outage must not crash the caller
        logger.warning("maintenance(%s): compaction failed: %s", reason, exc)

    return summary


# ---- the async schedule (boot -> daily loop, plus shutdown) ----------------


def _seconds_until_daily() -> float:
    """Seconds from now until the next DAILY_HOUR:00 in server local time."""
    now = datetime.now()
    target = now.replace(hour=DAILY_HOUR, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def _boot_and_loop() -> None:
    """Run the boot pass, then one forced pass each day at DAILY_HOUR."""
    try:
        async with _lock:
            await asyncio.to_thread(run_maintenance, "boot")
        while True:
            await asyncio.sleep(_seconds_until_daily())
            async with _lock:
                await asyncio.to_thread(run_maintenance, "daily", force=True)
    except asyncio.CancelledError:
        logger.info("maintenance: scheduler loop cancelled")
        raise


@contextlib.asynccontextmanager
async def lifespan(app):
    """Boot + daily + shutdown maintenance, in-process. A no-op when disabled."""
    task: asyncio.Task | None = None
    if settings.scheduler_enabled:
        task = asyncio.create_task(_boot_and_loop())
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if settings.scheduler_enabled:
            # Best-effort shutdown pass (usually a fast backup-only pass thanks to the
            # staleness guard). Never hang or crash shutdown on it.
            try:
                async with _lock:
                    await asyncio.to_thread(run_maintenance, "shutdown")
            except Exception as exc:  # noqa: BLE001 - shutdown must not hang or crash
                logger.warning("maintenance(shutdown): failed: %s", exc)
