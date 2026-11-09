"""Tests for src.scheduler.queue (RunQueue serial execution + waitlist)."""

import asyncio

import pytest

from src.scheduler.plan import ScheduledJob
from src.scheduler.queue import RunQueue


def _job(job_id: str) -> ScheduledJob:
    return ScheduledJob(id=job_id, prompt=f"prompt {job_id}")


@pytest.mark.asyncio
async def test_queue_starts_not_running():
    q = RunQueue()
    assert q.is_running is False
    assert q.waitlist_size == 0


@pytest.mark.asyncio
async def test_queue_runs_jobs_serially(monkeypatch):
    q = RunQueue()
    order = []
    lock = asyncio.Lock()

    async def run(job):
        async with lock:
            order.append(f"start:{job.id}")
            await asyncio.sleep(0.05)
            order.append(f"end:{job.id}")

    # Submit three jobs quickly; they must run one at a time.
    await q.submit(_job("a"))
    await q.submit(_job("b"))
    await q.submit(_job("c"))

    # Drain the queue serially.
    results = []
    while q.waitlist_size or q.is_running:
        job = await q.next_job()
        results.append(job.id)
        await run(job)
        await q.done()

    assert results == ["a", "b", "c"]
    # starts must be ordered and never overlap: start a, end a, start b, ...
    assert order == ["start:a", "end:a", "start:b", "end:b", "start:c", "end:c"]
    assert q.is_running is False
    assert q.waitlist_size == 0


@pytest.mark.asyncio
async def test_queue_waitlist_order_preserved():
    q = RunQueue()
    await q.submit(_job("first"))
    await q.submit(_job("second"))
    await q.submit(_job("third"))
    assert q.waitlist_size == 3
    ids = [ (await q.next_job()).id for _ in range(3) ]
    assert ids == ["first", "second", "third"]
    for _ in range(3):
        await q.done()
    assert q.waitlist_size == 0


@pytest.mark.asyncio
async def test_queue_is_running_while_job_out():
    q = RunQueue()
    await q.submit(_job("a"))
    await q.next_job()
    assert q.is_running is True
    await q.done()
    assert q.is_running is False
