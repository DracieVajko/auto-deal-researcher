"""Circuit breaker tests: a dead local endpoint must be skipped, not retried."""

import time
from types import SimpleNamespace

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
    def __init__(self):
        self.llm = SimpleNamespace(
            local=[], api_fallback=[], openrouter=None, gemini=None, mistral=None
        )


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

    async def fake_local(local_cfg, system, user, max_tokens, temperature=0.3):
        local_calls.append(local_cfg.endpoint)
        raise mod.requests.RequestException("connection refused")  # noqa: TRY003

    async def fake_cloud(provider, key, model, system, user, max_tokens, temperature=0.3):
        return "answer"

    monkeypatch.setattr(llm, "_call_local_llm_async", fake_local)
    monkeypatch.setattr(llm, "_call_cloud_llm_async", fake_cloud)

    for _ in range(5):
        assert await llm._chat("s", "u", max_tokens=5) == "answer"

    assert len(local_calls) == 2, f"local should be probed twice, got {len(local_calls)}"


@pytest.mark.asyncio
async def test_breaker_key_includes_model(monkeypatch):
    """A broken model must not disable a healthy model on the same endpoint."""
    cfg = Cfg()
    cfg.llm.local = [
        LLMLocalConfig(type="lmstudio", endpoint="http://localhost:1234",
                       model="broken"),
        LLMLocalConfig(type="lmstudio", endpoint="http://localhost:1234",
                       model="working"),
    ]
    llm = LLMClient(cfg)

    calls = []

    async def fake_local(local_cfg, system, user, max_tokens, temperature=0.3):
        calls.append(local_cfg.model)
        if local_cfg.model == "broken":
            raise mod.requests.RequestException("connection refused")  # noqa: TRY003
        return "local answer"

    monkeypatch.setattr(llm, "_call_local_llm_async", fake_local)

    for _ in range(4):
        assert await llm._chat("s", "u", max_tokens=5) == "local answer"

    assert calls.count("broken") == 2, "probe the broken model until its breaker opens"
    assert calls.count("working") == 4, "the healthy model keeps answering"


@pytest.mark.asyncio
async def test_rejected_cloud_key_is_blocked_for_the_run(monkeypatch):
    """A 401 never heals: probe it once, then stop paying for it on every call."""
    monkeypatch.setenv("BAD_KEY", "x")
    monkeypatch.setenv("GOOD_KEY", "y")
    cfg = Cfg()
    cfg.llm.local = []
    cfg.llm.api_fallback = [
        LLMAPIConfig(provider="openrouter", api_key_env="BAD_KEY", model="m"),
        LLMAPIConfig(provider="mistral", api_key_env="GOOD_KEY", model="m"),
    ]
    llm = LLMClient(cfg)

    calls = []

    async def fake_cloud(provider, key, model, system, user, max_tokens, temperature=0.3):
        calls.append(provider)
        if provider == "openrouter":
            response = mod.requests.Response()
            response.status_code = 401
            response._content = b'{"error": {"message": "User not found."}}'
            raise mod.requests.HTTPError("401 Client Error", response=response)  # noqa: TRY003
        return "answer"

    monkeypatch.setattr(llm, "_call_cloud_llm_async", fake_cloud)

    for _ in range(4):
        assert await llm._chat("s", "u", max_tokens=5) == "answer"

    assert calls.count("openrouter") == 1, "a rejected key must not be retried"
    assert calls.count("mistral") == 4