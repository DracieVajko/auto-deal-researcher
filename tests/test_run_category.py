"""run wiring: the category the model infers must reach site selection."""

import importlib

from typer.testing import CliRunner

from src.config.models import AppConfig

app_module = importlib.import_module("src.cli.app")
runner = CliRunner()


class StubLLMClient:
    def __init__(self, config, payload=None):
        self.payload = payload if payload is not None else {}

    async def extract_search_filters(self, prompt):
        return self.payload


class FakeSearcher:
    calls: list = []

    def __init__(self, config, llm, storage, browser_mgr):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def search(self, prompt, condition="any", category="any", filters=None, **kw):
        FakeSearcher.calls.append({"condition": condition, "category": category})
        return []


class FakeStorage:
    def __init__(self, path):
        pass

    def prune_missing(self, **kwargs):
        pass

    def save_deal(self, deal):
        pass


class FakeBrowser:
    def __init__(self, config):
        pass

    async def close(self):
        pass


def _setup(monkeypatch, tmp_path, payload):
    config = AppConfig()
    config.output.directory = str(tmp_path)
    monkeypatch.setattr(app_module, "load_config", lambda *a, **k: config)
    monkeypatch.setattr(app_module, "LLMClient", lambda cfg: StubLLMClient(cfg, payload))
    monkeypatch.setattr(app_module, "PlaywrightSearcher", FakeSearcher)
    monkeypatch.setattr(app_module, "StorageManager", FakeStorage)
    monkeypatch.setattr(app_module, "BrowserManager", FakeBrowser)
    FakeSearcher.calls = []
    return config


def test_inferred_category_reaches_the_searcher(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"category": "hobby"})
    result = runner.invoke(app_module.app, ["run", "--prompt", "horsky bicykel"])
    assert result.exit_code == 0, result.output
    assert FakeSearcher.calls[0]["category"] == "hobby"


def test_explicit_category_beats_inference(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"category": "hobby"})
    result = runner.invoke(
        app_module.app, ["run", "--prompt", "x", "--category", "electronics"]
    )
    assert result.exit_code == 0, result.output
    assert FakeSearcher.calls[0]["category"] == "electronics"


def test_any_suppresses_inference(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {"category": "hobby"})
    result = runner.invoke(
        app_module.app, ["run", "--prompt", "x", "--category", "any"]
    )
    assert result.exit_code == 0, result.output
    assert FakeSearcher.calls[0]["category"] == "any"


def test_unknown_explicit_category_fails_before_searching(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {})
    result = runner.invoke(
        app_module.app, ["run", "--prompt", "x", "--category", "bicycle"]
    )
    assert result.exit_code == 1
    assert "electronics" in result.output
    assert FakeSearcher.calls == []


def test_no_llm_category_stays_any(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, {})
    result = runner.invoke(app_module.app, ["run", "--prompt", "x"])
    assert result.exit_code == 0, result.output
    assert FakeSearcher.calls[0]["category"] == "any"
