"""Helpers for setup.sh / setup.bat, kept out of the shell quoting minefield."""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CONFIG = ROOT / "config.yaml"


def python_version() -> None:
    import platform

    v = sys.version_info
    print(f"  found {v.major}.{v.minor}.{v.micro} ({platform.python_implementation()})")
    if not ((3, 11) <= (v.major, v.minor) < (3, 14)):
        print("  !!  this project targets Python 3.11-3.13")


def list_browsers() -> None:
    from src.browser.browsers import REGISTRY, detect_all

    found = {p.id: exe for p, exe in detect_all()}
    print("  browsers found on this machine:")
    any_found = False
    for profile in REGISTRY:
        exe = found.get(profile.id)
        if exe:
            any_found = True
            tag = "CDP attach OK" if profile.supports_cdp else "launch only (no CDP)"
            print(f"    {profile.id:<10} {profile.name:<24} {tag}")
    if not any_found:
        print("    none - Playwright's bundled Chromium will be used")


def set_browser(browser_id: str) -> int:
    """Write browser_id into config.yaml, adding the key if it is absent."""
    if not CONFIG.exists():
        print("  !!  config.yaml not found; run setup first")
        return 1
    text = CONFIG.read_text(encoding="utf-8")
    line = f'  browser_id: "{browser_id}"'

    if re.search(r"(?m)^\s*browser_id:", text):
        new = re.sub(r"(?m)^(\s*)browser_id:.*$", line.replace("\\", "\\\\"), text)
    else:
        # Insert under the browser: block, or at the end.
        if re.search(r"(?m)^browser:\s*$", text):
            new = re.sub(r"(?m)^(browser:\s*)$", r"\1\n" + line, text, count=1)
        else:
            new = text.rstrip() + "\n\nbrowser:\n" + line + "\n"
    CONFIG.write_text(new, encoding="utf-8")
    print(f"  ok  browser_id set to {browser_id}")
    return 0


def login_status() -> None:
    from src.searcher.adapters import ADAPTER_REGISTRY
    from src.config import load_config

    cfg = load_config()
    wanted = {s.strip().lower() for s in cfg.browser.login_sites}
    wanted |= {n for n, c in ADAPTER_REGISTRY.items()
               if getattr(c, "requires_login", False)}
    session_dir = ROOT / "data" / "sessions"
    print("  sites needing a manual login:")
    for site in sorted(wanted):
        if site not in ADAPTER_REGISTRY:
            print(f"    {site:<12} (unknown adapter id in browser.login_sites)")
            continue
        saved = (session_dir / f"{site}.json").exists()
        print(f"    {site:<12} {'session saved' if saved else 'NOT logged in'}")


def doctor_hint() -> None:
    from src.searcher.adapters import ADAPTER_REGISTRY

    enabled = [
        (s.name, s.adapter_class)
        for s in _config_websites()
        if s.enabled
    ]
    print("  enabled sites:")
    for name, adapter in enabled:
        print(f"    {name:<12} adapter={adapter}")
    print(f"  adapters available: {', '.join(sorted(ADAPTER_REGISTRY))}")


def _config_websites():
    from src.config import load_config

    return load_config().search.websites


COMMANDS = {
    "python-version": python_version,
    "list-browsers": list_browsers,
    "set-browser": set_browser,
    "login-status": login_status,
    "doctor-hint": doctor_hint,
}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print(f"usage: {Path(sys.argv[0]).name} <{'|'.join(COMMANDS)}> [arg]")
        raise SystemExit(2)
    args = sys.argv[2:]
    sys.exit(COMMANDS[sys.argv[1]](*args) or 0)