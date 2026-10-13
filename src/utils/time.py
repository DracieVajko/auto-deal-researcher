"""Timezone-aware datetime helpers.

All timestamps stored in the database use UTC ISO-8601 format so that
lexicographic ordering matches chronological ordering and comparisons
across runs are consistent regardless of host timezone.
"""

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return the current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


def utcnow_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return utcnow().isoformat()


def today_iso() -> str:
    """Return today's UTC date as an ISO-8601 date string (YYYY-MM-DD)."""
    return utcnow().date().isoformat()


def utcnow_stamp() -> str:
    """Return a compact UTC timestamp for run IDs (YYYYMMDD_HHMMSS)."""
    return utcnow().strftime("%Y%m%d_%H%M%S")