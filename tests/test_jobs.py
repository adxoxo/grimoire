"""The background job registry and the maintenance/inbox routes that run through it.

All API tests use the offline fake provider and a per-test temp db. Jobs run on real
daemon threads, so the tests poll to completion with a deadline rather than sleeping
blind. The registry singleton is cleared per API test so one test's jobs never leak into
the next.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from grimoire import jobs


def _wait(pred, timeout: float = 10.0, interval: float = 0.02) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if pred():
            return True
        time.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# Registry unit tests (no HTTP)
# ---------------------------------------------------------------------------


def test_start_runs_and_captures_result():
    reg = jobs.Registry()
    job, started = reg.start("compact", lambda report: {"ok": 1})
    assert started is True
    # a trivial runner may already have finished by the time start() snapshots it; the
    # deterministic non-blocking proof is in the dedupe/progress tests below
    assert job["status"] in ("running", "done")
    assert _wait(lambda: reg.snapshot()["jobs"]["compact"]["status"] == "done")
    done = reg.snapshot()["jobs"]["compact"]
    assert done["result"] == {"ok": 1}
    assert done["finished_at"] is not None


def test_second_start_of_running_kind_is_deduped():
    reg = jobs.Registry()
    release = threading.Event()

    def blocked(_report):
        release.wait(5)
        return {"ok": 1}

    reg.start("compact", blocked)
    # while the first is still blocked, a second start must not launch a duplicate
    job2, started2 = reg.start("compact", lambda report: {"ok": 2})
    assert started2 is False
    assert job2["status"] == "running"
    release.set()
    assert _wait(lambda: reg.snapshot()["jobs"]["compact"]["status"] == "done")
    # the winner is the first runner, not the deduped second
    assert reg.snapshot()["jobs"]["compact"]["result"] == {"ok": 1}


def test_new_job_of_same_kind_starts_after_completion():
    reg = jobs.Registry()
    reg.start("recluster", lambda report: {"n": 1})
    assert _wait(lambda: reg.snapshot()["jobs"]["recluster"]["status"] == "done")
    _job, started = reg.start("recluster", lambda report: {"n": 2})
    assert started is True


def test_failure_is_captured_not_raised():
    reg = jobs.Registry()

    def boom(_report):
        raise RuntimeError("nope")

    reg.start("reembed", boom)
    assert _wait(lambda: reg.snapshot()["jobs"]["reembed"]["status"] == "failed")
    snap = reg.snapshot()["jobs"]["reembed"]
    assert "nope" in snap["error"]
    assert snap["finished_at"] is not None


def test_progress_is_visible_in_snapshot():
    reg = jobs.Registry()
    reported = threading.Event()
    release = threading.Event()

    def slow(report):
        report({"done": 1, "total": 3, "detail": "x"})
        reported.set()
        release.wait(5)
        return {"ok": 1}

    reg.start("autofile", slow)
    assert reported.wait(5)
    assert reg.snapshot()["jobs"]["autofile"]["progress"] == {"done": 1, "total": 3, "detail": "x"}
    release.set()


def test_snapshot_hands_out_copies_not_live_state():
    reg = jobs.Registry()
    reg.start("compact", lambda report: {"ok": 1})
    assert _wait(lambda: reg.snapshot()["jobs"]["compact"]["status"] == "done")
    snap = reg.snapshot()
    snap["jobs"]["compact"]["status"] = "tampered"
    # mutating the copy must not change what the registry reports next
    assert reg.snapshot()["jobs"]["compact"]["status"] == "done"


# ---------------------------------------------------------------------------
# Route behaviour (fake provider, temp db)
# ---------------------------------------------------------------------------


@pytest.fixture
def client(tmp_path: Path, monkeypatch):
    import grimoire.api as apimod
    from fastapi.testclient import TestClient
    from grimoire.providers import get_provider

    monkeypatch.setattr(apimod.settings, "db_path", tmp_path / "g.db")
    monkeypatch.setattr(apimod, "_provider", get_provider("fake"))
    jobs.registry._jobs.clear()  # a clean registry per test so jobs never leak across
    return TestClient(apimod.app)


def _poll_job(client, kind: str, timeout: float = 10.0) -> dict:
    def done() -> bool:
        j = client.get("/api/jobs").json()["jobs"].get(kind, {})
        return j.get("status") in ("done", "failed")

    assert _wait(done, timeout=timeout), f"{kind} did not finish in time"
    return client.get("/api/jobs").json()["jobs"][kind]


def test_compact_returns_immediately_then_completes(client):
    r = client.post("/api/maintenance/compact")
    assert r.status_code == 200
    body = r.json()
    assert body["started"] is True and body["job"]["kind"] == "compact"
    # status is running unless the (empty-db, fake-provider) job already finished
    assert body["job"]["status"] in ("running", "done")
    job = _poll_job(client, "compact")
    assert job["status"] == "done"
    assert isinstance(job["result"]["compacted"], list)


def test_recluster_route_exists_and_completes(client):
    # Regression: the dashboard called /api/maintenance/recluster but it was never
    # defined, so "Community detection" always 404'd. It exists now.
    r = client.post("/api/maintenance/recluster")
    assert r.status_code == 200 and r.json()["started"] is True
    job = _poll_job(client, "recluster")
    assert job["status"] == "done"
    assert "communities" in job["result"] and "nodes" in job["result"]


def test_autofile_empty_inbox_completes(client):
    r = client.post("/api/inbox/autofile")
    assert r.status_code == 200 and r.json()["started"] is True
    job = _poll_job(client, "autofile")
    assert job["status"] == "done"
    assert job["result"]["filed_count"] == 0 and job["result"]["skipped_count"] == 0


def test_jobs_read_open_but_writes_guarded(client, monkeypatch):
    import grimoire.api as apimod

    monkeypatch.setattr(apimod.settings, "api_token", "sekrit")
    # the status read stays open even when writes are token-guarded
    assert client.get("/api/jobs").status_code == 200
    # starting a job is a write: 401 without the bearer
    assert client.post("/api/maintenance/compact").status_code == 401
    assert client.post("/api/inbox/autofile").status_code == 401
    # accepted with the bearer
    ok = client.post("/api/maintenance/compact", headers={"authorization": "Bearer sekrit"})
    assert ok.status_code == 200 and ok.json()["started"] is True
