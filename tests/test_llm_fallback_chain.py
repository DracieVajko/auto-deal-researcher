"""The fallback chain must advance past an empty reply, not stop on it."""

import pytest

import src.llm.client as mod
from src.config.models import LLMAPIConfig
from src.llm.client import LLMClient, _content_from


class Cfg:
    class llm:
        local = []
        api_fallback = []
        openrouter = None
        gemini = None
        mistral = None


def make(providers):
    cfg = Cfg()
    cfg.llm.api_fallback = [
        LLMAPIConfig(provider=p, api_key_env=f"{p.upper()}_KEY", model="m") for p in providers
    ]
    return LLMClient(cfg)


def test_content_from_prefers_content():
    assert _content_from({"choices": [{"message": {"content": "hi"}}]}) == "hi"


def test_content_from_falls_back_to_reasoning_content():
    payload = {"choices": [{"message": {"content": None, "reasoning_content": "because"}}]}
    assert _content_from(payload) == "because"


def test_content_from_returns_empty_for_missing_shape():
    assert _content_from({}) == ""
    assert _content_from({"choices": []}) == ""
    assert _content_from({"choices": [{"message": {"content": None}}]}) == ""


@pytest.mark.asyncio
async def test_empty_reply_advances_to_next_provider(monkeypatch):
    """An empty completion must not be treated as success."""
    calls = []

    async def fake_call(provider, key, model, system, user, max_tokens, temperature=0.3):
        calls.append(provider)
        return "" if provider == "openrouter" else "gemini answer"

    monkeypatch.setattr(mod, "CLOUD_TIMEOUT", 5)
    for key in ("OPENROUTER_KEY", "GEMINI_KEY"):
        monkeypatch.setenv(key, "x")

    llm = make(["openrouter", "gemini"])
    monkeypatch.setattr(llm, "_call_cloud_llm_async", fake_call)
    out = await llm._chat("s", "u", max_tokens=10)

    assert calls == ["openrouter", "gemini"], "must advance past the empty reply"
    assert out == "gemini answer"


@pytest.mark.asyncio
async def test_all_empty_falls_back_to_prompt(monkeypatch):
    async def fake_call(provider, key, model, system, user, max_tokens, temperature=0.3):
        return ""

    for key in ("OPENROUTER_KEY", "GEMINI_KEY"):
        monkeypatch.setenv(key, "x")
    llm = make(["openrouter", "gemini"])
    monkeypatch.setattr(llm, "_call_cloud_llm_async", fake_call)
    out = await llm._chat("sys", "the user prompt", max_tokens=10)
    assert out == "the user prompt"