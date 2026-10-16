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

        benchmark = (research.get("market_intel") or {}).get("price_benchmarks", {}) \
            if isinstance(research, dict) else {}
        evaluated = []
        for deal in deals:
            deal.setdefault("metadata", {})
            if benchmark:
                deal["metadata"].setdefault("benchmark", self._category_benchmark(deal, benchmark))
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

    @staticmethod
    def _category_benchmark(deal, benchmark: dict) -> float | None:
        """Pick the closest benchmark range for a deal title."""
        title = str(deal.get("title", "")).lower()
        for key, band in (benchmark or {}).items():
            if not isinstance(band, dict):
                continue
            if key.lower() in title:
                mid = band.get("mid")
                if mid:
                    try:
                        return float(mid)
                    except (TypeError, ValueError):
                        return None
        return None

    async def _score_deal(self, deal) -> float:
        """Score a deal on weighted criteria (0-100).

        price_score was previously hard-coded to 0, which made every deal
        score identically; it is now derived from the price against a
        category benchmark.
        """
        weights = self.SCORING_WEIGHTS
        price = float(deal.get("price_eur", 0) or 0)
        benchmark = self._benchmark(deal)

        if benchmark and price > 0:
            ratio = price / benchmark
            # ratio 0.5 -> 1.0, ratio 1.0 -> 0.6, ratio >= 2 -> 0.1
            if ratio <= 1:
                price_score = min(1.0, 0.5 + (1 - ratio) * 1.0)
            else:
                price_score = max(0.1, 0.6 - (ratio - 1) * 0.5)
        else:
            price_score = 0.5

        condition = (deal.get("condition") or "unknown").lower()
        condition_score = {
            "new": 1.0, "refurbished": 0.8, "open_box": 0.75, "used": 0.6,
        }.get(condition, 0.5)

        seller_score = 0.8
        total = (
            price_score * weights["price_vs_benchmark"]
            + condition_score * weights["condition_match"]
            + seller_score * weights["seller_trust"]
            + 0.9 * weights["specs_match"]
        )
        return round(total * 100, 1)

    @staticmethod
    def _benchmark(deal) -> float:
        """Reference price for a deal, from metadata or a category default."""
        meta = deal.get("metadata") or {}
        for key in ("market_price", "benchmark", "avg_price"):
            value = meta.get(key)
            if value:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    continue
        price = float(deal.get("price_eur", 0) or 0)
        # Without history, treat the current price as the reference midpoint.
        return price if price > 0 else 0.0

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
