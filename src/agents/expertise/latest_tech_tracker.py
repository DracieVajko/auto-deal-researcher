"""Latest tech tracker agent."""

import logging

logger = logging.getLogger(__name__)


class LatestTechTrackerAgent:
    """Tracks latest tech launches, discontinuations, and generation transitions."""

    name = "latest_tech"
    role = "latest_tech"

    async def run(self, input_data: dict) -> dict:
        category = input_data.get("category", "electronics")
        intel = await self._check_latest_tech(category)
        return {
            "category": category,
            "upcoming_releases": intel["upcoming"],
            "discontinued": intel["discontinued"],
            "generation_changes": intel["generation_changes"],
            "recommendation": self._generate_timing_advice(intel),
        }

    async def _check_latest_tech(self, category: str) -> dict:
        tech_db = {
            "electronics": {
                "upcoming": [
                    {"product": "DJI Mini 4 Pro", "expected": "Q1 2025", "impact": "price drop on Mini 3 Pro"},
                    {"product": "DJI Air 3S", "expected": "Q2 2025", "impact": "price drop on Air 2S"},
                ],
                "discontinued": ["DJI Mini 2", "DJI Air 2 (original)"],
                "generation_changes": [
                    {"old": "DJI Mini 3", "new": "DJI Mini 3 Pro", "diff": "better obstacle avoidance"},
                    {"old": "Air 2", "new": "Air 2S", "diff": "1-inch sensor, better low light"},
                ],
            }
        }
        return tech_db.get(category, tech_db["electronics"])

    def _generate_timing_advice(self, intel: dict) -> str:
        advice = []
        if intel.get("upcoming"):
            for item in intel["upcoming"]:
                advice.append(f"⏳ {item['product']} expected {item['expected']} - {item['impact']}")
        if intel.get("discontinued"):
            advice.append(f"⚠️ Discontinued models: {', '.join(intel['discontinued'])} - prices may drop further")
        if intel.get("generation_changes"):
            for change in intel["generation_changes"]:
                advice.append(f"🔄 {change['old']} → {change['new']}: {change['diff']}")
        return "\n".join(advice) if advice else "No major timing concerns"
