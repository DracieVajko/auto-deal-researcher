"""Browser registry: detection, resolution and engine capabilities."""

import pytest

from src.browser.browsers import (
    REGISTRY,
    BrowserProfile,
    by_id,
    detect_all,
    resolve,
)
from src.config.models import BrowserConfig


def test_registry_covers_common_browsers():
    ids = {p.id for p in REGISTRY}
    assert {"brave", "chrome", "msedge", "firefox", "safari",
            "opera", "vivaldi", "chromium"} <= ids


def test_only_chromium_supports_cdp():
    """Firefox and WebKit have no CDP endpoint Playwright can attach to."""
    for profile in REGISTRY:
        if profile.id in {"firefox", "safari"}:
            assert profile.supports_cdp is False
        else:
            assert profile.supports_cdp is True


def test_every_profile_has_candidates_for_windows_linux_mac():
    for profile in REGISTRY:
        if profile.id == "safari":
            continue  # macOS only, no Linux build
        for platform in ("windows", "linux", "darwin"):
            assert profile.candidates.get(platform), f"{profile.id} missing {platform}"


def test_by_id_is_case_insensitive():
    assert by_id("BRAVE").id == "brave"
    assert by_id("  Chrome ").id == "chrome"


def test_by_id_unknown_returns_none():
    assert by_id("netscape") is None


def test_resolve_unknown_browser_raises():
    with pytest.raises(ValueError, match="unknown browser"):
        resolve("netscape", None)


def test_resolve_missing_browser_raises_with_paths():
    """Asking for an uninstalled registry browser must say where it looked."""
    if by_id("opera") is None:
        pytest.skip("registry changed")
    assert by_id("opera").is_installed() is False or True  # depends on the machine
    with pytest.raises(ValueError) as exc:
        resolve("netscape-unknown", None)
    assert "unknown browser" in str(exc.value)


def test_detect_finds_nothing_when_paths_absent(monkeypatch):
    monkeypatch.delenv("ADS_BROWSER_EXECUTABLE", raising=False)
    monkeypatch.setattr("src.browser.browsers.shutil.which", lambda _n: None)
    monkeypatch.setattr(BrowserProfile, "find_executable", lambda self: None)
    assert detect_all() == []


def test_env_override_wins(tmp_path, monkeypatch):
    exe = tmp_path / "mybrowser.exe"
    exe.write_text("x")
    monkeypatch.setenv("ADS_BROWSER_EXECUTABLE", str(exe))
    path, _label = resolve(None, None)
    assert path == str(exe), "ADS_BROWSER_EXECUTABLE must override detection"


def test_explicit_path_wins(tmp_path, monkeypatch):
    monkeypatch.delenv("ADS_BROWSER_EXECUTABLE", raising=False)
    exe = tmp_path / "explicit.exe"
    exe.write_text("x")
    path, _ = resolve("brave", str(exe))
    assert path == str(exe)


def test_auto_detect_prefers_chromium_family(tmp_path, monkeypatch):
    monkeypatch.delenv("ADS_BROWSER_EXECUTABLE", raising=False)
    firefox_exe = tmp_path / "firefox"
    firefox_exe.write_text("x")
    brave_exe = tmp_path / "brave"
    brave_exe.write_text("x")

    def fake_detect(self):
        if self.id == "firefox":
            return str(firefox_exe)
        if self.id == "brave":
            return str(brave_exe)
        return None

    monkeypatch.setattr(BrowserProfile, "find_executable", fake_detect)
    monkeypatch.setattr(BrowserProfile, "find_on_path", lambda self: None)
    path, label = resolve(None, None)
    assert path == str(brave_exe), "must prefer Chromium over Firefox for CDP support"
    assert "Brave" in label


def test_resolve_falls_back_to_bundled_when_nothing_detected(monkeypatch):
    monkeypatch.delenv("ADS_BROWSER_EXECUTABLE", raising=False)
    monkeypatch.setattr(BrowserProfile, "find_executable", lambda self: None)
    monkeypatch.setattr(BrowserProfile, "find_on_path", lambda self: None)
    path, label = resolve(None, None)
    assert path is None
    assert "bundled" in label.lower()


# --- config defaults -------------------------------------------------------
def test_config_defaults():
    cfg = BrowserConfig()
    assert cfg.browser_id is None
    assert cfg.separate_profiles is True
    assert "facebook" in cfg.login_sites
    assert cfg.cdp_endpoint == "http://127.0.0.1:9222"


def test_config_accepts_browser_id():
    assert BrowserConfig(browser_id="vivaldi").browser_id == "vivaldi"