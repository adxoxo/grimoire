"""In-process registry for the long dashboard maintenance jobs.

Compaction, re-embedding, community detection, and inbox auto-file each run for many
seconds. Run inside the HTTP request, the browser has to hold one long request open to
observe the run, so navigating away or switching tabs loses track of a job that is in
fact still running server-side. This registry runs each job on a background daemon
thread and exposes its live status, so the POST returns immediately and any client can
poll GET /api/jobs for the truth.

In-memory by design: the API process is terminal-lived (see grimoire/scheduler.py), so a
dead process means dead jobs and an empty registry after a restart is the honest state.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any, Callable

# A job's live status is a plain dict so it serialises straight to JSON:
#   kind        one of "compact" | "reembed" | "recluster" | "autofile"
#   status      "running" | "done" | "failed"
#   started_at  ISO-8601 UTC
#   finished_at ISO-8601 UTC, or None while running
#   progress    {"done": int, "total": int, "detail": str} | None
#   result      the runner's return value (the old sync response body), or None
#   error       str | None
Job = dict[str, Any]

# Runners receive this to report progress: report({"done": i, "total": n, "detail": ...}).
ReportFn = Callable[[dict[str, Any]], None]
Runner = Callable[[ReportFn], dict[str, Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Registry:
    """The latest job per kind, guarded by one lock. Every job handed out is a copy, so
    callers can never mutate live state; the background thread mutates only under the lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, Job] = {}

    def start(self, kind: str, runner: Runner) -> tuple[Job, bool]:
        """Run `runner` on a daemon thread unless a job of this kind is already running.

        Returns (job, started). When a live job of this kind already exists, returns that
        job with started=False and does not launch a second one, so a re-clicked button
        (or a second tab) can never start an overlapping duplicate.
        """
        with self._lock:
            existing = self._jobs.get(kind)
            if existing is not None and existing["status"] == "running":
                return dict(existing), False
            job: Job = {
                "kind": kind,
                "status": "running",
                "started_at": _now(),
                "finished_at": None,
                "progress": None,
                "result": None,
                "error": None,
            }
            self._jobs[kind] = job

        def report(progress: dict[str, Any]) -> None:
            with self._lock:
                job["progress"] = dict(progress)

        def run() -> None:
            try:
                result = runner(report)
                with self._lock:
                    job["status"] = "done"
                    job["result"] = result
                    job["finished_at"] = _now()
            except Exception as exc:  # noqa: BLE001 - a job failure must never crash its thread
                with self._lock:
                    job["status"] = "failed"
                    job["error"] = str(exc)
                    job["finished_at"] = _now()

        threading.Thread(target=run, name=f"job-{kind}", daemon=True).start()
        with self._lock:
            return dict(job), True

    def snapshot(self) -> dict[str, Any]:
        """{"jobs": {kind: job}} with the latest job per kind, each a copy."""
        with self._lock:
            return {"jobs": {kind: dict(job) for kind, job in self._jobs.items()}}


# The one registry the API process shares across requests.
registry = Registry()
