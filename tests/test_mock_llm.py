"""MockLLMClient must match the public searcher-facing LLM API."""

import pytest

from src.llm.mock_client import MockLLMClient


@pytest.mark.asyncio
async def test_mock_llm_exposes_public_query_ladder():
    client = MockLLMClient(config=None)
    query = await client.generate_search_query_async("DJI drone under 350")
    assert "DJI" in query
    assert client.keyword_query("mini pc ryzen 32gb", max_words=3) == "mini pc ryzen"
