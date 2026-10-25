"""LLM provider health checks must report the real failure, not just 'failed'."""

from types import SimpleNamespace

import pytest
import requests

from src.config.models import LLMAPIConfig, LLMLocalConfig
from src.llm import health
from src.llm.client import LLMClient


class Cfg:
    def __init__(self):
        self.llm = SimpleNamespace(
            local=[], api_fallback=[], openrouter=None, gemini=None, mistral=None
        )


def make_config(providers=(), locals_=()):
    cfg = Cfg()
    cfg.llm.api_fallback = [
        LLMAPIConfig(provider=p, api_key_env=f"{p.upper()}_KEY", model=f"{p}-model")
        for p in providers
    ]
    cfg.llm.local = list(locals_)
    return cfg


def http_error(status: int, message: str) -> requests.HTTPError:
    response = requests.Response()
    response.status_code = status
    response._content = f'{{"error": {{"message": "{message}"}}}}'.encode()
    response.headers["Content-Type"] = "application/json"
    return requests.HTTPError(f"{status} Client Error", response=response)


@pytest.mark.asyncio
async def test_missing_key_is_reported_without_calling_provider(monkeypatch):
    monkeypatch.delenv("OPENROUTER_KEY", raising=False)
    cfg = make_config(["openrouter"])
    client = LLMClient(cfg)

    called = []

    async def fake_call(*args, **kwargs):
        called.append(args)
        return "should not happen"

    monkeypatch.setattr(client, "_call_cloud_llm_async", fake_call)
    results = await health.check_cloud(client, cfg, "Reply with OK.", 5)

    assert len(results) == 1
    assert results[0].status == "no-key"
    assert results[0].ok is False
    assert "OPENROUTER_KEY" in results[0].detail
    assert called == []


@pytest.mark.asyncio
async def test_rejected_key_is_reported_as_auth_with_hint(monkeypatch):
    monkeypatch.setenv("OPENROUTER_KEY", "dead-key")
    cfg = make_config(["openrouter"])
    client = LLMClient(cfg)

    async def fake_call(*args, **kwargs):
        raise http_error(401, "User not found.")

    monkeypatch.setattr(client, "_call_cloud_llm_async", fake_call)
    results = await health.check_cloud(client, cfg, "Reply with OK.", 5)

    assert results[0].status == "auth"
    assert "User not found." in results[0].detail
    assert "openrouter.ai/keys" in results[0].hint


@pytest.mark.asyncio
async def test_empty_reply_is_reported_as_empty(monkeypatch):
    monkeypatch.setenv("GEMINI_KEY", "key")
    cfg = make_config(["gemini"])
    client = LLMClient(cfg)

    async def fake_call(*args, **kwargs):
        return ""

    monkeypatch.setattr(client, "_call_cloud_llm_async", fake_call)
    results = await health.check_cloud(client, cfg, "Reply with OK.", 5)

    assert results[0].status == "empty"
    assert "thinking" in results[0].hint.lower()


@pytest.mark.asyncio
async def test_rate_limited_provider_gets_a_quota_hint(monkeypatch):
    monkeypatch.setenv("GEMINI_KEY", "key")
    cfg = make_config(["gemini"])
    client = LLMClient(cfg)

    async def fake_call(*args, **kwargs):
        raise http_error(429, "You exceeded your current quota")

    monkeypatch.setattr(client, "_call_cloud_llm_async", fake_call)
    results = await health.check_cloud(client, cfg, "Reply with OK.", 5)

    assert results[0].status == "http"
    assert "quota" in results[0].detail.lower()
    assert "rate-limits" in results[0].hint


@pytest.mark.asyncio
async def test_working_provider_is_reported_ok(monkeypatch):
    monkeypatch.setenv("MISTRAL_KEY", "key")
    cfg = make_config(["mistral"])
    client = LLMClient(cfg)

    async def fake_call(*args, **kwargs):
        return "OK."

    monkeypatch.setattr(client, "_call_cloud_llm_async", fake_call)
    results = await health.check_cloud(client, cfg, "Reply with OK.", 5)

    assert results[0].status == "ok"
    assert results[0].ok is True
    assert results[0].detail == "OK."


@pytest.mark.asyncio
async def test_dead_local_endpoint_is_reported(monkeypatch):
    cfg = make_config(
        locals_=[LLMLocalConfig(type="lmstudio", endpoint="http://localhost:1234", model="m")]
    )
    client = LLMClient(cfg)

    async def fake_call(*args, **kwargs):
        raise requests.ConnectionError("connection refused")  # noqa: TRY003

    monkeypatch.setattr(client, "_call_local_llm_async", fake_call)
    results = await health.check_local(client, cfg, "Reply with OK.", 5)

    assert results[0].kind == "local"
    assert results[0].status == "error"
    assert "ConnectionError" in results[0].detail
    assert results[0].hint
