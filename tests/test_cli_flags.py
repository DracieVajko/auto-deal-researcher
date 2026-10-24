"""CLI wiring: --country and --max-sites must reach the search."""

import importlib

import pytest
from typer.testing import CliRunner

from src.cli import app

app_module = importlib.import_module("src.cli.app")

runner = CliRunner()


@pytest.fixture
def captured(monkeypatch):
    calls = {}

    async def fake(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return None

    for name in ("_run_async", "_search_async", "_diamond_search_async"):
        monkeypatch.setattr(app_module, name, fake)
    return calls


def test_country_and_max_sites_reach_the_run_command(captured):
    result = runner.invoke(
        app,
        ["run", "--prompt", "notebook", "--country", "cz", "--max-sites", "3"],
    )
    assert result.exit_code == 0, result.output
    assert captured["args"][-2:] == ("cz", 3)


def test_country_and_max_sites_reach_the_search_command(captured):
    result = runner.invoke(
        app,
        ["search", "--prompt", "notebook", "--country", "DE", "--max-sites", "5"],
    )
    assert result.exit_code == 0, result.output
    assert captured["args"][-2:] == ("DE", 5)


def test_run_command_defaults(captured):
    result = runner.invoke(app, ["run", "--prompt", "notebook"])
    assert result.exit_code == 0, result.output
    assert captured["args"][-2:] == (None, None)
