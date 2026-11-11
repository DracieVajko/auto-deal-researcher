"""The judge must not wipe out results when its reply is unreadable."""

import pytest

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


@pytest.mark.asyncio
async def test_python_prefilter_drops_clear_rejects_without_a_model_call(monkeypatch):
    """Accessories and over-budget listings are deterministic rejects."""
    llm = client()
    calls = []

    async def keep(system, user, max_tokens=100, **kwargs):
        calls.append(user)
        return "KEEP"

    monkeypatch.setattr(llm, "_chat", keep)
    deals = [
        Deal(url="pc", title="Mini PC 32GB", price_eur=300.0,
             condition="new", site_name="alza"),
        Deal(url="case", title="Obal na mini PC", price_eur=15.0,
             condition="new", site_name="alza"),
        Deal(url="over", title="Mini PC 64GB", price_eur=900.0,
             condition="new", site_name="alza"),
    ]

    out = await llm.judge_results("mini PC do 500 eur", deals)

    assert out["keep"] == ["pc"]
    assert calls == []


@pytest.mark.asyncio
async def test_explicit_constraints_are_decided_without_the_model(monkeypatch):
    """Budget, RAM and form factor are provable in Python."""
    llm = client()
    calls = []

    async def discard(system, user, max_tokens=100, **kwargs):
        calls.append(user)
        return "DISCARD"

    monkeypatch.setattr(llm, "_chat", discard)
    deals = [
        Deal(url="ok", title="Mini PC 32GB RAM", price_eur=450.0,
             condition="new", site_name="alza"),
        Deal(url="over", title="Mini PC 32GB RAM", price_eur=520.0,
             condition="new", site_name="alza"),
        Deal(url="low", title="Mini PC 8GB RAM", price_eur=180.0,
             condition="new", site_name="alza"),
        Deal(url="laptop", title="Laptop Lenovo 32GB RAM", price_eur=480.0,
             condition="used", site_name="bazos"),
    ]

    out = await llm.judge_results("mini PC s 32GB RAM do 500 eur", deals)

    assert out["keep"] == ["ok"]
    assert calls == []


@pytest.mark.asyncio
async def test_cheapest_rank_uses_model_storage_and_price(monkeypatch):
    """A specific cheapest request needs no model: match, then sort by price."""
    llm = client()
    calls = []

    async def boom(system, user, max_tokens=100, **kwargs):
        calls.append(1)
        return "1,2,3,4"

    monkeypatch.setattr(llm, "_chat", boom)
    deals = [
        Deal(url="r1", title="iPhone 15 Pro 256GB", price_eur=600.0,
             condition="used", site_name="bazos"),
        Deal(url="r2", title="iPhone 15 128GB", price_eur=450.0,
             condition="used", site_name="bazos"),
        Deal(url="r3", title="iPhone 15 256GB", price_eur=520.0,
             condition="used", site_name="alza"),
        Deal(url="r4", title="iPhone 14 128GB", price_eur=380.0,
             condition="used", site_name="bazos"),
    ]

    ranked = await llm.rank_results("najlacnejší iPhone 15 128GB", deals, top_n=4)

    assert ranked[0].url == "r2"
    assert {d.url for d in ranked} == {"r1", "r2", "r3", "r4"}
    assert calls == []


@pytest.mark.asyncio
async def test_ranking_keeps_every_deal_the_model_forgot(monkeypatch):
    """A short ranking reply must not silently drop listings."""
    llm = client()

    async def partial(system, user, max_tokens=100, **kwargs):
        return "2,1"

    monkeypatch.setattr(llm, "_chat", partial)
    deals = [make_deal(i) for i in range(3)]
    ranked = await llm.rank_results("mini pc", deals, top_n=3)

    assert {d.url for d in ranked} == {"u0", "u1", "u2"}
    assert [d.url for d in ranked[:2]] == ["u1", "u0"]


@pytest.mark.asyncio
async def test_ranking_honours_small_top_n(monkeypatch):
    llm = client()

    async def partial(system, user, max_tokens=100, **kwargs):
        return "2,1"

    monkeypatch.setattr(llm, "_chat", partial)
    deals = [make_deal(i) for i in range(3)]
    ranked = await llm.rank_results("mini pc", deals, top_n=2)

    assert [d.url for d in ranked] == ["u1", "u0"]