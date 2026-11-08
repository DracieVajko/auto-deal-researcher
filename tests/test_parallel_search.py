"""Parallel site search with bounded concurrency (offline)."""

import asyncio
from typing import ClassVar

import pytest

from src.config.models import AppConfig, Category, Condition, SearchConfig, WebsiteConfig
from src.diagnostics.selector_health import SiteHealth
from src.searcher.playwright_searcher import PlaywrightSearcher


class FakePage:
    def __init__(self):
        self.context = FakeContext()

    def set_default_timeout(self, value):
        pass

    def set_default_navigation_timeout(self, value):
        pass

    async def close(self):
        pass


class FakeContext:
    async def add_cookies(self, cookies):
        pass


class FakeBrowserManager:
    def __init__(self):
        self.page = FakePage()

    async def get_page(self, session_id=None):
        return self.page


class BarrierAdapter:
    instances: ClassVar[list] = []
    started = 0
    timeouts = 0
    both_started: ClassVar[asyncio.Event]

    def __init__(self, base_url=None, currency=None, enrich_limit=None):
        self.base_url = base_url
        self.calls = []
        type(self).instances.append(self)

    def matches_condition(self, condition):
        return True

    def matches_category(self, category):
        return True

    async def search(self, page, query, **kwargs):
        type(self).started += 1
        if type(self).started >= 2:
            type(self).both_started.set()
        try:
            await asyncio.wait_for(type(self).both_started.wait(), timeout=1.0)
        except TimeoutError:
            type(self).timeouts += 1
        return []


def _config(concurrency=2):
    config = AppConfig(
        search=SearchConfig(
            websites=[
                WebsiteConfig(
                    name=f"shop{i}",
                    base_url=f"https://shop{i}.test",
                    adapter_class="shop",
                    categories=[Category.ELECTRONICS],
                    conditions=[Condition.NEW],
                )
                for i in range(2)
            ],
            user_country="SK",
            max_sites=0,
            concurrency=concurrency,
        )
    )
    config.search.diamond_search.enabled = False
    return config


@pytest.mark.asyncio
async def test_two_sites_can_search_at_the_same_time(monkeypatch):
    BarrierAdapter.instances = []
    BarrierAdapter.started = 0
    BarrierAdapter.timeouts = 0
    BarrierAdapter.both_started = asyncio.Event()
    monkeypatch.setattr(
        "src.searcher.playwright_searcher.get_adapter", lambda name: BarrierAdapter
    )
    monkeypatch.setattr(
        "src.searcher.playwright_searcher.load_profiles", lambda: {}
    )

    config = _config(concurrency=2)
    searcher = PlaywrightSearcher(
        config, llm=object(), storage=object(), browser_manager=FakeBrowserManager()
    )
    searcher.profiles = {}
    # Isolate from persisted health state so adaptive throttling starts clean.
    searcher.health.sites.clear()

    deals = await searcher._execute_round("pc", "new", "electronics", set())

    assert deals == []
    assert BarrierAdapter.started == 2
    assert BarrierAdapter.timeouts == 0


def _degraded_config(site_count=3, concurrency=4):
    config = _config(concurrency=concurrency)
    config.search.websites = [
        WebsiteConfig(
            name=f"shop{i}",
            base_url=f"https://shop{i}.test",
            adapter_class="shop",
            categories=[Category.ELECTRONICS],
            conditions=[Condition.NEW],
        )
        for i in range(site_count)
    ]
    return config


@pytest.mark.asyncio
async def test_degraded_sites_share_half_sized_pool(monkeypatch):
    """Sites with a few consecutive failures get base//2 parallelism, not base."""
    monkeypatch.setattr(
        "src.searcher.playwright_searcher.get_adapter", lambda name: BarrierAdapter
    )
    monkeypatch.setattr(
        "src.searcher.playwright_searcher.load_profiles", lambda: {}
    )

    config = _degraded_config(site_count=3, concurrency=4)
    searcher = PlaywrightSearcher(
        config, llm=object(), storage=object(), browser_manager=FakeBrowserManager()
    )
    searcher.profiles = {}
    searcher.health.sites.clear()
    for site in config.search.websites:
        health = SiteHealth(site_name=site.name, adapter_class=site.adapter_class)
        health.total_searches = 10
        health.successful_searches = 8
        health.consecutive_failures = 2
        searcher.health.sites[site.name] = health

    in_flight = 0
    max_in_flight = 0

    async def fake_search(site, query, category, filters):
        nonlocal in_flight, max_in_flight
        in_flight += 1
        max_in_flight = max(max_in_flight, in_flight)
        await asyncio.sleep(0.05)
        in_flight -= 1
        return []

    searcher._search_one_site = fake_search

    await searcher._execute_round("pc", "new", "electronics", set())

    assert max_in_flight == 2
