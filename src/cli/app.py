"""Auto Deal Searcher - Typer app factory."""

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass

import typer

from src.browser.manager import BrowserManager
from src.cli.commands.history import history_app
from src.cli.commands.monitor import monitor as monitor_fn
from src.config import load_config
from src.diagnostics.doctor import Doctor, print_doctor_results
from src.llm.client import LLMClient
from src.llm.health import run_checks as run_llm_checks
from src.output.domains import DOMAIN_REGISTRY, get
from src.output.processor import ResultProcessor
from src.scheduler.tasks import install_schedule, uninstall_schedule
from src.searcher.filters import (
    CATEGORIES,
    ResolvedRequest,
    SearchFilters,
    filters_from_mapping,
    from_cli,
    merge_filters,
    resolve_request,
)
from src.searcher.playwright_searcher import PlaywrightSearcher
from src.storage.manager import StorageManager

app = typer.Typer(help="Auto Deal Searcher — find deals across marketplaces")
app.add_typer(history_app, name="history")


async def _resolve_runtime_filters(
    config,
    prompt: str,
    llm,
    min_price=None,
    max_price=None,
    condition=None,
    brand=None,
    location=None,
    shipping=None,
    seller_type=None,
    sort=None,
    extra_filters=None,
) -> ResolvedRequest:
    """Merge config defaults, prompt extraction and CLI values (CLI wins).

    The merged filters come back inside a ``ResolvedRequest`` together with
    the category the model proposed for the prompt (``None`` when nothing
    usable arrived), so commands that pin their own category can ignore it.
    """
    config_filters = filters_from_mapping(config.search.default_filters)
    cli_filters = from_cli(
        min_price=min_price,
        max_price=max_price,
        condition=condition,
        brand=brand,
        location=location,
        shipping=shipping,
        seller_type=seller_type,
        sort=sort,
        extra_filters=extra_filters,
    )
    prompt_request = await resolve_request(prompt, SearchFilters(), llm)
    merged = merge_filters(
        merge_filters(config_filters, prompt_request.filters), cli_filters
    ).validate()
    return ResolvedRequest(filters=merged, category=prompt_request.category)


def _validate_category_arg(category: str | None) -> None:
    """Reject a misspelt --category early, listing what is allowed."""
    if category is not None and category not in (*CATEGORIES, "any"):
        msg = (
            f"unknown category '{category}'. Allowed: any, "
            + ", ".join(CATEGORIES)
        )
        raise ValueError(msg)



def _available_llm_backends(config) -> list[str]:
    """Return the LLM backends that are configured and usable."""
    backends: list[str] = []
    if getattr(config.llm, "local", None):
        backends.append("local")
    cloud_ok = False
    for api in getattr(config.llm, "api_fallback", []) or []:
        if os.environ.get(api.api_key_env, ""):
            cloud_ok = True
            break
    if cloud_ok:
        backends.append("cloud")
    return backends



@app.command()
def ask(
    country: str | None = typer.Option(None, "--country", help="Market; asked when omitted"),
    max_sites: int | None = typer.Option(None, "--max-sites", help="Max shops per round; asked when omitted"),
):
    """Prompt-only search: describe what you want, the app infers the rest."""
    asyncio.run(_ask_async(country, max_sites))


async def _ask_async(country: str | None, max_sites: int | None) -> None:
    config = load_config()

    typer.echo("")
    typer.echo("Auto Deal Searcher - prompt-only search")
    typer.echo("-" * 40)

    prompt = typer.prompt("What are you looking for?").strip()
    while not prompt:
        prompt = typer.prompt("Please type a description of what you want.").strip()

    backends = _available_llm_backends(config)
    llm_mode = None
    if len(backends) >= 2:
        typer.echo("")
        typer.echo("LLM backend:")
        for i, b in enumerate(backends, 1):
            label = "local (LM Studio/Ollama)" if b == "local" else "cloud (mistral/gemini/openrouter)"
            typer.echo(f"  {i}) {label}")
        choice = typer.prompt("Choose", default="2" if "cloud" in backends else "1", type=int)
        if 1 <= choice <= len(backends):
            llm_mode = backends[choice - 1]
        else:
            llm_mode = backends[-1] if "cloud" in backends else backends[0]
    elif len(backends) == 1:
        llm_mode = backends[0]

    if not country:
        country = typer.prompt("Country", default=config.search.user_country)
    if max_sites is None:
        max_sites = typer.prompt("Max shops", default=int(config.search.max_sites), type=int)

    typer.echo("")

    def _brief(b: SearchBrief) -> None:
        parts = [f"condition={b.condition}", f"category={b.category}"]
        if not b.inferred and b.category == "any":
            parts[-1] = "category=any (no model guess)"
        for key in ("min_price", "max_price", "brand", "location", "shipping", "seller_type", "sort"):
            value = getattr(b.filters, key)
            if value is not None:
                parts.append(f"{key}={value}")
        typer.echo("Understood: " + ", ".join(parts))

    def _plan(names: list[str]) -> None:
        typer.echo("Shops: " + ", ".join(names))

    outcome = await run_search(
        prompt,
        country=country.upper(),
        max_sites=int(max_sites),
        llm_mode=llm_mode,
        brief=_brief,
        plan=_plan,
    )
    typer.echo(f"Found {outcome.deal_count} deals. Results in {outcome.results_dir}/")
    typer.echo(f"JSON: {outcome.json_path}")
    typer.echo(f"Markdown: {outcome.md_path}")


@app.command()
def run(
    prompt: str | None = typer.Option(None, "--prompt", "-p", help="Search prompt (single-run mode)"),
    prompt_file: str | None = typer.Option(None, "--prompt-file", "-f", help="YAML file with prompt (auto mode)"),
    condition: str = typer.Option("any", "--condition", "-c", help="Filter: new, used, refurbished, open_box, any"),
    category: str | None = typer.Option(None, "--category", "-cat", help="Pin the category (electronics, appliances, auto, home, hobby, general, any). Default: inferred from the prompt."),
    winners: int | None = typer.Option(None, "--winners", "-w", help="Override winners_count from config"),
    output_format: str | None = typer.Option(None, "--format", help="Override output format: json, markdown, both"),
    min_price: str | None = typer.Option(None, "--min-price", help="Minimum price in EUR"),
    max_price: str | None = typer.Option(None, "--max-price", help="Maximum price in EUR"),
    brand: str | None = typer.Option(None, "--brand", help="Brand filter"),
    location: str | None = typer.Option(None, "--location", help="Location filter"),
    shipping: str | None = typer.Option(None, "--shipping", help="free or paid"),
    seller_type: str | None = typer.Option(None, "--seller-type", help="retailer, marketplace, classifieds, auction, private"),
    sort: str | None = typer.Option(None, "--sort", help="relevance, price_asc, price_desc, newest"),
    extra_filters: list[str] | None = typer.Option(None, "--filter", help="Extra filter KEY=VALUE (repeatable)"),  # noqa: B008
    country: str | None = typer.Option(None, "--country", help="Market to prefer, e.g. SK, CZ, DE"),
    max_sites: int | None = typer.Option(None, "--max-sites", help="How many shops to open per round"),
    llm: str | None = typer.Option(None, "--llm", help="LLM backend: local, cloud, or auto (default)"),
    domain: str | None = typer.Option(None, "--domain", help="Force a product domain (bike, computer, phone, car, furniture, generic)"),
):
    """Run a single search cycle."""
    asyncio.run(
        _run_async(
            prompt,
            prompt_file,
            condition,
            category,
            winners,
            output_format,
            min_price,
            max_price,
            brand,
            location,
            shipping,
            seller_type,
            sort,
            extra_filters,
            country,
            max_sites,
            domain=domain,
        )
    )


@dataclass
class SearchBrief:
    """What the pipeline understood from the request before searching."""

    filters: SearchFilters
    condition: str
    category: str
    inferred: bool = False


@dataclass
class SearchOutcome:
    """The result of one search cycle, for the caller to present."""

    deal_count: int
    sites: list[str]
    json_path: str
    md_path: str
    results_dir: str


async def run_search(
    prompt: str,
    *,
    condition: str = "any",
    category: str | None = None,
    winners: int | None = None,
    output_format: str | None = None,
    min_price: str | None = None,
    max_price: str | None = None,
    brand: str | None = None,
    location: str | None = None,
    shipping: str | None = None,
    seller_type: str | None = None,
    sort: str | None = None,
    extra_filters: list[str] | None = None,
    country: str | None = None,
    max_sites: int | None = None,
    llm_mode: str | None = None,
    domain: str | None = None,
    brief: Callable[[SearchBrief], None] | None = None,
    plan: Callable[[list[str]], None] | None = None,
) -> SearchOutcome:
    """One full search cycle: resolve, search, store, report. Prints nothing.

    ``brief`` sees the resolved filters before anything opens a browser and
    ``plan`` sees the chosen shop names; ``run`` and ``ask`` share this code
    and each presents the outcome in its own words.
    """
    config = load_config()

    # Restrict the LLM backend when the caller asked for one.
    if llm_mode == "local":
        config.llm.api_fallback = []
    elif llm_mode == "cloud":
        config.llm.local = []

    # Override config
    if winners:
        config.search.winners_count = winners
    if output_format:
        config.output.format = output_format
    if country:
        config.search.user_country = country.upper()
    if max_sites:
        config.search.max_sites = max_sites

    llm = LLMClient(config)
    try:
        _validate_category_arg(category)
        resolved = await _resolve_runtime_filters(
            config,
            prompt,
            llm,
            min_price=min_price,
            max_price=max_price,
            condition=condition,
            brand=brand,
            location=location,
            shipping=shipping,
            seller_type=seller_type,
            sort=sort,
            extra_filters=extra_filters,
        )
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None
    filters = resolved.filters
    if condition == "any" and filters.condition:
        condition = filters.condition
    # An explicit --category (including 'any') outranks the model's guess.
    effective_category = category if category else (resolved.category or "any")
    if brief:
        brief(
            SearchBrief(
                filters=filters,
                condition=condition,
                category=effective_category,
                inferred=bool(resolved.category),
            )
        )

    sites: list[str] = []

    def _capture_plan(names: list[str]) -> None:
        for name in names:
            if name not in sites:
                sites.append(name)
        if plan:
            plan(list(names))

    storage = StorageManager(config.storage.db_path)
    browser_mgr = BrowserManager(config)
    processor = ResultProcessor(config, llm)
    # --domain beats output.domain; the config value is already loaded in __init__.
    if domain:
        processor.domain_override = domain

    async with PlaywrightSearcher(config, llm, storage, browser_mgr) as searcher:
        try:
            deals = await searcher.search(
                prompt, condition, effective_category, filters, on_sites=_capture_plan
            )
        finally:
            await browser_mgr.close()

    # Prune missing (deals not found this run)
    storage.prune_missing(max_age_days=config.search.prune_after_days or 30)

    # Save new deals
    for deal in deals:
        storage.save_deal(deal)

    # Output (AI-named, timestamped)
    json_path, md_path = await processor.save_results(
        deals, config.output.directory, prompt=prompt
    )
    return SearchOutcome(
        deal_count=len(deals),
        sites=sites,
        json_path=json_path,
        md_path=md_path,
        results_dir=config.output.directory,
    )


async def _run_async(
    prompt,
    prompt_file,
    condition,
    category,
    winners,
    output_format,
    min_price=None,
    max_price=None,
    brand=None,
    location=None,
    shipping=None,
    seller_type=None,
    sort=None,
    extra_filters=None,
    country=None,
    max_sites=None,
    llm_mode=None,
    domain=None,
):
    if domain:
        try:
            get(domain)
        except KeyError:
            typer.echo(
                f"Error: unknown domain '{domain}'. Known domains: "
                f"{', '.join(sorted(DOMAIN_REGISTRY))}",
                err=True,
            )
            raise typer.Exit(1) from None

    # Resolve prompt
    if prompt_file:
        import yaml
        with open(prompt_file) as f:  # noqa: ASYNC230 - small CLI startup read
            data = yaml.safe_load(f)
            prompt = data.get("prompt", "")
    if not prompt:
        typer.echo("Error: Provide --prompt or --prompt-file", err=True)
        raise typer.Exit(1)

    outcome = await run_search(
        prompt,
        condition=condition,
        category=category,
        winners=winners,
        output_format=output_format,
        min_price=min_price,
        max_price=max_price,
        brand=brand,
        location=location,
        shipping=shipping,
        seller_type=seller_type,
        sort=sort,
        extra_filters=extra_filters,
        country=country,
        max_sites=max_sites,
        llm_mode=llm_mode,
        domain=domain,
    )
    typer.echo(f"Found {outcome.deal_count} deals. Results in {outcome.results_dir}/")


@app.command()
def diamond_search(
    prompt: str = typer.Option(..., "--prompt", "-p", help="Search prompt"),
    condition: str = typer.Option("any", "--condition", "-c", help="Filter: new, used, refurbished, open_box, any"),
    category: str = typer.Option("any", "--category", "-cat", help="Filter: electronics, appliances, auto, home, hobby, any"),
    winners: int = typer.Option(3, "--winners", "-w", help="How many ranked deals to keep"),
    output_dir: str = typer.Option("./results", "--output-dir", help="Where to write the ranking"),
    min_price: str | None = typer.Option(None, "--min-price", help="Minimum price in EUR"),
    max_price: str | None = typer.Option(None, "--max-price", help="Maximum price in EUR"),
    brand: str | None = typer.Option(None, "--brand", help="Brand filter"),
    location: str | None = typer.Option(None, "--location", help="Location filter"),
    shipping: str | None = typer.Option(None, "--shipping", help="free or paid"),
    seller_type: str | None = typer.Option(None, "--seller-type", help="retailer, marketplace, classifieds, auction, private"),
    sort: str | None = typer.Option(None, "--sort", help="relevance, price_asc, price_desc, newest"),
    extra_filters: list[str] | None = typer.Option(None, "--filter", help="Extra filter KEY=VALUE (repeatable)"),  # noqa: B008
    country: str | None = typer.Option(None, "--country", help="Market to prefer, e.g. SK, CZ, DE"),
    max_sites: int | None = typer.Option(None, "--max-sites", help="How many shops to open per round"),
):
    """Run the full 7-agent Diamond Search pipeline."""
    asyncio.run(
        _diamond_search_async(
            prompt,
            condition,
            category,
            winners,
            output_dir,
            min_price,
            max_price,
            brand,
            location,
            shipping,
            seller_type,
            sort,
            extra_filters,
            country,
            max_sites,
        )
    )


async def _diamond_search_async(
    prompt,
    condition,
    category,
    winners,
    output_dir,
    min_price=None,
    max_price=None,
    brand=None,
    location=None,
    shipping=None,
    seller_type=None,
    sort=None,
    extra_filters=None,
    country=None,
    max_sites=None,
):
    config = load_config()
    if not config.search.diamond_search.enabled:
        typer.echo("Error: diamond_search.enabled is false in config.yaml", err=True)
        raise typer.Exit(1)
    if country:
        config.search.user_country = country.upper()
    if max_sites:
        config.search.max_sites = max_sites

    llm = LLMClient(config)
    try:
        resolved = await _resolve_runtime_filters(
            config,
            prompt,
            llm,
            min_price=min_price,
            max_price=max_price,
            condition=condition,
            brand=brand,
            location=location,
            shipping=shipping,
            seller_type=seller_type,
            sort=sort,
            extra_filters=extra_filters,
        )
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None
    filters = resolved.filters
    if condition == "any" and filters.condition:
        condition = filters.condition

    storage = StorageManager(config.storage.db_path)
    browser_mgr = BrowserManager(config)
    processor = ResultProcessor(config)
    config.search.winners_count = winners

    async with PlaywrightSearcher(config, llm, storage, browser_mgr) as searcher:
        if not searcher.diamond_search_enabled:
            typer.echo("Error: Diamond Search agents unavailable", err=True)
            raise typer.Exit(1)
        try:
            deals = await searcher.search_with_diamond(prompt, condition, category, filters)
        finally:
            await browser_mgr.close()

    for deal in deals:
        storage.save_deal(deal)

    await processor.save_results(deals, output_dir, prompt=prompt)

    typer.echo(f"Diamond Search finished: {len(deals)} deals")
    for d in deals:
        score = getattr(d, "expert_score", None)
        suffix = f" [expert {score}]" if score else ""
        typer.echo(f"  {d.site_name:<10} {d.price_eur:>9.2f} EUR {d.condition:<10} {d.title[:48]}{suffix}")
    typer.echo(f"Results in {output_dir}/")


@app.command()
def selector_health(
    limit: int = typer.Option(20, "--limit", "-n", help="How many recent events to show"),
    summary: bool = typer.Option(False, "--summary", help="Show the aggregate summary only"),
):
    """Show recent selector-health events and the per-site summary."""
    from src.diagnostics.selector_health import SelectorHealthTracker

    tracker = SelectorHealthTracker()

    if not summary:
        events = SelectorHealthTracker.read_events(limit)
        if not events:
            typer.echo("No selector health events recorded yet.")
        else:
            typer.echo(f"\nRecent selector-health events (last {len(events)}):")
            typer.echo(f"{'timestamp':<26} {'site':<14} {'ok':<4} {'deals':>6} {'ms':>9}  blocked")
            typer.echo("-" * 86)
            for e in events:
                typer.echo(
                    f"{e['ts']:<26} {e['site']:<14} "
                    f"{'yes' if e['success_rate'] > 0 else 'no':<4} "
                    f"{e['avg_deals_per_search']:>6} {e['latency_ms']:>9}  {e['blocked']}"
                )

    summary_data = tracker.get_summary()
    typer.echo(f"\nSelector health summary: {summary_data['healthy_sites']}/{summary_data['total_sites']} healthy")
    for site_name, data in summary_data["sites"].items():
        mark = "OK " if data["is_healthy"] else "BAD"
        typer.echo(
            f"  [{mark}] {site_name:<14} {data['success_rate']:>6.1%} success  "
            f"{data['consecutive_failures']} consecutive failures  "
            f"{data['avg_deals']} avg deals"
        )


@app.command()
def local_state():
    """Show what is resident in the local LLM backends (read-only).

    Loads and unloads nothing. Use this to check whether another model is
    occupying LM Studio or Ollama before starting a run.
    """
    from src.llm.client import LLMClient

    llm = LLMClient(load_config())
    typer.echo(llm.describe_local_state())

    coord = llm._coordinator
    if coord is None:
        return
    our = {getattr(model, "model", "") for model in llm.llm_config.local}
    foreign = coord.foreign_models(our)
    typer.echo(f"\npolicy      : {coord.policy}")
    typer.echo(f"quiet window: {coord.quiet_seconds}s")
    if foreign:
        typer.echo("foreign models resident (we would wait, then unload after quiet):")
        for m in foreign:
            typer.echo(f"  - {m}")
    else:
        typer.echo("no foreign model resident — local backend is free")


@app.command()
def browsers():
    """List the browsers detected on this machine and which one is selected."""
    from src.browser.browsers import REGISTRY, detect_all, resolve

    cfg = load_config()
    typer.echo("\nDetected browsers:\n")
    found = {p.id: exe for p, exe in detect_all()}
    for profile in REGISTRY:
        exe = found.get(profile.id)
        mark = "installed" if exe else "not found"
        cdp = "CDP attach OK" if profile.supports_cdp else "no CDP (launch only)"
        typer.echo(f"  {profile.id:<10} {profile.name:<26} {mark:<10} {cdp}")
        if exe:
            typer.echo(f"             {exe}")

    try:
        exe, label = resolve(cfg.browser.browser_id, cfg.browser.browser_executable)
        typer.echo(f"\nSelected: {label}")
        typer.echo(f"           {exe or '(Playwright bundled Chromium)'}")
    except ValueError as e:
        typer.echo(f"\nSelection problem: {e}", err=True)
        raise typer.Exit(1) from None

    typer.echo('\nSet it in config.yaml under "browser: browser_id".')


@app.command()
def login_sites():
    """List sites that need a manual login and which sessions are saved."""
    from pathlib import Path as _Path

    from src.searcher.adapters import ADAPTER_REGISTRY

    cfg = load_config()
    configured = {s.strip().lower() for s in cfg.browser.login_sites}
    needed = configured | {name for name, cls in ADAPTER_REGISTRY.items()
                            if getattr(cls, "requires_login", False)}

    typer.echo("\nSites needing a manual login:\n")
    session_dir = _Path("data") / "sessions"
    for site in sorted(needed):
        if site not in ADAPTER_REGISTRY:
            typer.echo(f"  {site:<12} (unknown adapter id - check browser.login_sites)")
            continue
        path = session_dir / f"{site}.json"
        state = "session saved" if path.exists() else "NOT logged in"
        typer.echo(f"  {site:<12} {state}")
    typer.echo("\nLog in with:  python scripts/login.py --site <id>")
    typer.echo("Verify with:  python scripts/login.py --site <id> --check")


@app.command()
def schedule_install():
    """Install automated scheduled tasks (Windows Task Scheduler / cron)."""
    config = load_config()
    install_schedule(config)
    typer.echo("Scheduled tasks installed.")


@app.command()
def schedule_uninstall():
    """Remove automated scheduled tasks."""
    uninstall_schedule()
    typer.echo("Scheduled tasks removed.")


@app.command()
def config_check():
    """Validate config.yaml against schema."""
    config = load_config()
    typer.echo("✅ Config valid")
    typer.echo(f"  Sites enabled: {[s.name for s in config.search.websites if s.enabled]}")
    typer.echo(f"  LLM local: {config.llm.local[0].type if config.llm.local else 'none'}")
    typer.echo(f"  Winners: {config.search.winners_count}")


@app.command("llm-check")
def llm_check(
    prompt: str = typer.Option("Reply with OK.", "--prompt", help="Probe prompt"),
    timeout: float = typer.Option(20.0, "--timeout", help="Per cloud provider timeout (s)"),
    local_timeout: float = typer.Option(
        10.0, "--local-timeout", help="Per local provider timeout (s)"
    ),
    local: bool = typer.Option(True, "--local/--no-local", help="Probe local models"),
    cloud: bool = typer.Option(True, "--cloud/--no-cloud", help="Probe cloud APIs"),
):
    """Probe every configured LLM provider and show which ones actually work."""
    config = load_config()
    statuses = asyncio.run(
        run_llm_checks(
            config,
            local=local,
            cloud=cloud,
            request_timeout=timeout,
            local_timeout=local_timeout,
            prompt=prompt,
        )
    )
    if not statuses:
        typer.echo(
            "No LLM providers configured (llm.local / llm.api_fallback in config.yaml)."
        )
        raise typer.Exit(code=1)

    typer.echo(f"{'provider':<12} {'kind':<6} {'status':<8} {'latency':>8}  model")
    typer.echo("-" * 60)
    for status in statuses:
        latency = f"{status.latency:.2f}s" if status.latency else "-"
        typer.echo(
            f"{status.provider:<12} {status.kind:<6} {status.status:<8} "
            f"{latency:>8}  {status.model}"
        )
        if status.detail:
            typer.echo(f"{'':<12} {status.detail}")
        if status.hint:
            typer.echo(f"{'':<12} hint: {status.hint}")

    healthy = sum(1 for status in statuses if status.ok)
    typer.echo("")
    typer.echo(f"{healthy}/{len(statuses)} providers healthy")
    if healthy == 0:
        raise typer.Exit(code=1)


@app.command()
def doctor(
    site: str | None = typer.Option(None, "--site", "-s", help="Check specific site only"),
    offline: bool = typer.Option(False, "--offline", help="Check config only, no network"),
):
    """Run site health diagnostics."""
    asyncio.run(_doctor_async(site, offline))


async def _doctor_async(site: str | None, offline: bool):
    config = load_config()
    doctor = Doctor(config)
    
    if site:
        result = await doctor.check_site(site, live=not offline)
        print_doctor_results([result])
    else:
        results = await doctor.check_all(live=not offline)
        print_doctor_results(results)


@app.command()
def search(
    prompt: str = typer.Option(..., "--prompt", "-p", help="Search prompt (e.g., 'DJI drone under 350 euros')"),
    condition: str = typer.Option("any", "--condition", "-c", help="Filter: new, used, refurbished, open_box, any"),
    category: str = typer.Option("any", "--category", "-cat", help="Filter: electronics, appliances, auto, home, hobby, any"),
    winners: int = typer.Option(3, "--winners", "-w", help="How many ranked deals to keep"),
    output_dir: str = typer.Option("./results", "--output-dir", help="Output directory for results"),
    max_pages: int = typer.Option(5, "--max-pages", help="Max pages per site"),
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run browser headless"),
    min_price: str | None = typer.Option(None, "--min-price", help="Minimum price in EUR"),
    max_price: str | None = typer.Option(None, "--max-price", help="Maximum price in EUR"),
    brand: str | None = typer.Option(None, "--brand", help="Brand filter"),
    location: str | None = typer.Option(None, "--location", help="Location filter"),
    shipping: str | None = typer.Option(None, "--shipping", help="free or paid"),
    seller_type: str | None = typer.Option(None, "--seller-type", help="retailer, marketplace, classifieds, auction, private"),
    sort: str | None = typer.Option(None, "--sort", help="relevance, price_asc, price_desc, newest"),
    extra_filters: list[str] | None = typer.Option(None, "--filter", help="Extra filter KEY=VALUE (repeatable)"),  # noqa: B008
    country: str | None = typer.Option(None, "--country", help="Market to prefer, e.g. SK, CZ, DE"),
    max_sites: int | None = typer.Option(None, "--max-sites", help="How many shops to open per round"),
):
    """AI-powered search across multiple sites with LLM judgment."""
    asyncio.run(
        _search_async(
            prompt,
            condition,
            category,
            winners,
            output_dir,
            max_pages,
            headless,
            min_price,
            max_price,
            brand,
            location,
            shipping,
            seller_type,
            sort,
            extra_filters,
            country,
            max_sites,
        )
    )


async def _search_async(
    prompt,
    condition,
    category,
    winners,
    output_dir,
    max_pages,
    headless,
    min_price=None,
    max_price=None,
    brand=None,
    location=None,
    shipping=None,
    seller_type=None,
    sort=None,
    extra_filters=None,
    country=None,
    max_sites=None,
):
    config = load_config()
    config.search.winners_count = winners
    if country:
        config.search.user_country = country.upper()
    if max_sites:
        config.search.max_sites = max_sites

    llm = LLMClient(config)
    try:
        resolved = await _resolve_runtime_filters(
            config,
            prompt,
            llm,
            min_price=min_price,
            max_price=max_price,
            condition=condition,
            brand=brand,
            location=location,
            shipping=shipping,
            seller_type=seller_type,
            sort=sort,
            extra_filters=extra_filters,
        )
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None
    filters = resolved.filters
    if condition == "any" and filters.condition:
        condition = filters.condition

    storage = StorageManager(config.storage.db_path)
    browser_mgr = BrowserManager(config)

    typer.echo(f"Searching for: {prompt}")
    typer.echo(f"Condition: {condition}, Category: {category}, Winners: {winners}")

    async with PlaywrightSearcher(config, llm, storage, browser_mgr) as searcher:
        try:
            deals = await searcher.search(prompt, condition, category, filters)
        finally:
            await browser_mgr.close()

    # Save results
    for deal in deals:
        storage.save_deal(deal)
    processor = ResultProcessor(config, llm)
    await processor.save_results(deals, output_dir, prompt=prompt)

    typer.echo(f"Found {len(deals)} deals")
    for d in deals[:winners]:
        typer.echo(f"  {d.site_name:<10} {d.price_eur:>9.2f} EUR {d.condition:<10} {d.title[:50]}")

    typer.echo(f"Results in {output_dir}/")


@app.command()
def monitor(
    prompt_file: str | None = typer.Option(None, "--prompt-file", "-f", help="YAML file with prompt (auto mode)"),
    interval_hours: int = typer.Option(12, "--interval", "-i", help="Interval between runs in hours"),
    max_runs: int = typer.Option(0, "--max-runs", "-m", help="Maximum runs (0 = infinite)"),
    output_dir: str = typer.Option("results/monitoring", "--output-dir", help="Output directory for reports"),
    price_drop_threshold: float = typer.Option(10.0, "--price-drop-threshold", help="Alert threshold for price drops (%)"),
):
    """Run continuous monitoring with intelligent change detection."""
    monitor_fn(prompt_file, interval_hours, max_runs, output_dir, price_drop_threshold)


if __name__ == "__main__":
    app()