"""Base adapter/base-url and filter-hook regression tests (offline)."""

import pytest

from src.searcher.adapters.alza import AlzaAdapter
from src.searcher.adapters.bazos import BazosAdapter
from src.searcher.adapters.facebook import FacebookAdapter
from src.searcher.filters import SearchFilters
from src.searcher.site_profiles import FilterSpec, SiteProfile, UrlFilterSpec


class FakePage:
    def __init__(self):
        self.url = "https://www.bazos.sk/"
        self._title = "Bazos"
        self.goto_urls = []

    async def title(self):
        return self._title

    async def goto(self, url, **kwargs):
        self.goto_urls.append(url)

    async def wait_for_selector(self, selector, timeout=0):  # noqa: ASYNC109
        return None

    async def query_selector(self, selector):
        return None

    async def query_selector_all(self, selector):
        return []

    async def wait_for_timeout(self, _timeout):
        return None


def test_alza_adapter_uses_configured_base_url():
    adapter = AlzaAdapter(base_url="https://www.alza.cz")
    assert adapter.default_search_url("mini pc") == "https://www.alza.cz/search.htm?exps=mini+pc"
    assert AlzaAdapter.base_url == "https://www.alza.sk"


def test_bazos_adapter_uses_configured_base_url():
    adapter = BazosAdapter(base_url="https://www.bazos.cz")
    assert adapter.default_search_url("pc") == "https://www.bazos.cz/search.php?hledat=pc"


def test_facebook_adapter_handles_marketplace_base_url():
    assert FacebookAdapter(base_url="https://www.facebook.com/marketplace").default_search_url(
        "pc"
    ) == "https://www.facebook.com/marketplace/search/?query=pc"
    assert FacebookAdapter(base_url="https://www.facebook.com").default_search_url("pc") == (
        "https://www.facebook.com/marketplace/search/?query=pc"
    )


@pytest.mark.asyncio
async def test_goto_search_prefers_profile_url(monkeypatch):
    page = FakePage()
    adapter = AlzaAdapter(base_url="https://www.alza.cz")
    profile = SiteProfile.model_validate(
        {
            "site_id": "alza_cz",
            "base_url": "https://www.alza.cz",
            "search": {"url_template": "https://www.alza.cz/search.htm?exps={query}"},
            "filters": {"price_max": {"url": {"param": "max"}}},
        }
    )
    await adapter._goto_search(
        page, "pc", SearchFilters(max_price=400), "any", profile
    )
    assert page.goto_urls == ["https://www.alza.cz/search.htm?exps=pc&max=400"]


@pytest.mark.asyncio
async def test_goto_search_falls_back_to_adapter_url():
    page = FakePage()
    adapter = BazosAdapter()
    await adapter._goto_search(page, "pc")
    assert page.goto_urls == ["https://www.bazos.sk/search.php?hledat=pc"]


@pytest.mark.asyncio
async def test_apply_filters_is_noop_without_profile():
    page = FakePage()
    adapter = BazosAdapter()
    assert await adapter._apply_filters(page, SearchFilters(max_price=100)) == []


@pytest.mark.asyncio
async def test_bazos_search_calls_goto_then_filters(monkeypatch):
    page = FakePage()
    adapter = BazosAdapter()
    calls = []

    async def fake_goto(*args, **kwargs):
        calls.append("goto")
        return "https://www.bazos.sk/search.php?hledat=pc"

    async def fake_apply(*args, **kwargs):
        calls.append("filters")
        return []

    monkeypatch.setattr(adapter, "_goto_search", fake_goto)
    monkeypatch.setattr(adapter, "_apply_filters", fake_apply)
    monkeypatch.setattr("src.searcher.adapters.bazos.asyncio.sleep", lambda *_: _instant())

    deals = await adapter.search(page, "pc", filters=SearchFilters(max_price=100))
    assert deals == []
    assert calls == ["goto", "filters"]


async def _instant():
    return None


@pytest.mark.asyncio
async def test_alza_search_applies_profile_filters_before_extraction(monkeypatch):
    page = FakePage()
    adapter = AlzaAdapter()
    calls = []

    async def fake_goto(*args, **kwargs):
        calls.append("goto")

    async def fake_apply(*args, **kwargs):
        calls.append("filters")
        return ["price_max"]

    monkeypatch.setattr(adapter, "_goto_search", fake_goto)
    monkeypatch.setattr(adapter, "_apply_filters", fake_apply)

    deals = await adapter.search(
        page,
        "pc",
        filters=SearchFilters(max_price=100),
        profile=SiteProfile.model_validate(
            {
                "site_id": "alza",
                "base_url": "https://www.alza.sk",
                "filters": {"price_max": {"url": {"param": "max"}}},
            }
        ),
    )
    assert deals == []
    assert calls == ["goto", "filters"]


def test_profile_filter_spec_is_optional_for_url_only():
    spec = FilterSpec(url=UrlFilterSpec(param="max"))
    assert spec.ui is None
