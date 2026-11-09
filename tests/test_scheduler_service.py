"""Tests for src.scheduler.service (SchedulerService daemon loop)."""

import asyncio
import os
import tempfile

import pytest

from src.scheduler.service import SchedulerService
from src.storage.manager import StorageManager


class FakeSearcher:
    """Async context-manager searcher that records calls and concurrency."""

    def __init__(self, deals, active_counter):
        self.deals = list(deals)
        self.calls = []
        self.active_counter = active_counter
        self.active = 0
        self.max_active = 0

    async def __aenter__(self):
        self.active += 1
        self.active_counter["current"] += 1
        self.active_counter["peak"] = max(self.active_counter["peak"],
                                          self.active_counter["current"])
        return self

    async def __aexit__(self, *args):
        self.active -= 1
        self.active_counter["current"] -= 1
        return False

    async def search(self, prompt, condition, category):
        self.calls.append((prompt, condition, category))
        await asyncio.sleep(0.05)  # simulate browser work
        return self.deals


@pytest.fixture
def storage():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = StorageManager(path)
    try:
        yield store
    finally:
        store.db.close()
        try:
            os.unlink(path)
        except OSError:
            pass


def _add_job(storage, job_id, prompt="x", mode="once", trigger="asap",
             trigger_value=None, unit="minutes", repeats=None,
             next_run_at="2026-11-09T08:00:00+00:00", enabled=True,
             condition="any", category="any"):
    storage.save_scheduled_job(
        job_id=job_id, prompt=prompt, condition=condition, category=category,
        mode=mode, trigger=trigger, trigger_value=trigger_value,
        every_unit=unit, repeats=repeats,
        max_runs=0 if mode == "watchdog" else 1,
        enabled=enabled, next_run_at=next_run_at,
    )


@pytest.mark.asyncio
async def test_service_runs_due_job_and_records(storage):
    counter = {"current": 0, "peak": 0}
    _add_job(storage, "j1", prompt="dji drone", next_run_at="2026-11-09T08:00:00+00:00")

    def make_searcher():
        return FakeSearcher([{"url": "u1", "title": "DJI", "price_eur": 100.0}], counter)

    svc = SchedulerService(storage, make_searcher, poll_interval=0.05)
    async def _stop_later():
        await asyncio.sleep(0.4)
        svc._stop = True

    await asyncio.gather(svc.run(), _stop_later())

    runs = storage.get_all_runs(limit=5)
    assert len(runs) == 1
    r = runs[0]
    assert r.prompt == "dji drone"
    assert r.status == "completed"
    assert r.total_deals == 1
    # Job is `once`, so next_run_at cleared -> disabled.
    job = storage.get_scheduled_job("j1")
    assert job["next_run_at"] is None
    assert job["runs_done"] == 1
    assert job["last_status"] == "completed"
    assert counter["peak"] <= 1  # no overlap


@pytest.mark.asyncio
async def test_service_serial_execution_no_overlap(storage):
    counter = {"current": 0, "peak": 0}
    # Both due at the same time; second must queue and run after first.
    now = "2026-11-09T08:00:00+00:00"
    _add_job(storage, "j1", prompt="prvy", next_run_at=now)
    _add_job(storage, "j2", prompt="druhy", next_run_at=now)

    def make_searcher():
        return FakeSearcher([], counter)

    svc = SchedulerService(storage, make_searcher, poll_interval=0.05)

    async def _stop_later():
        await asyncio.sleep(0.8)
        svc._stop = True

    await asyncio.gather(svc.run(), _stop_later())

    runs = storage.get_all_runs(limit=10)
    assert len(runs) == 2
    assert counter["peak"] <= 1  # never two searches at once
    # Both jobs advanced (once -> disabled).
    assert storage.get_scheduled_job("j1")["next_run_at"] is None
    assert storage.get_scheduled_job("j2")["next_run_at"] is None


@pytest.mark.asyncio
async def test_service_watchdog_reschedules(storage):
    _add_job(storage, "j1", prompt="watchdog", mode="watchdog",
             trigger="every", trigger_value="10", unit="minutes",
             next_run_at="2026-11-09T08:00:00+00:00")

    def make_searcher():
        return FakeSearcher([], {"current": 0, "peak": 0})

    svc = SchedulerService(storage, make_searcher, poll_interval=0.05)

    async def _stop_later():
        await asyncio.sleep(0.4)
        svc._stop = True

    await asyncio.gather(svc.run(), _stop_later())

    job = storage.get_scheduled_job("j1")
    assert job["runs_done"] == 1
    assert job["last_status"] == "completed"
    # next run = last_run_at + 10 minutes (within a small window)
    assert job["next_run_at"] is not None
    from datetime import datetime, timedelta

    base = datetime.fromisoformat(job["last_run_at"])
    value = datetime.fromisoformat(job["next_run_at"])
    expected = base + timedelta(minutes=10)
    assert abs((value - expected).total_seconds()) <= 60


@pytest.mark.asyncio
async def test_service_skips_disabled_and_not_due(storage):
    _add_job(storage, "j1", prompt="disabled", enabled=False,
             next_run_at="2026-11-09T08:00:00+00:00")
    _add_job(storage, "j2", prompt="future",
             next_run_at="2026-11-10T08:00:00+00:00")  # not due

    def make_searcher():
        return FakeSearcher([], {"current": 0, "peak": 0})

    svc = SchedulerService(storage, make_searcher, poll_interval=0.05)

    async def _stop_later():
        await asyncio.sleep(0.3)
        svc._stop = True

    await asyncio.gather(svc.run(), _stop_later())

    runs = storage.get_all_runs(limit=10)
    assert len(runs) == 0
