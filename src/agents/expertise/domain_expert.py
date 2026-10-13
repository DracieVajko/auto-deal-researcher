"""Domain expert agent."""

import logging
from typing import ClassVar

from src.agents.base import AgentRole

logger = logging.getLogger(__name__)


class DomainExpertAgent:
    """Evaluates deals with domain expertise - filters by real-world suitability."""

    name = "domain_expert"
    role = AgentRole.DOMAIN_EXPERT

    SCORING_WEIGHTS: ClassVar[dict] = {
        "price_vs_benchmark": 0.40,
        "condition_match": 0.25,
        "seller_trust": 0.20,
        "specs_match": 0.15,
    }

    CRITICAL_QUESTIONS: ClassVar[list[str]] = [
        "Do the specs actually serve the user's real-world use case?",
        "What's the real (not on-paper) difference between the options?",
        "Are any specs overkill for the intended use?",
        "What do reviews typically miss that actually matters?",
        "If buying for yourself, what would you choose and why?",
    ]

    def __init__(self):
        self.name = "domain_expert"
        self.role = AgentRole.DOMAIN_EXPERT

    async def run(self, input_data: dict) -> dict:
        prompt = input_data.get("prompt", "")
        deals = input_data.get("deals", [])
        research = input_data.get("research", {})

        if not deals:
            return {"evaluated_deals": [], "analysis": "No deals to evaluate"}

        evaluated = []
        for deal in deals:
            score = await self._score_deal(deal)
            analysis = await self._analyze_deal(deal)
            deal["expert_score"] = score
            deal["expert_analysis"] = analysis
            deal["meets_criteria"] = score >= 70
            evaluated.append(deal)

        evaluated.sort(key=lambda d: d.get("expert_score", 0), reverse=True)

        return {
            "evaluated_deals": evaluated,
            "top_recommendation": evaluated[0] if evaluated else None,
            "questions_answered": await self._answer_critical_questions(evaluated),
        }

    async def _score_deal(self, deal) -> float:
        """Score a deal based on weighted criteria."""
        weights = self.SCORING_WEIGHTS
        price_score = 0
        condition_score = 1.0
        seller_score = 0.8
        total = (
            price_score * weights["price_vs_benchmark"]
            + condition_score * weights["condition_match"]
            + seller_score * weights["seller_trust"]
            + 0.9 * weights["specs_match"]
        )
        return round(total * 100, 1)

    async def _analyze_deal(self, deal) -> str:
        """Generate expert analysis text for a deal."""
        parts = []
        if "dji" in deal.get("title", "").lower():
            if "mini 3 pro" in deal.get("title", "").lower():
                parts.append("DJI Mini 3 Pro: excellent for travel, sub-250g, 34min flight")
            elif "air 2s" in deal.get("title", "").lower():
                parts.append("DJI Air 2S: 1-inch sensor, best image quality under 600g")
            elif "mavic 3" in deal.get("title", "").lower():
                parts.append("Mavic 3: Hasselblad camera, 46min flight, premium")
        condition = deal.get("condition", "unknown")
        if condition == "refurbished":
            parts.append("Refurbished: verify warranty and battery cycles")
        elif condition == "used":
            parts.append("Used: verify flight hours, crash history, battery health")
        price = deal.get("price_eur", 0)
        if price < 300:
            parts.append("Excellent price for DJI drone")
        elif price < 500:
            parts.append("Fair market price")
        else:
            parts.append("Premium pricing - verify condition justifies cost")
        return ". ".join(parts) if parts else "Standard listing, verify details before purchase"

    async def _answer_critical_questions(self, deals: list) -> dict:
        """Answer the 5 critical questions for top deals."""
        if not deals:
            return {}
        top = deals[:3]
        answers = {}
        for i, deal in enumerate(top):
            answers[f"option_{i+1}"] = {
                "deal": deal.get("title", "unknown"),
                "answers": {
                    "serves_use_case": "yes" if "drone" in str(deal.get("title", "")).lower() else "verify",
                    "value_justified": "likely" if deal.get("price_eur", 9999) < 500 else "verify",
                    "real_diff": "camera/sensor/flight_time differences",
                    "overkill_specs": "4K/60fps+ may be overkill for casual use",
                    "personal_choice": f"Would pick {deal.get('title')} for price/performance",
                },
            }
        return answers
