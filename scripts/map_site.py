"""Record a browser walkthrough so the flow can be turned into an adapter.

You drive the browser, this captures every action to a JSON file that can be
replayed in tests:

    python scripts/map_site.py record https://www.example.sk --out flows/example.json
    # ... a browser opens; navigate, type, click, accept cookies as usual ...
    # close the window or press Enter in the terminal to finish

    python scripts/map_site.py show flows/example.json          # summary
    python scripts/map_site.py replay flows/example.json        # verify it still works

Nothing here is committed automatically; review flows/*.json before adding
them. Recorded steps are a starting point for selectors, not a finished
adapter: a recording captures one session and cannot know which parts are
stable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def record(url: str, out: Path, headed: bool = True, user_dir: str = "./browser_profile") -> None:
    """Open a real browser and record clicks/typing/navigation."""
    events: list[dict] = []

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=user_dir,
            headless=not headed,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        page.on("framenavigated", lambda f: events.append(
            {"type": "goto", "url": f.url}) if f == page.main_frame else None)
        page.on("request", lambda r: events.append(
            {"type": "request", "method": r.method, "url": r.url, "resource": r.resource_type}
        ) if r.resource_type in ("xhr", "fetch") and "analytics" not in r.url else None)

        def on_click(msg):
            events.append({"type": "click", "selector": msg.get("selector")})

        def on_fill(msg):
            events.append({"type": "fill", "selector": msg.get("selector"),
                           "value": msg.get("value")})

        def on_submit(msg):
            events.append({"type": "submit", "selector": msg.get("selector")})

        page.on("click", on_click)
        page.on("fill", on_fill)
        page.on("submit", on_submit)

        page.goto(url, wait_until="domcontentloaded")
        print("\nBrowser open. Do the search manually.")
        print("Navigate, type a query, click through, accept cookies.")
        print("When finished, close the browser window.\n")

        ctx.on("close", lambda _: print("browser closed"))
        # Block until the user closes the window.
        try:
            while ctx.pages:
                ctx.wait_for_timeout(500)
        except KeyboardInterrupt:
            print("interrupted")

        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(events, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nSaved {len(events)} events to {out}")


def replay(path: Path, headed: bool = False) -> int:
    if not path.exists():
        raise SystemExit(f"no such recording: {path}")
    events = json.loads(path.read_text(encoding="utf-8"))
    performed = failed = 0

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir="./browser_profile", headless=not headed,
            viewport={"width": 1440, "height": 900})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        for ev in events:
            try:
                if ev["type"] == "goto":
                    page.goto(ev["url"], wait_until="domcontentloaded", timeout=30000)
                elif ev["type"] == "fill":
                    page.fill(ev["selector"], ev["value"], timeout=8000)
                elif ev["type"] == "click":
                    page.click(ev["selector"], timeout=8000)
                elif ev["type"] == "submit":
                    el = page.query_selector(ev["selector"])
                    if el:
                        el.evaluate("e => e.requestSubmit ? e.requestSubmit() : e.submit()")
                performed += 1
            except Exception as e:
                failed += 1
                print(f"  FAIL {ev['type']:<7} {str(ev.get('selector') or ev.get('url'))[:60]}"
                      f"  ({type(e).__name__})")
        ctx.close()

    print(f"\nreplayed {performed} steps, {failed} failed")
    return failed


def show(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"no such recording: {path}\n"
                         "record one with: python scripts/map_site.py record <url> --out <file>")
    events = json.loads(path.read_text(encoding="utf-8"))
    print(f"{len(events)} events in {path}\n")
    for i, ev in enumerate(events):
        key = ev.get("selector") or ev.get("url", "")
        val = f"  value={ev['value']!r}" if ev.get("value") else ""
        print(f"{i:>3}  {ev['type']:<7} {key[:80]}{val}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="drive the browser and capture the flow")
    r.add_argument("url")
    r.add_argument("--out", required=True)

    s = sub.add_parser("show", help="print a recording")
    s.add_argument("file")

    p = sub.add_parser("replay", help="replay a recording to verify it")
    p.add_argument("file")
    p.add_argument("--headed", action="store_true")

    args = ap.parse_args()
    if args.cmd == "record":
        record(args.url, Path(args.out))
    elif args.cmd == "show":
        show(Path(args.file))
    else:
        raise SystemExit(replay(Path(args.file), args.headed))


if __name__ == "__main__":
    main()