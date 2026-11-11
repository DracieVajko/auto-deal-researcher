"""Tests for the file-based prompt folders (single / watchdog)."""

import asyncio
from pathlib import Path

import pytest

from src.scheduler import file_jobs
from src.scheduler.service import SchedulerService
from src.storage.manager import StorageManager


class FakeSearcher:
    def __init__(self, deals, counter):
        self.deals = list(deals)
        self.calls = []
        self.active_counter = counter
        self.active = 0

    async def __aenter__(self):
        self.active += 1
        self.active_counter["current"] += 1
        self.active_counter["peak"] = max(
            self.active_counter["peak"], self.active_counter["current"]
        )
        return self

    async def __aexit__(self, *args):
        self.active -= 1
        self.active_counter["current"] -= 1
        return False

    async def search(self, prompt, condition, category):
        self.calls.append((prompt, condition, category))
        await asyncio.sleep(0.01)
        return self.deals


def _write(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def test_parse_prompt_file_reads_settings_and_prompt(tmp_path):
    path = _write(
        tmp_path / "ev.txt",
        "category: auto\ncondition: used\nmax_price: 10000\n---\n"
        "Elektrické auto, bateria v dobrom stave.\n",
    )

    job = file_jobs.parse_prompt_file(path, "watchdog")

    assert job.mode == "watchdog"
    assert job.category == "auto"
    assert job.condition == "used"
    assert "Elektrické auto" in job.prompt
    assert "Max price: 10000 EUR." in job.prompt


def test_parse_prompt_file_without_separator_uses_whole_text(tmp_path):
    path = _write(tmp_path / "plain.txt", "Mini PC 32GB RAM do 500 eur\n")

    job = file_jobs.parse_prompt_file(path, "once")

    assert job.prompt.strip() == "Mini PC 32GB RAM do 500 eur"
    assert job.category == "any"
    assert job.condition == "any"


def test_templates_are_skipped(tmp_path):
    _write(tmp_path / "_template.txt", "---\ntemplate\n")
    _write(tmp_path / "real.txt", "---\nreal prompt\n")

    jobs = file_jobs.scan(tmp_path, "once")

    assert [job.path.name for job in jobs] == ["real.txt"]


def test_done_and_watchdog_markers(tmp_path):
    path = _write(tmp_path / "x.txt", "---\nx\n")

    assert file_jobs.is_done(path) is False
    file_jobs.mark_done(path, "run1")
    assert file_jobs.is_done(path) is True

    assert file_jobs.ran_today(path) is False
    file_jobs.mark_watchdog_run(path, "run2")
    assert file_jobs.ran_today(path) is True


@pytest.mark.asyncio
async def test_single_file_runs_once_then_skips(tmp_path):
    single = tmp_path / "single"
    watchdog = tmp_path / "watchdog"
    path = _write(single / "mini.txt", "category: electronics\n---\nMini PC do 500 eur\n")

    store = StorageManager(str(tmp_path / "deals.db"))
    counter = {"current": 0, "peak": 0}
    try:
        svc = SchedulerService(
            store,
            lambda: FakeSearcher([], counter),
            poll_interval=0.01,
            single_dir=single,
            watchdog_dir=watchdog,
        )
        await asyncio.wait_for(svc.run(exit_when_idle=True), timeout=2.0)
        assert file_jobs.is_done(path)
        first_runs = len(store.get_all_runs(limit=10))
        assert first_runs == 1

        svc2 = SchedulerService(
            store,
            lambda: FakeSearcher([], counter),
            poll_interval=0.01,
            single_dir=single,
            watchdog_dir=watchdog,
        )
        await asyncio.wait_for(svc2.run(exit_when_idle=True), timeout=2.0)
        assert len(store.get_all_runs(limit=10)) == first_runs
    finally:
        store.db.close()


@pytest.mark.asyncio
async def test_watchdog_file_runs_once_per_day(tmp_path):
    single = tmp_path / "single"
    watchdog = tmp_path / "watchdog"
    path = _write(watchdog / "ev.txt", "category: auto\n---\nEV do 10 000 eur\n")

    store = StorageManager(str(tmp_path / "deals.db"))
    counter = {"current": 0, "peak": 0}
    try:
        svc = SchedulerService(
            store,
            lambda: FakeSearcher([], counter),
            poll_interval=0.01,
            single_dir=single,
            watchdog_dir=watchdog,
        )
        await asyncio.wait_for(svc.run(exit_when_idle=True), timeout=2.0)
        assert file_jobs.ran_today(path)
        first_runs = len(store.get_all_runs(limit=10))
        assert first_runs == 1

        svc2 = SchedulerService(
            store,
            lambda: FakeSearcher([], counter),
            poll_interval=0.01,
            single_dir=single,
            watchdog_dir=watchdog,
        )
        await asyncio.wait_for(svc2.run(exit_when_idle=True), timeout=2.0)
        assert len(store.get_all_runs(limit=10)) == first_runs
    finally:
        store.db.close()
