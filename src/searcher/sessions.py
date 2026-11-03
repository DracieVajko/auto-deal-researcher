"""Saved per-site cookie sessions for sites that need a real browser login."""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SESSION_DIR = Path(__file__).resolve().parents[2] / "data" / "sessions"


def session_path(site_id: str) -> Path:
    """Return the cookie file for one site id."""
    return SESSION_DIR / f"{site_id}.json"


def has_session(site_id: str) -> bool:
    """True when a saved cookie file exists for *site_id*."""
    return session_path(site_id).is_file()


def load_cookies(site_id: str) -> list[dict]:
    """Load saved cookies; a missing or malformed file means no session."""
    path = session_path(site_id)
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        logger.warning("Ignoring malformed session for %s: %s", site_id, exc)
        return []
    return data if isinstance(data, list) else []


async def apply_session(context, site_id: str) -> bool:
    """Add saved cookies to *context*. Returns True when cookies were applied."""
    cookies = load_cookies(site_id)
    if not cookies:
        return False
    try:
        await context.add_cookies(cookies)
    except Exception as exc:  # noqa: BLE001 - a bad cookie must not stop a run
        logger.warning("Could not apply session for %s: %s", site_id, exc)
        return False
    return True


__all__ = [
    "SESSION_DIR",
    "apply_session",
    "has_session",
    "load_cookies",
    "session_path",
]
