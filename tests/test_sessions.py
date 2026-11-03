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


def test_invalid_utf8_session_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(sessions, "SESSION_DIR", tmp_path)
    (tmp_path / "ebay.json").write_bytes(b"\xff\xfe\x00")
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
            raise AssertionError("must not be called")  # noqa: TRY003

    assert await sessions.apply_session(FakeContext(), "missing") is False


def test_login_base_url_falls_back_to_the_registry():
    from scripts.login import site_base_url

    assert site_base_url("nkon_nl") == "https://www.nkon.nl"


def test_login_check_loads_saved_cookies_into_the_context(tmp_path, monkeypatch):
    import scripts.login as login_module

    cookies = [{"name": "sid", "value": "x", "domain": ".ebay.de", "path": "/"}]
    (tmp_path / "ebay.json").write_text(json.dumps(cookies), encoding="utf-8")
    monkeypatch.setattr(login_module, "SESSION_DIR", tmp_path)

    class FakePage:
        def goto(self, *args, **kwargs):
            return None

        def inner_text(self, selector):
            return "Signed in"

        def wait_for_timeout(self, value):
            pass

    class FakeContext:
        def __init__(self):
            self.cookies = None

        def add_cookies(self, values):
            self.cookies = values

        def new_page(self):
            return FakePage()

        def close(self):
            pass

    class FakeBrowser:
        def __init__(self):
            self.context = FakeContext()

        def new_context(self, **kwargs):
            assert "storage_state" not in kwargs
            return self.context

        def close(self):
            pass

    class FakeChromium:
        def __init__(self):
            self.browser = FakeBrowser()

        def launch(self, **kwargs):
            return self.browser

    class FakePlaywright:
        def __init__(self):
            self.chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    fake = FakePlaywright()
    monkeypatch.setattr(login_module, "sync_playwright", lambda: fake)

    assert login_module.check("ebay") is True
    assert fake.chromium.browser.context.cookies == cookies
