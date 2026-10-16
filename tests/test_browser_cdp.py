"""Browser/CDP wiring: endpoint parsing and CDP-first attach behaviour."""

import pytest

from src.browser.manager import _port_from
from src.config.models import BrowserConfig


@pytest.mark.parametrize(
    ("endpoint", "expected"),
    [
        ("http://127.0.0.1:9222", 9222),
        ("http://localhost:9222/json/version", 9222),
        ("ws://127.0.0.1:9333/devtools/browser/x", 9333),
        ("http://127.0.0.1", None),
        ("", None),
        (None, None),
    ],
)
def test_port_from_endpoint(endpoint, expected):
    assert _port_from(endpoint) == expected


def test_default_cdp_endpoint_is_ipv4():
    """Chrome/Brave bind IPv4; 'localhost' may resolve to ::1 and fail."""
    assert BrowserConfig().cdp_endpoint == "http://127.0.0.1:9222"
    assert "localhost" not in BrowserConfig().cdp_endpoint


def test_browser_executable_defaults_to_none():
    assert BrowserConfig().browser_executable is None


def test_browser_config_accepts_custom_executable():
    cfg = BrowserConfig(browser_executable=r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe")
    assert "brave.exe" in cfg.browser_executable


@pytest.mark.asyncio
async def test_manager_uses_connect_over_cdp(monkeypatch):
    """Regression: connect() speaks Playwright's protocol and failed against
    a raw DevTools endpoint with 'reading startsWith'."""
    from src.browser.manager import BrowserManager

    calls = []

    class FakeChromium:
        async def connect_over_cdp(self, endpoint):
            calls.append(("connect_over_cdp", endpoint))
            raise RuntimeError("would connect")

        async def connect(self, endpoint):  # pragma: no cover - must not run
            calls.append(("connect", endpoint))
            raise AssertionError("connect() must not be used for a CDP endpoint")

    class FakePW:
        chromium = FakeChromium()

        async def start(self):
            return self

        async def stop(self):
            return None

    manager = BrowserManager.__new__(BrowserManager)
    manager.config = type("C", (), {"browser": BrowserConfig(
        cdp_endpoint="http://127.0.0.1:9222", use_persistent_context=False)})()
    manager._playwright = FakePW()
    manager._context = None
    manager._fingerprint_rotator = None

    import src.browser.manager as mod
    monkeypatch.setattr(mod, "async_playwright", type("A", (), {
        "start": staticmethod(lambda: FakePW())}))

    # use_persistent_context False and no CDP -> falls through to plain launch,
    # which we do not want to run here. Just assert the CDP call was attempted.
    try:
        await manager._create_browser()
    except Exception:
        pass
    assert calls and calls[0][0] == "connect_over_cdp"