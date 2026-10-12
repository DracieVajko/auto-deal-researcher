"""Mock LLM Client for testing without API keys."""

import asyncio
import concurrent.futures
import logging
from src.searcher.adapters.base import Deal

logger = logging.getLogger(__name__)


class MockLLMClient:
    """Mock LLM client that returns deterministic responses for testing."""
    
    def __init__(self, config):
        self.config = config
        self.call_count = 0

    # === Async methods (used by searcher) ===
    async def generate_search_query(self, prompt: str, broader: bool = False) -> str:
        """Generate search queries using LLM (async version)."""
        self.call_count += 1
        if broader:
            return "drone DJI"
        prompt_lower = prompt.lower()
        terms = []
        if "dji" in prompt_lower:
            terms.append("DJI")
        if "drone" in prompt_lower:
            terms.append("drone")
        if "350" in prompt_lower or "€" in prompt_lower:
            terms.append("under 350")
        if "gimbal" in prompt_lower:
            terms.append("gimbal")
        if "sensor" in prompt_lower:
            terms.append("obstacle avoidance")
        return " ".join(terms) if terms else "DJI drone under 350"

    async def refine_query(self, prompt: str, current_deals: list[Deal], round_num: int) -> str:
        self.call_count += 1
        models_found = [d.title for d in current_deals]
        return f"DJI drone under 350 NOT {' '.join(models_found[:3])}"

    async def judge_results(self, prompt: str, deals: list[Deal]) -> dict:
        self.call_count += 1
        keep_urls = []
        for deal in deals:
            title_lower = deal.title.lower()
            if ("dji" in title_lower or "mini" in title_lower or "air" in title_lower or "mavic" in title_lower) and deal.price_eur <= 350:
                keep_urls.append(deal.url)
        return {"keep": keep_urls}

    async def rank_results(self, prompt: str, deals: list[Deal], top_n: int) -> list[Deal]:
        self.call_count += 1
        def score(deal):
            score = 0
            title_lower = deal.title.lower()
            if "dji" in title_lower:
                score += 100
            if "mini 3 pro" in title_lower:
                score += 50
            elif "air 2s" in title_lower:
                score += 40
            elif "mavic 3" in title_lower:
                score += 30
            score -= deal.price_eur / 10
            return score
        
        ranked = sorted(deals, key=score, reverse=True)
        return ranked[:top_n]

    # === Sync methods (backward compatibility) ===
    def generate_search_query_sync(self, product_description):
        return asyncio.run(self.generate_search_query(product_description))

    def judge_results_sync(self, results, query):
        return asyncio.run(self._judge_results_async(results, query))

    async def _judge_results_async(self, results, query):
        """Legacy format compatibility."""
        deals = [
            Deal(url=r.get("link", ""), title=r.get("title", ""), 
                 price_eur=float(r.get("price", 0).replace("€", "").replace(",", ".")) if r.get("price") else 0,
                 condition=r.get("condition", "unknown"),
                 category=r.get("category", "general"),
                 site_name=r.get("website", "unknown"))
            for r in results
        ]
        judged = await self.judge_results(query, deals)
        return [r for r in results if r.get("link", "") in judged["keep"]]