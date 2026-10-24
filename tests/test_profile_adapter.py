"""Generic profile adapter extraction (offline, fake DOM)."""

import pytest

from src.searcher.adapters.profile_adapter import ProfileAdapter
from src.searcher.site_profiles import SiteProfile


class FakeChild:
    def __init__(self, text="", href=None):
        self.text = text
        self.href = href

    async def inner_text(self):
        return self.text

    async def get_attribute(self, name):
        return self.href if name == "href" else None


class FakeElement:
    def __init__(self, mapping=None, text="", href=None):
        self.mapping = mapping or {}
        self.text = text
        self.href = href

    async def query_selector(self, selector):
        return self.mapping.get(selector)

    async def inner_text(self):
        return self.text

    async def get_attribute(self, name):
        return self.href if name == "href" else None


def _profile(**overrides):
    data = {
        "site_id": "mall",
        "base_url": "https://www.mall.sk",
        "status": "validated",
        "search": {"url_template": "https://www.mall.sk/search?q={query}"},
        "extraction": {
            "item_selector": ".product",
            "title_selector": ".title",
            "price_selector": ".price",
            "link_selector": "a",
            "condition_selector": ".condition",
            "location_selector": ".location",
            "brand_selector": ".brand",
        },
    }
    data.update(overrides)
    return SiteProfile.model_validate(data)


@pytest.mark.asyncio
async def test_profile_adapter_extracts_from_fixture_element():
    element = FakeElement(
        mapping={
            ".title": FakeChild("Notebook Lenovo"),
            ".price": FakeChild("1 299,50 €"),
            "a": FakeChild(href="/p/123"),
            ".condition": FakeChild("Použité"),
            ".location": FakeChild("Bratislava"),
            ".brand": FakeChild("Lenovo"),
        }
    )
    adapter = ProfileAdapter(profile=_profile())
    deal = await adapter.extract_deal(None, element)
    assert deal is not None
    assert deal.title == "Notebook Lenovo"
    assert deal.price_eur == 1299.50
    assert deal.url == "https://www.mall.sk/p/123"
    assert deal.condition == "used"
    assert deal.site_name == "mall"
    assert deal.metadata["location"] == "Bratislava"
    assert deal.metadata["brand"] == "Lenovo"


@pytest.mark.asyncio
async def test_profile_adapter_skips_card_without_price():
    element = FakeElement(
        mapping={
            ".title": FakeChild("Notebook"),
            ".price": FakeChild("na vyžiadanie"),
            "a": FakeChild(href="/p/123"),
        }
    )
    adapter = ProfileAdapter(profile=_profile())
    assert await adapter.extract_deal(None, element) is None


@pytest.mark.asyncio
async def test_profile_adapter_requires_runtime_ready_profile():
    adapter = ProfileAdapter(profile=_profile(status="draft"))
    assert await adapter.search(None, "pc") == []


def test_profile_adapter_uses_profile_base_url():
    adapter = ProfileAdapter(base_url="https://ignored.test", profile=_profile())
    assert adapter.base_url == "https://www.mall.sk"


def test_profile_adapter_prefers_the_explicit_currency_over_the_profile():
    """The registry is authoritative; an older profile may still say EUR."""
    profile = _profile(currency="EUR")
    adapter = ProfileAdapter(profile=profile, currency="CZK")
    assert adapter.currency == "CZK"


def test_profile_adapter_falls_back_to_the_profile_currency():
    adapter = ProfileAdapter(profile=_profile(currency="CZK"))
    assert adapter.currency == "CZK"


def test_profile_adapter_default_search_url():
    adapter = ProfileAdapter(profile=_profile())
    assert adapter.default_search_url("mini pc") == "https://www.mall.sk/search?q=mini+pc"
