"""Bazos detail pages: the description and town live outside the result card."""

import pytest
from playwright.async_api import Error as PlaywrightError

from src.searcher.adapters.base import Deal
from src.searcher.adapters.bazos import BazosAdapter


class FakeElement:
    def __init__(self, text: str):
        self._text = text

    async def inner_text(self) -> str:
        return self._text


class FakePage:
    """Minimal Playwright page: maps a selector to fixed text."""

    def __init__(self, pages: dict[str, str] | None = None, fail: bool = False):
        self.pages = pages or {}
        self.fail = fail
        self.visited: list[str] = []

    async def goto(self, url: str, **kwargs) -> None:
        if self.fail:
            raise PlaywrightError("navigation failed")  # noqa: TRY003
        self.visited.append(url)

    async def query_selector(self, selector: str):
        text = self.pages.get(selector, "")
        return FakeElement(text) if text else None

    async def reload(self, **kwargs) -> None:
        self.visited.append("reload")


def _deal(url: str = "https://sport.bazos.sk/inzerat/1/item.php") -> Deal:
    return Deal(
        url=url,
        title="Horský bicykel",
        price_eur=90.0,
        site_name="bazos",
    )


@pytest.mark.asyncio
async def test_enrich_details_stores_description_and_location():
    adapter = BazosAdapter()
    adapter.detail_delay_seconds = 0
    deal = _deal()
    page = FakePage(
        {
            ".popisdetail": 'Predám horský bicykel.  Kolesá 26", rám L.',
            ".maincontent": "Cena: 90 € Lokalita: 841 04 Bratislava Videlo: 42",
        }
    )

    failed = await adapter._enrich_details(page, [deal])

    assert failed == 0
    assert deal.metadata["description"] == 'Predám horský bicykel. Kolesá 26", rám L.'
    assert deal.metadata["location"] == "841 04 Bratislava"
    assert page.visited == [deal.url]

@pytest.mark.asyncio
async def test_enrich_details_keeps_card_data_when_page_fails():
    adapter = BazosAdapter()
    adapter.detail_delay_seconds = 0
    deal = _deal()

    failed = await adapter._enrich_details(FakePage(fail=True), [deal])

    assert failed == 1
    assert deal.metadata == {"detail_failed": True}


class FakeRetryPage(FakePage):
    """First load has no description; the reload serves the full page."""

    def __init__(self, pages: dict[str, str], retry_pages: dict[str, str]):
        super().__init__(pages)
        self.retry_pages = retry_pages
        self.reloads = 0

    async def reload(self, **kwargs) -> None:
        self.reloads += 1
        self.pages = self.retry_pages


@pytest.mark.asyncio
async def test_enrich_details_retries_an_empty_page(monkeypatch):
    import src.searcher.adapters.bazos as bazos_mod

    adapter = BazosAdapter()
    adapter.detail_delay_seconds = 0
    deal = _deal()
    page = FakeRetryPage(
        {".maincontent": "Cena: 90 € Lokalita: 841 04 Bratislava Videlo: 1"},
        {
            ".popisdetail": "Predám bicykel, rám L.",
            ".maincontent": "Cena: 90 € Lokalita: 841 04 Bratislava Videlo: 1",
        },
    )

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(bazos_mod.asyncio, "sleep", noop)

    failed = await adapter._enrich_details(page, [deal])

    assert failed == 0
    assert page.reloads == 1
    assert deal.metadata["description"] == "Predám bicykel, rám L."


def test_parse_location_variants():
    assert (
        BazosAdapter._parse_location("Lokalita: 022 01 Čadca Videlo: 5")
        == "022 01 Čadca"
    )
    assert (
        BazosAdapter._parse_location("Lokalita: 984 03 Lučenec Zobrazené: 9")
        == "984 03 Lučenec"
    )
    assert BazosAdapter._parse_location("no location here") == ""


@pytest.mark.asyncio
async def test_details_can_be_disabled(monkeypatch):
    """ADS_BAZOS_DETAILS=0 must skip the extra requests."""
    import src.searcher.adapters.bazos as bazos_mod

    adapter = BazosAdapter()
    calls = []

    async def fake_enrich(page, deals):
        calls.append(deals)

    async def noop(*args, **kwargs):
        return None

    async def five_elements(*args, **kwargs):
        return [object()] * 25

    created = []

    async def fake_extract(page, title_el, price_el):
        deal = _deal(url=f"https://sport.bazos.sk/inzerat/{len(created)}/item.php")
        created.append(deal)
        return deal

    monkeypatch.setattr(adapter, "_enrich_details", fake_enrich)
    monkeypatch.setattr(adapter, "_goto_search", noop)
    monkeypatch.setattr(adapter, "_handle_cookie_consent", noop)
    monkeypatch.setattr(adapter, "_apply_filters", noop)
    monkeypatch.setattr(adapter, "_extract_from_group", fake_extract)
    monkeypatch.setattr(bazos_mod.asyncio, "sleep", noop)

    page = FakePage()
    page.wait_for_selector = noop
    page.query_selector_all = five_elements

    monkeypatch.setenv("ADS_BAZOS_DETAILS", "0")
    assert len(await adapter.search(page, "bicykel")) == 5
    assert calls == []

    monkeypatch.setenv("ADS_BAZOS_DETAILS", "1")
    monkeypatch.setenv("ADS_BAZOS_DETAIL_LIMIT", "2")
    assert len(await adapter.search(page, "bicykel")) == 5
    assert len(calls) == 1
    assert len(calls[0]) == 2


@pytest.mark.asyncio
async def test_enrichment_covers_the_whole_page_by_default(monkeypatch):
    import src.searcher.adapters.bazos as bazos_mod

    adapter = BazosAdapter()
    calls = []

    async def fake_enrich(page, selected):
        calls.append(list(selected))
        return 0

    async def noop(*args, **kwargs):
        return None

    async def elements(*args, **kwargs):
        return [object()] * 75

    created = []

    async def fake_extract(page, title_el, price_el):
        deal = _deal(url=f"https://sport.bazos.sk/inzerat/{len(created)}/item.php")
        created.append(deal)
        return deal

    monkeypatch.delenv("ADS_BAZOS_DETAIL_LIMIT", raising=False)
    monkeypatch.setattr(adapter, "_enrich_details", fake_enrich)
    monkeypatch.setattr(adapter, "_goto_search", noop)
    monkeypatch.setattr(adapter, "_handle_cookie_consent", noop)
    monkeypatch.setattr(adapter, "_apply_filters", noop)
    monkeypatch.setattr(adapter, "_extract_from_group", fake_extract)
    monkeypatch.setattr(bazos_mod.asyncio, "sleep", noop)

    page = FakePage()
    page.wait_for_selector = noop
    page.query_selector_all = elements

    assert len(await adapter.search(page, "iphone")) == 15
    assert len(calls[0]) == 15


@pytest.mark.asyncio
async def test_enrichment_prefers_the_cheapest_when_capped(monkeypatch):
    import src.searcher.adapters.bazos as bazos_mod

    adapter = BazosAdapter()
    prices = [300.0, 100.0, 200.0, 400.0]
    calls = []

    async def fake_enrich(page, selected):
        calls.append(list(selected))
        return 0

    async def noop(*args, **kwargs):
        return None

    async def elements(*args, **kwargs):
        return [object()] * 20

    created = []

    async def fake_extract(page, title_el, price_el):
        deal = _deal(url=f"https://sport.bazos.sk/inzerat/{len(created)}/item.php")
        deal.price_eur = prices[len(created)]
        created.append(deal)
        return deal

    monkeypatch.setenv("ADS_BAZOS_DETAIL_LIMIT", "2")
    monkeypatch.setattr(adapter, "_enrich_details", fake_enrich)
    monkeypatch.setattr(adapter, "_goto_search", noop)
    monkeypatch.setattr(adapter, "_handle_cookie_consent", noop)
    monkeypatch.setattr(adapter, "_apply_filters", noop)
    monkeypatch.setattr(adapter, "_extract_from_group", fake_extract)
    monkeypatch.setattr(bazos_mod.asyncio, "sleep", noop)

    page = FakePage()
    page.wait_for_selector = noop
    page.query_selector_all = elements

    await adapter.search(page, "iphone")
    assert [d.price_eur for d in calls[0]] == [100.0, 200.0]


@pytest.mark.asyncio
async def test_failed_detail_is_marked_not_guessed():
    adapter = BazosAdapter()
    adapter.detail_delay_seconds = 0
    deal = _deal()

    failed = await adapter._enrich_details(FakePage(fail=True), [deal])

    assert failed == 1
    assert deal.metadata["detail_failed"] is True

