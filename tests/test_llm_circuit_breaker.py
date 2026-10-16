"""Circuit breaker tests: a dead local endpoint must be skipped, not retried."""

import time

import pytest

import src.llm.client as mod
from src.config.models import LLMAPIConfig, LLMLocalConfig
from src.llm.client import LLMClient, LocalCircuitBreaker


def test_breaker_opens_after_threshold():
    b = LocalCircuitBreaker(cooldown=60, threshold=2)
    assert b.is_open("x") is False
    b.record_failure("x")
    assert b.is_open("x") is False, "opens only after the threshold"
    b.record_failure("x")
    assert b.is_open("x") is True


def test_breaker_success_resets():
    b = LocalCircuitBreaker(cooldown=60, threshold=1)
    b.record_failure("x")
    assert b.is_open("x") is True
    b.record_success("x")
    assert b.is_open("x") is False


def test_breaker_cooldown_expiry_allows_probe(monkeypatch):
    b = LocalCircuitBreaker(cooldown=0.01, threshold=1)
    b.record_failure("x")
    assert b.is_open("x") is True
    # Capture the real clock first: inside the patched lambda mod.time.time()
    # would recurse.
    future = time.time() + 10_000.0
    monkeypatch.setattr(mod.time, "time", lambda: future)
    assert b.is_open("x") is False, "half-open after cooldown"


class Cfg:
    class llm:
        local = []
        api_fallback = []
        openrouter = None
        gemini = None
        mistral = None


@pytest.mark.asyncio
async def test_dead_local_is_skipped_after_two_failures(monkeypatch):
    """The whole point: don't pay the local timeout on every call."""
    monkeypatch.setenv("MISTRAL_KEY", "x")
    cfg = Cfg()
    cfg.llm.local = [LLMLocalConfig(type="lmstudio", endpoint="http://localhost:1234",
                                    model="m")]
    cfg.llm.api_fallback = [LLMAPIConfig(provider="mistral", api_key_env="MISTRAL_KEY",
                                        model="m")]
    llm = LLMClient(cfg)

    local_calls = []

    async def fake_local(local_cfg, system, user, max_tokens):
        local_calls.append(local_cfg.endpoint)
        raise mod.requests.RequestException("connection refused")

    async def fake_cloud(provider, key, model, system, user, max_tokens):
        return "answer"

    monkeypatch.setattr(llm, "_call_local_llm_async", fake_local)
    monkeypatch.setattr(llm, "_call_cloud_llm_async", fake_cloud)

    for _ in range(5):
        assert await llm._chat("s", "u", max_tokens=5) == "answer"

    assert len(local_calls) == 2, f"local should be probed twice, got {len(local_calls)}"