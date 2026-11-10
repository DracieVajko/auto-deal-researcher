"""LLM fallback for ambiguous price cards, with evidence validation."""

import pytest

from src.llm.client import LLMClient
from src.searcher.pricing import validate_price_classification


def _client():
    cfg = type(
        "C",
        (),
        {
            "llm": type(
                "L",
                (),
                {
                    "local": [],
                    "api_fallback": [],
                    "openrouter": None,
                    "gemini": None,
                    "mistral": None,
                },
            )()
        },
    )()
    return LLMClient(cfg)


@pytest.mark.asyncio
async def test_classify_price_quotes_parses_batch(monkeypatch):
    client = _client()
    calls = []

    async def fake_chat(system, user, max_tokens=100):
        calls.append(user)
        return (
            '{"quotes": [{"id": "L0", "kind": "regular", '
            '"shipping_cost_eur": 4.99, "bundle_min_quantity": 1, '
            '"warnings": [], "confidence": 0.9, '
            '"evidence": ["289 €"]}]}'
        )

    monkeypatch.setattr(client, "_chat", fake_chat)
    items = [
        {
            "id": "L0",
            "text": "PocketBook 634Verse Pro 289 €",
            "listed_price_eur": 289.0,
            "currency": "EUR",
        }
    ]
    result = await client.classify_price_quotes(items)
    assert result["L0"]["kind"] == "regular"
    assert result["L0"]["shipping_cost_eur"] == 4.99

    again = await client.classify_price_quotes(items)
    assert again["L0"]["kind"] == "regular"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_clear_cards_skip_the_model(monkeypatch):
    """Deterministic signals must be used before spending a model call."""
    client = _client()
    calls = []

    async def fake_chat(system, user, max_tokens=100):
        calls.append(user)
        return "{}"

    monkeypatch.setattr(client, "_chat", fake_chat)
    items = [
        {"id": "F", "text": "Doprava zdarma", "listed_price_eur": 10.0, "currency": "EUR"},
        {"id": "C", "text": "s kódom SALE20", "listed_price_eur": 10.0, "currency": "EUR"},
        {"id": "B", "text": "2 ks za 19,90 €", "listed_price_eur": 19.9, "currency": "EUR"},
        {"id": "R", "text": "od 259 €", "listed_price_eur": 259.0, "currency": "EUR"},
        {"id": "P", "text": "+ 9,90 € doprava", "listed_price_eur": 289.0, "currency": "EUR"},
    ]
    result = await client.classify_price_quotes(items)

    assert result["F"]["shipping_is_free"] is True
    assert result["C"]["kind"] == "coupon"
    assert result["B"]["bundle_min_quantity"] == 2
    assert result["R"]["kind"] == "range"
    assert result["R"]["price_from"] is True
    assert result["P"]["shipping_cost_eur"] == 9.9
    assert calls == []


def test_hallucinated_evidence_is_rejected():
    payload = {
        "kind": "account_gated",
        "shipping_cost_eur": 4.99,
        "evidence": ["not in the card"],
    }
    assert validate_price_classification(payload, "New user price 9.99") is None


def test_evidence_substring_is_accepted():
    payload = {
        "kind": "account_gated",
        "shipping_cost_eur": None,
        "evidence": ["New user price"],
    }
    result = validate_price_classification(payload, "New user price 9.99")
    assert result is not None
    assert result["kind"] == "account_gated"


def test_out_of_range_number_is_rejected():
    payload = {
        "kind": "regular",
        "shipping_cost_eur": 1_000_001,
        "evidence": ["price"],
    }
    assert validate_price_classification(payload, "price 9.99") is None
