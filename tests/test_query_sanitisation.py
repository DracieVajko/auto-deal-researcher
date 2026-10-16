"""LLM replies must become one usable search query, not prose or an OR-chain."""

import pytest

from src.llm.client import LLMClient

clean = LLMClient._clean_query


def test_prefers_first_quoted_phrase():
    raw = 'Here is a refined query: *"DJI drone under $350" OR "DJI mini" OR "Mavic"'
    assert clean(raw) == "DJI drone under $350"


def test_ors_chain_becomes_single_query():
    """The exact failure mode: a 300+ char URL matching nothing."""
    raw = ('"DJI drone under €350" OR "DJI quadcopter under €350" OR "DJI mini drone under €350" '
           'OR "DJI budget drone under €350" OR "DJI Mavic Mini under €350"')
    out = clean(raw)
    assert out == "DJI drone under €350"
    assert len(out) < 60


def test_strips_preamble_and_markdown():
    assert clean("Sure! Here is your query:\n**DJI Neo 2 under 350**") == "DJI Neo 2 under 350"


def test_keeps_only_first_sentence():
    assert clean("DJI drone under 350. You might also like the Mini 3 Pro.") \
        == "DJI drone under 350"


def test_caps_length():
    out = clean(" ".join(["word"] + ["extra"] * 40))
    assert len(out.split()) <= 12


def test_empty_returns_fallback():
    assert clean("", fallback="dji drone") == "dji drone"
    assert clean("   ", fallback="dji drone") == "dji drone"
    assert clean("***", fallback="dji drone") == "dji drone"


def test_plain_query_passes_through():
    assert clean("DJI Neo 2") == "DJI Neo 2"


def test_never_contains_newlines_or_markers():
    out = clean("Here:\n**A**\n**B**")
    assert "\n" not in out
    assert "*" not in out


@pytest.mark.asyncio
async def test_generate_query_is_sanitised(monkeypatch):
    cfg = type("C", (), {"llm": type("L", (), {"local": [], "api_fallback": [],
                                                "openrouter": None, "gemini": None,
                                                "mistral": None})()})()
    llm = LLMClient(cfg)

    async def fake_chat(system, user, max_tokens=100):
        return 'Here is a query: *"DJI Neo 2 under 350" OR "DJI Mini"'

    monkeypatch.setattr(llm, "_chat", fake_chat)
    out = await llm._generate_search_query_async("dji drone")
    assert out == "DJI Neo 2 under 350"


@pytest.mark.asyncio
async def test_refine_query_is_sanitised(monkeypatch):
    cfg = type("C", (), {"llm": type("L", (), {"local": [], "api_fallback": [],
                                                "openrouter": None, "gemini": None,
                                                "mistral": None})()})()
    llm = LLMClient(cfg)

    async def fake_chat(system, user, max_tokens=100):
        return ("Here's a refined search query to find **different** drones.\n\n---\n"
                "**\"DJI mini 3 pro\"** OR **\"dji air 2s\"**")

    monkeypatch.setattr(llm, "_chat", fake_chat)
    out = await llm.refine_query("dji drone", [], 1)
    assert out == "DJI mini 3 pro"