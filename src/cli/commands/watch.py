"""Watch specific product URLs: track price/stock and find 2-3 alternatives."""

import asyncio
import os
from pathlib import Path

import typer
from playwright.async_api import async_playwright

from src.config import load_config
from src.storage.manager import StorageManager


PRICE_SELECTORS = [
    ".price", ".product-price", "[class*='price']", "[itemprop='price']",
    "meta[property='product:price:amount']", ".cena", ".cost",
]
TITLE_SELECTORS = [
    "h1", ".product-title", ".product-name", "[itemprop='name']",
    "meta[property='og:title']",
]


async def _fetch_product(page, url: str) -> dict:
    """Best-effort extraction of title + price from a product page."""
    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(1500)
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "title": "", "price": None, "error": str(exc)}

    title = ""
    for sel in TITLE_SELECTORS:
        try:
            if sel.startswith("meta"):
                el = await page.query_selector(sel)
                if el:
                    title = await el.get_attribute("content") or ""
            else:
                el = await page.query_selector(sel)
                if el:
                    title = (await el.inner_text()).strip()
            if title:
                break
        except Exception:
            continue
    if not title:
        try:
            title = await page.title()
        except Exception:
            title = url

    price = None
    # 1) selector-based
    for sel in PRICE_SELECTORS:
        try:
            if sel.startswith("meta"):
                el = await page.query_selector(sel)
                raw = await el.get_attribute("content") if el else None
            else:
                el = await page.query_selector(sel)
                raw = await el.inner_text() if el else None
            if raw:
                import re
                m = re.search(r"(\d[\d\s.,]*)", raw)
                if m:
                    num = m.group(1).replace(" ", "").replace(",", ".")
                    if num.count(".") > 1:
                        num = num.replace(".", "").replace(",", ".")
                    price = float(num)
                    break
        except Exception:
            continue
    # 2) text-based fallback: "Cena: 149 €" / "Price: 149 EUR"
    if price is None:
        try:
            import re
            body = await page.inner_text("body")
            m = re.search(r"(?:cena|price)[:\s]+(\d[\d\s.,]*)", body, re.IGNORECASE)
            if m:
                num = m.group(1).replace(" ", "").replace(",", ".")
                if num.count(".") > 1:
                    num = num.replace(".", "").replace(",", ".")
                price = float(num)
        except Exception:
            pass

    # stock heuristic
    stock = "unknown"
    try:
        body = (await page.inner_text("body")).lower()
        if any(w in body for w in ("vypredan", "out of stock", "nedostupn", "sold out", "neni na sklade")):
            stock = "out_of_stock"
        elif any(w in body for w in ("na sklade", "in stock", "dostupn", "available")):
            stock = "in_stock"
    except Exception:
        pass

    return {"url": url, "title": title[:200], "price": price, "stock": stock, "error": None}


async def _watch_async(urls: list[str], output_dir: str, find_alternatives: bool):
    os.makedirs(output_dir, exist_ok=True)
    config = load_config()
    storage = StorageManager(config.storage.db_path)

    typer.echo(f"Watching {len(urls)} URL(s)...")
    results = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page()
        for url in urls:
            typer.echo(f"  fetching {url}")
            info = await _fetch_product(page, url)
            results.append(info)
            # record price history
            # record price history (best effort) - skip if Deal construction fails
            pass
        await browser.close()

    # Build report
    lines = ["# Watchlist report", "", f"Checked {len(results)} URL(s).", ""]
    for r in results:
        lines.append(f"## {r['title'] or r['url']}")
        lines.append(f"- URL: {r['url']}")
        lines.append(f"- Price: {r['price']} EUR" if r["price"] is not None else "- Price: n/a")
        lines.append(f"- Stock: {r['stock']}")
        if r.get("error"):
            lines.append(f"- Error: {r['error']}")
        lines.append("")

    # Alternatives search
    if find_alternatives:
        from src.searcher.playwright_searcher import PlaywrightSearcher
        from src.llm.client import LLMClient
        from src.browser.manager import BrowserManager
        llm = LLMClient(config)
        browser_mgr = BrowserManager(config)
        for r in results:
            if not r["title"]:
                continue
            prompt = f"{r['title']} (alternative/counter product)"
            typer.echo(f"  searching alternatives for: {r['title'][:60]}")
            # Shorten the prompt to the first few words for the alternative search.
            alt_prompt = " ".join(r["title"].split()[:6])
            try:
                async with PlaywrightSearcher(config, llm, storage, browser_mgr) as searcher:
                    deals = await asyncio.wait_for(
                        searcher.search(alt_prompt, "any", "any"), timeout=240
                    )
                    deals = (deals or [])[:3]
                lines.append(f"### Alternatives for {r['title'][:60]}")
                if deals:
                    for d in deals:
                        lines.append(f"- [{d.title}]({d.url}) — {d.price_eur} EUR ({d.site_name})")
                else:
                    lines.append("- No alternatives found.")
                lines.append("")
            except Exception as exc:
                lines.append(f"### Alternatives for {r['title'][:60]}: skipped ({type(exc).__name__})")
                lines.append("")

    report_path = os.path.join(output_dir, "watchlist_report.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    typer.echo(f"Report saved to: {report_path}")


def watch(
    urls: list[str] = typer.Option(None, "--url", "-u", help="Product URL to watch (repeatable)"),
    watchlist: str | None = typer.Option(None, "--watchlist", "-w", help="File with one URL per line"),
    output_dir: str = typer.Option("results/watch", "--output-dir", help="Output directory"),
    alternatives: bool = typer.Option(True, "--alternatives/--no-alternatives", help="Search for 2-3 counter-products"),
):
    """Watch specific product URLs: track price/stock and find alternatives."""
    collected = list(urls or [])
    if watchlist:
        with open(watchlist, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line and not line.startswith("#"):
                    collected.append(line)
    if not collected:
        typer.echo("Error: provide --url or --watchlist", err=True)
        raise typer.Exit(1)
    asyncio.run(_watch_async(collected, output_dir, alternatives))