"""Site selection agent."""

import logging
from typing import ClassVar

logger = logging.getLogger(__name__)


class SiteSelectionAgent:
    """Selects optimal sites based on user criteria."""

    name = "site_selection"
    role = "site_selection"

    SITE_CAPABILITIES: ClassVar[dict] = {
        "alza": {"conditions": ["new", "open_box"], "categories": ["electronics", "appliances"], "priority": 1},
        "bazos": {"conditions": ["used"], "categories": ["electronics", "appliances", "auto", "general"], "priority": 2},
        "backmarket": {"conditions": ["refurbished"], "categories": ["electronics"], "priority": 1},
        "ebay": {"conditions": ["used", "refurbished", "new", "open_box"], "categories": ["electronics", "appliances", "auto"], "priority": 2},
        "facebook": {"conditions": ["used", "marketplace"], "categories": ["all"], "priority": 3, "requires_login": True},
    }

    def __init__(self):
        self.name = "site_selection"
        self.role = "site_selection"

    async def run(self, input_data: dict) -> dict:
        prompt = input_data.get("prompt", "")
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
        for site, caps in self.SITE_CAPABILITIES.items():
            cond_match = condition == "any" or condition in caps["conditions"]
            cat_match = category == "any" or category in caps["categories"]
            if cond_match and cat_match:
                selected.append(site)
        return sorted(selected, key=lambda s: self.SITE_CAPABILITIES[s]["priority"])

    def _explain_selection(self, sites: list[str], condition: str, category: str) -> str:
        if not sites:
            return "No sites match criteria"
        return f"Selected {len(sites)} sites for {condition} {category}: {', '.join(sites)}"
