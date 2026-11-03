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


def _real_site(name, *, enabled=True):
    from src.searcher.site_registry import by_id

    spec = by_id(name)
    return WebsiteConfig(
        name=name,
        base_url=spec.base_url,
        enabled=enabled,
        adapter_class=spec.adapter_class,
        categories=[Category(c) for c in spec.categories],
        conditions=[Condition(c) for c in spec.conditions],
        country=spec.country,
        currency=spec.currency,
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
    assert ("used", "auto", "auto", frozenset()) in searcher._site_selection_cache


@pytest.mark.asyncio
async def test_zero_max_sites_selects_every_candidate():
    config = AppConfig(search=SearchConfig(
        websites=[_site(f"shop{i}", "SK") for i in range(12)],
        user_country="SK",
        max_sites=0,
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    _profiles(searcher, *[f"shop{i}" for i in range(12)])

    selected = await searcher._select_sites("used", "auto", "auto")
    assert len(selected) == 12


@pytest.mark.asyncio
async def test_requested_sites_bypass_the_llm():
    class ExplodingLLM:
        async def chat_json(self, *args, **kwargs):
            raise AssertionError("the LLM must not be called")

    config = AppConfig(search=SearchConfig(
        websites=[_site("shop_a", "SK"), _site("shop_b", "SK")],
        user_country="SK",
        max_sites=0,
    ))
    config.search.diamond_search.enabled = False
    searcher = PlaywrightSearcher(
        config, llm=ExplodingLLM(), storage=object(), browser_manager=object()
    )
    _profiles(searcher, "shop_a", "shop_b")

    selected = await searcher._select_sites(
        "used", "auto", "auto", requested_sites=["shop_b"]
    )
    assert [s.name for s in selected] == ["shop_b"]


@pytest.mark.asyncio
async def test_unknown_requested_site_raises():
    config = AppConfig(search=SearchConfig(websites=[], user_country="SK"))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)

    with pytest.raises(ValueError, match="Unknown site"):
        await searcher._select_sites(
            "used", "auto", "auto", requested_sites=["nope"]
        )


@pytest.mark.asyncio
async def test_blocked_site_is_skipped_with_a_reason():
    config = AppConfig(search=SearchConfig(
        websites=[_real_site("solaro_sk")],
        user_country="SK",
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)

    selected = await searcher._select_sites("new", "electronics", "solar")
    assert selected == []
    assert any(
        item["name"] == "solaro_sk" and "blocked" in item["reason"]
        for item in searcher._skipped_sites
    )


@pytest.mark.asyncio
async def test_requested_blocked_site_is_still_skipped():
    config = AppConfig(search=SearchConfig(
        websites=[_real_site("solaro_sk")],
        user_country="SK",
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)

    selected = await searcher._select_sites(
        "new", "electronics", "solar", requested_sites=["solaro_sk"]
    )
    assert selected == []
    assert any(
        item["name"] == "solaro_sk" and "blocked" in item["reason"]
        for item in searcher._skipped_sites
    )


@pytest.mark.asyncio
async def test_planned_site_without_profile_is_skipped(monkeypatch):
    from types import SimpleNamespace

    import src.searcher.playwright_searcher as module

    monkeypatch.setattr(
        module,
        "by_id",
        lambda name: SimpleNamespace(status="planned", notes="", specialties=())
        if name == "shop_planned"
        else None,
    )
    config = AppConfig(search=SearchConfig(
        websites=[_site("shop_planned", "SK")],
        user_country="SK",
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    searcher.profiles = {}

    assert await searcher._select_sites("used", "auto", "auto") == []
    assert any(
        item["name"] == "shop_planned" and "profile" in item["reason"]
        for item in searcher._skipped_sites
    )


@pytest.mark.asyncio
async def test_needs_login_without_session_is_skipped(monkeypatch):
    from src.searcher import sessions

    monkeypatch.setattr(sessions, "has_session", lambda name: False)
    config = AppConfig(search=SearchConfig(
        websites=[_real_site("ebay")],
        user_country="SK",
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)

    assert await searcher._select_sites("used", "electronics", "phone") == []
    assert any(
        item["name"] == "ebay" and "login" in item["reason"].lower()
        for item in searcher._skipped_sites
    )


@pytest.mark.asyncio
async def test_cache_key_includes_the_prompt():
    config = AppConfig(search=SearchConfig(
        websites=[_site("shop_a", "SK")],
        user_country="SK",
        max_sites=0,
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    _profiles(searcher, "shop_a")

    await searcher._select_sites("used", "auto", "battery")
    await searcher._select_sites("used", "auto", "laptop")
    assert ("used", "auto", "battery", frozenset()) in searcher._site_selection_cache
    assert ("used", "auto", "laptop", frozenset()) in searcher._site_selection_cache


@pytest.mark.asyncio
async def test_site_plan_contains_selected_and_skipped():
    config = AppConfig(search=SearchConfig(
        websites=[_real_site("solaro_sk"), _site("shop_a", "SK")],
        user_country="SK",
    ))
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    _profiles(searcher, "shop_a")

    await searcher._select_sites("used", "auto", "solar")
    assert "shop_a" in searcher.site_plan.selected
    assert any(item["name"] == "solaro_sk" for item in searcher.site_plan.skipped)


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
                    name="aukro",
                    base_url="https://aukro.cz",
                    adapter_class="aukro",
                    categories=[Category.ELECTRONICS],
                )
            ]
        )
    )
    config.search.diamond_search.enabled = False
    searcher = _searcher(config)
    assert searcher._site_market(config.search.websites[0]) == ("CZ", "CZK")
