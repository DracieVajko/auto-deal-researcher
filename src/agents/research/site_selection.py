"""Site selection agent.

The agent no longer carries a hardcoded capability table. It reads the site
registry, so a newly registered site is known to it immediately, and it can
hand the LLM the candidate list to narrow down.
"""

import logging
from typing import ClassVar

from src.searcher.site_registry import SITES, SiteSpec
from src.searcher.site_selection import SiteCandidate

logger = logging.getLogger(__name__)


class SiteSelectionAgent:
    """Selects optimal sites based on user criteria."""

    name = "site_selection"
    role = "site_selection"

    SITE_CAPABILITIES: ClassVar[dict] = {}

    def __init__(self, llm=None):
        self.name = "site_selection"
        self.role = "site_selection"
        self.llm = llm

    @staticmethod
    def capabilities() -> dict:
        """Site capabilities derived from the registry, not hardcoded."""
        if not SiteSelectionAgent.SITE_CAPABILITIES:
            SiteSelectionAgent.SITE_CAPABILITIES = {
                spec.id: {
                    "conditions": list(spec.conditions),
                    "categories": list(spec.categories),
                    "priority": 1 if spec.status == "working" else 2,
                    "country": spec.country,
                    "currency": spec.currency,
                }
                for spec in SITES
            }
        return SiteSelectionAgent.SITE_CAPABILITIES

    @staticmethod
    def candidates(specs: list[SiteSpec] | None = None) -> list[SiteCandidate]:
        """Turn registry entries into selection candidates."""
        return [
            SiteCandidate(
                id=spec.id,
                name=spec.name,
                country=spec.country,
                currency=spec.currency,
                categories=spec.categories,
                conditions=spec.conditions,
                status=spec.status,
                adapter_class=spec.adapter_class,
            )
            for spec in (specs if specs is not None else SITES)
        ]

    async def run(self, input_data: dict) -> dict:
        condition = input_data.get("condition", "any")
        category = input_data.get("category", "any")
        selected_sites = self._select_sites(condition, category)
        return {
            "selected_sites": selected_sites,
            "reasoning": self._explain_selection(selected_sites, condition, category),
        }

    def _select_sites(self, condition: str, category: str) -> list[str]:
        """Select sites matching condition and category."""
        selected = []
        for site, caps in self.capabilities().items():
            cond_match = condition == "any" or condition in caps["conditions"]
            cat_match = category == "any" or category in caps["categories"]
            if cond_match and cat_match:
                selected.append(site)
        return sorted(selected, key=lambda s: self.capabilities()[s]["priority"])

    def _explain_selection(self, sites: list[str], condition: str, category: str) -> str:
        if not sites:
            return "No sites match criteria"
        return f"Selected {len(sites)} sites for {condition} {category}: {', '.join(sites)}"
