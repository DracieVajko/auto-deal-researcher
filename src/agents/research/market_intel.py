"""Market intel agent."""

import logging

logger = logging.getLogger(__name__)


class MarketIntelAgent:
    """Gathers market intelligence - price benchmarks, trends, seasonal patterns."""

    name = "market_intel"
    role = "market_intel"

    async def run(self, input_data: dict) -> dict:
        prompt = input_data.get("prompt", "")
        category = input_data.get("category", "electronics")
        intel = await self._gather_intel(prompt, category)
        return {
            "category": category,
            "price_benchmarks": intel["benchmarks"],
            "seasonal_patterns": intel["seasonal"],
            "known_issues": intel["issues"],
        }

    async def _gather_intel(self, prompt: str, category: str) -> dict:
        intel_db = {
            "electronics": {
                "benchmarks": {"drone": {"low": 200, "mid": 500, "high": 1500}},
                "seasonal": {"best_months": [11, 12, 1], "avoid_months": [6, 7, 8]},
                "issues": ["battery degradation", "propeller damage", "gimbal issues"],
            },
            "appliances": {
                "benchmarks": {"coffee_machine": {"low": 200, "mid": 500, "high": 1200}},
                "seasonal": {"best_months": [1, 9], "avoid_months": [11, 12]},
                "issues": ["scale buildup", "grinder wear", "pump failure"],
            },
            "auto": {
                "benchmarks": {"octavia": {"low": 8000, "mid": 18000, "high": 30000}},
                "seasonal": {"best_months": [3, 4, 9, 10], "avoid_months": [12, 1]},
                "issues": ["service history", "hidden chassis damage", "winter tyres"],
            },
            "home": {
                "benchmarks": {"dining_table": {"low": 150, "mid": 450, "high": 1200}},
                "seasonal": {"best_months": [1, 2, 9], "avoid_months": [11, 12]},
                "issues": ["flat-pack assembly", "scratches on delivery", "missing parts"],
            },
            "hobby": {
                "benchmarks": {"cordless_drill": {"low": 60, "mid": 140, "high": 350}},
                "seasonal": {"best_months": [1, 2, 9, 10], "avoid_months": [12]},
                "issues": ["battery wear", "missing accessories", "warranty on used tools"],
            },
        }
        return intel_db.get(category, intel_db["electronics"])
