"""Browser registry: what is installed, and which ones we can drive.

Chromium-family browsers (Chrome, Edge, Brave, Opera, Vivaldi, Chromium) can
be driven two ways:

  * persistent context  — we launch the real browser with our own profile
  * CDP attach          — we attach to one you already started with
    --remote-debugging-port, reusing your existing cookies and logins

Firefox and WebKit (Safari) have no CDP equivalent, so they can only be
launched by us; attaching to a running instance is not possible. That is a
Playwright limitation, not a choice made here.

Every path here is detected on the current machine; nothing is downloaded or
installed automatically.
"""

from __future__ import annotations

import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path

CHROMIUM = "chromium"
FIREFOX = "firefox"
WEBKIT = "webkit"

WINDOWS = platform.system() == "Windows"
MAC = platform.system() == "Darwin"
LINUX = platform.system() == "Linux"

# Environment overrides always win, e.g. ADS_BROWSER_EXECUTABLE.
ENV_OVERRIDE = "ADS_BROWSER_EXECUTABLE"


@dataclass
class BrowserProfile:
    """One installable/detectable browser."""

    id: str
    name: str
    engine: str = CHROMIUM
    # Playwright channel name, when the browser ships one (chromium.launch).
    channel: str | None = None
    # Candidate executables per platform, tried in order.
    candidates: dict[str, list[str]] = field(default_factory=dict)
    # Extra flags needed to make a third-party Chromium work well.
    extra_args: list[str] = field(default_factory=list)

    @property
    def supports_cdp(self) -> bool:
        """Only Chromium exposes the DevTools protocol Playwright can attach to."""
        return self.engine == CHROMIUM

    def candidate_paths(self) -> list[str]:
        return self.candidates.get(platform.system().lower(), [])

    def find_executable(self) -> str | None:
        override = os.environ.get(ENV_OVERRIDE)
        if override:
            return override
        for raw in self.candidate_paths():
            path = Path(os.path.expandvars(raw))
            if path.is_file():
                return str(path)
        return None

    def is_installed(self) -> bool:
        return bool(self.find_executable())

    def find_on_path(self) -> str | None:
        """Look the binary up on PATH as a last resort."""
        names = {
            "chrome": "chrome",
            "msedge": "msedge",
            "brave": "brave",
            "firefox": "firefox",
            "opera": "opera",
            "vivaldi": "vivaldi",
            "chromium": "chromium",
        }
        exe = names.get(self.id)
        return shutil.which(exe) if exe else None


def _win(p: list[str]) -> list[str]:
    return p


REGISTRY: list[BrowserProfile] = [
    BrowserProfile(
        id="brave",
        name="Brave (Chromium)",
        channel=None,
        candidates={
            "windows": _win([
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
                r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe",
            ]),
            "darwin": [
                "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            ],
            "linux": [
                "/usr/bin/brave-browser",
                "/usr/bin/brave",
                "/snap/bin/brave",
            ],
        },
        extra_args=["--disable-features=UseOzonePlatform"],
    ),
    BrowserProfile(
        id="chrome",
        name="Google Chrome",
        channel="chrome",
        candidates={
            "windows": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe",
            ],
            "darwin": ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"],
            "linux": ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable"],
        },
    ),
    BrowserProfile(
        id="msedge",
        name="Microsoft Edge",
        channel="msedge",
        candidates={
            "windows": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ],
            "darwin": ["/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"],
            "linux": ["/usr/bin/microsoft-edge", "/usr/bin/microsoft-edge-stable"],
        },
    ),
    BrowserProfile(
        id="opera",
        name="Opera",
        candidates={
            "windows": [
                r"C:\Program Files\Opera\opera.exe",
                r"C:\Program Files (x86)\Opera\opera.exe",
                r"%LOCALAPPDATA%\Programs\Opera\opera.exe",
            ],
            "darwin": ["/Applications/Opera.app/Contents/MacOS/Opera"],
            "linux": ["/usr/bin/opera"],
        },
    ),
    BrowserProfile(
        id="vivaldi",
        name="Vivaldi",
        candidates={
            "windows": [
                r"C:\Program Files\Vivaldi\Application\vivaldi.exe",
                r"%LOCALAPPDATA%\Vivaldi\Application\vivaldi.exe",
            ],
            "darwin": ["/Applications/Vivaldi.app/Contents/MacOS/Vivaldi"],
            "linux": ["/usr/bin/vivaldi", "/usr/bin/vivaldi-stable"],
        },
    ),
    BrowserProfile(
        id="chromium",
        name="Chromium",
        candidates={
            "windows": [
                r"C:\Program Files\Chromium\Application\chrome.exe",
                r"%LOCALAPPDATA%\Chromium\Application\chrome.exe",
            ],
            "darwin": ["/Applications/Chromium.app/Contents/MacOS/Chromium"],
            "linux": ["/usr/bin/chromium", "/usr/bin/chromium-browser"],
        },
    ),
    BrowserProfile(
        id="firefox",
        name="Mozilla Firefox",
        engine=FIREFOX,
        candidates={
            "windows": [
                r"C:\Program Files\Mozilla Firefox\firefox.exe",
                r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
            ],
            "darwin": ["/Applications/Firefox.app/Contents/MacOS/firefox"],
            "linux": ["/usr/bin/firefox"],
        },
    ),
    BrowserProfile(
        id="safari",
        name="Safari (WebKit)",
        engine=WEBKIT,
        candidates={
            "darwin": ["/Applications/Safari.app/Contents/MacOS/Safari"],
        },
    ),
]


def by_id(browser_id: str) -> BrowserProfile | None:
    for profile in REGISTRY:
        if profile.id == browser_id.lower().strip():
            return profile
    return None


def detect_all() -> list[tuple[BrowserProfile, str | None]]:
    """Return (profile, executable) for every browser found on this machine."""
    found = []
    for profile in REGISTRY:
        exe = profile.find_executable() or profile.find_on_path()
        if exe:
            found.append((profile, exe))
    return found


def resolve(browser_id: str | None, explicit_path: str | None = None) -> tuple[str | None, str]:
    """Work out which browser to launch.

    Returns (executable_path, description). explicit_path wins, then the
    registry id, then the first detected Chromium browser, then None (which
    means Playwright's bundled Chromium).
    """
    if explicit_path and Path(os.path.expandvars(explicit_path)).is_file():
        return os.path.expandvars(explicit_path), "config browser_executable"

    if browser_id:
        profile = by_id(browser_id)
        if profile is None:
            raise ValueError(
                f"unknown browser {browser_id!r}; known: {[p.id for p in REGISTRY]}"
            )
        exe = profile.find_executable() or profile.find_on_path()
        if exe:
            return exe, profile.name
        raise ValueError(
            f"{profile.name} is not installed (looked in "
            f"{', '.join(profile.candidate_paths()) or 'PATH'})"
        )

    for profile, exe in detect_all():
        if profile.engine == CHROMIUM:
            return exe, f"{profile.name} (auto-detected)"

    return None, "Playwright bundled Chromium"