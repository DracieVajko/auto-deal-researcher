"""Mock LLM Client for testing without API keys."""

import logging
from collections.abc import Sequence

from src.llm import protocols
from src.searcher.adapters.base import Deal

DealLike = protocols.DealLike

logger = logging.getLogger(__name__)


class MockLLMClient:
    """Mock LLM client that returns deterministic responses for testing."""
    
    def __init__(self, config):
        self.config = config
        self.call_count = 0

    # === Async methods (used by searcher) ===
    async def generate_search_query_async(self, prompt: str, broader: bool = False) -> str:
        """Public query ladder entry point used by PlaywrightSearcher."""
        return await self._generate_search_query_async(prompt, broader)

    @staticmethod
    def keyword_query(prompt: str, max_words: int = 5) -> str:
        """Deterministic short query fallback."""
        return " ".join((prompt or "").split()[:max_words])

    async def _generate_search_query_async(self, prompt: str, broader: bool = False) -> str:
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

    async def refine_query(self, prompt: str, current_deals: list[DealLike], round_num: int) -> str:
        self.call_count += 1
        models_found = [d.title for d in current_deals]
        return f"DJI drone under 350 NOT {' '.join(models_found[:3])}"

    async def judge_results(self, prompt: str, deals: Sequence[DealLike]) -> dict:
        self.call_count += 1
        keep_urls = []
        for deal in deals:
            title_lower = deal.title.lower()
            if ("dji" in title_lower or "mini" in title_lower or "air" in title_lower or "mavic" in title_lower) and deal.price_eur <= 350:
                keep_urls.append(deal.url)
        return {"keep": keep_urls}

    async def rank_results(self, prompt: str, deals: list[DealLike], top_n: int) -> list[DealLike]:
        self.call_count += 1
        def score(deal):
            total = 0
            title_lower = deal.title.lower()
            if "dji" in title_lower:
                total += 100
            if "mini 3 pro" in title_lower:
                total += 50
            elif "air 2s" in title_lower:
                total += 40
            elif "mavic 3" in title_lower:
                total += 30
            total -= deal.price_eur / 10
            return total
        
        ranked = sorted(deals, key=score, reverse=True)
        return ranked[:top_n]

    async def extract_search_filters(self, prompt: str) -> dict:
        """Mock: return empty filter dict."""
        return {}

    async def describe_local_state(self) -> str:
        """Mock: return empty state description."""
        return ""

    async def chat_json(self, system: str, user: str, max_tokens: int = 400) -> dict:
        """Mock: return empty JSON object."""
        return {}

    async def classify_price_quotes(self, items: list[dict]) -> dict[str, dict]:
        """Mock: return empty classification."""
        return {}

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
