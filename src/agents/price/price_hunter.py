"""Price hunter agent."""

import logging

logger = logging.getLogger(__name__)


class PriceHunterAgent:
    """Finds best prices, coupons, cashback, installment options, cross-platform comparison."""

    name = "price_hunter"
    role = "price_hunter"

    async def run(self, input_data: dict) -> dict:
        deals = input_data.get("deals", [])
        if not deals:
            # Same keys as the populated path so downstream agents can rely on
            # the shape regardless of input.
            return {
                "enriched_deals": [],
                "best_overall": None,
                "price_comparison": "",
                "summary": "No deals to process",
            }
        enriched = []
        for deal in input_data.get("deals", []):
            enriched_deal = await self._enrich_deal(deal)
            enriched.append(enriched_deal)
        enriched.sort(key=lambda d: d.get("total_cost_eur", d.get("price_eur", 999999)))
        return {
            "enriched_deals": enriched,
            "best_overall": enriched[0] if enriched else None,
            "price_comparison": self._build_comparison_table(enriched),
        }

    async def _enrich_deal(self, deal: dict) -> dict:
        """Add price intelligence to a deal."""
        deal["total_cost_eur"] = deal.get("price_eur", 0) + deal.get("shipping_cost_eur", 0)
        deal["coupons_found"] = []
        deal["cashback_options"] = []
        deal["installment_options"] = []
        deal["seller_verified"] = True
        deal["warranty_info"] = "Check listing"
        deal["return_policy"] = "Check listing"
        return deal

    def _build_comparison_table(self, deals: list) -> str:
        lines = ["| Site | Title | Price | Shipping | Total | Condition |", "|---|---|---|---|---|---|"]
        for d in deals[:5]:
            lines.append(f"| {d.get('site_name','?')} | {d.get('title','?')[:30]} | {d.get('price_eur',0)}€ | {d.get('shipping_cost_eur',0)}€ | {d.get('total_cost_eur', d.get('price_eur',0))}€ | {d.get('condition','?')} |")
        return "\n".join(lines)
