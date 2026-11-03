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
    notes: str = ""
    specialties: tuple[str, ...] = ()

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
        max_sites: int | None = None,
    ) -> tuple[list[SiteCandidate], str]:
        """Return ``(selected, reasoning)``.

        The deterministic ranking is the baseline. When an LLM is available
        it may narrow the set further, but never widen it. ``max_sites`` is a
        cap only when it is positive; ``0`` and ``None`` mean unlimited.
        """
        ranked = rank_by_location(candidates, user_country)
        if not ranked:
            return [], "No candidate sites match the request."
        if len(ranked) == 1:
            return ranked, "Only one site carries this category."

        picked, reasoning = await self._llm_pick(ranked, prompt, user_country)
        if picked is None:
            picked = ranked
            reasoning = "Ranked by market distance (no usable LLM selection)."
        if max_sites and max_sites > 0:
            picked = picked[:max_sites]
        return picked, reasoning

    async def _llm_pick(
        self,
        ranked: list[SiteCandidate],
        prompt: str,
        user_country: str,
    ) -> tuple[list[SiteCandidate] | None, str]:
        """Ask the LLM which of the ranked candidates are worth visiting.

        ``None`` means the model was unavailable or answered nonsense, so the
        caller should fall back to every candidate. An empty list is a valid
        answer meaning no shop fits.
        """
        if self.llm is None:
            return None, ""
        chat_json = getattr(self.llm, "chat_json", None)
        if chat_json is None:
            return None, ""

        catalogue = "\n".join(
            f"- {c.id}: {c.name} ({c.country}, {c.currency}, "
            f"categories: {', '.join(c.categories)}; "
            f"specialties: {', '.join(c.specialties) or 'general'}; "
            f"notes: {c.notes or 'none'})"
            for c in ranked
        )
        system = (
            "You choose which online shops are worth searching for a product. "
            "The user shops in this market: "
            f"{user_country}. Prefer local shops, then neighbouring markets. "
            "Use the specialties and notes: a battery request belongs on "
            "nkon/ecoprodukt, a solar request on solaro/ecoprodukt, a general "
            "electronics request on amazon/nay/alza. "
            "Select EVERY shop that is genuinely useful for this request. "
            "The count is not limited; do not stop at six. "
            "Reply with ONLY a JSON object: "
            '{"selected": ["site_id", ...], "reasoning": "one short sentence"}. '
            "Use only site ids from the list. An empty list is valid only when "
            "no shop fits."
        )
        user = f"Request: {prompt}\n\nAvailable shops:\n{catalogue}"

        try:
            data = await chat_json(system, user, max_tokens=300)
        except Exception as exc:  # noqa: BLE001 - selection must never break a search
            logger.warning("Site selection LLM call failed: %s", exc)
            return None, ""

        if not isinstance(data, dict):
            return None, ""
        raw_ids = data.get("selected")
        if not isinstance(raw_ids, list):
            return None, ""

        allowed = {c.id: c for c in ranked}
        picked: list[SiteCandidate] = []
        for raw in raw_ids:
            site_id = str(raw or "").strip()
            candidate = allowed.get(site_id)
            if candidate is not None and candidate not in picked:
                picked.append(candidate)

        reasoning = str(data.get("reasoning") or "").strip()
        if not picked and not reasoning:
            reasoning = "The LLM selected no suitable shop."
        return picked, reasoning


__all__ = [
    "NEIGHBOURS",
    "SiteCandidate",
    "SiteSelector",
    "market_distance",
    "rank_by_location",
]
