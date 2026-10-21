"""The judge must not wipe out results when its reply is unreadable."""

import pytest

import src.llm.client as mod
from src.llm.client import LLMClient
from src.searcher.adapters.base import Deal


def make_deal(i):
    return Deal(url=f"u{i}", title=f"Deal {i}", price_eur=100.0 + i,
                condition="new", site_name="alza")


def client():
    cfg = type("C", (), {"llm": type("L", (), {"local": [], "api_fallback": [],
                                                "openrouter": None, "gemini": None,
                                                "mistral": None})()})()
    return LLMClient(cfg)


@pytest.mark.asyncio
async def test_unreadable_reply_keeps_all_deals(monkeypatch):
    """The flake that made whole runs return zero deals."""
    llm = client()

    async def prose(system, user, max_tokens=100, **kwargs):
        return "Sure! Based on your criteria these all look fine to me honestly."

    monkeypatch.setattr(llm, "_chat", prose)
    deals = [make_deal(i) for i in range(5)]
    out = await llm.judge_results("dji drone", deals)

    assert sorted(out["keep"]) == sorted(d.url for d in deals)


@pytest.mark.asyncio
async def test_real_discard_verdicts_are_respected(monkeypatch):
    llm = client()

    async def verdicts(system, user, max_tokens=100, **kwargs):
        return "KEEP\nDISCARD\nDISCARD\nKEEP\nDISCARD"

    monkeypatch.setattr(llm, "_chat", verdicts)
    deals = [make_deal(i) for i in range(5)]
    out = await llm.judge_results("dji drone", deals)
    assert out["keep"] == ["u0", "u3"]


@pytest.mark.asyncio
async def test_all_discard_is_respected(monkeypatch):
    """If the model genuinely says no, honour it — do not second-guess."""
    llm = client()

    async def verdicts(system, user, max_tokens=100, **kwargs):
        return "DISCARD\nDISCARD\nDISCARD"

    monkeypatch.setattr(llm, "_chat", verdicts)
    deals = [make_deal(i) for i in range(3)]
    out = await llm.judge_results("dji drone", deals)
    assert out["keep"] == []


@pytest.mark.asyncio
async def test_verdicts_found_inside_prose_still_applied(monkeypatch):
    """A reply with real verdicts embedded in prose is parseable."""
    llm = client()

    async def mixed(system, user, max_tokens=100, **kwargs):
        return "Let me review:\n1. KEEP this one\n2. DISCARD overpriced\n3. KEEP cheap"

    monkeypatch.setattr(llm, "_chat", mixed)
    deals = [make_deal(i) for i in range(3)]
    out = await llm.judge_results("dji drone", deals)
    assert out["keep"] == ["u0", "u2"]


@pytest.mark.asyncio
async def test_empty_deals_short_circuits(monkeypatch):
    llm = client()
    assert await llm.judge_results("x", []) == {"keep": []}