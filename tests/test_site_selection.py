"""Location-aware site selection (deterministic ranking + LLM narrowing)."""

import pytest

from src.searcher.site_selection import (
    SiteCandidate,
    SiteSelector,
    market_distance,
    rank_by_location,
)


def _candidate(site_id, country, categories=("auto",), conditions=("used", "new")):
    return SiteCandidate(
        id=site_id,
        name=site_id.upper(),
        country=country,
        currency="EUR",
        categories=categories,
        conditions=conditions,
    )


def test_market_distance_same_country():
    assert market_distance("SK", "SK") == 0


def test_market_distance_neighbour():
    assert market_distance("CZ", "SK") == 1
    assert market_distance("DE", "SK") == 1


def test_market_distance_far_market():
    assert market_distance("US", "SK") == 2
    assert market_distance("", "SK") == 2


def test_rank_by_location_puts_local_market_first():
    candidates = [
        _candidate("shop_cz", "CZ"),
        _candidate("autobazar_sk", "SK"),
        _candidate("mobile_de", "DE"),
    ]
    ranked = rank_by_location(candidates, "SK")
    assert [c.id for c in ranked] == ["autobazar_sk", "mobile_de", "shop_cz"]


def test_rank_by_location_is_stable_within_a_market():
    candidates = [
        _candidate("b_shop", "SK"),
        _candidate("a_shop", "SK"),
    ]
    ranked = rank_by_location(candidates, "SK")
    assert [c.id for c in ranked] == ["a_shop", "b_shop"]


def test_candidate_carries_checks_category_and_condition():
    candidate = _candidate("car_portal", "CZ", ("auto",), ("used",))
    assert candidate.carries("auto", "used")
    assert candidate.carries("any", "any")
    assert not candidate.carries("electronics", "used")
    assert not candidate.carries("auto", "refurbished")


@pytest.mark.asyncio
async def test_select_falls_back_to_ranking_without_llm():
    candidates = [_candidate("a", "SK"), _candidate("b", "CZ")]
    selected, reasoning = await SiteSelector().select(candidates, "auto", "SK", max_sites=1)
    assert [c.id for c in selected] == ["a"]
    assert reasoning


@pytest.mark.asyncio
async def test_select_respects_max_sites():
    candidates = [_candidate(f"s{i}", "SK") for i in range(10)]
    selected, _ = await SiteSelector().select(candidates, "auto", "SK", max_sites=3)
    assert len(selected) == 3


@pytest.mark.asyncio
async def test_select_uses_llm_pick():
    class FakeLLM:
        async def chat_json(self, system, user, max_tokens=400):
            return {"selected": ["b", "a"], "reasoning": "b is cheaper overall"}

    candidates = [_candidate("a", "SK"), _candidate("b", "CZ")]
    selected, reasoning = await SiteSelector(FakeLLM()).select(candidates, "auto", "SK")
    assert [c.id for c in selected] == ["b", "a"]
    assert reasoning == "b is cheaper overall"


@pytest.mark.asyncio
async def test_llm_cannot_introduce_unknown_sites():
    class FakeLLM:
        async def chat_json(self, system, user, max_tokens=400):
            return {"selected": ["a", "not_a_real_site"], "reasoning": "x"}

    candidates = [_candidate("a", "SK")]
    selected, _ = await SiteSelector(FakeLLM()).select(candidates, "auto", "SK")
    assert [c.id for c in selected] == ["a"]


@pytest.mark.asyncio
async def test_select_without_cap_returns_every_candidate():
    candidates = [_candidate(f"s{i}", "SK") for i in range(12)]
    selected, _ = await SiteSelector().select(candidates, "battery", "SK", max_sites=0)
    assert len(selected) == 12


@pytest.mark.asyncio
async def test_llm_may_select_every_candidate():
    class FakeLLM:
        async def chat_json(self, system, user, max_tokens=400):
            return {"selected": ["a", "b", "c"], "reasoning": "all match"}

    candidates = [_candidate("a", "SK"), _candidate("b", "SK"), _candidate("c", "SK")]
    selected, _ = await SiteSelector(FakeLLM()).select(candidates, "battery", "SK")
    assert [c.id for c in selected] == ["a", "b", "c"]


@pytest.mark.asyncio
async def test_valid_empty_selection_means_no_shops():
    class FakeLLM:
        async def chat_json(self, system, user, max_tokens=400):
            return {"selected": [], "reasoning": "no suitable shop"}

    candidates = [_candidate("a", "SK"), _candidate("b", "CZ")]
    selected, reasoning = await SiteSelector(FakeLLM()).select(candidates, "battery", "SK")
    assert selected == []
    assert reasoning == "no suitable shop"


@pytest.mark.asyncio
async def test_malformed_selection_falls_back_to_all():
    class FakeLLM:
        async def chat_json(self, system, user, max_tokens=400):
            return {"selected": "not-a-list", "reasoning": ""}

    candidates = [_candidate("a", "SK"), _candidate("b", "CZ")]
    selected, reasoning = await SiteSelector(FakeLLM()).select(candidates, "battery", "SK")
    assert [c.id for c in selected] == ["a", "b"]
    assert "Ranked by market distance" in reasoning


@pytest.mark.asyncio
async def test_prompt_includes_specialties_and_notes():
    captured = {}

    class FakeLLM:
        async def chat_json(self, system, user, max_tokens=400):
            captured["system"] = system
            captured["user"] = user
            return {"selected": ["a"], "reasoning": "ok"}

    candidate = SiteCandidate(
        id="a", name="A", country="SK", currency="EUR",
        categories=("electronics",), conditions=("new",),
        notes="battery specialist", specialties=("battery", "18650"),
    )
    other = SiteCandidate(
        id="b", name="B", country="CZ", currency="EUR",
        categories=("electronics",), conditions=("new",),
    )
    await SiteSelector(FakeLLM()).select([candidate, other], "18650", "SK")
    assert "battery specialist" in captured["user"]
    assert "18650" in captured["user"]
    assert "at most 6" not in captured["system"].lower()


@pytest.mark.asyncio
async def test_llm_failure_falls_back_to_ranking():
    class BrokenLLM:
        async def chat_json(self, system, user, max_tokens=400):
            raise RuntimeError("model down")  # noqa: TRY003 - simulating a dead LLM

    candidates = [_candidate("a", "SK"), _candidate("b", "CZ")]
    selected, _ = await SiteSelector(BrokenLLM()).select(candidates, "auto", "SK")
    assert [c.id for c in selected] == ["a", "b"]


@pytest.mark.asyncio
async def test_select_with_no_candidates():
    selected, reasoning = await SiteSelector().select([], "auto", "SK")
    assert selected == []
    assert reasoning
