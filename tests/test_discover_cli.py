"""Discovery CLI must forward the requested browser visibility unchanged."""

from types import SimpleNamespace

import pytest

from scripts import discover_sites as ds


def _discover_args(tmp_path, headless):
    return SimpleNamespace(
        all=False,
        site=["alza"],
        category="electronics",
        profile_dir=tmp_path / "profiles",
        flows_dir=tmp_path / "flows",
        user_data_dir=tmp_path / "browser",
        headless=headless,
        no_pause=True,
        no_html=True,
        screenshots=False,
        force=False,
        resume=False,
        state=tmp_path / "state.json",
        report_dir=None,
    )


@pytest.mark.parametrize(("headless", "expected"), [(False, False), (True, True)])
def test_run_discover_forwards_headless_unchanged(monkeypatch, tmp_path, headless, expected):
    seen = {}

    def fake_discover(*args, **kwargs):
        seen.update(kwargs)
        return {"site_id": "alza", "status": "validated"}

    monkeypatch.setattr(ds, "discover_site", fake_discover)
    assert ds.run_discover(_discover_args(tmp_path, headless)) == 0
    assert seen["headless"] is expected


def test_run_validate_forwards_headless_unchanged(monkeypatch, tmp_path):
    profile = SimpleNamespace(
        site_id="alza",
        search=SimpleNamespace(category_urls={"electronics": "https://x.test/?q={query}"}),
    )
    seen = {}

    def fake_validate(*args, **kwargs):
        seen.update(kwargs)
        return {"site_id": "alza", "status": "validated", "cards": 1}

    monkeypatch.setattr(ds, "load_profile", lambda site_id, directory: profile)
    monkeypatch.setattr(ds, "validate_profile", fake_validate)
    args = SimpleNamespace(
        all=False,
        site=["alza"],
        category="electronics",
        profile_dir=tmp_path,
        user_data_dir=tmp_path,
        headless=False,
        no_pause=True,
    )
    assert ds.run_validate(args) == 0
    assert seen["headless"] is False


def test_run_discover_prints_the_failure_reason(monkeypatch, tmp_path, capsys):
    """A crashed site must say why, not just 'failed'."""

    def boom(*args, **kwargs):
        raise RuntimeError("net::ERR_CONNECTION_RESET at https://www.autobazar.sk/")  # noqa: TRY003

    monkeypatch.setattr(ds, "discover_site", boom)
    assert ds.run_discover(_discover_args(tmp_path, True)) == 0
    out = capsys.readouterr().out
    assert "failed" in out
    assert "ERR_CONNECTION_RESET" in out


def test_run_validate_prints_the_failure_reason(monkeypatch, tmp_path, capsys):
    profile = SimpleNamespace(
        site_id="alza",
        search=SimpleNamespace(category_urls={"electronics": "https://x.test/?q={query}"}),
    )

    def boom(*args, **kwargs):
        raise RuntimeError("selector timeout")  # noqa: TRY003

    monkeypatch.setattr(ds, "load_profile", lambda site_id, directory: profile)
    monkeypatch.setattr(ds, "validate_profile", boom)
    args = SimpleNamespace(
        all=False,
        site=["alza"],
        category="electronics",
        profile_dir=tmp_path,
        user_data_dir=tmp_path,
        headless=False,
        no_pause=True,
    )
    assert ds.run_validate(args) == 0
    out = capsys.readouterr().out
    assert "failed" in out
    assert "selector timeout" in out


def test_error_text_flattens_the_playwright_call_log():
    class FakePlaywrightError(Exception):
        message = "Page.goto: net::ERR_CONNECTION_RESET\nCall log:\n  - navigating to x"

    text = ds._error_text(FakePlaywrightError("ignored"))
    assert "\n" not in text
    assert text.startswith("Page.goto: net::ERR_CONNECTION_RESET")
    assert len(text) <= 300
