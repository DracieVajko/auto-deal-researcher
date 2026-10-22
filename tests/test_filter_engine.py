"""URL, UI and post-filter application for canonical search filters."""

import pytest

from src.searcher.adapters.base import Deal
from src.searcher.filter_engine import FilterEngine
from src.searcher.filters import SearchFilters
from src.searcher.site_profiles import (
    FilterSpec,
    SearchSpec,
    SiteProfile,
    UiFilterSpec,
    UrlFilterSpec,
)


def _profile(search=None, filters=None, **overrides):
    data = {
        "site_id": "x",
        "base_url": "https://x.test",
        "status": "validated",
        "search": search or {},
        "filters": filters or {},
    }
    data.update(overrides)
    return SiteProfile.model_validate(data)


def test_build_url_uses_category_url_and_query_param():
    profile = _profile(
        search=SearchSpec(
            category_urls={"electronics": "https://x.test/e"},
            query_param="q",
        ),
        filters={
            "price_max": FilterSpec(url=UrlFilterSpec(param="max")),
        },
    )
    url = FilterEngine.build_search_url(
        profile, "mini pc", "electronics", SearchFilters(max_price=400)
    )
    assert url is not None
    assert url.startswith("https://x.test/e?")
    assert "q=mini+pc" in url
    assert "max=400" in url


def test_build_url_uses_url_template():
    profile = _profile(search=SearchSpec(url_template="https://x.test/s?q={query}"))
    url = FilterEngine.build_search_url(profile, "mini pc", "any", SearchFilters())
    assert url == "https://x.test/s?q=mini+pc"


def test_build_url_maps_condition_value():
    profile = _profile(
        search=SearchSpec(url_template="https://x.test/s?q={query}"),
        filters={
            "condition": FilterSpec(
                url=UrlFilterSpec(param="cond", value_map={"open_box": "openbox"})
            )
        },
    )
    url = FilterEngine.build_search_url(
        profile, "pc", "any", SearchFilters(condition="open_box")
    )
    assert url is not None
    assert "cond=openbox" in url


def test_build_url_encodes_diacritics_and_spaces():
    profile = _profile(search=SearchSpec(url_template="https://x.test/s?q={query}"))
    url = FilterEngine.build_search_url(profile, "práčka na prádlo", "any", SearchFilters())
    assert url is not None
    assert "pr%C3%A1%C4%8Dka+na+pr%C3%A1dlo" in url


def test_build_url_returns_none_without_search_spec():
    profile = _profile()
    assert FilterEngine.build_search_url(profile, "pc", "any", SearchFilters()) is None


def test_build_url_keeps_fixed_template_without_query():
    profile = _profile(search=SearchSpec(url_template="https://x.test/deals"))
    assert FilterEngine.build_search_url(profile, "pc", "any", SearchFilters()) == (
        "https://x.test/deals"
    )


class FakePage:
    def __init__(self, fail_selectors=()):
        self.fail_selectors = set(fail_selectors)
        self.calls = []
        self.waited = []

    async def fill(self, selector, value):
        if selector in self.fail_selectors:
            raise RuntimeError
        self.calls.append(("fill", selector, value))

    async def select_option(self, selector, **kwargs):
        self.calls.append(("select", selector, kwargs.get("value"), kwargs.get("label")))

    async def check(self, selector):
        if selector in self.fail_selectors:
            raise RuntimeError
        self.calls.append(("check", selector))

    async def click(self, selector):
        self.calls.append(("click", selector))

    async def wait_for_selector(self, selector, **kwargs):
        self.waited.append(selector)

    async def wait_for_timeout(self, _timeout):
        pass


@pytest.mark.asyncio
async def test_apply_ui_continues_when_selector_missing():
    page = FakePage(fail_selectors={"#brand"})
    profile = _profile(
        filters={
            "price_max": FilterSpec(ui=UiFilterSpec(kind="input", selector="#max")),
            "brand": FilterSpec(ui=UiFilterSpec(kind="input", selector="#brand")),
        }
    )
    applied = await FilterEngine.apply_ui(
        page, profile, SearchFilters(max_price=400, brand="AMD")
    )
    assert applied == ["price_max"]
    assert ("fill", "#max", "400") in page.calls


@pytest.mark.asyncio
async def test_apply_ui_maps_select_value_and_waits():
    page = FakePage()
    profile = _profile(
        filters={
            "condition": FilterSpec(
                ui=UiFilterSpec(
                    kind="select",
                    selector="#cond",
                    value_map={"open_box": "openbox"},
                    wait_selector="#results",
                )
            )
        }
    )
    applied = await FilterEngine.apply_ui(page, profile, SearchFilters(condition="open_box"))
    assert applied == ["condition"]
    assert page.calls == [("select", "#cond", "openbox", None)]
    assert page.waited == ["#results"]


@pytest.mark.asyncio
async def test_apply_ui_formats_checkbox_selector():
    page = FakePage()
    profile = _profile(
        filters={
            "brand": FilterSpec(
                ui=UiFilterSpec(
                    kind="checkbox",
                    selector="input[name='brand'][value='{value}']",
                    value_map={"amd": "AMD"},
                )
            )
        }
    )
    applied = await FilterEngine.apply_ui(page, profile, SearchFilters(brand="amd"))
    assert applied == ["brand"]
    assert page.calls == [("check", "input[name='brand'][value='AMD']")]


def test_post_filter_price_range_keeps_unknown_and_drops_outside():
    deals = [
        Deal(url="a", title="cheap", price_eur=50),
        Deal(url="b", title="ok", price_eur=200),
        Deal(url="c", title="unknown", price_eur=0.0),
    ]
    result = FilterEngine.post_filter(deals, SearchFilters(min_price=100, max_price=500))
    assert [deal.url for deal in result] == ["b", "c"]


def test_post_filter_condition_keeps_unknown():
    deals = [
        Deal(url="a", title="new", price_eur=1, condition="new"),
        Deal(url="b", title="used", price_eur=2, condition="used"),
        Deal(url="c", title="unknown", price_eur=3, condition="unknown"),
    ]
    result = FilterEngine.post_filter(deals, SearchFilters(condition="used"))
    assert [deal.url for deal in result] == ["b", "c"]


def test_post_filter_brand_only_when_metadata_present():
    deals = [
        Deal(url="a", title="amd", price_eur=1, metadata={"brand": "AMD"}),
        Deal(url="b", title="intel", price_eur=2, metadata={"brand": "Intel"}),
        Deal(url="c", title="unknown", price_eur=3),
    ]
    result = FilterEngine.post_filter(deals, SearchFilters(brand="amd"))
    assert [deal.url for deal in result] == ["a", "c"]


def test_post_filter_extras_only_when_metadata_present():
    deals = [
        Deal(url="a", title="match", price_eur=1, metadata={"socket": "AM5"}),
        Deal(url="b", title="mismatch", price_eur=2, metadata={"socket": "LGA1700"}),
        Deal(url="c", title="unknown", price_eur=3),
    ]
    result = FilterEngine.post_filter(deals, SearchFilters(extras={"socket": "am5"}))
    assert [deal.url for deal in result] == ["a", "c"]


def test_post_filter_sorts_with_unknown_last():
    deals = [
        Deal(url="a", title="300", price_eur=300),
        Deal(url="b", title="100", price_eur=100),
        Deal(url="c", title="unknown", price_eur=0.0),
    ]
    result = FilterEngine.post_filter(deals, SearchFilters(sort="price_asc"))
    assert [deal.url for deal in result] == ["b", "a", "c"]
