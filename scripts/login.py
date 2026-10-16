"""Interactive login for sites that require a real browser session (Facebook).

The flow is deliberately manual: sites with 2FA or mobile approval must be
signed into by a human in a visible browser. Afterwards the cookies are saved
and reused, so scheduled runs never have to log in again.

    # 1. log in once (headed browser, type your own credentials)
    python scripts/login.py --site facebook

    # 2. verify the saved session is still valid
    python scripts/login.py --site facebook --check

    # 3. remove it
    python scripts/login.py --site facebook --logout

Sessions are written to data/sessions/<site>.json, which is git-ignored.
They contain real login cookies: treat them like a password.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

from src.config import load_config  # noqa: E402
from src.searcher.adapters import get_adapter  # noqa: E402

SESSION_DIR = ROOT / "data" / "sessions"

# Where a human has to sign in. Anything not listed uses the site root, which
# is enough for sites that only set cookies on first visit.
LOGIN_URLS = {
    "facebook": "https://www.facebook.com/login",
    "ebay": "https://www.ebay.de/",
    "alza": "https://www.alza.sk/",
    "bazos": "https://www.bazos.sk/",
    "backmarket": "https://www.backmarket.sk/",
}


def session_file(site: str) -> Path:
    return SESSION_DIR / f"{site}.json"


def login_sites() -> list[str]:
    """Adapter ids that need a manual login: config list plus requires_login."""
    from src.searcher.adapters import ADAPTER_REGISTRY

    cfg = load_config()
    wanted = {s.strip().lower() for s in cfg.browser.login_sites}
    wanted |= {n for n, c in ADAPTER_REGISTRY.items()
               if getattr(c, "requires_login", False)}
    return sorted(wanted)


def profile_dir(cfg) -> Path:
    """Per-browser profile dir, matching what BrowserManager will use."""
    base = ROOT / cfg.browser.user_data_dir
    if cfg.browser.browser_id and cfg.browser.separate_profiles:
        return base / cfg.browser.browser_id
    return base


def login(site: str, headless: bool = False) -> None:
    adapter = get_adapter(site)()
    url = LOGIN_URLS.get(site, adapter.base_url)
    cfg = load_config()
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    profile = profile_dir(cfg)
    profile.mkdir(parents=True, exist_ok=True)

    print(f"\nOpening {url} in a visible browser (profile: {profile}).")
    print("Log in yourself, including any 2FA / mobile approval.")
    print("When the page shows you as signed in, close the window.\n")

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(profile),
            headless=headless,
            viewport={"width": 1440, "height": 900},
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        try:
            while ctx.pages:
                ctx.wait_for_timeout(500)
        except KeyboardInterrupt:
            pass

        cookies = ctx.cookies()
        target = session_file(site)
        target.write_text(json.dumps(cookies, indent=2), encoding="utf-8")
        ctx.close()

    print(f"\nSaved {len(cookies)} cookies to {target}")


def check(site: str) -> bool:
    path = session_file(site)
    if not path.exists():
        print(f"no saved session for {site} — run: python scripts/login.py --site {site}")
        return False

    cookies = json.loads(path.read_text(encoding="utf-8"))
    adapter = get_adapter(site)()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(storage_state=str(path),
                                  viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(adapter.base_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        body = page.inner_text("body").lower()
        still_login = any(s in body for s in ("log in", "log into", "prihlásiť"))
        print(f"cookies on disk : {len(cookies)}")
        print(f"visits login    : {still_login}")
        print("VERDICT:", "session expired — log in again" if still_login
              else "session looks valid")
        ctx.close()
        browser.close()
    return not still_login


async def await_text(page) -> str:
    try:
        return await page.inner_text("body")
    except Exception:
        return ""


def logout(site: str) -> None:
    path = session_file(site)
    if path.exists():
        path.unlink()
        print(f"removed {path}")
    else:
        print("nothing to remove")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", help="adapter id, e.g. facebook")
    ap.add_argument("--all", action="store_true",
                    help="log into every site that needs it, one browser at a time")
    ap.add_argument("--list", action="store_true", help="show which sites need a login")
    ap.add_argument("--check", action="store_true", help="verify the saved session")
    ap.add_argument("--logout", action="store_true", help="delete the saved session")
    args = ap.parse_args()

    if args.list:
        for site in login_sites():
            state = "session saved" if session_file(site).exists() else "NOT logged in"
            print(f"  {site:<12} {state}")
        return

    sites = login_sites() if args.all else ([args.site] if args.site else [])
    if not sites:
        ap.error("pass --site <id>, --all or --list")

    for site in sites:
        if args.logout:
            logout(site)
        elif args.check:
            check(site)
        else:
            login(site)


if __name__ == "__main__":
    main()