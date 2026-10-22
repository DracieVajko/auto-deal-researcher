"""Deterministic listing filters shared by the searcher and the output layer.

The LLM judge sees only titles, prices and conditions, so it can keep a
clearly wrong product type (a ZenBook laptop in a mini-PC search). These
checks are cheap, explainable and always run before and after the LLM.
"""

from __future__ import annotations

import re

# Brand/model lines that are always laptops or notebooks. Generic words
# ("laptop", "notebook") use word boundaries; brand lines are matched as
# substrings because listings often glue them to a model number.
LAPTOP_MARKERS: tuple[str, ...] = (
    "laptop",
    "notebook",
    "ultrabook",
    "chromebook",
    "macbook",
    "zenbook",
    "vivobook",
    "ideapad",
    "thinkpad",
    "thinkbook",
    "elitebook",
    "probook",
    "zbook",
    "latitude",
    "inspiron",
    "alienware",
    "surface laptop",
    "yoga",
    "legion",
    "zephyrus",
    "katana",
    "predator",
    "pavilion",
    "spectre",
    "omen",
    "victus",
    "acer swift",
    "lg gram",
    "galaxy book",
    "matebook",
    "mobile workstation",
)

_WORD_MARKERS = frozenset(
    {"laptop", "notebook", "ultrabook", "chromebook", "yoga"}
)

MINI_PC_HINTS: tuple[str, ...] = (
    "mini pc",
    "mini-pc",
    "minipc",
    "barebone",
    "nuc",
    "sff",
    "small form factor",
    "deskmini",
    "mini itx",
    "mini-itx",
)


def is_laptop_title(title: str | None) -> bool:
    """Return True when a listing title clearly describes a laptop/notebook."""
    text = (title or "").lower()
    if not text:
        return False
    for marker in LAPTOP_MARKERS:
        if marker in _WORD_MARKERS:
            if re.search(rf"\b{re.escape(marker)}s?\b", text):
                return True
        elif marker in text:
            return True
    return False


def wants_mini_pc_form_factor(prompt: str | None) -> bool:
    """Return True when the request explicitly asks for a mini PC/barebone."""
    text = (prompt or "").lower()
    return any(hint in text for hint in MINI_PC_HINTS)


def excluded_by_form_factor(prompt: str | None, title: str | None) -> bool:
    """True when the listing's form factor contradicts the request."""
    return wants_mini_pc_form_factor(prompt) and is_laptop_title(title)
