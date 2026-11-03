"""Cross-site product links.

Different shops often list the same product with the same title. We do not
collapse those listings — a cheaper copy may have worse shipping or condition —
but we link them so the report can show "Also at" alternatives.

The match is deliberately conservative: the normalized title must be identical
and contain at least three meaningful tokens.
"""

from __future__ import annotations

import re

from src.searcher.adapters.base import Deal
from src.text.normalize import fold

_NOISE = re.compile(
    r"\b(?:new|used|refurbished|open\s*box|top|akcia|zlava|sale|"
    r"skladem|na\s+sklade|doprava\s+zdarma|free\s+shipping)\b"
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def product_key(title: str) -> str:
    """Normalize a title enough for conservative cross-site matching."""
    folded = fold(title or "")
    folded = _NOISE.sub(" ", folded)
    folded = _NON_ALNUM.sub(" ", folded)
    return " ".join(token for token in folded.split() if len(token) > 2)


def cross_site_groups(deals: list[Deal]) -> dict[str, list[Deal]]:
    """Return groups whose normalized title appears on at least two sites."""
    groups: dict[str, list[Deal]] = {}
    for deal in deals:
        key = product_key(deal.title)
        if len(key.split()) < 3:
            continue
        groups.setdefault(key, []).append(deal)
    return {
        key: group
        for key, group in groups.items()
        if len({deal.site_name for deal in group}) >= 2
    }


__all__ = ["cross_site_groups", "product_key"]
