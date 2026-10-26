"""The ask wizard: a prompt is all the user has to type."""

import importlib

from typer.testing import CliRunner

from src.config.models import AppConfig
from src.searcher.filters import SearchFilters

app_module = importlib.import_module("src.cli.app")
runner = CliRunner()


def _stub(monkeypatch, tmp_path):
    calls = {}
    config = AppConfig()
    config.output.directory = str(tmp_path)
    monkeypatch.setattr(app_module, "load_config", lambda *a, **k: config)

    async def fake_run_search(
        prompt,
        *,
        condition="any",
        category=None,
        country=None,
        max_sites=None,
        brief=None,
        plan=None,
        **kwargs,
    ):
        calls["prompt"] = prompt
        calls["country"] = country
        calls["max_sites"] = max_sites
        brief(
            app_module.SearchBrief(
                filters=SearchFilters(max_price=200.0, condition="used"),
                condition="used",
                category="hobby",
            )
        )
        plan(["bazos"])
        from src.cli.app import SearchOutcome

        return SearchOutcome(
            deal_count=3,
            sites=["bazos"],
            json_path="j",
            md_path="m",
            results_dir="d",
        )

    monkeypatch.setattr(app_module, "run_search", fake_run_search)
    return calls


def test_ask_prompts_once_and_prints_the_summary(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    result = runner.invoke(app_module.app, ["ask"], input="horské kolo used do 200\n\n\n")
    assert result.exit_code == 0, result.output
    assert calls["prompt"] == "horské kolo used do 200"
    out = result.output
    assert "Understood:" in out and "condition=used" in out and "category=hobby" in out
    assert "Shops: bazos" in out
    assert "Found 3 deals" in out


def test_ask_reprompts_an_empty_prompt(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    result = runner.invoke(app_module.app, ["ask"], input="\n  \nnotebook\n\n\n")
    assert result.exit_code == 0, result.output
    assert calls["prompt"] == "notebook"


def test_ask_seeds_skip_questions(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    result = runner.invoke(
        app_module.app, ["ask", "--country", "CZ", "--max-sites", "4"], input="kolo\n"
    )
    assert result.exit_code == 0, result.output
    assert calls["country"] == "CZ"
    assert calls["max_sites"] == 4


def test_ask_non_numeric_max_sites_reprompts(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    result = runner.invoke(app_module.app, ["ask"], input="kolo\nSK\nabc\n7\n")
    assert result.exit_code == 0, result.output
    assert calls["max_sites"] == 7


def test_ask_aborts_cleanly_at_eof(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    result = runner.invoke(app_module.app, ["ask"], input="")
    assert result.exit_code != 0
    assert "prompt" not in calls


def test_ask_shows_any_without_a_guess(monkeypatch, tmp_path):
    calls = _stub(monkeypatch, tmp_path)
    # Stub with no inferred category: override the brief the stub sends.
    config = AppConfig()
    config.output.directory = str(tmp_path)
    monkeypatch.setattr(app_module, "load_config", lambda *a, **k: config)

    async def fake_run_search(prompt, *, condition="any", category=None,
                              country=None, max_sites=None, brief=None, plan=None,
                              **kwargs):
        calls["prompt"] = prompt
        brief(app_module.SearchBrief(
            filters=SearchFilters(max_price=None, condition=None),
            condition="any",
            category="any",
        ))
        plan(["bazos"])
        from src.cli.app import SearchOutcome

        return SearchOutcome(
            deal_count=0,
            sites=["bazos"],
            json_path="j",
            md_path="m",
            results_dir="d",
        )

    monkeypatch.setattr(app_module, "run_search", fake_run_search)
    result = runner.invoke(app_module.app, ["ask"], input="bicykel\n\n\n")
    assert result.exit_code == 0, result.output
    assert "category=any (no model guess)" in result.output