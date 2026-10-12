"""Smart searcher with adapter integration and multi-round LLM refinement."""

from __future__ import annotations
import asyncio
from dataclasses import dataclass
from typing import Optional
from playwright.async_api import Browser, BrowserContext, Page
from src.config.models import AppConfig, WebsiteConfig
from src.llm.client import LLMClient
from src.searcher.adapters import get_adapter, BaseAdapter, Deal
from src.storage.manager import StorageManager


@dataclass
class SearchRound:
    round_num: int
    query: str
    results_found: int
    new_deals: list[Deal]


class PlaywrightSearcher:
    def __init__(
        self,
        config: AppConfig,
        llm: LLMClient,
        storage: StorageManager,
        browser_manager
    ):
        self.config = config
        self.llm = llm
        self.storage = storage
        self.browser_manager = browser_manager
        self.browser: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def __aenter__(self):
        self.browser = await self.browser_manager.get_browser()
        return self

    async def __aexit__(self, *args):
        pass  # Browser manager handles cleanup

    def _filter_sites(self, user_condition: str, user_category: str) -> list[WebsiteConfig]:
        """Return only enabled sites matching condition + category."""
        sites = []
        for site in self.config.search.websites:
            if not site.enabled:
                continue
            try:
                adapter_cls = get_adapter(site.adapter_class)
                adapter = adapter_cls()
                if adapter.matches_condition(user_condition) and adapter.matches_category(user_category):
                    sites.append(site)
            except ValueError:
                continue  # unknown adapter
        return sites

    async def search(self, prompt: str, condition: str = "any", category: str = "any") -> list[Deal]:
        """Main search entry point — multi-round with LLM query refinement."""
        all_deals: list[Deal] = []
        seen_urls = set()
        rounds: list[SearchRound] = []

        # Round 1: LLM generates initial query
        query = await self.llm._generate_search_query_async(prompt)

        max_rounds = getattr(self.config.search, 'max_rounds', 3)
        retry_on_empty = getattr(self.config.search, 'retry_on_empty', True)

        for round_num in range(1, max_rounds + 1):
            round_deals = await self._execute_round(query, condition, category, seen_urls)
            rounds.append(SearchRound(round_num, query, len(round_deals), round_deals))

            if not round_deals:
                if round_num == 1 and retry_on_empty:
                    # Retry once with broader query
                    query = await self.llm._generate_search_query_async(prompt, broader=True)
                    continue
                break  # no results, stop

            # Add new deals
            for deal in round_deals:
                if deal.url not in seen_urls:
                    seen_urls.add(deal.url)
                    all_deals.append(deal)

            # LLM judges results so far
            if all_deals:
                judged = await self.llm.judge_results(prompt, all_deals)
                all_deals = [d for d in all_deals if d.url in judged["keep"]]

            # Generate refined query for next round (find DIFFERENT items)
            if round_num < max_rounds and all_deals:
                query = await self.llm.refine_query(prompt, all_deals, round_num)

        # Final LLM ranking → top N
        winners_count = getattr(self.config.search, 'winners_count', 3)
        final_ranked = await self.llm.rank_results(prompt, all_deals, winners_count)
        return final_ranked

    async def _execute_round(self, query: str, condition: str, category: str, seen_urls: set) -> list[Deal]:
        sites = self._filter_sites(condition, category)
        all_deals = []

        for site in sites:
            page = None
            try:
                # Create fresh page for each site to avoid state issues
                page = await self.browser_manager.get_page()
                page.set_default_timeout(30000)
                page.set_default_navigation_timeout(30000)
                
                adapter_cls = get_adapter(site.adapter_class)
                adapter = adapter_cls()
                print(f"[{site.name}] Adapter search method: {adapter.search}")
                deals = await adapter.search(page, query, max_results=20)
                print(f"[{site.name}] Got {len(deals)} deals")
                # Filter by condition/category if adapter supports it
                for deal in deals:
                    deal.site_name = site.name
                    if deal.url not in seen_urls:
                        all_deals.append(deal)
                # Rate limiting
                await asyncio.sleep(1)
            except Exception as e:
                print(f"[{site.name}] Search error: {e}")
                import traceback
                traceback.print_exc()
            finally:
                if page:
                    await page.close()

        return all_deals