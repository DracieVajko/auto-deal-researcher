"""System-monitor service: loads due scheduled jobs and runs them serially.

Guarantees mutual exclusion: at most one job runs at a time. Jobs that become
due while another is running are parked in the :class:`RunQueue` waitlist and
started in order as soon as the running job finishes.

The service is a long-running asyncio loop intended to be launched by the
`schedule service` CLI command, which in turn is registered to start with the
system (Windows Task Scheduler logon trigger).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from src.scheduler.plan import ScheduledJob, ScheduleSpec
from src.scheduler.queue import RunQueue
from src.storage.manager import StorageManager
from src.utils.time import utcnow_iso

logger = logging.getLogger(__name__)

# A searcher factory is an async context manager returning an object with
# an async ``search(prompt, condition, category) -> list[Deal]`` method.
SearcherFactory = Callable[[], Any]


class SchedulerService:
    """Daemon that polls for due scheduled jobs and executes them serially."""

    def __init__(
        self,
        storage: StorageManager,
        make_searcher: SearcherFactory,
        queue: RunQueue | None = None,
        poll_interval: float = 30.0,
    ) -> None:
        self.storage = storage
        self.make_searcher = make_searcher
        self.queue = queue or RunQueue()
        self.poll_interval = float(poll_interval)
        self._stop = False
        self._worker_task: asyncio.Task | None = None
        self._in_flight: set[str] = set()

    async def run(self) -> None:
        """Main loop: enqueue due jobs, worker executes them serially."""
        self._stop = False
        self._worker_task = asyncio.create_task(self._worker())
        try:
            while not self._stop:
                await self._enqueue_due()
                await asyncio.sleep(self.poll_interval)
        finally:
            self._stop = True
            if self._worker_task is not None:
                self._worker_task.cancel()
                try:
                    await self._worker_task
                except asyncio.CancelledError:
                    pass

    async def _enqueue_due(self) -> None:
        """Submit due, enabled, not-in-flight jobs to the run queue."""
        now = utcnow_iso()
        for row in self.storage.due_scheduled_jobs(now):
            job_id = row["id"]
            if job_id in self._in_flight:
                continue
            job = ScheduledJob(
                id=job_id,
                prompt=row["prompt"],
                condition=row["condition"],
                category=row["category"],
                mode=row["mode"],
                spec=ScheduleSpec(
                    trigger=row["trigger"],
                    trigger_value=row["trigger_value"],
                    every_unit=row["every_unit"],
                    repeats=row["repeats"],
                ),
                enabled=row["enabled"],
                next_run_at=row["next_run_at"],
                created_at=row["created_at"],
                last_run_at=row["last_run_at"],
                runs_done=row["runs_done"],
                last_status=row["last_status"],
            )
            await self.queue.submit(job)
            self._in_flight.add(job_id)
            logger.info("Enqueued scheduled job %s (%s)", job_id, job.prompt)

    async def _worker(self) -> None:
        """Pull jobs from the queue and run them one at a time."""
        while not self._stop:
            try:
                job = await asyncio.wait_for(self.queue.next_job(), timeout=1.0)
            except TimeoutError:
                continue
            try:
                await self._run_job(job)
            finally:
                self._in_flight.discard(job.id)
                await self.queue.done()

    async def _run_job(self, job: ScheduledJob) -> None:
        """Execute a single scheduled job and persist its result."""
        from src.searcher.adapters.base import Deal

        run_id = f"sched_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}"
        self.storage.create_run(run_id, job.prompt, job.condition, job.category)
        now = utcnow_iso()
        status = "completed"
        total_deals = 0
        error = ""

        try:
            async with self.make_searcher() as searcher:
                deals = await searcher.search(job.prompt, job.condition, job.category)
            deals = list(deals or [])
            total_deals = len(deals)
            for deal in deals:
                if isinstance(deal, Deal):
                    self.storage.save_deal(deal, run_id)
        except Exception as exc:
            status = "failed"
            error = str(exc)
            logger.exception("Scheduled job %s failed", job.id)
        finally:
            self.storage.complete_run(run_id, total_deals, total_deals, status, error)
            job.advance(now, status)
            self.storage.mark_job_scheduled(
                job_id=job.id,
                next_run_at=job.next_run_at,
                runs_done=job.runs_done,
                last_status=job.last_status,
                last_run_at=job.last_run_at,
            )
            logger.info(
                "Scheduled job %s finished: %s deals, status=%s, next_run_at=%s",
                job.id, total_deals, status, job.next_run_at,
            )
