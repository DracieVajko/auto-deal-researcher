"""Saved per-site cookie sessions."""

import json

import pytest

from src.searcher import sessions


def test_missing_session_file_is_false(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    assert sessions.has_session("ebay") is False
    assert sessions.load_cookies("ebay") == []


def test_load_cookies_reads_the_saved_list(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    (tmp_path / "ebay.json").write_text(
        json.dumps(
            [{"name": "sid", "value": "x", "domain": ".ebay.de", "path": "/"}]
        ),
        encoding="utf-8",
    )
    assert sessions.has_session("ebay") is True
    assert sessions.load_cookies("ebay")[0]["name"] == "sid"


def test_malformed_session_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    (tmp_path / "ebay.json").write_text("{broken", encoding="utf-8")
    assert sessions.load_cookies("ebay") == []


@pytest.mark.asyncio
async def test_apply_session_adds_cookies(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    (tmp_path / "ebay.json").write_text(
        json.dumps(
            [{"name": "sid", "value": "x", "domain": ".ebay.de", "path": "/"}]
        ),
        encoding="utf-8",
    )

    class FakeContext:
        def __init__(self):
            self.cookies = None

        async def add_cookies(self, cookies):
            self.cookies = cookies

    context = FakeContext()
    assert await sessions.apply_session(context, "ebay") is True
    assert context.cookies[0]["name"] == "sid"


@pytest.mark.asyncio
async def test_apply_session_without_file_is_false(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)

    class FakeContext:
        async def add_cookies(self, cookies):
            raise AssertionError("must not be called")

    assert await sessions.apply_session(FakeContext(), "missing") is False


def test_login_base_url_falls_back_to_the_registry():
    from scripts.login import site_base_url

    assert site_base_url("nkon_nl") == "https://www.nkon.nl"
