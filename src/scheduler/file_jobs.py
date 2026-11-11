"""File-based scheduled prompts: two folders, plain-text prompt files.

Layout::

    prompts/single/      # run once, then a .done marker stops repeats
    prompts/watchdog/    # run once per day (marker stores the last run date)

A file is plain text.  Optional settings go before a ``---`` line; the text
after it is the prompt (multi-line is fine).  Example::

    # settings (all optional)
    category: auto
    condition: used
    max_price: 10000
    schedule: 05:00
    ---
    Elektrické auto do 10 000 eur, bateria v dobrom stave.

Files starting with ``_`` or ``.`` are templates/ignored.  Deleting the
``.txt`` file removes the job; no database edit is needed.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

SINGLE_DIR = Path("prompts/single")
WATCHDOG_DIR = Path("prompts/watchdog")

_META_KEYS = {
    "prompt",
    "category",
    "condition",
    "max_price",
    "min_price",
    "sites",
    "schedule",
}
_META_RE = re.compile(r"^\s*([A-Za-z_]+)\s*:\s*(.*)$")


@dataclass(frozen=True)
class FileJob:
    """One parsed prompt file."""

    path: Path
    mode: str  # "once" | "watchdog"
    prompt: str
    condition: str = "any"
    category: str = "any"
    schedule_time: str = "05:00"


def done_marker(path: Path) -> Path:
    """Sidecar marker for a completed single job."""
    return path.with_suffix(path.suffix + ".done")


def state_file(path: Path) -> Path:
    """Sidecar file with the last watchdog run date."""
    return path.with_suffix(path.suffix + ".state.json")


def is_done(path: Path) -> bool:
    """True when a single job already produced its output."""
    return done_marker(path).is_file()


def mark_done(path: Path, run_id: str) -> None:
    """Record that a single job completed successfully."""
    done_marker(path).write_text(
        json.dumps({"run_id": run_id, "completed_at": datetime.now().isoformat()}),
        encoding="utf-8",
    )


def ran_today(path: Path) -> bool:
    """True when a watchdog job already ran today (local date)."""
    marker = state_file(path)
    if not marker.is_file():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return data.get("date") == datetime.now().date().isoformat()


def mark_watchdog_run(path: Path, run_id: str) -> None:
    """Record today's watchdog run so a manual restart does not repeat it."""
    state_file(path).write_text(
        json.dumps(
            {
                "run_id": run_id,
                "date": datetime.now().date().isoformat(),
                "completed_at": datetime.now().isoformat(),
            }
        ),
        encoding="utf-8",
    )


def parse_prompt_file(path: Path, mode: str) -> FileJob:
    """Parse one prompt file. Raises ValueError when the prompt is empty."""
    text = path.read_text(encoding="utf-8", errors="replace")
    meta: dict[str, str] = {}
    prompt_lines: list[str] = []
    in_prompt = False

    for line in text.splitlines():
        stripped = line.strip()
        if not in_prompt:
            if stripped == "---":
                in_prompt = True
                continue
            if not stripped or stripped.startswith("#"):
                continue
            match = _META_RE.match(line)
            if match and match.group(1).lower() in _META_KEYS:
                meta[match.group(1).lower()] = match.group(2).strip()
                continue
            # No separator: everything from here on is the prompt.
            in_prompt = True
        if in_prompt:
            prompt_lines.append(line)

    prompt = "\n".join(prompt_lines).strip()
    if not prompt:
        prompt = meta.get("prompt", "").strip()
    if not prompt:
        raise ValueError(f"{path.name}: empty prompt")

    # A max_price setting is folded into the prompt so the existing
    # filter extractor sees it without a new search() argument.
    max_price = meta.get("max_price", "").strip()
    if max_price and max_price.lower() not in {"none", "null", "any"}:
        prompt = f"{prompt}\nMax price: {max_price} EUR."

    return FileJob(
        path=path,
        mode=mode,
        prompt=prompt,
        condition=meta.get("condition", "any").strip() or "any",
        category=meta.get("category", "any").strip() or "any",
        schedule_time=meta.get("schedule", "05:00").strip() or "05:00",
    )


def scan(directory: Path, mode: str) -> list[FileJob]:
    """Return parsed jobs from *directory*; templates and markers are skipped."""
    if not directory.is_dir():
        return []
    jobs: list[FileJob] = []
    for path in sorted(directory.glob("*.txt")):
        if path.name.startswith(("_", ".")):
            continue
        try:
            jobs.append(parse_prompt_file(path, mode))
        except (OSError, ValueError) as exc:
            logger.warning("Skipping prompt file %s: %s", path, exc)
    return jobs


def remove_prompt(path: Path) -> None:
    """Delete a prompt and its sidecars (used by the CLI)."""
    for candidate in (path, done_marker(path), state_file(path)):
        try:
            candidate.unlink()
        except FileNotFoundError:
            pass
