import pytest

from src.searcher.filters import (
    CATEGORIES,
    ResolvedRequest,
    SearchFilters,
    resolve_filters,
    resolve_request,
)


class StubLLM:
    def __init__(self, payload):
        self.payload = payload

    async def extract_search_filters(self, prompt):
        return self.payload


class BrokenLLM:
    async def extract_search_filters(self, prompt):
        raise RuntimeError("429")


@pytest.mark.asyncio
async def test_valid_category_is_returned_folded():
    req = await resolve_request(
        "notebook", SearchFilters(), StubLLM({"category": " Electronics "})
    )
    assert req.category == "electronics"


@pytest.mark.asyncio
async def test_uppercase_and_accented_spellings_normalise():
    req = await resolve_request(
        "notebook", SearchFilters(), StubLLM({"category": "Hobby"})
    )
    assert req.category == "hobby"


@pytest.mark.asyncio
async def test_category_outside_the_enum_is_dropped():
    for bad in ("drone", "", None, 12):
        req = await resolve_request(
            "notebook", SearchFilters(), StubLLM({"category": bad})
        )
        assert req.category is None, bad


@pytest.mark.asyncio
async def test_category_list_is_dropped():
    req = await resolve_request(
        "notebook", SearchFilters(), StubLLM({"category": ["electronics"]})
    )
    assert req.category is None


@pytest.mark.asyncio
async def test_category_never_reaches_extras():
    req = await resolve_request(
        "notebook",
        SearchFilters(),
        StubLLM({"category": "electronics", "max_price": 300}),
    )
    assert req.filters.max_price == 300.0
    assert req.category == "electronics"
    assert "category" not in req.filters.extras


@pytest.mark.asyncio
async def test_broken_or_missing_llm_yields_no_category():
    assert (await resolve_request("pc", SearchFilters(), BrokenLLM())).category is None
    assert (await resolve_request("pc", SearchFilters(), None)).category is None


@pytest.mark.asyncio
async def test_cli_filters_still_win_over_prompt():
    req = await resolve_request("pc do 300 eur", SearchFilters(max_price=100), None)
    assert req.filters.max_price == 100.0


def test_categories_constant_matches_spec():
    assert CATEGORIES == ("electronics", "appliances", "auto", "home", "hobby", "general")


def test_categories_constant_matches_the_config_enum():
    from src.config.models import Category

    assert CATEGORIES == tuple(c.value for c in Category if c is not Category.ANY)


def test_resolved_request_is_frozen():
    import dataclasses

    req = ResolvedRequest(filters=SearchFilters(), category=None)
    with pytest.raises(dataclasses.FrozenInstanceError):
        req.category = "auto"  # type: ignore[misc]


def test_resolve_filters_wrapper_is_unchanged():
    import asyncio

    result = asyncio.run(
        resolve_filters(
            "pc",
            SearchFilters(max_price=300),
            StubLLM({"category": "electronics"}),
        )
    )
    assert isinstance(result, SearchFilters)
    assert result.max_price == 300.0


@pytest.mark.asyncio
async def test_extraction_prompt_asks_for_category(monkeypatch):
    from src.config.models import AppConfig
    from src.llm.client import LLMClient

    captured = {}

    async def fake_chat_json(self, system, user, **kwargs):
        captured["system"] = system
        return {}

    monkeypatch.setattr(LLMClient, "chat_json", fake_chat_json)
    await LLMClient(AppConfig()).extract_search_filters("notebook")
    assert (
        "category (electronics|appliances|auto|home|hobby|general)" in captured["system"]
    )
