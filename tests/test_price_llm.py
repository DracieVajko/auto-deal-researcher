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

    async def fake_chat(system, user, max_tokens=100):
        return (
            '{"quotes": [{"id": "L1", "kind": "account_gated", '
            '"shipping_cost_eur": 4.99, "bundle_min_quantity": 1, '
            '"warnings": ["new user"], "confidence": 0.9, '
            '"evidence": ["New user price"]}]}'
        )

    monkeypatch.setattr(client, "_chat", fake_chat)
    result = await client.classify_price_quotes(
        [
            {
                "id": "L1",
                "text": "New user price 9.99",
                "listed_price_eur": 9.99,
                "currency": "EUR",
            }
        ]
    )
    assert result["L1"]["kind"] == "account_gated"
    assert result["L1"]["shipping_cost_eur"] == 4.99


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
