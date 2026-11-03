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
async def test_detect_block_flags_aliexpress_punish_page():
    adapter = get_adapter("bazos")()
    reason = await adapter.detect_block(
        FakePage(
            url="https://www.aliexpress.com/_____tmd_____/punish?x5secdata=abc&x5step=1",
            title="",
        )
    )
    assert reason == "aliExpress anti-bot challenge"


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
    src = inspect.getsource(BackMarketAdapter.default_search_url)
    assert "/sk-sk/search?q=" in src


def test_html_adapters_expose_selectors():
    """Every scraper adapter must declare both selectors for diagnostics."""
    for name, cls in ADAPTER_REGISTRY.items():
        assert cls.item_selector, f"{name} has no item_selector"
        assert cls.results_selector, f"{name} has no results_selector"


def test_site_blocked_error_is_runtime_error():
    assert issubclass(SiteBlockedError, RuntimeError)


class FakeText:
    def __init__(self, text="", href=None):
        self.text = text
        self.href = href

    async def inner_text(self):
        return self.text

    async def get_attribute(self, name):
        return self.href if name == "href" else None


class FakeContainer:
    def __init__(self, text="", mapping=None):
        self.text = text
        self.mapping = mapping or {}

    async def inner_text(self):
        return self.text

    async def query_selector(self, selector):
        return self.mapping.get(selector)


@pytest.mark.asyncio
async def test_bazos_quote_reads_shipping_from_card():
    link = FakeText("Notebook Lenovo", href="/inzerat/1")
    title_container = FakeContainer(
        "Notebook Lenovo", {".nadpis a": link, "a[href*='inzerat']": link}
    )
    price = FakeText("26 € Doprava 4,99 €")
    price_container = FakeContainer(
        "26 € Doprava 4,99 €", {"span, b, strong": price}
    )

    adapter = get_adapter("bazos")()
    deal = await adapter._extract_from_group(None, title_container, price_container)
    assert deal is not None
    assert deal.price_quote is not None
    assert deal.price_quote.shipping.cost_eur == 4.99
    assert deal.price_quote.effective_price_eur == 30.99


@pytest.mark.asyncio
async def test_ebay_card_attaches_a_price_quote():
    class FakeChild:
        def __init__(self, text="", href=None):
            self.text = text
            self.href = href

        async def inner_text(self):
            return self.text

        async def get_attribute(self, name):
            return self.href if name == "href" else None

    class FakeCard:
        mapping = {
            ".s-card__title": FakeChild("18650 battery"),
            ".s-card__price": FakeChild("19,99 €"),
            'a[href*="/itm/"]': FakeChild(href="https://www.ebay.de/itm/1"),
            ".s-card__subtitle": FakeChild("Used"),
        }

        async def query_selector(self, selector):
            return self.mapping.get(selector)

        async def inner_text(self):
            return "18650 battery 19,99 € Used + shipping 4,99 €"

    deal = await EbayAdapter().extract_deal(None, FakeCard())
    assert deal is not None
    assert deal.price_quote is not None
    assert deal.price_quote.shipping.cost_eur == 4.99


@pytest.mark.asyncio
async def test_ebay_error_page_is_blocked():
    reason = await EbayAdapter().detect_block(
        FakePage(url="https://www.ebay.de/sch/i.html", title="Error Page | eBay")
    )
    assert reason == "ebay bot block"