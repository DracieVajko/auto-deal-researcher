"""Adapter regression tests (offline — no network)."""

import inspect

import pytest

from src.searcher.adapters import ADAPTER_REGISTRY, get_adapter
from src.searcher.adapters.alza import AlzaAdapter
from src.searcher.adapters.backmarket import BackMarketAdapter
from src.searcher.adapters.base import BaseAdapter, SiteBlockedError
from src.searcher.adapters.ebay import EbayAdapter


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("339 €", 339.0),
        ("339\xa0€", 339.0),              # NBSP as used by Alza
        ("1 299 €", 1299.0),
        ("1.299,50 €", 1299.50),
        ("1,299.50 €", 1299.50),
        ("EUR 249,00", 249.0),
        ("249,00 EUR", 249.0),
        ("339 €\nOd 7,80 € mesačne", 339.0),  # first price wins
        ("2,56 €", 2.56),
        ("", None),
        ("no price here", None),
    ],
)
def test_parse_price_eur(raw, expected):
    assert BaseAdapter.parse_price_eur(raw) == expected


class FakePage:
    def __init__(self, url="https://x", title="t"):
        self.url = url
        self._title = title

    async def title(self):
        return self._title


@pytest.mark.asyncio
async def test_detect_block_flags_cloudflare():
    adapter = get_adapter("bazos")()
    reason = await adapter.detect_block(
        FakePage(url="https://www.backmarket.sk/testchallengepage?next=x", title="Just a moment...")
    )
    assert reason == "cloudflare challenge"


@pytest.mark.asyncio
async def test_detect_block_passes_clean_page():
    adapter = get_adapter("bazos")()
    assert await adapter.detect_block(FakePage(url="https://www.bazos.sk", title="Bazos")) is None


def test_alza_selectors_match_live_dom():
    """Alza uses .browsingitem; .browsinglink matched 0 elements."""
    a = AlzaAdapter()
    assert a.item_selector == ".browsingitem"
    assert a.results_selector == ".browsingitemcontainer"


def test_ebay_selectors_match_live_dom():
    """eBay renamed .s-item to .s-card."""
    e = EbayAdapter()
    assert e.item_selector == ".s-card"


def test_backmarket_uses_locale_aware_search_path():
    """backmarket.sk serves /sk-sk/search, not /search."""
    src = inspect.getsource(BackMarketAdapter.search)
    assert "/sk-sk/search?q=" in src


def test_html_adapters_expose_selectors():
    """Every scraper adapter must declare both selectors for diagnostics."""
    for name, cls in ADAPTER_REGISTRY.items():
        assert cls.item_selector, f"{name} has no item_selector"
        assert cls.results_selector, f"{name} has no results_selector"


def test_site_blocked_error_is_runtime_error():
    assert issubclass(SiteBlockedError, RuntimeError)