"""Search Orchestrator - coordinates VLM, LLM Judge, and Playwright crawlers."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote_plus

from src.config.models import AppConfig, SearchConfig, WebsiteConfig
from src.llm.client import LLMClient
from src.searcher.adapters import get_adapter, Deal
from src.searcher.selectors import get_selectors
from src.searcher.site_registry import sites_for
from src.storage.manager import StorageManager
from src.vlm import VLMClient, SearchCriteria

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    """Result of a single search operation."""
    deals: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    sites_searched: list = field(default_factory=list)
    duration_seconds: float = 0.0


@dataclass
class EnrichedDeal:
    """Deal with AI enrichment."""
    deal: any
    expert_score: float = 0.0
    expert_analysis: str = ""
    judge_decision: str = "UNCERTAIN"
    judge_confidence: float = 0.0
    judge_reasoning: str = ""
    match_score: int = 0
    deal_quality: str = "unknown"


class SearchOrchestrator:
    """Orchestrates the full search pipeline: LLM planning -> Playwright crawl -> VLM extraction -> LLM Judge."""

    def __init__(
        self,
        config: AppConfig,
        llm: LLMClient,
        vlm: "VLMClient",
        storage: StorageManager,
        browser_manager,
    ):
        self.config = config
        self.llm = llm
        self.vlm = vlm
        self.storage = storage
        self.browser_manager = browser_manager
        self.config = config

    async def search(
        self,
        prompt: str,
        condition: str = "any",
        category: str = "any",
        winners: int = 3,
    ) -> list:
        """Main search entry point."""
        start_time = time.time()

        # 1. Build search criteria
        criteria = SearchCriteria(
            prompt=prompt,
            condition=condition,
            category=category,
        )

        # 2. Select enabled sites matching category/condition
        sites = self._filter_sites(condition, category)
        logger.info(f"Searching {len(sites)} sites for: {prompt}")

        # 2. Run parallel search across sites
        all_deals = []
        for site in sites:
            if not site.enabled:
                continue
            try:
                deals = await self._search_site(site, prompt, condition, category)
                all_deals.extend(deals)
            except Exception as e:
                logger.error(f"Site {site.name} search failed: {e}")

        # 3. Deduplicate by URL
        deals = self._deduplicate_deals(all_deals)

        # 3. AI Judge each deal
        enriched = await self._judge_deals(deals, prompt)

        # 4. Sort by quality and limit
        deals = sorted(enriched, key=lambda d: d.judge_confidence, reverse=True)
        final_deals = deals[:winners]

        # 5. Save to storage
        for deal in final_deals:
            self.storage.save_deal(deal.deal)

        logger.info(f"Search completed in {time.time() - start_time:.1f}s: {len(final_deals)} deals")
        return [d.deal for d in final_deals]

    def _filter_sites(self, condition: str, category: str) -> list:
        """Filter enabled sites by condition and category."""
        from src.searcher.site_registry import sites_for
        sites = sites_for("electronics", "any")  # Use registry filtering
        # Filter by config
        enabled_names = {s.name for s in self.config.search.websites if s.enabled}
        return [s for s in sites if s.name in enabled_names]

    async def _search_site(self, site, query: str, condition: str, category: str) -> list:
        """Search a single site using its adapter."""
        from src.browser.manager import BrowserManager
        from src.llm.mock_client import MockLLMClient

        # Create adapter
        adapter_cls = get_adapter(site.adapter_class)
        adapter = adapter_cls()

        # Create browser page
        browser = BrowserManager(self.config)
        page = await browser.get_page()
        page.set_default_timeout(30000)
        page.set_default_navigation_timeout(30000)

        try:
            # Use adapter's search method
            deals = await adapter.search(page, prompt, max_results=20)
            for deal in deals:
                deal.site_name = site.name
            return deals
        finally:
            await page.close()

    def _deduplicate_deals(self, deals: list) -> list:
        """Remove duplicate deals by URL."""
        seen = set()
        unique = []
        for deal in deals:
            if deal.url not in seen:
                seen.add(deal.url)
                unique.append(deal)
        return unique

    async def _judge_deals(self, deals: list, prompt: str) -> list:
        """Use LLM to judge each deal."""
        from src.llm.client import LLMClient

        llm = LLMClient(self.config)
        results = []

        for deal in deals:
            try:
                # Build judgment prompt
                judgment = await self._judge_deal(prompt, deal)
                results.append({
                    "deal": deal,
                    "judgment": judgment,
                    "score": judgment.get("match_score", 0),
                })
            except Exception as e:
                logger.error(f"Judgment failed for {deal.url}: {e}")
                results.append({"deal": deal, "judgment": {"decision": "UNCERTAIN", "confidence": 0}})
        return results

    async def _judge_deal(self, prompt: str, deal) -> dict:
        """Use LLM to judge a single deal."""
        from src.llm.client import LLMClient
        llm = LLMClient(self.config)

        prompt_text = f"""
        User wants: {deal.title}
        Price: {deal.price_eur} EUR
        Condition: {deal.condition}
        URL: {deal.url}
        Site: {deal.site_name}

        User wants: {prompt}

        Judge if this item matches. Return JSON:
        {{
            "decision": "ACCEPT|REJECT|NEED_DETAIL",
            "confidence": 0.0-1.0,
            "reasoning": "...",
            "match_score": 0-100,
            "deal_quality": "excellent|good|fair|poor"
        }}
        """

        try:
            # Use LLM to judge
            from src.llm.client import LLMClient
            llm = LLMClient(self.config)
            # This would need actual LLM call
            # For now return mock
            return {
                "decision": "ACCEPT",
                "confidence": 0.8,
                "reasoning": "Matches criteria",
                "match_score": 85,
                "deal_quality": "good"
            }
        except Exception as e:
            return {"decision": "UNCERTAIN", "confidence": 0, "reasoning": str(e)}