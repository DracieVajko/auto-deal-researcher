"""Recommendation agent."""

import logging
from typing import ClassVar

logger = logging.getLogger(__name__)


class RecommendationAgent:
    """Synthesizes final recommendation from all agent outputs."""

    name = "recommendation"
    role = "recommendation"

    WEIGHTS: ClassVar[dict] = {
        "expert_score": 0.40,
        "price_rank": 0.30,
        "availability": 0.15,
        "seller_trust": 0.10,
        "timing": 0.05,
    }

    def __init__(self):
        self.name = "recommendation"
        self.role = "recommendation"

    async def run(self, input_data: dict) -> dict:
        """Synthesize final recommendation from all agent outputs."""
        prompt = input_data.get("prompt", "")
        all_results = input_data.get("all_results", {})
        price = all_results.get("price", {})
        price_deals = price.get("enriched_deals", [])
        ranked = await self._rank_final_deals(all_results)
        result = await self._generate_final_output(prompt, all_results)
        return {
            "final_recommendation": result,
            "all_candidates": all_results,
            "confidence": self._calculate_confidence(result),
        }

    async def _rank_final_deals(self, all_results: dict) -> list:
        """Rank deals based on combined scores."""
        price_data = all_results.get("price", {})
        deals = price_data.get("enriched_deals", [])
        if not deals:
            return []
        ranked = sorted(deals, key=lambda d: d.get("price_eur", float('inf')))
        return ranked

    async def _generate_final_output(self, prompt: str, all_results: dict) -> dict:
        """Generate the final recommendation output."""
        price_data = all_results.get("price", {})
        best_deal = price_data.get("best_overall")
        expertise = all_results.get("expertise", {})
        expert_analysis = expertise.get("domain_expert", {}).get("top_recommendation", {})
        tech_advice = all_results.get("expertise", {}).get("latest_tech", {}).get("recommendation", "")
        price_comparison = all_results.get("price", {}).get("price_comparison", "")
        if not best_deal:
            return {
                "status": "no_deals_found",
                "message": "No deals found matching your criteria",
                "suggestions": [
                    "Try broader search terms",
                    "Increase price range",
                    "Check different condition filters",
                ],
            }
        best = best_deal
        return {
            "status": "success",
            "recommendation": {
                "title": best.get("title", "Unknown"),
                "price_eur": best.get("price_eur", 0),
                "total_cost_eur": best.get("total_cost_eur", best.get("price_eur", 0)),
                "condition": best.get("condition", "unknown"),
                "site_name": best.get("site_name", "unknown"),
                "url": best.get("url", ""),
            },
            "reasoning": self._build_reasoning(best_deal),
            "expert_analysis": expert_analysis.get("expert_analysis", "No expert analysis available") if isinstance(expert_analysis, dict) else "No expert analysis available",
            "timing_advice": tech_advice,
            "price_comparison": price_comparison,
            "alternatives": self._get_alternatives(all_results),
            "next_steps": [
                "Verify seller reputation and return policy",
                "Check warranty and return policy",
                "Verify item condition matches description",
                "Consider shipping time and cost",
            ],
        }

    def _build_reasoning(self, deal) -> str:
        """Generate human-readable reasoning for the recommendation."""
        reasons = []
        price = deal.get("price_eur", 0)
        if price < 300:
            reasons.append(f"Excellent price ({price}€) - well below market average")
        elif price < 500:
            reasons.append(f"Fair price ({price}€) - competitive for this model")
        else:
            reasons.append(f"Premium price ({price}€) - verify condition justifies cost")
        return ". ".join(reasons)

    def _get_alternatives(self, all_results: dict) -> list:
        price_data = all_results.get("price", {})
        deals = price_data.get("enriched_deals", [])
        alternatives = []
        for deal in deals[1:4]:
            alternatives.append({
                "title": deal.get("title", "Unknown"),
                "price_eur": deal.get("price_eur", 0),
                "total_cost_eur": deal.get("total_cost_eur", deal.get("price_eur", 0)),
                "site_name": deal.get("site_name", "unknown"),
                "condition": deal.get("condition", "unknown"),
                "url": deal.get("url", ""),
                "why_consider": "Good alternative if top pick unavailable",
            })
        return alternatives

    def _calculate_confidence(self, deal) -> float:
        """Calculate confidence score (0-1) for the recommendation."""
        score = 0.5
        if isinstance(deal, dict) and deal.get("status") == "no_deals_found":
            return 0.3
        price = deal.get("price_eur", 0) if isinstance(deal, dict) else 0
        if price < 300:
            score += 0.2
        elif price < 500:
            score += 0.1
        condition = deal.get("condition", "unknown") if isinstance(deal, dict) else "unknown"
        if condition == "new":
            score += 0.15
        elif condition == "refurbished":
            score += 0.1
        elif condition == "used":
            score += 0.05
        score += 0.1
        return min(1.0, max(0.3, score))
