"""Diamond Search agent tests with a mocked LLMClient (no network)."""

import pytest

from src.agents.coordinator import CoordinatorAgent
from src.agents.expertise.domain_expert import DomainExpertAgent
from src.agents.llm_support import as_list, extract_json
from src.agents.research.query_expansion import QueryExpansionAgent
from src.agents.research.site_selection import SiteSelectionAgent


class FakeLLM:
    """Stands in for LLMClient: records calls, returns canned replies."""

    def __init__(self, reply=None, raises=False):
        self.reply = reply
        self.raises = raises
        self.calls = []

    async def chat(self, system, user, max_tokens=400):
        self.calls.append((system, user, max_tokens))
        if self.raises:
            raise RuntimeError("llm down")  # noqa: TRY003 - simulating a dead LLM
        return self.reply


# --- helpers ---------------------------------------------------------------
def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_from_fence():
    assert extract_json('```json\n{"a": 2}\n```') == {"a": 2}


def test_extract_json_from_prose():
    assert extract_json('Sure! Here you go: [{"q": "x"}] hope that helps') == [{"q": "x"}]


def test_extract_json_garbage_returns_none():
    assert extract_json("no json at all") is None


def test_as_list_cleans_and_dedupes():
    assert as_list(['- "dji mini"', 'dji mini', 'dji air', {"query": "mavic"}], 10) == [
        "dji mini", "dji air", "mavic",
    ]


# --- query expansion -------------------------------------------------------
@pytest.mark.asyncio
async def test_query_expansion_uses_llm_when_available():
    llm = FakeLLM(reply='["dji mini 3 pro", "dji air 2s", "dji mavic 3"]')
    out = await QueryExpansionAgent(llm).run({"prompt": "dji drone under 350"})

    assert out["source"] == "llm"
    assert out["expanded_queries"] == ["dji mini 3 pro", "dji air 2s", "dji mavic 3"]
    assert llm.calls, "LLM should have been called"


@pytest.mark.asyncio
async def test_query_expansion_falls_back_when_llm_absent():
    out = await QueryExpansionAgent(None).run({"prompt": "dji drone under 350"})
    assert out["source"] == "fallback"
    assert out["query_count"] > 0


@pytest.mark.asyncio
async def test_query_expansion_survives_llm_exception():
    out = await QueryExpansionAgent(FakeLLM(raises=True)).run({"prompt": "dji drone"})
    assert out["query_count"] > 0
    assert out["source"] == "llm"  # llm was wired but failed; heuristic filled in


@pytest.mark.asyncio
async def test_query_expansion_respects_limit():
    llm = FakeLLM(reply='["a1","a2","a3","a4","a5","a6"]')
    out = await QueryExpansionAgent(llm).run({"prompt": "x", "max_queries": 2})
    assert len(out["expanded_queries"]) == 2


# --- site selection --------------------------------------------------------
@pytest.mark.asyncio
async def test_site_selection_filters_by_condition():
    """Only sites advertising 'refurbished' survive."""
    out = await SiteSelectionAgent().run(
        {"prompt": "x", "condition": "refurbished", "category": "electronics"}
    )
    assert set(out["selected_sites"]) == {
        "backmarket",
        "ebay",
        "heureka",
        "idealo",
        "amazon_de",
        "aukro",
    }
    assert "alza" not in out["selected_sites"]
    assert "reasoning" in out


@pytest.mark.asyncio
async def test_site_selection_reads_the_registry():
    """The agent must know every registered site, not a hardcoded table."""
    caps = SiteSelectionAgent.capabilities()
    assert "autobazar_sk" in caps
    assert "aukro" in caps
    assert caps["autobazar_sk"]["country"] == "SK"
    assert caps["aukro"]["currency"] == "CZK"


# --- domain expert ---------------------------------------------------------
@pytest.mark.asyncio
async def test_domain_expert_scores_vary_by_price_and_condition():
    agent = DomainExpertAgent()
    cheap_new = {"title": "DJI Mini", "price_eur": 200.0, "condition": "new", "metadata": {"benchmark": 400}}
    dear_used = {"title": "DJI Air", "price_eur": 600.0, "condition": "used", "metadata": {"benchmark": 400}}

    cheap_score = await agent._score_deal(cheap_new)
    dear_score = await agent._score_deal(dear_used)

    assert cheap_score > dear_score, "cheaper/better-condition must score higher"
    assert cheap_score != dear_score, "scores must not be constant"


@pytest.mark.asyncio
async def test_domain_expert_uses_market_intel_benchmark():
    agent = DomainExpertAgent()
    deals = [{"title": "DJI drone", "price_eur": 300.0, "condition": "new"}]
    research = {"market_intel": {"price_benchmarks": {"drone": {"mid": 500}}}}
    out = await agent.run({"prompt": "x", "deals": deals, "research": research})

    evaluated = out["evaluated_deals"]
    assert len(evaluated) == 1
    assert evaluated[0]["metadata"]["benchmark"] == 500
    assert "expert_score" in evaluated[0]


@pytest.mark.asyncio
async def test_domain_expert_sorts_descending():
    agent = DomainExpertAgent()
    deals = [
        {"title": "a", "price_eur": 900.0, "condition": "used", "metadata": {"benchmark": 400}},
        {"title": "b", "price_eur": 100.0, "condition": "new", "metadata": {"benchmark": 400}},
    ]
    out = await agent.run({"prompt": "x", "deals": deals})
    scores = [d["expert_score"] for d in out["evaluated_deals"]]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.asyncio
async def test_domain_expert_handles_empty():
    out = await DomainExpertAgent().run({"prompt": "x", "deals": []})
    assert out["evaluated_deals"] == []


# --- coordinator -----------------------------------------------------------
def _agents(llm=None):
    """A full agent set matching what CoordinatorAgent expects."""
    from src.agents.expertise.latest_tech_tracker import LatestTechTrackerAgent
    from src.agents.price.price_hunter import PriceHunterAgent
    from src.agents.research.market_intel import MarketIntelAgent
    from src.agents.synthesis.recommendation import RecommendationAgent

    return [
        QueryExpansionAgent(llm),
        SiteSelectionAgent(),
        MarketIntelAgent(),
        DomainExpertAgent(),
        LatestTechTrackerAgent(),
        PriceHunterAgent(),
        RecommendationAgent(),
    ]


@pytest.mark.asyncio
async def test_coordinator_forwards_deals_to_expertise():
    coord = CoordinatorAgent(_agents(), {"llm_call_budget": 50, "llm_token_budget": 100000})
    deals = [{"url": "u1", "title": "DJI", "price_eur": 100.0, "condition": "new",
              "category": "electronics", "site_name": "bazos", "metadata": {}}]
    research = await coord._run_research_layer("dji drone", "run_x")
    assert "query_expansion" in research

    expertise = await coord._run_expertise_layer("dji drone", research, "run_x", deals)
    evaluated = expertise["domain_expert"]["evaluated_deals"]
    assert len(evaluated) == 1
    assert evaluated[0]["expert_score"] > 0


@pytest.mark.asyncio
async def test_coordinator_respects_call_budget():
    coord = CoordinatorAgent(_agents(), {"llm_call_budget": 0, "llm_token_budget": 100000})
    out = await coord._run_research_layer("x", "run_x")
    assert "error" in out