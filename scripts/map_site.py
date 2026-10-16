"""Record a full browser walkthrough so the flow can be turned into an adapter.

You drive the browser, this captures every action (navigation, clicks, typing,
form submits, XHR/fetch) plus page snapshots (HTML + screenshot) at each
navigation. The resulting JSON is everything needed to build or repair an
adapter without me having to reproduce the site myself.

Usage:
    python scripts/map_site.py record https://www.alza.sk --out flows/alza.json
    # ... a browser opens; navigate, type, click, accept cookies as usual ...
    # close the window or press Enter in the terminal to finish

    python scripts/map_site.py show flows/alza.json          # summary
    python scripts/map_site.py replay flows/alza.json        # verify it still works
    python scripts/map_site.py html flows/alza.json          # dump one page's HTML

Nothing here is committed automatically; review flows/*.json before adding
them. A recording captures one session and cannot know which parts are
stable, but it gives me the real DOM to work from.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright  # noqa: E402

SNAP_DIR = "snapshots"


def _selector(el) -> str:
    """Build a short, stable selector for an element."""
    parts = []
    tag = el.evaluate("e => e.tagName.toLowerCase()")
    parts.append(tag)
    for attr in ("id", "data-testid", "data-qa", "data-webid", "data-code",
                 "data-product", "role", "name", "type", "href"):
        val = el.get_attribute(attr)
        if val:
            if attr == "href":
                # keep only the path component, not query params
                val = val.split("?")[0][:60]
            parts.append(f'{attr}="{val}"')
            break
    cls = el.get_attribute("class")
    if cls:
        # first 2 classes only, to avoid huge strings
        short = " ".join(cls.split()[:2])
        parts.append(f'class="{short}"')
    text = (el.inner_text() or "").strip()[:40]
    if text:
        parts.append(f'text="{text}"')
    return " | ".join(parts)


def record(url: str, out: Path, headed: bool = True, user_dir: str = "./browser_profile") -> None:
    """Open a real browser and record clicks/typing/navigation + snapshots."""
    events: list[dict] = []
    snapshots: dict[str, str] = {}  # label -> html
    snap_counter = {"n": 0}

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=user_dir,
            headless=not headed,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1440, "height": 900},
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def snapshot(label: str):
            try:
                html = page.content()
                snap_counter["n"] += 1
                key = f"{snap_counter['n']:02d}_{label}"
                snapshots[key] = html
                events.append({"type": "snapshot", "key": key, "url": page.url,
                               "title": page.title(), "ts": datetime.now().isoformat()})
            except Exception as e:
                events.append({"type": "snapshot_error", "error": str(e),
                               "url": page.url})

        def on_click(msg):
            try:
                events.append({"type": "click",
                               "selector": _selector(msg.get("element")),
                               "tag": msg.get("element").evaluate("e=>e.tagName.toLowerCase()"),
                               "ts": datetime.now().isoformat()})
            except Exception:
                events.append({"type": "click", "raw": str(msg)[:200],
                               "ts": datetime.now().isoformat()})

        def on_fill(msg):
            events.append({"type": "fill",
                           "selector": _selector(msg.get("element")),
                           "value": (msg.get("value") or "")[:200],
                           "ts": datetime.now().isoformat()})

        def on_submit(msg):
            events.append({"type": "submit",
                           "selector": _selector(msg.get("element")),
                           "ts": datetime.now().isoformat()})

        page.on("click", on_click)
        page.on("fill", on_fill)
        page.on("submit", on_submit)

        def on_nav(frame):
            if frame == page.main_frame:
                events.append({"type": "goto", "url": frame.url,
                               "ts": datetime.now().isoformat()})
                # snapshot after a short settle
                page.wait_for_timeout(1500)
                snapshot("nav")

        page.on("framenavigated", on_nav)

        def on_request(r):
            if r.resource_type in ("xhr", "fetch") and "analytics" not in r.url:
                events.append({"type": "request",
                               "method": r.method, "url": r.url[:300],
                               "resource": r.resource_type,
                               "ts": datetime.now().isoformat()})

        page.on("request", on_request)

        page.goto(url, wait_until="domcontentloaded")
        snapshot("initial")

        print("\nBrowser open. Do the search manually:")
        print("  - accept cookies")
        print("  - type a query into the search box")
        print("  - click search / submit")
        print("  - open a result, scroll, go back")
        print("  - try filters, sort, pagination if you want")
        print("Close the window (or Ctrl+C) when finished.\n")

        try:
            while ctx.pages:
                page.wait_for_timeout(500)
        except KeyboardInterrupt:
            print("\ninterrupted by user")
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    out.parent.mkdir(parents=True, exist_ok=True)
    payload = {"url": url, "recorded_at": datetime.now().isoformat(),
               "events": events, "snapshots": snapshots}
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nSaved {len(events)} events + {len(snapshots)} snapshots to {out}")


def show(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"no such recording: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    events = data["events"]
    print(f"url        : {data['url']}")
    print(f"recorded   : {data['recorded_at']}")
    print(f"events     : {len(events)}")
    print(f"snapshots  : {len(data.get('snapshots', {}))}\n")
    for i, ev in enumerate(events):
        if ev["type"] == "snapshot":
            print(f"{i:>3}  SNAPSHOT  {ev['key']}  {ev['title'][:40]}")
        elif ev["type"] == "goto":
            print(f"{i:>3}  GOTO      {ev['url'][:70]}")
        elif ev["type"] in ("click", "fill", "submit"):
            print(f"{i:>3}  {ev['type'].upper():<7} {ev.get('selector','')[:80]}")
            if ev.get("value"):
                print(f"           value={ev['value']!r}")
        elif ev["type"] == "request":
            print(f"{i:>3}  REQUEST   {ev['method']} {ev['url'][:70]}")


def html_dump(path: Path, label: str | None = None) -> None:
    """Print one snapshot's HTML so I can inspect it."""
    if not path.exists():
        raise SystemExit(f"no such recording: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    snaps = data.get("snapshots", {})
    if not snaps:
        print("no snapshots in this recording")
        return
    if label is None:
        key = sorted(snaps)[0]
    else:
        key = next((k for k in snaps if label in k), None)
        if key is None:
            print("available snapshots:")
            for k in sorted(snaps):
                print("  ", k)
            return
    out = path.parent / f"{path.stem}_{key}.html"
    out.write_text(snaps[key], encoding="utf-8")
    print(f"wrote {out} ({len(snaps[key])} chars)")


def replay(path: Path, headed: bool = False) -> int:
    if not path.exists():
        raise SystemExit(f"no such recording: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    events = data["events"]
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
                    page.fill(ev["selector"].split(" | ")[0], ev["value"], timeout=8000)
                elif ev["type"] == "click":
                    page.click(ev["selector"].split(" | ")[0], timeout=8000)
                elif ev["type"] == "submit":
                    el = page.query_selector(ev["selector"].split(" | ")[0])
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("record", help="drive the browser and capture the flow")
    r.add_argument("url")
    r.add_argument("--out", required=True)
    r.add_argument("--headed", action="store_true", default=True,
                   help="show the browser (default: yes)")

    s = sub.add_parser("show", help="print a recording")
    s.add_argument("file")

    h = sub.add_parser("html", help="dump one snapshot's HTML for inspection")
    h.add_argument("file")
    h.add_argument("--label", default=None, help="substring of the snapshot key")

    p = sub.add_parser("replay", help="replay a recording to verify it")
    p.add_argument("file")
    p.add_argument("--headed", action="store_true")

    args = ap.parse_args()
    if args.cmd == "record":
        record(args.url, Path(args.out), args.headed)
    elif args.cmd == "show":
        show(Path(args.file))
    elif args.cmd == "html":
        html_dump(Path(args.file), args.label)
    else:
        raise SystemExit(replay(Path(args.file), args.headed))


if __name__ == "__main__":
    main()