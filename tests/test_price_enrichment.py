"""LLM enrichment pass for ambiguous price cards."""

import pytest

from src.searcher.adapters.base import Deal
from src.searcher.playwright_searcher import PlaywrightSearcher
from src.searcher.pricing import PriceKind, ShippingQuote, build_price_quote


@pytest.mark.asyncio
async def test_ambiguous_quote_is_replaced_by_validated_llm_result():
    deal = Deal(
        url="https://x/1",
        title="New user price",
        price_eur=9.99,
        metadata={"card_text": "New user price 9.99"},
        price_quote=build_price_quote(
            9.99,
            kind=PriceKind.REGULAR,
            shipping=ShippingQuote(),
            source="regex",
            confidence=0.0,
        ),
    )

    class FakeLLM:
        async def classify_price_quotes(self, items):
            return {
                "L0": {
                    "kind": "account_gated",
                    "shipping_cost_eur": None,
                    "evidence": ["New user price"],
                    "confidence": 0.9,
                }
            }

    searcher = object.__new__(PlaywrightSearcher)
    searcher.llm = FakeLLM()
    await searcher._enrich_price_quotes([deal])
    assert deal.price_quote.kind == PriceKind.ACCOUNT_GATED
    assert deal.price_quote.source == "llm"
    assert deal.price_quote.confidence == 0.9


@pytest.mark.asyncio
async def test_plain_card_without_signals_is_not_sent_twice():
    """A quote that already has a signal is not ambiguous."""
    deal = Deal(
        url="https://x/1",
        title="X",
        price_eur=100.0,
        metadata={"card_text": "Doprava zdarma"},
        price_quote=build_price_quote(
            100.0,
            shipping=ShippingQuote(cost_eur=0.0, is_free=True),
            source="regex",
            confidence=1.0,
        ),
    )

    calls = []

    class FakeLLM:
        async def classify_price_quotes(self, items):
            calls.append(items)
            return {}

    searcher = object.__new__(PlaywrightSearcher)
    searcher.llm = FakeLLM()
    await searcher._enrich_price_quotes([deal])
    assert calls == []


@pytest.mark.asyncio
async def test_llm_cannot_lower_trust_or_invent_shipping():
    deal = Deal(
        url="https://x/1",
        title="X",
        price_eur=10.0,
        metadata={"card_text": "Notebook 10 €"},
        price_quote=build_price_quote(
            10.0,
            shipping=ShippingQuote(),
            source="regex",
            confidence=0.0,
        ),
    )

    class FakeLLM:
        async def classify_price_quotes(self, items):
            return {
                "L0": {
                    "kind": "regular",
                    "shipping_cost_eur": None,
                    "confidence": 0.9,
                    "warnings": [],
                    "evidence": [],
                }
            }

    searcher = object.__new__(PlaywrightSearcher)
    searcher.llm = FakeLLM()
    await searcher._enrich_price_quotes([deal])
    # The model contributed no field, so the regex quote and its trust stand.
    assert deal.price_quote.source == "regex"
    assert deal.price_quote.trust == 0.9


@pytest.mark.asyncio
async def test_llm_failure_keeps_deterministic_quote():
    deal = Deal(
        url="https://x/1",
        title="X",
        price_eur=10.0,
        metadata={"card_text": "Notebook 10 €"},
        price_quote=build_price_quote(10.0, source="regex", confidence=0.0),
    )

    class FakeLLM:
        async def classify_price_quotes(self, items):
            raise TimeoutError

    searcher = object.__new__(PlaywrightSearcher)
    searcher.llm = FakeLLM()
    await searcher._enrich_price_quotes([deal])
    assert deal.price_quote.kind == PriceKind.REGULAR
    assert deal.price_quote.source == "regex"
