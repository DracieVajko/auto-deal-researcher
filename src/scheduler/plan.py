"""Scheduling primitives for the system monitor.

Defines ``ScheduleSpec`` (how / when a job repeats) and ``ScheduledJob``
(a persisted prompt plus its schedule state), together with
``compute_next_run`` which calculates the next ISO-8601 UTC run time from
a trigger spec. All timestamps are UTC so lexicographic order matches
chronology.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, tzinfo

Trigger = str       # "asap" | "at" | "every"
Mode = str          # "once" | "watchdog"
EveryUnit = str     # "minutes" | "hours"


@dataclass
class ScheduleSpec:
    """When a job runs next. Pure trigger config, independent of job mode."""

    trigger: Trigger = "asap"      # asap | at | every
    trigger_value: str | None = None   # "08:00" for at; "60" for every
    every_unit: EveryUnit = "minutes"  # minutes | hours
    repeats: int | None = None   # max runs for watchdog; None = unlimited

    def __post_init__(self) -> None:
        if self.trigger not in ("asap", "at", "every"):
            msg = f"unknown trigger {self.trigger!r}"
            raise ValueError(msg)
        if self.every_unit not in ("minutes", "hours"):
            msg = f"unknown every_unit {self.every_unit!r}"
            raise ValueError(msg)
        if self.trigger == "at" and self.trigger_value is None:
            msg = "trigger 'at' requires trigger_value (HH:MM)"
            raise ValueError(msg)
        if self.trigger == "every" and self.trigger_value is None:
            msg = "trigger 'every' requires trigger_value (N)"
            raise ValueError(msg)


@dataclass
class ScheduledJob:
    """A persisted prompt plus its schedule state."""

    id: str
    prompt: str
    condition: str = "any"
    category: str = "any"
    mode: Mode = "once"            # once = single search, watchdog = repeating
    spec: ScheduleSpec = field(default_factory=ScheduleSpec)
    enabled: bool = True
    next_run_at: str | None = None
    created_at: str | None = None
    last_run_at: str | None = None
    runs_done: int = 0
    last_status: str | None = None
    # Timezone used to interpret "at HH:MM" values. None keeps UTC (the
    # long-standing behaviour and the format stored in the database).
    tz: tzinfo | None = None
    # Set for jobs loaded from prompts/single or prompts/watchdog. Such jobs
    # are not persisted in scheduled_jobs; their completion is tracked by a
    # sidecar file next to the prompt.
    source_path: str | None = None

    @property
    def max_runs(self) -> int:
        """Effective maximum runs: 1 for once; repeats or 0 for watchdog."""
        if self.mode == "once":
            return 1
        if self.spec.repeats is not None:
            return self.spec.repeats
        return 0  # 0 = unlimited watchdog

    def is_due(self, now: str | None = None) -> bool:
        """True when the job is enabled and its next_run_at has arrived."""
        if not self.enabled or self.next_run_at is None:
            return False
        if now is None:
            from src.utils.time import utcnow_iso

            now = utcnow_iso()
        return self.next_run_at <= now

    def first_run_at(self, now: str) -> str:
        """Compute the very first run time for a fresh job."""
        return compute_next_run(
            self.spec.trigger,
            self.spec.trigger_value,
            now,
            unit=self.spec.every_unit,
            tz=self.tz,
        )

    def advance(self, now: str, status: str) -> None:
        """Advance the job after a run finished with *status*.

        Updates runs_done, last_run_at, last_status and recomputes
        next_run_at. A ``once`` job or a watchdog that exhausted its
        repeats gets next_run_at = None (disabled).
        """
        self.runs_done += 1
        self.last_run_at = now
        self.last_status = status

        if self.mode == "once":
            self.next_run_at = None
            return

        # Watchdog: enforce repeats limit.
        if self.spec.repeats is not None and self.runs_done >= self.spec.repeats:
            self.next_run_at = None
            return

        self.next_run_at = compute_next_run(
            self.spec.trigger,
            self.spec.trigger_value,
            now,
            unit=self.spec.every_unit,
            tz=self.tz,
        )


def compute_next_run(
    trigger: Trigger,
    trigger_value: str | None,
    now: str,
    *,
    unit: EveryUnit = "minutes",
    tz: tzinfo | None = None,
) -> str:
    """Return the next ISO-8601 UTC run time at-or-after *now* for the trigger.

    ``at`` times are interpreted in *tz* when given (local wall-clock time)
    and converted back to UTC for storage.  ``tz=None`` keeps the original
    UTC interpretation.
    """
    base = _parse_iso(now)

    if trigger == "asap":
        return base.isoformat()

    if trigger == "at":
        if trigger_value is None:
            msg = "trigger 'at' requires trigger_value (HH:MM)"
            raise ValueError(msg)
        hour, minute = _parse_hhmm(trigger_value)
        if tz is not None:
            base_local = base.astimezone(tz)
            target_local = base_local.replace(
                hour=hour, minute=minute, second=0, microsecond=0
            )
            if target_local < base_local:
                target_local += timedelta(days=1)
            return target_local.astimezone(UTC).isoformat()
        target = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if target < base:  # already passed today -> tomorrow
            target += timedelta(days=1)
        return target.isoformat()

    if trigger == "every":
        if trigger_value is None:
            msg = "trigger 'every' requires trigger_value (N)"
            raise ValueError(msg)
        n = int(trigger_value)
        delta = timedelta(minutes=n) if unit == "minutes" else timedelta(hours=n)
        return (base + delta).isoformat()

    msg = f"unknown trigger {trigger!r}"
    raise ValueError(msg)

def _parse_iso(value: str) -> datetime:
    """Parse an ISO-8601 UTC string into a timezone-aware datetime."""
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


def _parse_hhmm(value: str) -> tuple[int, int]:
    """Parse HH:MM into (hour, minute), validating ranges."""
    try:
        hour_s, minute_s = value.split(":")
        hour = int(hour_s)
        minute = int(minute_s)
    except (ValueError, AttributeError) as exc:
        msg = f"invalid HH:MM value {value!r}"
        raise ValueError(msg) from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        msg = f"invalid HH:MM value {value!r}"
        raise ValueError(msg)
    return hour, minute
