"""Location-aware site selection.

The registry knows which market every site belongs to. The user knows where
they shop. This module bridges the two: it ranks the runnable candidates by
how close their market is to the user's, and lets the LLM narrow the result
down further.

The LLM can only ever *narrow* the candidate set. It cannot introduce a site
that the deterministic filter rejected, and when it fails or answers with
nonsense the deterministic ranking is used instead.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Markets that are close enough to the user's own country to rank high.
NEIGHBOURS: dict[str, set[str]] = {
    "SK": {"CZ", "AT", "DE", "PL", "HU"},
    "CZ": {"SK", "AT", "DE", "PL"},
    "AT": {"DE", "CZ", "SK", "HU"},
    "DE": {"AT", "CZ", "PL", "SK"},
    "PL": {"CZ", "DE", "SK"},
    "HU": {"AT", "SK", "CZ"},
}


@dataclass(frozen=True)
class SiteCandidate:
    """One site the searcher may open."""

    id: str
    name: str
    country: str
    currency: str
    categories: tuple[str, ...]
    conditions: tuple[str, ...]
    status: str = "planned"
    adapter_class: str = ""

    def carries(self, category: str, condition: str) -> bool:
        """True when the site can serve this category/condition."""
        if category not in ("any",) and category not in self.categories:
            return False
        return not (condition not in ("any",) and condition not in self.conditions)


def market_distance(site_country: str, user_country: str) -> int:
    """0 = same market, 1 = neighbouring market, 2 = everything else."""
    site = (site_country or "").upper()
    user = (user_country or "").upper()
    if not site or not user:
        return 2
    if site == user:
        return 0
    if site in NEIGHBOURS.get(user, set()):
        return 1
    return 2


def rank_by_location(
    candidates: list[SiteCandidate],
    user_country: str = "SK",
) -> list[SiteCandidate]:
    """Order candidates: own market first, neighbours second, rest last."""
    return sorted(
        candidates,
        key=lambda c: (market_distance(c.country, user_country), c.id),
    )


class SiteSelector:
    """Chooses which candidate sites to visit, with LLM assistance."""

    def __init__(self, llm=None):
        self.llm = llm

    async def select(
        self,
        candidates: list[SiteCandidate],
        prompt: str = "",
        user_country: str = "SK",
        max_sites: int = 8,
    ) -> tuple[list[SiteCandidate], str]:
        """Return ``(selected, reasoning)``.

        The deterministic ranking is the baseline. When an LLM is available
        it may narrow the set further, but never widen it and never exceed
        *max_sites*.
        """
        ranked = rank_by_location(candidates, user_country)
        if not ranked:
            return [], "No candidate sites match the request."
        if len(ranked) == 1:
            return ranked, "Only one site carries this category."

        picked, reasoning = await self._llm_pick(ranked, prompt, user_country)
        if not picked:
            picked = ranked[:max_sites]
            reasoning = "Ranked by market distance (no usable LLM selection)."
        return picked[:max_sites], reasoning

    async def _llm_pick(
        self,
        ranked: list[SiteCandidate],
        prompt: str,
        user_country: str,
    ) -> tuple[list[SiteCandidate], str]:
        """Ask the LLM which of the ranked candidates are worth visiting."""
        if self.llm is None:
            return [], ""
        chat_json = getattr(self.llm, "chat_json", None)
        if chat_json is None:
            return [], ""

        catalogue = "\n".join(
            f"- {c.id}: {c.name} ({c.country}, {c.currency}, "
            f"categories: {', '.join(c.categories)})"
            for c in ranked
        )
        system = (
            "You choose which online shops are worth searching for a product. "
            "The user shops in this market: "
            f"{user_country}. Prefer local shops, then neighbouring markets. "
            "Reply with ONLY a JSON object: "
            '{"selected": ["site_id", ...], "reasoning": "one short sentence"}. '
            "Use only site ids from the list. Pick at most 6."
        )
        user = f"Request: {prompt}\n\nAvailable shops:\n{catalogue}"

        try:
            data = await chat_json(system, user, max_tokens=300)
        except Exception as exc:  # noqa: BLE001 - selection must never break a search
            logger.warning("Site selection LLM call failed: %s", exc)
            return [], ""

        if not isinstance(data, dict):
            return [], ""
        raw_ids = data.get("selected")
        if not isinstance(raw_ids, list):
            return [], ""

        allowed = {c.id: c for c in ranked}
        picked: list[SiteCandidate] = []
        for raw in raw_ids:
            site_id = str(raw or "").strip()
            candidate = allowed.get(site_id)
            if candidate is not None and candidate not in picked:
                picked.append(candidate)

        if not picked:
            return [], "The LLM returned no usable site."
        reasoning = str(data.get("reasoning") or "").strip()
        return picked, reasoning


__all__ = [
    "NEIGHBOURS",
    "SiteCandidate",
    "SiteSelector",
    "market_distance",
    "rank_by_location",
]
