import pytest

from src.searcher.query_language import (
    detect_language,
    language_for_country,
    localise_query,
    protected_tokens,
)


def test_country_to_language():
    assert language_for_country("SK") == "sk"
    assert language_for_country("CZ") == "cs"
    assert language_for_country("DE") == "de"
    assert language_for_country("AT") == "de"
    assert language_for_country("EU") == "en"
    assert language_for_country("") == "en"


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Predám horský bicykel, dobrý stav", "sk"),
        ("Prodám horské kolo, dobrý stav", "cs"),
        ("Verkaufe Fahrrad, guter Zustand", "de"),
        ("Selling a mountain bike, good condition", "en"),
        ("horský bicykel fahrrad", "sk"),
    ],
)
def test_detect_language(text, language):
    assert detect_language(text) == language


def test_protected_tokens_keep_models():
    assert protected_tokens("iPhone 13 128GB unter 300") == [
        "iPhone",
        "13",
        "128GB",
        "300",
    ]


@pytest.mark.asyncio
async def test_translation_is_rejected_when_a_model_disappears():
    class BadLLM:
        async def _chat(self, system, user, **kwargs):
            return "Fahrrad"

    result = await localise_query(BadLLM(), "Kellys Madman 10", "de", {})
    assert result == "Kellys Madman 10"


@pytest.mark.asyncio
async def test_translation_is_used_when_models_survive():
    class GoodLLM:
        async def _chat(self, system, user, **kwargs):
            return "Kellys Madman 10 Mountainbike"

    result = await localise_query(GoodLLM(), "Kellys Madman 10 bicykel", "de", {})
    assert result == "Kellys Madman 10 Mountainbike"


@pytest.mark.asyncio
async def test_localise_query_caches_by_query_and_target():
    calls = []

    class CountingLLM:
        async def _chat(self, system, user, **kwargs):
            calls.append((system, user))
            return "Fahrrad 26 Zoll"

    cache: dict[tuple[str, str], str] = {}
    first = await localise_query(CountingLLM(), "bicykel 26", "de", cache)
    second = await localise_query(CountingLLM(), "bicykel 26", "de", cache)
    assert first == second == "Fahrrad 26 Zoll"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_same_query_other_target_is_translated_again():
    calls = []

    class CountingLLM:
        async def _chat(self, system, user, **kwargs):
            calls.append(user)
            return "bicykl 26 palců"

    cache: dict[tuple[str, str], str] = {("bicykel 26", "de"): "Fahrrad 26"}
    result = await localise_query(CountingLLM(), "bicykel 26", "cs", cache)
    assert result == "bicykl 26 palců"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_no_llm_keeps_the_original_query():
    result = await localise_query(None, "horský bicykel", "de", {})
    assert result == "horský bicykel"


@pytest.mark.asyncio
async def test_query_already_in_target_language_skips_translation():
    calls = []

    class NoCallLLM:
        async def _chat(self, system, user, **kwargs):
            calls.append(user)
            return "someday"

    result = await localise_query(NoCallLLM(), "Verkaufe Fahrrad", "de", {})
    assert result == "Verkaufe Fahrrad"
    assert calls == []
