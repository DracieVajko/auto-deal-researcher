"""Environment overrides must actually take effect."""

import pytest

from src.config.models import AppConfig, LLMConfig, LLMLocalConfig
from src.llm.client import LLMClient


def make_client():
    return LLMClient(AppConfig(llm=LLMConfig(local=[
        LLMLocalConfig(type="lmstudio", endpoint="http://localhost:1234", model="m"),
        LLMLocalConfig(type="ollama", endpoint="http://localhost:11434", model="m2"),
    ])))


def test_lmstudio_endpoint_env_overrides_config(monkeypatch):
    """Regression: LMSTUDIO_ENDPOINT was documented but never read."""
    monkeypatch.setenv("LMSTUDIO_ENDPOINT", "http://192.168.1.5:1234")
    client = make_client()
    lm, ollama = client.llm_config.local
    assert lm.endpoint == "http://192.168.1.5:1234"
    assert ollama.endpoint == "http://localhost:11434", "other types untouched"


def test_ollama_endpoint_env_overrides(monkeypatch):
    monkeypatch.setenv("ADS_OLLAMA_ENDPOINT", "http://host.docker.internal:11434")
    client = make_client()
    assert client.llm_config.local[1].endpoint == "http://host.docker.internal:11434"


def test_config_used_when_env_absent(monkeypatch):
    for var in ("LMSTUDIO_ENDPOINT", "ADS_OLLAMA_ENDPOINT", "ADS_LLAMACPP_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)
    client = make_client()
    assert client.llm_config.local[0].endpoint == "http://localhost:1234"


def test_blank_env_is_ignored(monkeypatch):
    monkeypatch.setenv("LMSTUDIO_ENDPOINT", "   ")
    client = make_client()
    assert client.llm_config.local[0].endpoint == "http://localhost:1234"


@pytest.mark.parametrize("var", ["ADS_LOCAL_POLICY", "ADS_LOCAL_QUIET_SECONDS",
                                 "ADS_LOCAL_POLL_SECONDS", "ADS_LOCAL_MAX_WAIT",
                                 "ADS_LOCAL_LLM_TIMEOUT", "ADS_CLOUD_LLM_TIMEOUT"])
def test_documented_overrides_are_read(var, monkeypatch):
    """Every override advertised in the README must exist in the code."""
    import src.llm.client as mod

    assert var in Path(mod.__file__).read_text(encoding="utf-8")


from pathlib import Path  # noqa: E402