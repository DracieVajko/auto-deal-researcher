"""Location-aware site selection inside PlaywrightSearcher (offline)."""

import pytest

from src.config.models import AppConfig, Category, Condition, SearchConfig, WebsiteConfig
from src.searcher.playwright_searcher import PlaywrightSearcher


def _site(name, country, currency="EUR", categories=None, conditions=None, enabled=True):
    return WebsiteConfig(
        name=name,
        base_url=f"https://www.{name}.test",
        enabled=enabled,
        adapter_class=name,
        categories=categories or [Category.AUTO],
        conditions=conditions or [Condition.USED],
        country=country,
        currency=currency,
    )


def _searcher(config):
    return PlaywrightSearcher(config, llm=object(), storage=object(), browser_manager=object())


def _profiles(searcher, *names):
    from src.searcher.site_profiles import SiteProfile

    searcher.profiles = {
        name: SiteProfile.model_validate(
            {
                "site_id": name,
                "base_url": f"https://www.{name}.test",
                "status": "validated",
                "search": {"url_template": f"https://www.{name}.test/s?q={{query}}"},
                "extraction": {"item_selector": ".item"},
            }
        )
        for name in names
    }


@pytest.mark.asyncio
async def test_local_market_is_searched_first():
    config = AppConfig(
        search=SearchConfig(
            websites=[
                _site("shop_cz", "CZ"),
                _site("autobazar_sk", "SK"),
                _site("mobile_de", "DE"),
            ],
            user_country="SK",
            max_sites=10,
        )
    )
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    _profiles(searcher, "shop_cz", "autobazar_sk", "mobile_de")

    selected = await searcher._select_sites("used", "auto", "octavia")
    assert [s.name for s in selected] == ["autobazar_sk", "mobile_de", "shop_cz"]


@pytest.mark.asyncio
async def test_max_sites_caps_the_number_of_shops():
    config = AppConfig(
        search=SearchConfig(
            websites=[_site(f"shop{i}", "SK") for i in range(6)],
            user_country="SK",
            max_sites=2,
        )
    )
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    _profiles(searcher, *[f"shop{i}" for i in range(6)])

    selected = await searcher._select_sites("used", "auto", "auto")
    assert len(selected) == 2


@pytest.mark.asyncio
async def test_selection_is_cached_per_condition_and_category():
    config = AppConfig(
        search=SearchConfig(
            websites=[_site("autobazar_sk", "SK")],
            user_country="SK",
            max_sites=5,
        )
    )
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    _profiles(searcher, "autobazar_sk")

    first = await searcher._select_sites("used", "auto", "auto")
    second = await searcher._select_sites("used", "auto", "auto")
    assert first == second
    assert ("used", "auto") in searcher._site_selection_cache


@pytest.mark.asyncio
async def test_disabled_sites_are_never_selected():
    config = AppConfig(
        search=SearchConfig(
            websites=[_site("autobazar_sk", "SK", enabled=False)],
            user_country="SK",
        )
    )
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    _profiles(searcher, "autobazar_sk")

    assert await searcher._select_sites("used", "auto", "auto") == []


@pytest.mark.asyncio
async def test_site_without_profile_is_not_selected():
    config = AppConfig(
        search=SearchConfig(
            websites=[_site("autobazar_sk", "SK")],
            user_country="SK",
        )
    )
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    searcher.profiles = {}

    assert await searcher._select_sites("used", "auto", "auto") == []


def test_site_market_falls_back_to_the_registry():
    config = AppConfig(
        search=SearchConfig(
            websites=[
                WebsiteConfig(
                    name="mironet_cz",
                    base_url="https://www.mironet.cz",
                    adapter_class="mironet",
                    categories=[Category.ELECTRONICS],
                )
            ]
        )
    )
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    assert searcher._site_market(config.search.websites[0]) == ("CZ", "CZK")
