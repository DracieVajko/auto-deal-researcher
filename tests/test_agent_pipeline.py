"""Tests for the price and synthesis stages of the Diamond pipeline."""

import pytest

from src.agents.price.price_hunter import PriceHunterAgent
from src.agents.synthesis.recommendation import RecommendationAgent


def _deal(url, title, price, condition="used", site="bazos", shipping=0.0, **meta):
    return {
        "url": url, "title": title, "price_eur": price, "condition": condition,
        "category": "electronics", "site_name": site,
        "shipping_cost_eur": shipping, "metadata": meta,
    }


@pytest.mark.asyncio
async def test_price_hunter_sorts_by_total_cost():
    agent = PriceHunterAgent()
    deals = [
        _deal("u1", "cheap", 50.0, shipping=20.0),
        _deal("u2", "dear", 60.0, shipping=0.0),
    ]
    out = await agent.run({"deals": deals})
    enriched = out["enriched_deals"]
    # Sorting is by TOTAL cost, so the 50 + 20 shipping deal ranks last.
    assert enriched[0]["title"] == "dear"
    assert enriched[0]["total_cost_eur"] == 60.0
    assert enriched[1]["title"] == "cheap"
    assert enriched[1]["total_cost_eur"] == 70.0
    assert out["best_overall"]["title"] == "dear"


@pytest.mark.asyncio
async def test_price_hunter_handles_empty():
    out = await PriceHunterAgent().run({"deals": []})
    assert out["enriched_deals"] == []
    assert out["best_overall"] is None


@pytest.mark.asyncio
async def test_price_hunter_builds_comparison_table():
    agent = PriceHunterAgent()
    out = await agent.run({"deals": [_deal("u1", "DJI Mini", 250.0)]})
    table = out["price_comparison"]
    assert table.startswith("| Site |")
    assert "DJI Mini" in table


@pytest.mark.asyncio
async def test_recommendation_picks_best_and_scores_confidence():
    agent = RecommendationAgent()
    all_results = {
        "price": {
            "enriched_deals": [
                _deal("u1", "DJI Mini 3 Pro", 250.0, condition="new"),
                _deal("u2", "DJI Air 2S", 520.0),
            ],
            "best_overall": _deal("u1", "DJI Mini 3 Pro", 250.0, condition="new"),
            "price_comparison": "| table |",
        },
        "expertise": {
            "domain_expert": {"top_recommendation": {"expert_analysis": "great value"}},
            "latest_tech": {"recommendation": "wait for Mini 4"},
        },
    }
    out = await agent.run({"prompt": "dji drone", "all_results": all_results})

    rec = out["final_recommendation"]
    assert rec["status"] == "success"
    assert rec["recommendation"]["title"] == "DJI Mini 3 Pro"
    assert rec["recommendation"]["price_eur"] == 250.0
    assert out["confidence"] > 0.3
    assert rec["timing_advice"] == "wait for Mini 4"
    assert rec["expert_analysis"] == "great value"
    assert len(rec["alternatives"]) == 1


@pytest.mark.asyncio
async def test_recommendation_reports_no_deals():
    out = await RecommendationAgent().run({"prompt": "x", "all_results": {"price": {}}})
    assert out["final_recommendation"]["status"] == "no_deals_found"
    assert out["confidence"] == 0.3


@pytest.mark.asyncio
async def test_recommendation_confidence_rises_with_quality():
    agent = RecommendationAgent()
    cheap_new = agent._calculate_confidence({"price_eur": 200.0, "condition": "new"})
    dear_used = agent._calculate_confidence({"price_eur": 900.0, "condition": "used"})
    assert cheap_new > dear_used
    assert 0.3 <= dear_used <= 1.0


@pytest.mark.asyncio
async def test_recommendation_reasoning_reflects_price_band():
    agent = RecommendationAgent()
    assert "Excellent price" in agent._build_reasoning({"price_eur": 200.0})
    assert "Fair price" in agent._build_reasoning({"price_eur": 400.0})
    assert "Premium price" in agent._build_reasoning({"price_eur": 1200.0})