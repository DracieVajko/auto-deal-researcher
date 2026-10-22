"""Smart searcher with adapter integration and multi-round LLM refinement."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from playwright.async_api import BrowserContext, Page

from src.config.models import AppConfig, WebsiteConfig
from src.diagnostics.selector_health import SelectorHealthTracker
from src.llm.client import LLMClient
from src.searcher.adapters import Deal, get_adapter
from src.searcher.adapters.base import SiteBlockedError
from src.searcher.listing_filter import excluded_by_form_factor
from src.storage.manager import StorageManager
from src.utils.time import utcnow_stamp

# Diamond Search agents (optional import)
try:
    from src.agents import (
        CoordinatorAgent,
        DomainExpertAgent,
        LatestTechTrackerAgent,
        MarketIntelAgent,
        PriceHunterAgent,
        QueryExpansionAgent,
        RecommendationAgent,
        SiteSelectionAgent,
    )
    DIAMOND_SEARCH_AVAILABLE = True
except ImportError:
    DIAMOND_SEARCH_AVAILABLE = False

logger = logging.getLogger(__name__)


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
        self.browser: BrowserContext | None = None
        self.page: Page | None = None
        
        # Diamond Search setup
        self.diamond_search_enabled = (
            DIAMOND_SEARCH_AVAILABLE and 
            getattr(config.search, 'diamond_search', None) and 
            config.search.diamond_search.enabled
        )
        self.health = SelectorHealthTracker()
        self._diamond_coordinator = None
        if self.diamond_search_enabled:
            self._init_diamond_agents()
    
    def _init_diamond_agents(self):
        """Initialize the 7-agent Diamond Search pipeline."""
        agents = [
            QueryExpansionAgent(self.llm),
            SiteSelectionAgent(),
            MarketIntelAgent(),
            DomainExpertAgent(),
            LatestTechTrackerAgent(),
            PriceHunterAgent(),
            RecommendationAgent(),
        ]
        # Filter out None agents
        agents = [a for a in agents if a is not None]
        diamond_config = self.config.search.diamond_search.model_dump() if hasattr(self.config.search.diamond_search, 'model_dump') else {}
        self._diamond_coordinator = CoordinatorAgent(agents, diamond_config)

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

        max_rounds = getattr(self.config.search, "max_rounds", 3)
        retry_on_empty = getattr(self.config.search, "retry_on_empty", True)

        # Query ladder. The model's own phrasing first, then deterministic
        # keyword queries of decreasing specificity. Without this, one bad
        # model phrasing ("mini PC or barebone new/used with Thunderbolt/
        # OCuLink, DDR5 RAM 32GB/64GB, AMD Ryzen") makes every site return
        # zero even though "mini pc ryzen" finds the right products.
        attempts: list[str] = []
        for raw_candidate in (
            await self.llm._generate_search_query_async(prompt),
            self.llm.keyword_query(prompt, max_words=5),
            self.llm.keyword_query(prompt, max_words=2),
        ):
            candidate = (raw_candidate or "").strip()
            if candidate and candidate not in attempts:
                attempts.append(candidate)

        round_num = 0
        while attempts and round_num < max_rounds:
            query = attempts.pop(0)
            round_num += 1
            round_deals = await self._execute_round(query, condition, category, seen_urls)
            rounds.append(SearchRound(round_num, query, len(round_deals), round_deals))
            for deal in round_deals:
                if deal.url not in seen_urls:
                    seen_urls.add(deal.url)
                    all_deals.append(deal)
            if not retry_on_empty and not round_deals:
                break

        # Refine for additional, different items once we have something.
        while all_deals and round_num < max_rounds:
            round_num += 1
            query = await self.llm.refine_query(prompt, all_deals, round_num)
            round_deals = await self._execute_round(query, condition, category, seen_urls)
            rounds.append(SearchRound(round_num, query, len(round_deals), round_deals))
            if not round_deals:
                break
            for deal in round_deals:
                if deal.url not in seen_urls:
                    seen_urls.add(deal.url)
                    all_deals.append(deal)

        # Judge once at the end: fewer LLM calls than per-round judging.
        if all_deals:
            # Deterministic form-factor gate before the LLM sees the list.
            # A keyword match on "mini pc" also returns laptops (ZenBook etc.),
            # and the judge kept them often enough to pollute the report.
            before = len(all_deals)
            all_deals = [
                deal
                for deal in all_deals
                if not excluded_by_form_factor(prompt, deal.title)
            ]
            if len(all_deals) != before:
                logger.info(
                    "Dropped %d laptop/notebook listing(s) for a mini-PC request",
                    before - len(all_deals),
                )

            judged = await self.llm.judge_results(prompt, all_deals)
            all_deals = [d for d in all_deals if d.url in judged["keep"]]

        # Rank the whole list. winners_count is the number of highlighted
        # picks, not a cut-off: the report shows every judged deal with a
        # score, so a used classifieds listing is not hidden behind three
        # retailer results.
        final_ranked = await self.llm.rank_results(
            prompt, all_deals, max(len(all_deals), 1)
        )
        return final_ranked

    async def _execute_round(self, query: str, condition: str, category: str, seen_urls: set) -> list[Deal]:
        sites = self._filter_sites(condition, category)
        all_deals = []

        for site in sites:
            page = None
            started = time.perf_counter()
            self.health.record_search_start(site.name, site.adapter_class)
            try:
                # Per-site stable fingerprint session; fresh page per site, closed after
                page = await self.browser_manager.get_page(session_id=f"search-{site.name}")
                page.set_default_timeout(30000)
                page.set_default_navigation_timeout(30000)
                
                adapter_cls = get_adapter(site.adapter_class)
                adapter = adapter_cls()
                deals = await adapter.search(page, query, max_results=20)
                latency = (time.perf_counter() - started) * 1000
                self.health.record_search_result(
                    site.name, bool(deals), len(deals), latency
                )
                # Filter by condition/category if adapter supports it
                for deal in deals:
                    deal.site_name = site.name
                    if deal.url not in seen_urls:
                        all_deals.append(deal)
                # Rate limiting
                await asyncio.sleep(1)
            except SiteBlockedError as e:
                # Anti-bot interstitial: expected for some sites, not a bug.
                logger.warning(f"[{site.name}] Blocked: {e}")
                self.health.record_search_result(
                    site.name, False, 0, (time.perf_counter() - started) * 1000, blocked=True
                )
            except Exception:
                logger.exception(f"[{site.name}] Search error")
                self.health.record_search_result(
                    site.name, False, 0, (time.perf_counter() - started) * 1000
                )
            finally:
                if page:
                    await page.close()

        return all_deals

    async def search_with_diamond(self, prompt: str, condition: str = "any", category: str = "any") -> list[Deal]:
        """
        Execute search using the Diamond Search 7-agent pipeline.
        
        This runs the full agent pipeline:
        1. Research Layer (parallel): Query Expansion, Site Selection, Market Intel
        2. Expertise Layer (parallel): Domain Expert, Latest Tech Tracker
        3. Price Layer (sequential): Price Hunter
        4. Synthesis: Recommendation Agent
        """
        if not self.diamond_search_enabled or not self._diamond_coordinator:
            logger.warning("Diamond Search not available, falling back to standard search")
            return await self.search(prompt, condition, category)
        
        logger.info("Starting Diamond Search pipeline...")
        
        # Execute the diamond search pipeline
        input_data = {
            "prompt": prompt,
            "condition": condition,
            "category": category,
        }

        result = await self._diamond_coordinator.run(input_data)

        if not result.success:
            logger.error(f"Diamond Search failed: {result.error}")
            return await self.search(prompt, condition, category)

        # The coordinator returns the final recommendation
        # We need to also run the actual searches to get real deals
        # The agent pipeline provides intelligence, but we still need to fetch deals
        
        # For now, run standard search with the enhanced queries from the pipeline.
        # The recommendation agent's output can guide which results to prioritize.

        # Re-run the pipeline now that real deals exist, so the expertise,
        # price and synthesis agents actually receive something to score.
        run_id = f"diamond_{utcnow_stamp()}"
        research = result.payload.get("research", {})
        queries = (research.get("query_expansion") or {}).get("expanded_queries") or []
        search_query = queries[0] if queries else prompt
        logger.info(f"[{run_id}] research layer -> searching for {search_query!r}")

        deals = await self.search(search_query, condition, category)

        deal_dicts = [
            {
                "url": d.url, "title": d.title, "price_eur": d.price_eur,
                "condition": d.condition, "category": d.category,
                "site_name": d.site_name, "metadata": dict(d.metadata or {}),
            }
            for d in deals
        ]

        expertise = await self._diamond_coordinator._run_expertise_layer(
            prompt, research, run_id, deal_dicts
        )
        scored = (expertise.get("domain_expert") or {}).get("evaluated_deals") or deal_dicts
        price = await self._diamond_coordinator._run_price_layer(
            prompt, research, expertise, run_id, scored
        )
        final = await self._diamond_coordinator._synthesize_results(
            prompt, {"research": research, "expertise": expertise, "price": price}, run_id
        )

        evaluated_deals = scored
        best = final.get("recommendation") if isinstance(final, dict) else None

        if evaluated_deals:
            # Merge expert scores with deals
            expert_by_url = {d.get("url"): d for d in evaluated_deals if d.get("url")}
            for deal in deals:
                if deal.url in expert_by_url:
                    deal.expert_score = expert_by_url[deal.url].get("expert_score", 0)
                    deal.expert_analysis = expert_by_url[deal.url].get("expert_analysis", "")

        logger.info(
            f"Diamond Search completed [run_id={run_id}]: {len(deals)} deals, "
            f"best={best.get('title') if best else 'n/a'}"
        )
        return deals