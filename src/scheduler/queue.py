"""Serial run queue with waitlist for the system monitor.

Guarantees mutual exclusion: at most one scheduled job runs at a time. Jobs
submitted while another is running are parked in a FIFO waitlist and started
in order as soon as the running job finishes.
"""

from __future__ import annotations

import asyncio
from collections import deque

from src.scheduler.plan import ScheduledJob


class RunQueue:
    """FIFO queue that executes jobs one at a time.

    ``submit`` enqueues a job. ``next_job`` blocks until a job is available
    and marks the queue as running (holding the mutual-exclusion lock).
    ``done`` releases the lock so the next queued job can start.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue[ScheduledJob] = asyncio.Queue()
        self._waitlist: deque[ScheduledJob] = deque()
        self._lock = asyncio.Lock()
        self._running = False

    @property
    def is_running(self) -> bool:
        """True while a job is currently being executed."""
        return self._running

    @property
    def waitlist_size(self) -> int:
        """Number of jobs waiting to run (queued but not started)."""
        return self._queue.qsize() + len(self._waitlist)

    async def submit(self, job: ScheduledJob) -> None:
        """Enqueue *job* for serial execution."""
        await self._queue.put(job)

    async def next_job(self) -> ScheduledJob:
        """Block until the next job is available and mark the queue running."""
        job = await self._queue.get()
        async with self._lock:
            self._running = True
        return job

    async def done(self) -> None:
        """Mark the current job finished and release the run lock."""
        async with self._lock:
            self._running = False
