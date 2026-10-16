"""eBay Browse API adapter tests (mocked HTTP, no network)."""

import pytest

from src.searcher.adapters import get_adapter
from src.searcher.adapters.base import SiteBlockedError
from src.searcher.adapters.ebay_api import EbayApiAdapter

SAMPLE = {
    "itemSummaries": [
        {
            "itemId": "v1|284719302163|0",
            "title": "DJI Mini 3 Pro (Drone Only)",
            "itemWebUrl": "https://www.ebay.de/itm/284719302163",
            "price": {"value": 249.0, "currency": "EUR"},
            "condition": "LIKE_NEW",
            "seller": {"username": "seller_x", "feedbackScore": 1200, "feedbackPercentage": "98.7"},
            "itemLocation": {"country": "DE"},
            "shippingOptions": [{"shippingCost": {"value": 4.99, "currency": "EUR"}}],
        },
        {
            "itemId": "v2|1|0",
            "title": "DJI Air 2S Refurbished",
            "itemWebUrl": "https://www.ebay.de/itm/999",
            "price": {"value": 399.0, "currency": "EUR"},
            "condition": "SELLER_REFURBISHED",
            "seller": {"username": "seller_y"},
        },
    ],
    "total": 2,
}


def test_registered_as_ebay_api():
    assert get_adapter("ebay_api") is EbayApiAdapter


def test_api_adapter_declares_no_css_selectors():
    a = EbayApiAdapter()
    assert a.item_selector == ""
    assert a.results_selector == ""


def test_to_deal_maps_all_fields():
    deal = EbayApiAdapter.to_deal(SAMPLE["itemSummaries"][0])
    assert deal.url == "https://www.ebay.de/itm/284719302163"
    assert deal.title == "DJI Mini 3 Pro (Drone Only)"
    assert deal.price_eur == 249.0
    assert deal.currency == "EUR"
    assert deal.condition == "new"
    assert deal.site_name == "ebay_api"
    assert deal.metadata["seller"] == "seller_x"
    assert deal.metadata["shipping"] == 4.99
    assert deal.metadata["item_location"] == "DE"


@pytest.mark.parametrize(
    ("condition_id", "expected"),
    [
        ("NEW", "new"),
        ("LIKE_NEW", "new"),
        ("CERTIFIED_REFURBISHED", "refurbished"),
        ("EXCELLENT_REFURBISHED", "refurbished"),
        ("USED_EXCELLENT", "used"),
        ("FOR_PARTS_OR_NOT_WORKING", "used"),
        ("SOMETHING_NEW", "used"),  # unknown ids fall back
    ],
)
def test_condition_mapping(condition_id, expected):
    item = dict(SAMPLE["itemSummaries"][0], condition=condition_id)
    assert EbayApiAdapter.to_deal(item).condition == expected


def test_to_deal_rejects_incomplete_items():
    assert EbayApiAdapter.to_deal({"title": "x"}) is None
    assert EbayApiAdapter.to_deal({"title": "x", "itemWebUrl": "u", "price": {}}) is None


def test_unconfigured_raises_clear_error(monkeypatch):
    monkeypatch.delenv("EBAY_APP_ID", raising=False)
    monkeypatch.delenv("EBAY_CERT_ID", raising=False)
    adapter = EbayApiAdapter()
    assert adapter.configured is False
    with pytest.raises(SiteBlockedError, match="EBAY_APP_ID"):
        adapter._access_token()


@pytest.mark.asyncio
async def test_search_maps_items(monkeypatch):
    import src.searcher.adapters.ebay_api as mod

    adapter = EbayApiAdapter()
    adapter._token = "tok"
    adapter._token_expires_at = 9e12  # valid cached token

    seen = {}

    def fake_get(url, params=None, headers=None, timeout=None):
        seen["url"] = url
        seen["headers"] = headers
        seen["params"] = params

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return SAMPLE

        return R()

    monkeypatch.setattr(mod.requests, "get", fake_get)
    deals = await adapter.search(None, "dji drone", max_results=10)

    assert len(deals) == 2
    assert seen["url"].endswith("/buy/browse/v1/item_summary/search")
    assert seen["headers"]["X-EBAY-C-MARKETPLACE-ID"]
    assert seen["headers"]["Authorization"] == "Bearer tok"
    assert seen["params"]["q"] == "dji drone"


@pytest.mark.asyncio
async def test_search_drops_token_on_401(monkeypatch):
    import src.searcher.adapters.ebay_api as mod

    adapter = EbayApiAdapter()
    adapter._token = "stale"
    adapter._token_expires_at = 9e12

    def fake_get(url, params=None, headers=None, timeout=None):
        class R:
            status_code = 401

            def raise_for_status(self):
                raise AssertionError("should not reach raise_for_status")

            def json(self):
                return {}

        return R()

    monkeypatch.setattr(mod.requests, "get", fake_get)
    with pytest.raises(SiteBlockedError, match="401"):
        await adapter.search(None, "x", max_results=1)
    assert adapter._token == ""