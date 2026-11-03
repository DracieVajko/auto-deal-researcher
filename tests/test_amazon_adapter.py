"""Amazon.de adapter extraction and block detection (offline)."""

import pytest

from src.searcher.adapters.amazon import AmazonAdapter


class FakeChild:
    def __init__(self, text="", href=None):
        self.text = text
        self.href = href

    async def inner_text(self):
        return self.text

    async def get_attribute(self, name):
        return self.href if name == "href" else None


class FakeCard:
    def __init__(self):
        self.mapping = {
            "h2 a span": FakeChild("Anker 18650 battery 2-pack"),
            ".a-price .a-offscreen": FakeChild("19,99 €"),
            "h2 a": FakeChild(href="/dp/B000TEST"),
        }

    async def query_selector(self, selector):
        return self.mapping.get(selector)

    async def inner_text(self):
        return "Anker 18650 battery 2-pack 19,99 € + shipping 4,99 €"


@pytest.mark.asyncio
async def test_amazon_card_becomes_a_deal_with_a_quote():
    deal = await AmazonAdapter().extract_deal(None, FakeCard())
    assert deal is not None
    assert deal.title.startswith("Anker")
    assert deal.price_eur == 19.99
    assert deal.url == "https://www.amazon.de/dp/B000TEST"
    assert deal.price_quote is not None
    assert deal.price_quote.shipping.cost_eur == 4.99


@pytest.mark.asyncio
async def test_amazon_captcha_is_a_block():
    class FakePage:
        url = "https://www.amazon.de/errors/validateCaptcha"

        async def title(self):
            return "Robot Check"

    reason = await AmazonAdapter().detect_block(FakePage())
    assert reason == "amazon captcha"


def test_amazon_search_url_encodes_the_query():
    adapter = AmazonAdapter()
    assert adapter.default_search_url("18650 battery") == (
        "https://www.amazon.de/s?k=18650+battery"
    )
