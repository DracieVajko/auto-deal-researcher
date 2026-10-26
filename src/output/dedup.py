"""Collapse repeated listings before they are scored and reported.

The same seller posting the same item twice (or a scraper visiting one listing
under two urls) must not double-count in the median or fill the report with
duplicates. Two listings are the same when they come from the same site and
their titles fold to the same text; the cheapest copy survives.
"""

from __future__ import annotations

from src.searcher.adapters.base import Deal
from src.text.normalize import collapse_ws, fold


def collapse_duplicates(deals: list[Deal]) -> tuple[list[Deal], int]:
    """Keep the cheapest of each identical-title group; return (kept, collapsed)."""
    groups: dict[tuple[str, str], list[Deal]] = {}
    for deal in deals:
        key = (deal.site_name, fold(collapse_ws(deal.title)))
        groups.setdefault(key, []).append(deal)

    kept: list[Deal] = []
    collapsed = 0
    for group in groups.values():
        # A known cheap price wins; an unknown price (<= 0) loses.
        ordered = sorted(group, key=lambda deal: (deal.price_eur <= 0, deal.price_eur))
        winner = ordered[0]
        if len(ordered) > 1:
            winner.metadata["duplicates"] = [
                {"url": deal.url, "price_eur": deal.price_eur} for deal in ordered[1:]
            ]
            collapsed += len(ordered) - 1
        kept.append(winner)

    return kept, collapsed
