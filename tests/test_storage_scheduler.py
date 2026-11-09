"""Tests for scheduled_jobs storage (schema v7)."""

import os
import tempfile

import pytest

from src.storage.manager import StorageManager


@pytest.fixture
def storage():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        yield StorageManager(path)
    finally:
        StorageManager(path).db.close()
        try:
            os.unlink(path)
        except OSError:
            pass


def _job(storage, job_id="job-1", prompt="test prompt", enabled=True, next_run_at=None):
    storage.save_scheduled_job(
        job_id=job_id,
        prompt=prompt,
        condition="new",
        category="electronics",
        mode="watchdog",
        trigger="every",
        trigger_value="60",
        every_unit="minutes",
        repeats=None,
        max_runs=0,
        enabled=enabled,
        next_run_at=next_run_at,
    )


def test_save_and_get_scheduled_job(storage):
    _job(storage)
    row = storage.get_scheduled_job("job-1")
    assert row is not None
    assert row["prompt"] == "test prompt"
    assert row["condition"] == "new"
    assert row["category"] == "electronics"
    assert row["mode"] == "watchdog"
    assert row["trigger"] == "every"
    assert row["trigger_value"] == "60"
    assert row["every_unit"] == "minutes"
    assert row["repeats"] is None
    assert row["max_runs"] == 0
    assert row["enabled"] == 1
    assert row["runs_done"] == 0
    assert row["last_status"] is None


def test_list_scheduled_jobs(storage):
    _job(storage, job_id="job-1", prompt="jedna")
    _job(storage, job_id="job-2", prompt="dva", enabled=False)
    rows = storage.list_scheduled_jobs()
    assert len(rows) == 2
    active = storage.list_scheduled_jobs(enabled_only=True)
    assert len(active) == 1
    assert active[0]["prompt"] == "jedna"


def test_due_scheduled_jobs(storage, monkeypatch):
    import src.storage.manager as m

    now = "2026-11-09T08:00:00+00:00"
    monkeypatch.setattr(m, "utcnow_iso", lambda: now)
    _job(storage, job_id="due", prompt="due job", next_run_at=now)
    _job(storage, job_id="future", prompt="future job",
         next_run_at="2026-11-10T08:00:00+00:00")
    _job(storage, job_id="disabled", prompt="disabled job",
         enabled=False, next_run_at=now)
    due = storage.due_scheduled_jobs()
    ids = {r["id"] for r in due}
    assert ids == {"due"}


def test_mark_job_scheduled_updates_next_run(storage):
    _job(storage, job_id="job-1", next_run_at="2026-11-09T08:00:00+00:00")
    storage.mark_job_scheduled(
        job_id="job-1",
        next_run_at="2026-11-09T09:00:00+00:00",
        runs_done=1,
        last_status="completed",
        last_run_at="2026-11-09T08:05:00+00:00",
    )
    row = storage.get_scheduled_job("job-1")
    assert row["next_run_at"] == "2026-11-09T09:00:00+00:00"
    assert row["runs_done"] == 1
    assert row["last_status"] == "completed"
    assert row["last_run_at"] == "2026-11-09T08:05:00+00:00"


def test_remove_scheduled_job(storage):
    _job(storage, job_id="job-1")
    assert storage.get_scheduled_job("job-1") is not None
    assert storage.remove_scheduled_job("job-1") is True
    assert storage.get_scheduled_job("job-1") is None
    assert storage.remove_scheduled_job("job-1") is False


def test_enable_disable_scheduled_job(storage):
    _job(storage, job_id="job-1", enabled=True)
    assert storage.disable_scheduled_job("job-1") is True
    assert storage.get_scheduled_job("job-1")["enabled"] == 0
    assert storage.enable_scheduled_job("job-1") is True
    assert storage.get_scheduled_job("job-1")["enabled"] == 1
    assert storage.disable_scheduled_job("missing") is False


def test_get_missing_job_returns_none(storage):
    assert storage.get_scheduled_job("missing") is None
