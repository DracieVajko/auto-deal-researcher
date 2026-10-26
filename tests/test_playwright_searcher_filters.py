"""Runtime site selection and filter forwarding (offline)."""

from typing import ClassVar

import pytest

from src.config.models import AppConfig, Category, Condition, SearchConfig, WebsiteConfig
from src.searcher.filters import SearchFilters
from src.searcher.playwright_searcher import PlaywrightSearcher
from src.searcher.site_profiles import SiteProfile


def _config(*websites):
    config = AppConfig(
        search=SearchConfig(websites=list(websites)),
    )
    config.search.diamond_search.enabled = False
    return config


def _searcher(config):
    return PlaywrightSearcher(config, llm=object(), storage=object(), browser_manager=object())


def _profile(site_id="mall", status="validated"):
    return SiteProfile.model_validate(
        {
            "site_id": site_id,
            "base_url": "https://www.mall.sk",
            "status": status,
            "search": {"url_template": "https://www.mall.sk/search?q={query}"},
            "extraction": {"item_selector": ".product"},
        }
    )


def test_profile_only_site_is_included_when_validated():
    config = _config(
        WebsiteConfig(
            name="mall",
            base_url="https://www.mall.sk",
            adapter_class="mall",
            categories=[Category.ELECTRONICS],
            conditions=[Condition.NEW],
        )
    )
    searcher = _searcher(config)
    searcher.profiles = {"mall": _profile()}
    assert [site.name for site in searcher._filter_sites("any", "electronics")] == ["mall"]


def test_profile_only_site_is_excluded_when_blocked():
    config = _config(
        WebsiteConfig(
            name="mall",
            base_url="https://www.mall.sk",
            adapter_class="mall",
            categories=[Category.ELECTRONICS],
            conditions=[Condition.NEW],
        )
    )
    searcher = _searcher(config)
    searcher.profiles = {"mall": _profile(status="blocked")}
    assert searcher._filter_sites("any", "electronics") == []


def test_profile_only_site_honours_config_category_and_condition():
    config = _config(
        WebsiteConfig(
            name="mall",
            base_url="https://www.mall.sk",
            adapter_class="mall",
            categories=[Category.ELECTRONICS],
            conditions=[Condition.NEW],
        )
    )
    searcher = _searcher(config)
    searcher.profiles = {"mall": _profile()}
    assert searcher._filter_sites("used", "electronics") == []
    assert searcher._filter_sites("new", "appliances") == []


def test_profile_with_mismatched_base_url_is_ignored():
    config = _config(
        WebsiteConfig(
            name="mall",
            base_url="https://www.mall.cz",
            adapter_class="mall",
            categories=[Category.ELECTRONICS],
            conditions=[Condition.NEW],
        )
    )
    searcher = _searcher(config)
    searcher.profiles = {"mall": _profile()}
    assert searcher._profile_for(config.search.websites[0]) is None


def test_unknown_site_without_profile_is_skipped():
    config = _config(
        WebsiteConfig(
            name="mall",
            base_url="https://www.mall.sk",
            adapter_class="mall",
            categories=[Category.ANY],
            conditions=[Condition.ANY],
        )
    )
    searcher = _searcher(config)
    searcher.profiles = {}
    assert searcher._filter_sites("any", "any") == []


def test_registered_adapter_uses_configured_base_url():
    config = _config(
        WebsiteConfig(
            name="alza_cz",
            base_url="https://www.alza.cz",
            adapter_class="alza",
            categories=[Category.ELECTRONICS],
            conditions=[Condition.NEW],
        )
    )
    searcher = _searcher(config)
    searcher.profiles = {}
    sites = searcher._filter_sites("new", "electronics")
    assert [site.name for site in sites] == ["alza_cz"]


class FakePage:
    def __init__(self):
        self.closed = False

    def set_default_timeout(self, value):
        pass

    def set_default_navigation_timeout(self, value):
        pass

    async def close(self):
        self.closed = True


class FakeBrowserManager:
    def __init__(self):
        self.page = FakePage()

    async def get_page(self, session_id=None):
        return self.page


class FakeAdapter:
    instances: ClassVar[list] = []

    def __init__(self, base_url=None, currency=None, enrich_limit=None):
        self.base_url = base_url
        self.currency = currency
        self.enrich_limit = enrich_limit
        self.calls = []
        FakeAdapter.instances.append(self)

    def matches_condition(self, condition):
        return True

    def matches_category(self, category):
        return True

    async def search(self, page, query, **kwargs):
        self.calls.append((query, kwargs))
        return []


@pytest.mark.asyncio
async def test_execute_round_forwards_filters_to_adapter(monkeypatch):
    config = _config(
        WebsiteConfig(
            name="alza_cz",
            base_url="https://www.alza.cz",
            adapter_class="alza",
            categories=[Category.ELECTRONICS],
            conditions=[Condition.NEW],
        )
    )
    searcher = _searcher(config)
    searcher.profiles = {}
    searcher.browser_manager = FakeBrowserManager()
    FakeAdapter.instances = []
    monkeypatch.setattr("src.searcher.playwright_searcher.get_adapter", lambda name: FakeAdapter)

    filters = SearchFilters(max_price=400, brand="amd")
    deals = await searcher._execute_round("pc", "new", "electronics", set(), filters)

    assert deals == []
    assert len(FakeAdapter.instances) == 2
    adapter = FakeAdapter.instances[-1]
    assert adapter.base_url == "https://www.alza.cz"
    assert adapter.calls[0][0] == "pc"
    assert adapter.calls[0][1]["filters"] is filters
    assert adapter.calls[0][1]["category"] == "electronics"
    assert adapter.calls[0][1]["profile"] is None


@pytest.mark.asyncio
async def test_execute_round_reports_selected_sites(monkeypatch):
    """The wizard's plan hook must receive the site names once."""
    config = _config(
        WebsiteConfig(
            name="alza_cz",
            base_url="https://www.alza.cz",
            adapter_class="alza",
            categories=[Category.ELECTRONICS],
            conditions=[Condition.NEW],
        )
    )
    searcher = _searcher(config)
    searcher.profiles = {}
    searcher.browser_manager = FakeBrowserManager()
    FakeAdapter.instances = []
    monkeypatch.setattr("src.searcher.playwright_searcher.get_adapter", lambda name: FakeAdapter)

    names = []
    await searcher._execute_round(
        "pc", "new", "electronics", set(), None, on_sites=names.extend
    )

    assert names == ["alza_cz"]
