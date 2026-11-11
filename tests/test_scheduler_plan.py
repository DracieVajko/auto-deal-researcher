"""Tests for src.scheduler.plan (ScheduleSpec / ScheduledJob scheduling math)."""

import pytest

from src.scheduler.plan import ScheduledJob, ScheduleSpec, compute_next_run


def test_compute_next_run_asap():
    now = "2026-11-09T08:00:00+00:00"
    assert compute_next_run("asap", None, now) == now


def test_compute_next_run_at_today():
    now = "2026-11-09T07:00:00+00:00"   # before 08:00 today
    assert compute_next_run("at", "08:00", now) == "2026-11-09T08:00:00+00:00"


def test_compute_next_run_at_tomorrow():
    now = "2026-11-09T09:00:00+00:00"   # after 08:00 today
    assert compute_next_run("at", "08:00", now) == "2026-11-10T08:00:00+00:00"


def test_compute_next_run_at_exact():
    now = "2026-11-09T08:00:00+00:00"
    assert compute_next_run("at", "08:00", now) == "2026-11-09T08:00:00+00:00"


def test_compute_next_run_at_uses_local_timezone():
    from datetime import timedelta, timezone

    tz = timezone(timedelta(hours=1))
    # 03:00 UTC = 04:00 local, before 05:00 local -> 04:00 UTC same day.
    assert compute_next_run(
        "at", "05:00", "2026-11-09T03:00:00+00:00", tz=tz
    ) == "2026-11-09T04:00:00+00:00"
    # 04:30 UTC = 05:30 local, after 05:00 local -> 04:00 UTC next day.
    assert compute_next_run(
        "at", "05:00", "2026-11-09T04:30:00+00:00", tz=tz
    ) == "2026-11-10T04:00:00+00:00"


def test_compute_next_run_every_minutes():
    now = "2026-11-09T08:00:00+00:00"
    assert compute_next_run("every", "60", now, unit="minutes") == \
        "2026-11-09T09:00:00+00:00"


def test_compute_next_run_every_hours():
    now = "2026-11-09T08:00:00+00:00"
    assert compute_next_run("every", "2", now, unit="hours") == \
        "2026-11-09T10:00:00+00:00"


def test_schedule_spec_defaults():
    spec = ScheduleSpec()
    assert spec.trigger == "asap"
    assert spec.trigger_value is None
    assert spec.every_unit == "minutes"
    assert spec.repeats is None


def test_schedule_spec_invalid_trigger_raises():
    with pytest.raises(ValueError):
        ScheduleSpec(trigger="unknown")


def test_scheduled_job_defaults():
    job = ScheduledJob(id="j1", prompt="dji drone")
    assert job.mode == "once"
    assert job.max_runs == 1
    assert job.enabled is True
    assert job.next_run_at is None


def test_scheduled_job_computes_first_run():
    job = ScheduledJob(
        id="j1",
        prompt="dji drone",
        mode="watchdog",
        spec=ScheduleSpec(trigger="at", trigger_value="08:00"),
    )
    first = job.first_run_at("2026-11-09T07:00:00+00:00")
    assert first == "2026-11-09T08:00:00+00:00"


def test_scheduled_job_is_due():
    job = ScheduledJob(id="j1", prompt="x", next_run_at="2026-11-09T08:00:00+00:00")
    assert job.is_due("2026-11-09T08:00:00+00:00") is True
    assert job.is_due("2026-11-09T07:59:00+00:00") is False
    job2 = ScheduledJob(id="j2", prompt="x")  # no next_run_at
    assert job2.is_due("2026-11-09T08:00:00+00:00") is False
    job3 = ScheduledJob(id="j3", prompt="x", enabled=False,
                        next_run_at="2026-11-09T08:00:00+00:00")
    assert job3.is_due("2026-11-09T08:00:00+00:00") is False


def test_scheduled_job_advance_once_disables():
    job = ScheduledJob(id="j1", prompt="x", mode="once", runs_done=0)
    job.advance("2026-11-09T09:00:00+00:00", "completed")
    assert job.runs_done == 1
    assert job.next_run_at is None  # once -> no further runs


def test_scheduled_job_advance_watchdog_every():
    job = ScheduledJob(
        id="j1", prompt="x", mode="watchdog",
        spec=ScheduleSpec(trigger="every", trigger_value="30", every_unit="minutes"),
        runs_done=0,
    )
    job.advance("2026-11-09T08:00:00+00:00", "completed")
    assert job.runs_done == 1
    assert job.next_run_at == "2026-11-09T08:30:00+00:00"


def test_scheduled_job_advance_watchdog_at_next_day():
    job = ScheduledJob(
        id="j1", prompt="x", mode="watchdog",
        spec=ScheduleSpec(trigger="at", trigger_value="08:00"),
        runs_done=0,
    )
    job.advance("2026-11-09T09:00:00+00:00", "completed")
    assert job.runs_done == 1
    assert job.next_run_at == "2026-11-10T08:00:00+00:00"


def test_scheduled_job_advance_repeats_limits():
    job = ScheduledJob(
        id="j1", prompt="x", mode="watchdog",
        spec=ScheduleSpec(trigger="asap", repeats=2),
    )
    job.advance("2026-11-09T08:00:00+00:00", "completed")
    assert job.runs_done == 1
    assert job.next_run_at == "2026-11-09T08:00:00+00:00"  # asap -> immediate
    job.advance("2026-11-09T08:00:01+00:00", "completed")
    assert job.runs_done == 2
    assert job.next_run_at is None  # repeats exhausted -> disabled


def test_compute_next_run_invalid_trigger_raises():
    with pytest.raises(ValueError):
        compute_next_run("unknown", None, "2026-11-09T08:00:00+00:00")


def test_compute_next_run_invalid_at_format_raises():
    with pytest.raises(ValueError):
        compute_next_run("at", "25:00", "2026-11-09T08:00:00+00:00")
