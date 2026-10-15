"""Regression tests for adaptive LLM client timeouts."""

import src.llm.client as client_mod
from src.llm.client import CLOUD_TIMEOUT, LOCAL_TIMEOUT, LLMClient


class DummyConfig:
    class llm:
        local = []
        api_fallback = []


def test_timeouts_are_generous_enough_for_slow_local_models():
    """A hardcoded 5s timeout killed every slow local model (1-2 tok/s)."""
    assert LOCAL_TIMEOUT >= 120
    assert CLOUD_TIMEOUT >= 30


def test_local_timeout_is_configurable(monkeypatch):
    monkeypatch.setenv("ADS_LOCAL_LLM_TIMEOUT", "42")
    assert client_mod._timeout_from_env() == 42.0


def test_env_invalid_value_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("ADS_CLOUD_LLM_TIMEOUT", "not-a-number")
    assert client_mod._timeout_from_env("ADS_CLOUD_LLM_TIMEOUT", CLOUD_TIMEOUT) == CLOUD_TIMEOUT


def test_no_hardcoded_five_second_timeouts():
    """Guards against the original `timeout=5` regression."""
    import inspect

    source = inspect.getsource(LLMClient)
    assert "timeout=5)" not in source
    assert "timeout=5," not in source