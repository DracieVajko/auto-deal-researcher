"""Gemini replies must survive thinking models and empty answer parts."""

from types import SimpleNamespace

import pytest
import requests

import src.llm.client as mod
from src.llm.client import LLMClient, _content_from_gemini


class Cfg:
    def __init__(self):
        self.llm = SimpleNamespace(
            local=[], api_fallback=[], openrouter=None, gemini=None, mistral=None
        )


def gemini_response(parts):
    response = requests.Response()
    response.status_code = 200
    body = '{"candidates": [{"content": {"parts": ' + parts + "}}]}"
    response._content = body.encode()
    response.headers["Content-Type"] = "application/json"
    return response


def test_content_from_gemini_skips_thought_parts():
    payload = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {"text": "internal reasoning", "thought": True},
                        {"text": "OK"},
                    ]
                }
            }
        ]
    }
    assert _content_from_gemini(payload) == "OK"


def test_content_from_gemini_handles_missing_parts():
    assert _content_from_gemini({}) == ""
    assert _content_from_gemini({"candidates": []}) == ""
    assert _content_from_gemini({"candidates": [{"content": {}}]}) == ""
    # MAX_TOKENS before any answer part: no text, but no crash either.
    assert _content_from_gemini({"candidates": [{"finishReason": "MAX_TOKENS"}]}) == ""


@pytest.mark.asyncio
async def test_gemini_output_budget_has_a_floor(monkeypatch):
    captured = {}

    def fake_post(url, *, headers, json_body, timeout, attempts=3):
        captured.update(json_body)
        return gemini_response('[{"text": "OK"}]')

    monkeypatch.setattr(mod, "_post_with_retry", fake_post)
    client = LLMClient(Cfg())

    reply = await client._call_gemini_async(
        "key", "gemini-2.5-flash", "system", "user", 16, 0.0, 5
    )

    assert reply == "OK"
    budget = captured["generationConfig"]["maxOutputTokens"]
    assert budget >= mod.GEMINI_MIN_OUTPUT_TOKENS


@pytest.mark.asyncio
async def test_gemini_thought_only_reply_is_empty_not_a_crash(monkeypatch):
    def fake_post(url, *, headers, json_body, timeout, attempts=3):
        return gemini_response('[{"text": "thinking...", "thought": true}]')

    monkeypatch.setattr(mod, "_post_with_retry", fake_post)
    client = LLMClient(Cfg())

    reply = await client._call_gemini_async(
        "key", "gemini-2.5-flash", "system", "user", 16, 0.0, 5
    )

    assert reply == ""
