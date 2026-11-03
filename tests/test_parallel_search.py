"""Parallel site search with bounded concurrency (offline)."""

import asyncio
from typing import ClassVar

import pytest

from src.config.models import AppConfig, Category, Condition, SearchConfig, WebsiteConfig
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
        except asyncio.TimeoutError:
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

    deals = await searcher._execute_round("pc", "new", "electronics", set())

    assert deals == []
    assert BarrierAdapter.started == 2
    assert BarrierAdapter.timeouts == 0
