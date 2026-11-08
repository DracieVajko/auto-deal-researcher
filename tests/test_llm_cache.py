"""Tests for llm_cache.py (LLM response caching)."""

import time

from src.intelligence.llm_cache import LLMCache


def test_cache_set_and_get(tmp_path):
    cache = LLMCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=3600)
    cache.set("gemini", "gemini-2.5", "prompt A", "response A")
    assert cache.get("gemini", "gemini-2.5", "prompt A") == "response A"
    assert cache.get("gemini", "gemini-2.5", "prompt B") is None
    assert cache.get("mistral", "mistral-7b", "prompt A") is None


def test_cache_expiry(tmp_path):
    cache = LLMCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=1)
    cache.set("gemini", "gemini-2.5", "prompt", "response")
    assert cache.get("gemini", "gemini-2.5", "prompt") == "response"
    time.sleep(1.1)
    assert cache.get("gemini", "gemini-2.5", "prompt") is None


def test_cache_persistence(tmp_path):
    cache_dir = str(tmp_path / "cache")
    cache1 = LLMCache(cache_dir=cache_dir, ttl_seconds=3600)
    cache1.set("gemini", "gemini-2.5", "prompt", "response")
    # New instance reads from disk
    cache2 = LLMCache(cache_dir=cache_dir, ttl_seconds=3600)
    assert cache2.get("gemini", "gemini-2.5", "prompt") == "response"


def test_cache_clear(tmp_path):
    cache = LLMCache(cache_dir=str(tmp_path / "cache"), ttl_seconds=3600)
    cache.set("gemini", "gemini-2.5", "prompt A", "response A")
    cache.set("gemini", "gemini-2.5", "prompt B", "response B")
    assert cache.clear() == 2
    assert cache.get("gemini", "gemini-2.5", "prompt A") is None
    assert cache.get("gemini", "gemini-2.5", "prompt B") is None
