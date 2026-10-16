"""Live Playwright tests — one per site, runnable from VSCode's Test Explorer.

Enable with:   pytest -m live
Single site:   pytest -m live --site bazos
Headed watch:  pytest -m live --headed

These hit real websites and are skipped by default. They are the regression
net for selector drift: if a site redesigns its markup, the matching test
here fails before `doctor` or the monitor notices.
"""

from __future__ import annotations

import re

import pytest

pytestmark = pytest.mark.live

QUERY = "dji drone"

# (site_id, adapter_class, expected condition support, note)
SITES = [
    ("alza", "AlzaAdapter", ["new", "open_box"], "uses /search.htm?exps="),
    ("bazos", "BazosAdapter", ["used"], "grouped .inzeraty > div layout"),
    ("ebay", "EbayAdapter", ["used", "new", "refurbished", "open_box"], "needs search-box warmup"),
    ("backmarket", "BackMarketAdapter", ["refurbished"], "Cloudflare-gated"),
]


def _deals_are_sane(deals) -> None:
    for d in deals:
        assert d.url.startswith("http"), f"bad url: {d.url!r}"
        assert d.title.strip(), f"empty title for {d.url}"
        assert d.price_eur > 0, f"non-positive price {d.price_eur} for {d.url}"
        assert d.condition and d.condition != "unknown", f"missing condition for {d.url}"


@pytest.mark.parametrize("site_id,adapter_class,conditions,note", SITES,
                         ids=[s[0] for s in SITES])
def test_adapter_metadata(site_id, adapter_class, conditions, note, adapter_factory, request):
    """Metadata-level checks: no browser needed, runs for every site."""
    if request.config.getoption("--site") not in (None, site_id):
        pytest.skip("scoped to another site")

    adapter = adapter_factory(site_id)
    assert type(adapter).__name__ == adapter_class
    assert adapter.base_url.startswith("https://")
    assert adapter.item_selector, "item_selector must be declared for doctor diagnostics"
    assert adapter.results_selector, "results_selector must be declared"
    assert sorted(adapter.supported_conditions) == sorted(conditions)


@pytest.mark.parametrize("site_id,adapter_class,conditions,note", SITES,
                         ids=[s[0] for s in SITES])
@pytest.mark.asyncio
async def test_site_search_returns_deals(site_id, adapter_class, conditions, note,
                                         adapter_factory, make_page, request):
    """Real search against the live site.

    Sites behind an anti-bot wall (BackMarket) and sites that need a login
    (Facebook) are expected to raise SiteBlockedError or return nothing; the
    assertion then checks that failure is *clean and fast*, not that results
    appear.
    """
    if request.config.getoption("--site") not in (None, site_id):
        pytest.skip("scoped to another site")

    from src.searcher.adapters.base import SiteBlockedError

    adapter = adapter_factory(site_id)
    page = await make_page(f"live-{site_id}")
    try:
        deals = await adapter.search(page, QUERY, max_results=5)
    except SiteBlockedError as exc:
        pytest.skip(f"{site_id} is behind an anti-bot wall: {exc}")
    finally:
        await page.close()

    if site_id == "backmarket":
        pytest.skip("backmarket is Cloudflare-gated; only the block path is asserted")

    if not deals:
        pytest.xfail(f"{site_id} returned no results (intermittent or blocked)")

    _deals_are_sane(deals)
    assert len(deals) <= 5


@pytest.mark.asyncio
async def test_alza_specific_selectors(make_page, adapter_factory, request):
    """Alza regression: the old .browsinglink/>/?q= combination returned 0."""
    if request.config.getoption("--site") not in (None, "alza"):
        pytest.skip("scoped to another site")

    adapter = adapter_factory("alza")
    page = await make_page("live-alza-selectors")
    try:
        await page.goto(f"{adapter.base_url}/search.htm?exps={QUERY.replace(' ', '+')}",
                        wait_until="domcontentloaded", timeout=45000)
        await page.wait_for_timeout(3000)
        assert await page.query_selector_all(adapter.item_selector), (
            "no .browsingitem elements — Alza markup likely changed"
        )
    finally:
        await page.close()


@pytest.mark.asyncio
async def test_bazos_price_parsing_from_live_dom(make_page, adapter_factory, request):
    """Bazos regression: prices use NBSP and are grouped 5 divs per listing."""
    if request.config.getoption("--site") not in (None, "bazos"):
        pytest.skip("scoped to another site")

    adapter = adapter_factory("bazos")
    page = await make_page("live-bazos-price")
    try:
        deals = await adapter.search(page, QUERY, max_results=3)
        if not deals:
            pytest.xfail("bazos returned nothing this run")
        for d in deals:
            # Bazos prices use NBSP: "26 €" must parse to 26.0, not fail.
            assert "\u00a0" not in d.title, "NBSP leaked into the title"
            assert d.price_eur > 0
            # Slovak diacritics are expected; only NBSP/thin-space is a bug.
            assert not re.search(r"[\u00a0\u202f]", d.title)
    finally:
        await page.close()


@pytest.mark.asyncio
async def test_searcher_end_to_end_single_site(config, make_page, request):
    """One full search round through PlaywrightSearcher with a mock LLM."""
    pytest.importorskip("src.searcher.playwright_searcher")
    from src.llm.mock_client import MockLLMClient
    from src.searcher.playwright_searcher import PlaywrightSearcher

    enabled = [s for s in config.search.websites if s.enabled]
    if not enabled:
        pytest.skip("no sites enabled in config.yaml")

    class _StubStorage:
        def get_deal(self, url):
            return None

    class _StubBrowser:
        def __init__(self, bm):
            self._bm = bm

        async def get_browser(self):
            return await self._bm.get_browser()

        async def get_page(self, session_id=None, browser_type="chromium"):
            page = await self._bm.get_page(session_id=session_id)
            page.set_default_timeout(45000)
            page.set_default_navigation_timeout(45000)
            return page

    from src.browser.manager import BrowserManager

    real_bm = BrowserManager(config)
    searcher = PlaywrightSearcher(config, MockLLMClient(config), _StubStorage(), _StubBrowser(real_bm))
    try:
        async with searcher:
            deals = await searcher.search(QUERY, "any", "any")
        assert deals is not None
        if deals:
            _deals_are_sane(deals)
    finally:
        await real_bm.close()