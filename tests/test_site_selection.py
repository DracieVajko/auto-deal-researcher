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
        _candidate("garaz_cz", "CZ"),
        _candidate("autobazar_sk", "SK"),
        _candidate("mobile_de", "DE"),
    ]
    ranked = rank_by_location(candidates, "SK")
    assert [c.id for c in ranked] == ["autobazar_sk", "garaz_cz", "mobile_de"]


def test_rank_by_location_is_stable_within_a_market():
    candidates = [
        _candidate("b_shop", "SK"),
        _candidate("a_shop", "SK"),
    ]
    ranked = rank_by_location(candidates, "SK")
    assert [c.id for c in ranked] == ["a_shop", "b_shop"]


def test_candidate_carries_checks_category_and_condition():
    candidate = _candidate("sauto", "CZ", ("auto",), ("used",))
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
async def test_llm_garbage_falls_back_to_ranking():
    class FakeLLM:
        async def chat_json(self, system, user, max_tokens=400):
            return {"selected": [], "reasoning": ""}

    candidates = [_candidate("a", "SK"), _candidate("b", "CZ")]
    selected, reasoning = await SiteSelector(FakeLLM()).select(candidates, "auto", "SK")
    assert [c.id for c in selected] == ["a", "b"]
    assert "Ranked by market distance" in reasoning


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
