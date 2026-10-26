"""Verify hard requirements from the request against what the listing states.

The model sometimes claims a specification is "not stated" even though the
deterministic layer read it from the text. This module folds the request into
numeric requirements and lets the guard drop those false claims — never to
rescue a listing with an independent defect, only to correct a wrong fact.
"""

from __future__ import annotations

import re

from src.text.normalize import fold

_STORAGE_RE = re.compile(r"\b(\d{2,4})\s*(?:gb|go)\b")
_BATTERY_RE = re.compile(
    r"\b(?:aspon|min|minimalne|alespon|mindestens|at least|least)\s*(\d{2,3})\s*%"
    r"|\b(\d{2,3})\s*%\s*(?:bater|batter|akku)"
)
_PRICE_RE = re.compile(
    r"\b(?:do|max(?:imum)?|maximal|pod|unter|bis|under|up\s+to|najviac|"
    r"menej\s+ako)\s*(\d[\d\s.,]*)"
)

_HARD_DEFECTS = (
    "cracked",
    "broken",
    "water damage",
    "does not work",
    "not working",
    "faulty",
    "missing part",
    "wrong model",
    "icloud locked",
    "blacklisted",
)


def extract_requirements(prompt: str) -> dict[str, float | int | None]:
    """Read the optional numeric demands out of a (possibly non-English) prompt."""
    folded = fold(prompt or "")

    storage_gb: int | None = None
    match = _STORAGE_RE.search(folded)
    if match:
        storage_gb = int(match.group(1))

    min_battery_percent: int | None = None
    match = _BATTERY_RE.search(folded)
    if match:
        min_battery_percent = int(match.group(1) or match.group(2))

    max_price_eur: float | int | None = None
    match = _PRICE_RE.search(folded)
    if match:
        digits = re.sub(r"[^\d.]", "", match.group(1).replace(",", "."))
        if digits:
            value = float(digits)
            max_price_eur = int(value) if value == int(value) else value

    return {
        "storage_gb": storage_gb,
        "min_battery_percent": min_battery_percent,
        "max_price_eur": max_price_eur,
    }


def _stated_storage_gb(value: str) -> int | None:
    match = re.search(r"(\d{1,4})\s*(gb|go|tb)", fold(value))
    if not match:
        return None
    number = int(match.group(1))
    return number * 1000 if match.group(2) == "tb" else number


def _stated_battery_percent(value: str) -> int | None:
    match = re.search(r"(\d{1,3})", fold(value))
    return int(match.group(1)) if match else None


# requirement key -> (spec key, stated-value parser, "not stated" con patterns)
_GUARDS = {
    "storage_gb": (
        "storage",
        _stated_storage_gb,
        (
            r"storage.*not stated",
            r"not stated.*storage",
            r"no mention of storage",
            r"storage.*not mentioned",
            r"storage.*missing",
            r"neuveden",
            r"nicht angegeben",
        ),
    ),
    "min_battery_percent": (
        "battery_health",
        _stated_battery_percent,
        (
            r"batter.*not stated",
            r"not stated.*batter",
            r"no mention of batter",
            r"battery.*not mentioned",
            r"batter.*missing",
            r"akku.*nicht",
            r"bater.*neuveden",
        ),
    ),
}


def apply_requirement_guard(
    cons: list[str],
    specs: dict[str, str],
    requirements: dict[str, float | int | None],
) -> tuple[list[str], bool]:
    """Drop cons that falsely claim a stated-and-satisfying spec is missing."""
    # max_price_eur is deliberately not guarded: price is a deal field and
    # "above your maximum" is a real reason, never a false "not stated".
    drop_patterns: list[re.Pattern[str]] = []
    for key, (spec_key, parse, patterns) in _GUARDS.items():
        required = requirements.get(key)
        stated = specs.get(spec_key)
        if required is None or not stated:
            continue
        actual = parse(stated)
        if actual is None or actual < required:
            continue
        drop_patterns.extend(re.compile(pattern) for pattern in patterns)

    if not drop_patterns:
        return list(cons), False

    kept: list[str] = []
    rescued = False
    for con in cons:
        folded = fold(con)
        if any(pattern.search(folded) for pattern in drop_patterns):
            rescued = True
            continue
        kept.append(con)
    return kept, rescued


def has_hard_defect(cons: list[str]) -> bool:
    """True when a remaining con names an independent, physical defect."""
    return any(word in fold(con) for con in cons for word in _HARD_DEFECTS)
