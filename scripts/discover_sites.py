"""Discover site search/filter mappings and write sanitised profiles.

Usage:
    python scripts/discover_sites.py discover --all --headed
    python scripts/discover_sites.py discover --site alza --site mall
    python scripts/discover_sites.py validate --all

Raw controls, HTML and screenshots stay in git-ignored ``flows/``. Only the
sanitised YAML profile under ``src/searcher/site_profiles/`` is committed.
"""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qsl, quote_plus, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from src.searcher.adapters.base import BLOCK_MARKERS
from src.searcher.filter_engine import FilterEngine
from src.searcher.filters import SearchFilters
from src.searcher.selectors import get_selectors
from src.searcher.site_profiles import (
    PROFILE_DIR,
    ExtractionSpec,
    FilterSpec,
    ProfileFilters,
    SearchSpec,
    SiteProfile,
    UiFilterSpec,
    UrlFilterSpec,
    load_profile,
    save_profile,
)
from src.searcher.site_registry import SITES, SiteSpec, by_id, seed_query

DEFAULT_FLOWS_DIR = ROOT / "flows"
DEFAULT_STATE = ROOT / "data" / "discovery_state.json"
DEFAULT_REPORT_DIR = ROOT / "results"
DEFAULT_USER_DATA = ROOT / "browser_profile" / "discovery"

SEARCH_INPUT_SELECTORS = (
    'input[type="search"]',
    'input[name="q"]',
    'input[name="query"]',
    'input[name="search"]',
    'input[name="hledat"]',
    'input[name="hladat"]',
    'input[placeholder*="Hľadať" i]',
    'input[placeholder*="Hledat" i]',
    'input[placeholder*="Search" i]',
    'input[aria-label*="Hľadať" i]',
    'input[aria-label*="Search" i]',
)
COOKIE_SELECTORS = (
    'button:has-text("Prijať")',
    'button:has-text("Prijať všetko")',
    'button:has-text("Súhlasím")',
    'button:has-text("Souhlasím")',
    'button:has-text("Accept")',
    'button:has-text("Accept all")',
    'button[class*="accept"]',
    'button[id*="accept"]',
    '#onetrust-accept-btn-handler',
    '.cookie-accept',
)
SEARCH_NAMES = {"q", "query", "search", "hledat", "hladat", "searchtext"}

CSS_PATH_JS = r"""
el => {
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s)
    : String(s).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  if (el.id) return "#" + esc(el.id);
  for (const attr of ["data-testid", "data-qa", "name", "aria-label", "placeholder"]) {
    const value = el.getAttribute(attr);
    if (value) return el.tagName.toLowerCase() + "[" + attr + '="' + esc(value) + '"]';
  }
  let parts = [];
  let node = el;
  for (let i = 0; node && node.nodeType === 1 && i < 4; i++) {
    let part = node.tagName.toLowerCase();
    if (node.classList.length) {
      part += "." + [...node.classList].slice(0, 2).map(esc).join(".");
    }
    const parent = node.parentElement;
    if (parent) {
      const siblings = [...parent.children].filter((child) => child.tagName === node.tagName);
      if (siblings.length > 1) part += ":nth-of-type(" + (siblings.indexOf(node) + 1) + ")";
    }
    parts.unshift(part);
    node = node.parentElement;
  }
  return parts.join(" > ");
}
"""

CONTROL_JS = r"""
() => {
  const esc = (s) => (window.CSS && CSS.escape) ? CSS.escape(s)
    : String(s).replace(/[^a-zA-Z0-9_-]/g, "\\$&");
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    const style = getComputedStyle(el);
    return rect.width > 0 && rect.height > 0 &&
      style.visibility !== "hidden" && style.display !== "none";
  };
  const cssPath = (el) => {
    if (el.id) return "#" + esc(el.id);
    for (const attr of ["data-testid", "data-qa", "name", "aria-label", "placeholder"]) {
      const value = el.getAttribute(attr);
      if (value) return el.tagName.toLowerCase() + "[" + attr + '="' + esc(value) + '"]';
    }
    let parts = [];
    let node = el;
    for (let i = 0; node && node.nodeType === 1 && i < 4; i++) {
      let part = node.tagName.toLowerCase();
      if (node.classList.length) {
        part += "." + [...node.classList].slice(0, 2).map(esc).join(".");
      }
      const parent = node.parentElement;
      if (parent) {
        const siblings = [...parent.children].filter((child) => child.tagName === node.tagName);
        if (siblings.length > 1) part += ":nth-of-type(" + (siblings.indexOf(node) + 1) + ")";
      }
      parts.unshift(part);
      node = node.parentElement;
    }
    return parts.join(" > ");
  };
  const label = (el) => {
    const bits = [
      el.getAttribute("aria-label"), el.getAttribute("placeholder"),
      el.getAttribute("name"), el.id, el.getAttribute("title"),
    ];
    const wrapper = el.closest("label");
    if (wrapper) bits.push(wrapper.innerText);
    const previous = el.previousElementSibling;
    if (previous && previous.innerText) bits.push(previous.innerText);
    return bits.filter(Boolean).join(" ").replace(/\s+/g, " ").trim().slice(0, 160);
  };
  return [...document.querySelectorAll("input, select, textarea, button")]
    .filter(visible).slice(0, 250).map((el) => ({
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute("type") || "").toLowerCase(),
      name: el.getAttribute("name") || "",
      id: el.id || "",
      placeholder: el.getAttribute("placeholder") || "",
      aria_label: el.getAttribute("aria-label") || "",
      label: label(el),
      selector: cssPath(el),
      value: el.value || "",
      options: el.tagName.toLowerCase() === "select"
        ? [...el.options].map((option) => ({value: option.value, text: (option.textContent || "").trim()}))
        : [],
    }));
}
"""


def _norm(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _today():
    return datetime.now().astimezone().date()


def derive_search_spec(final_url: str, query: str) -> SearchSpec:
    """Turn the URL reached by typing *query* into a reusable template."""
    parts = urlsplit(final_url)
    pairs = parse_qsl(parts.query, keep_blank_values=True)
    wanted = _norm(query).strip()
    matched: str | None = None
    rendered: list[tuple[str, str]] = []
    for key, value in pairs:
        if matched is None and _norm(value).strip() == wanted:
            rendered.append((key, "{query}"))
            matched = key
            continue
        if matched is None and wanted and wanted in _norm(value):
            rendered.append((key, "{query}"))
            matched = key
            continue
        rendered.append((key, value))
    if matched is None:
        return SearchSpec(url_template=final_url)
    raw_query = "&".join(f"{key}={value}" for key, value in rendered)
    template = urlunsplit((parts.scheme, parts.netloc, parts.path, raw_query, parts.fragment))
    return SearchSpec(url_template=template, query_param=matched)


def derive_extraction(selector_key: str) -> ExtractionSpec:
    """Build extraction selectors from the existing selector table."""
    selectors = get_selectors(selector_key)
    condition = selectors.get("condition")
    if condition in {"new", "used", "refurbished", "open_box", "unknown"}:
        condition = None
    return ExtractionSpec(
        item_selector=selectors.get("listing"),
        title_selector=selectors.get("title"),
        price_selector=selectors.get("price"),
        link_selector=selectors.get("link"),
        image_selector=selectors.get("image"),
        condition_selector=condition,
        seller_selector=selectors.get("seller"),
        location_selector=selectors.get("location"),
    )


def classify_control(control: dict) -> str | None:
    """Map a discovered form control to a canonical filter key."""
    tag = str(control.get("tag") or "").lower()
    type_ = str(control.get("type") or "").lower()
    name = _norm(str(control.get("name") or "")).strip()
    if tag == "input" and (type_ == "search" or name in SEARCH_NAMES):
        return None

    label = _norm(
        " ".join(
            str(control.get(key) or "")
            for key in ("label", "aria_label", "placeholder", "name", "id")
        )
    )
    if not label.strip():
        return None

    if any(token in label for token in ("cena od", "min price", "price from", "od ceny", "cena min")):
        return "price_min"
    if any(token in label for token in ("cena do", "max price", "price to", "do ceny", "cena max")):
        return "price_max"
    if any(token in label for token in ("stav", "condition", "nové", "nove", "použité", "pouzite")):
        return "condition"
    if any(token in label for token in ("značka", "znacka", "brand", "výrobca", "vyrobca", "manufacturer")):
        return "brand"
    if any(token in label for token in ("lokalita", "location", "mesto", "city", "región", "region")):
        return "location"
    if any(token in label for token in ("doprava", "shipping", "poštovné", "postovne", "delivery")):
        return "shipping"
    if any(token in label for token in ("predajca", "seller", "obchod", "shop", "obchodník")):
        return "seller_type"
    if any(token in label for token in ("zoradiť", "zoradit", "triedenie", "sort", "order by")):
        return "sort"
    return None


def option_value_map(control: dict, canonical: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for option in control.get("options") or []:
        if not isinstance(option, dict):
            continue
        value = str(option.get("value") or option.get("text") or "").strip()
        text = _norm(str(option.get("text") or value))
        if not value:
            continue
        if canonical == "condition":
            if "rozbal" in text or "open box" in text or "openbox" in text:
                mapping["open_box"] = value
            elif "refurb" in text or "repas" in text or "rekonstru" in text:
                mapping["refurbished"] = value
            elif "nov" in text or "new" in text:
                mapping["new"] = value
            elif "použ" in text or "pouz" in text or "used" in text or "bazar" in text:
                mapping["used"] = value
        elif canonical == "shipping":
            if "zdarma" in text or "free" in text:
                mapping["free"] = value
            elif "plat" in text or "paid" in text:
                mapping["paid"] = value
        elif canonical == "sort":
            if "najlacn" in text or "cheap" in text:
                mapping["price_asc"] = value
            elif "najdrah" in text or "expensive" in text:
                mapping["price_desc"] = value
            elif "najnov" in text or "newest" in text or "latest" in text:
                mapping["newest"] = value
            elif "relevant" in text:
                mapping["relevance"] = value
        elif canonical == "seller_type":
            if "obchod" in text or "retail" in text or "shop" in text:
                mapping["retailer"] = value
            elif "bazar" in text or "classified" in text:
                mapping["classifieds"] = value
            elif "auk" in text or "auction" in text:
                mapping["auction"] = value
            elif "market" in text:
                mapping["marketplace"] = value
    return mapping


def control_to_filter_spec(control: dict, canonical: str) -> FilterSpec | None:
    selector = str(control.get("selector") or "").strip()
    if not selector:
        return None
    tag = str(control.get("tag") or "").lower()
    type_ = str(control.get("type") or "").lower()
    kind = "select"
    if tag != "select":
        if type_ in ("checkbox", "radio"):
            kind = type_
        elif tag == "button":
            kind = "button"
        else:
            kind = "input"
    value_map = option_value_map(control, canonical)
    name = str(control.get("name") or "").strip()
    url_spec = None
    if name and _norm(name) not in SEARCH_NAMES and type_ not in ("submit", "button", "search"):
        url_spec = UrlFilterSpec(param=name, value_map=value_map)
    return FilterSpec(
        url=url_spec,
        ui=UiFilterSpec(kind=kind, selector=selector, value_map=value_map),
        source="heuristic",
        confidence=0.55 if url_spec else 0.4,
        sample_value=str(control.get("label") or "")[:120] or None,
    )


def build_profile(
    site_id: str,
    base_url: str,
    final_url: str,
    query: str,
    category: str,
    controls: list[dict],
    extraction: ExtractionSpec,
    status: str,
    input_selector: str | None = None,
    notes: str = "",
) -> SiteProfile:
    search = derive_search_spec(final_url, query)
    search.input_selector = input_selector
    if category != "any" and search.url_template:
        search.category_urls[category] = search.url_template

    filters: dict[str, FilterSpec] = {}
    for control in controls:
        canonical = classify_control(control)
        if canonical is None or canonical in filters:
            continue
        spec = control_to_filter_spec(control, canonical)
        if spec is not None:
            filters[canonical] = spec

    return SiteProfile(
        site_id=site_id,
        base_url=base_url.rstrip("/"),
        status=status,
        last_verified=_today() if status == "validated" else None,
        search=search,
        filters=ProfileFilters(**filters),
        extraction=extraction,
        notes=notes,
    )


def _safe_text(element, default: str = "") -> str:
    try:
        return " ".join((element.inner_text() or "").split())
    except (PlaywrightError, AttributeError, TypeError):
        return default


def _accept_cookies(page) -> None:
    for selector in COOKIE_SELECTORS:
        try:
            button = page.query_selector(selector)
            if button and button.is_visible():
                button.click()
                page.wait_for_timeout(500)
                return
        except PlaywrightError:
            continue


def _find_search_input(page):
    for selector in SEARCH_INPUT_SELECTORS:
        try:
            element = page.query_selector(selector)
            if element and element.is_visible():
                return element, selector
        except PlaywrightError:
            continue
    return None, None


def _element_selector(element) -> str:
    try:
        return str(element.evaluate(CSS_PATH_JS))
    except PlaywrightError:
        return ""


def _page_state(page) -> str | None:
    try:
        url = (page.url or "").lower()
        title = (page.title() or "").lower()
        body = (page.locator("body").inner_text(timeout=5000) or "")[:5000].lower()
    except PlaywrightError:
        return None
    haystack = f"{url} {title}"
    for marker, _reason in BLOCK_MARKERS:
        if marker in haystack or marker in body[:2500]:
            return "blocked"
    for marker in ("log in to continue", "sign in to continue", "prihláste sa", "prihlaste sa"):
        if marker in body:
            return "needs_login"
    if any(part in url for part in ("/login", "checkpoint", "/signin")):
        return "needs_login"
    return None


def _intervene(page, state: str, pause: bool) -> str | None:
    if not pause:
        return state
    print(f"\n  Page needs attention: {state}")
    print("  Solve the challenge/login in the browser, then press Enter here.")
    try:
        input("  Enter when ready: ")
    except EOFError:
        return state
    page.wait_for_timeout(1000)
    return _page_state(page)


def _capture_controls(page) -> list[dict]:
    try:
        controls = page.evaluate(CONTROL_JS)
        return controls if isinstance(controls, list) else []
    except PlaywrightError:
        return []


def _capture_cards(page, extraction: ExtractionSpec) -> dict:
    selector = extraction.item_selector
    if not selector:
        return {"selector": None, "count": 0, "samples": []}
    try:
        elements = page.query_selector_all(selector)
    except PlaywrightError:
        return {"selector": selector, "count": 0, "samples": []}
    samples = []
    for element in elements[:5]:
        try:
            link = element.query_selector("a[href]")
            samples.append(
                {
                    "text": _safe_text(element)[:300],
                    "href": link.get_attribute("href") if link else "",
                }
            )
        except PlaywrightError:
            continue
    return {"selector": selector, "count": len(elements), "samples": samples}


def _write_raw(
    flows_dir: Path,
    site_id: str,
    category: str,
    payload: dict,
    page,
    save_html: bool,
    screenshots: bool,
) -> Path:
    site_dir = flows_dir / site_id
    site_dir.mkdir(parents=True, exist_ok=True)
    path = site_dir / f"{category}.json"
    if save_html:
        try:
            payload["html"] = page.content()
        except PlaywrightError:
            payload["html"] = ""
    if screenshots:
        shot = site_dir / f"{category}.png"
        try:
            page.screenshot(path=str(shot), full_page=False)
            payload["screenshot"] = str(shot)
        except PlaywrightError:
            pass
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def discover_site(
    site: SiteSpec,
    category: str,
    profile_dir: Path,
    flows_dir: Path,
    user_data_dir: Path,
    headless: bool,
    pause: bool,
    save_html: bool,
    screenshots: bool,
    force: bool,
    resume: bool = False,
) -> dict:
    existing = load_profile(site.id, profile_dir)
    if existing and existing.status == "validated" and resume and not force:
        return {"site_id": site.id, "status": "skipped", "reason": "validated profile exists"}

    query = seed_query(site.id, category)
    final_url = site.base_url
    controls: list[dict] = []
    cards = {"selector": None, "count": 0, "samples": []}
    state = None
    input_selector = None
    extraction = derive_extraction(site.adapter_class or site.id)
    html_saved = False

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1440, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(30000)
        try:
            page.goto(site.base_url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2000)
            _accept_cookies(page)
            state = _page_state(page)
            if state:
                state = _intervene(page, state, pause)
            if state is None:
                search_input, _matched = _find_search_input(page)
                if search_input is not None:
                    input_selector = _element_selector(search_input) or _matched
                    search_input.fill(query)
                    search_input.press("Enter")
                    try:
                        page.wait_for_load_state("domcontentloaded", timeout=30000)
                    except PlaywrightError:
                        pass
                    page.wait_for_timeout(3000)
                    _accept_cookies(page)
                else:
                    template = get_selectors(site.adapter_class or site.id).get("search_url_template")
                    if template:
                        page.goto(template.replace("{query}", quote_plus(query)),
                                  wait_until="domcontentloaded", timeout=45000)
                        page.wait_for_timeout(3000)
                        _accept_cookies(page)
                state = _page_state(page)
                if state:
                    state = _intervene(page, state, pause)
            final_url = page.url
            controls = _capture_controls(page)
            cards = _capture_cards(page, extraction)
            _write_raw(
                flows_dir,
                site.id,
                category,
                {
                    "site_id": site.id,
                    "category": category,
                    "query": query,
                    "base_url": site.base_url,
                    "final_url": final_url,
                    "state": state,
                    "controls": controls,
                    "cards": cards,
                    "captured_at": datetime.now().astimezone().isoformat(),
                },
                page,
                save_html,
                screenshots,
            )
            html_saved = save_html
        finally:
            try:
                context.close()
            except PlaywrightError:
                pass

    search_spec = derive_search_spec(final_url, query)
    has_query_url = bool(search_spec.query_param)
    if state == "blocked":
        status = "blocked"
        notes = "Anti-bot challenge prevented discovery."
    elif state == "needs_login":
        status = "needs_login"
        notes = "Login is required before discovery."
    elif cards["count"] > 0 and extraction.item_selector and has_query_url:
        status = "validated"
        notes = f"Found {cards['count']} result card(s) with {cards['selector']}."
    elif cards["count"] > 0 and extraction.item_selector:
        status = "draft"
        notes = "Cards found, but the search query is not present in the URL."
    elif extraction.item_selector:
        status = "draft"
        notes = "Search page captured, but no result cards matched the selector."
    else:
        status = "needs_manual"
        notes = "No search input, URL template or extraction selector found."

    profile = build_profile(
        site.id,
        site.base_url,
        final_url,
        query,
        category,
        controls,
        extraction,
        status,
        input_selector=input_selector,
        notes=notes,
    )
    save_profile(profile, profile_dir)
    return {
        "site_id": site.id,
        "status": status,
        "query": query,
        "cards": cards["count"],
        "controls": len(controls),
        "url_template": profile.search.url_template,
        "raw_html": html_saved,
        "notes": notes,
    }


def validate_profile(
    profile: SiteProfile,
    category: str,
    profile_dir: Path,
    user_data_dir: Path,
    headless: bool,
    pause: bool = True,
) -> dict:
    query = seed_query(profile.site_id, category)
    url = FilterEngine.build_search_url(profile, query, category, SearchFilters())
    if not url:
        profile.status = "needs_manual"
        profile.last_verified = None
        save_profile(profile, profile_dir)
        return {"site_id": profile.site_id, "status": "needs_manual", "cards": 0}
    selector = profile.extraction.item_selector
    count = 0
    page_state = None
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(user_data_dir),
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
            viewport={"width": 1440, "height": 900},
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(2500)
            _accept_cookies(page)
            page_state = _page_state(page)
            if page_state:
                page_state = _intervene(page, page_state, pause)
            if page_state not in ("blocked", "needs_login") and selector:
                try:
                    page.wait_for_selector(selector, timeout=15000)
                    count = len(page.query_selector_all(selector))
                except PlaywrightError:
                    count = 0
        finally:
            try:
                context.close()
            except PlaywrightError:
                pass
    if page_state in ("blocked", "needs_login"):
        profile.status = page_state
    else:
        profile.status = "validated" if count > 0 else "draft"
    profile.last_verified = _today() if profile.status == "validated" else None
    save_profile(profile, profile_dir)
    return {"site_id": profile.site_id, "status": profile.status, "cards": count}


def _default_category(site: SiteSpec) -> str:
    for category in ("electronics", "appliances", "auto", "general"):
        if category in site.categories:
            return category
    return "general"


def _selected_sites(args) -> list[SiteSpec]:
    if args.all:
        return list(SITES)
    specs = []
    for site_id in args.site or []:
        spec = by_id(site_id)
        if spec is None:
            print(f"Unknown site: {site_id}", file=sys.stderr)
            raise SystemExit(2)
        specs.append(spec)
    return specs


def _write_state(state_path: Path, result: dict) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            state = {}
    state[result["site_id"]] = result
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


def run_discover(args) -> int:
    specs = _selected_sites(args)
    if not specs:
        print("Choose --all or at least one --site.")
        return 2
    results = []
    for site in specs:
        category = args.category if args.category != "any" else _default_category(site)
        if args.category != "any" and args.category not in site.categories:
            results.append(
                {"site_id": site.id, "status": "skipped", "reason": "category not carried"}
            )
            continue
        print(f"\n[{site.id}] {site.name} / {category} / seed={seed_query(site.id, category)!r}")
        try:
            result = discover_site(
                site,
                category,
                args.profile_dir,
                args.flows_dir,
                args.user_data_dir,
                headless=not args.headless,
                pause=not args.no_pause,
                save_html=not args.no_html,
                screenshots=args.screenshots,
                force=args.force,
                resume=args.resume,
            )
        except Exception as exc:  # noqa: BLE001 - one site must not abort the batch
            result = {"site_id": site.id, "status": "failed", "error": str(exc)[:300]}
        results.append(result)
        _write_state(args.state, result)
        print(f"  -> {result.get('status')}: {result.get('notes') or result.get('reason', '')}")

    if args.report_dir:
        args.report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        report = args.report_dir / f"discovery_{stamp}.json"
        report.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nReport: {report}")
    return 0


def run_validate(args) -> int:
    if args.all:
        profiles = [load_profile(site.id, args.profile_dir) for site in SITES]
    else:
        profiles = [load_profile(site_id, args.profile_dir) for site_id in args.site or []]
    profiles = [profile for profile in profiles if profile is not None]
    if not profiles:
        print("No profiles found to validate.")
        return 2
    results = []
    for profile in profiles:
        category = args.category if args.category != "any" else next(
            iter(profile.search.category_urls), "electronics"
        )
        print(f"\n[{profile.site_id}] validating / {category}")
        try:
            result = validate_profile(
                profile,
                category,
                args.profile_dir,
                args.user_data_dir,
                headless=not args.headless,
                pause=not args.no_pause,
            )
        except Exception as exc:  # noqa: BLE001 - one site must not abort the batch
            result = {"site_id": profile.site_id, "status": "failed", "error": str(exc)[:300]}
        results.append(result)
        print(f"  -> {result.get('status')} ({result.get('cards', 0)} cards)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(target):
        target.add_argument("--site", action="append", help="Site id; repeat for multiple sites")
        target.add_argument("--all", action="store_true", help="Every registered site")
        target.add_argument("--category", default="any", help="electronics, appliances, auto, general, any")
        target.add_argument("--profile-dir", type=Path, default=PROFILE_DIR)
        target.add_argument("--user-data-dir", type=Path, default=DEFAULT_USER_DATA)
        display = target.add_mutually_exclusive_group()
        display.add_argument("--headed", dest="headless", action="store_false", help="Show the browser (default)")
        display.add_argument("--headless", dest="headless", action="store_true", help="Hide the browser")
        target.set_defaults(headless=False)
        target.add_argument("--no-pause", action="store_true", help="Do not wait for manual challenge/login")

    discover = sub.add_parser("discover", help="Record sites and write profiles")
    common(discover)
    discover.add_argument("--flows-dir", type=Path, default=DEFAULT_FLOWS_DIR)
    discover.add_argument("--state", type=Path, default=DEFAULT_STATE)
    discover.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    discover.add_argument("--resume", action="store_true", help="Skip validated profiles")
    discover.add_argument("--force", action="store_true", help="Rediscover validated profiles")
    discover.add_argument("--no-html", action="store_true", help="Do not store raw HTML")
    discover.add_argument("--screenshots", action="store_true", help="Store a PNG snapshot")
    discover.add_argument("--no-llm", action="store_true", help="Use heuristics only (current default)")

    validate = sub.add_parser("validate", help="Replay existing profiles and update status")
    common(validate)

    args = parser.parse_args()
    if args.command == "discover":
        return run_discover(args)
    return run_validate(args)


if __name__ == "__main__":
    raise SystemExit(main())
