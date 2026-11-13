"""Auto Deal Searcher - Typer app factory."""

import asyncio
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass

import typer

from src.browser.manager import BrowserManager
from src.cli.commands.history import history_app
from src.cli.commands.monitor import monitor as monitor_fn
from src.cli.commands.schedule import schedule_app
from src.cli.commands.watch import watch as watch_fn
from src.config import load_config
from src.config.models import Category, Condition
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
from src.cli.search_service import (
    SearchContext,
    SearchResult,
    build_context,
    build_notification_manager,
    run_pipeline,
)


def _load_config(*args, **kwargs):
    config = load_config(*args, **kwargs)
    from src.searcher.currency import set_rates

    set_rates(getattr(getattr(config, "search", None), "currency_rates", None))
    return config


logger = logging.getLogger(__name__)

app = typer.Typer(help="Auto Deal Searcher — find deals across marketplaces")
app.add_typer(history_app, name="history")
app.add_typer(schedule_app, name="schedule")


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
    if category is not None and category not in (*CATEGORIES, Category.ANY):
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



def _split_sites(raw: str | None) -> list[str] | None:
    """Parse a comma-separated --sites value."""
    if not raw:
        return None
    values = [part.strip() for part in raw.split(",") if part.strip()]
    return values or None


@app.command()
def ask(
    country: str | None = typer.Option(None, "--country", help="Market; asked when omitted"),
    max_sites: int | None = typer.Option(None, "--max-sites", help="Optional cap; omit for all suitable shops"),
    sites: str | None = typer.Option(None, "--sites", help="Comma-separated shop ids; overrides automatic selection"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Verbose LLM provider diagnostics"),
):
    """Prompt-only search: describe what you want, the app infers the rest."""
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')
    asyncio.run(_ask_async(country, max_sites, _split_sites(sites), debug))


async def _ask_async(
    country: str | None,
    max_sites: int | None,
    sites: list[str] | None = None,
    debug: bool = False,
) -> None:
    config = _load_config()
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')

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

    typer.echo("")

    def _brief(b: SearchBrief) -> None:
        parts = [f"condition={b.condition}", f"category={b.category}"]
        _category = b.category.value if hasattr(b.category, "value") else str(b.category)
        if not b.inferred and _category == Category.ANY:
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
        max_sites=max_sites,
        sites=sites,
        llm_mode=llm_mode,
        debug=debug,
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
    max_sites: int | None = typer.Option(None, "--max-sites", help="Optional cap; omit for all suitable shops"),
    sites: str | None = typer.Option(None, "--sites", help="Comma-separated shop ids; overrides automatic selection"),
    llm: str | None = typer.Option(None, "--llm", help="LLM backend: local, cloud, or auto (default)"),
    debug: bool = typer.Option(False, "--debug", "-d", help="Verbose LLM provider diagnostics"),
    domain: str | None = typer.Option(None, "--domain", help="Force a product domain (bike, computer, phone, car, furniture, generic)"),
):
    """Run a single search cycle."""
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')
    asyncio.run(
        run_async(
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
            sites=_split_sites(sites),
            llm_mode=llm,
            debug=debug,
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
    json_path: str | None
    md_path: str | None
    results_dir: str


async def run_search(
    prompt: str,
    *,
    condition: str = Condition.ANY,
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
    sites: list[str] | None = None,
    llm_mode: str | None = None,
    debug: bool = False,
    domain: str | None = None,
    brief: Callable[[SearchBrief], None] | None = None,
    plan: Callable[[list[str]], None] | None = None,
) -> SearchOutcome:
    """One full search cycle: resolve, search, store, report. Prints nothing.

    ``brief`` sees the resolved filters before anything opens a browser and
    ``plan`` sees the chosen shop names; ``run`` and ``ask`` share this code
    and each presents the outcome in its own words.
    """
    config = _load_config()

    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')

    # Restrict the LLM backend when the caller asked for one.
    if llm_mode == "local":
        config.llm.api_fallback = []
    elif llm_mode == "cloud":
        config.llm.local = []

    # Override config
    if winners:
        config.search.winners_count = winners
    if output_format:
        config.output.format = output_format  # type: ignore[assignment]
    if country:
        config.search.user_country = country.upper()
    if max_sites is not None:
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
    if condition == Condition.ANY and filters.condition:
        condition = filters.condition
    # An explicit --category (including 'any') outranks the model's guess.
    effective_category = category if category else (resolved.category or Category.ANY)
    if brief:
        brief(
            SearchBrief(
                filters=filters,
                condition=condition,
                category=effective_category,
                inferred=bool(resolved.category),
            )
        )

    selected_sites: list[str] = []

    def _capture_plan(names: list[str]) -> None:
        for name in names:
            if name not in selected_sites:
                selected_sites.append(name)
        if plan:
            plan(list(names))

    ctx = await build_context(
        config,
        brand_filter=filters.brand,
        llm_class=LLMClient,
        storage_class=StorageManager,
        browser_manager_class=BrowserManager,
        processor_class=ResultProcessor,
    )
    result = await run_pipeline(
        prompt,
        condition,
        effective_category,
        filters,
        sites,
        ctx,
        on_sites=_capture_plan,
        searcher_class=PlaywrightSearcher,
    )
    return SearchOutcome(
        deal_count=len(result.deals),
        sites=selected_sites,
        json_path=result.json_path,
        md_path=result.md_path,
        results_dir=result.results_dir,
    )


async def run_async(
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
    sites=None,
    llm_mode=None,
    debug=False,
    domain=None,
):
    if debug:
        import logging
        logging.basicConfig(level=logging.DEBUG, format='%(name)s: %(message)s')
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
        sites=sites,
        llm_mode=llm_mode,
        debug=debug,
        domain=domain,
    )
    typer.echo(f"Found {outcome.deal_count} deals. Results in {outcome.results_dir}/")


@app.command()
def diamond_search(
    prompt: str = typer.Option(..., "--prompt", "-p", help="Search prompt"),
    condition: str = typer.Option("any", "--condition", "-c", help="Filter: new, used, refurbished, open_box, any"),
    category: str = typer.Option("any", "--category", "-cat", help="Filter: electronics, appliances, auto, home, hobby, any"),
    winners: int = typer.Option(3, "--winners", "-w", help="How many ranked deals to keep"),
    output_dir: str = typer.Option("./reports", "--output-dir", help="Where to write the ranking"),
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
    config = _load_config()
    if not config.search.diamond_search.enabled:
        typer.echo("Error: diamond_search.enabled is false in config.yaml", err=True)
        raise typer.Exit(1)
    if country:
        config.search.user_country = country.upper()
    if max_sites is not None:
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
    if condition == Condition.ANY and filters.condition:
        condition = filters.condition

    ctx = await build_context(
        config,
        brand_filter=filters.brand,
        llm_class=LLMClient,
        storage_class=StorageManager,
        browser_manager_class=BrowserManager,
        processor_class=ResultProcessor,
    )
    try:
        result = await run_pipeline(
            prompt,
            condition,
            category,
            filters,
            None,
            ctx,
            diamond=True,
            output_dir=output_dir,
            searcher_class=PlaywrightSearcher,
        )
    except RuntimeError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None

    typer.echo(f"Diamond Search finished: {len(result.deals)} deals")
    for d in result.deals:
        score = getattr(d, "expert_score", None)
        suffix = f" [expert {score}]" if score else ""
        typer.echo(f"  {d.site_name:<10} {d.price_eur:>9.2f} EUR {d.condition:<10} {d.title[:48]}{suffix}")
    typer.echo(f"Results in {result.results_dir}/")


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

    llm = LLMClient(_load_config())
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

    cfg = _load_config()
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
def sites(
    all_sites: bool = typer.Option(False, "--all", help="Include disabled sites"),
    status: str | None = typer.Option(None, "--status", help="Filter by registry status"),
):
    """List catalogue sites, enabled state and profile readiness."""
    from src.searcher.site_profiles import load_profiles
    from src.searcher.site_registry import SITES

    config = _load_config()
    enabled = {site.name for site in config.search.websites if site.enabled}
    profiles = load_profiles()
    rows = []
    for spec in SITES:
        if status and spec.status != status:
            continue
        if not all_sites and spec.id not in enabled:
            continue
        profile = profiles.get(spec.id)
        rows.append(
            (
                spec.id,
                spec.status,
                "enabled" if spec.id in enabled else "disabled",
                "ready" if profile and profile.is_runtime_ready else "none",
                spec.name,
            )
        )
    if not rows:
        typer.echo("No sites match.")
        return
    typer.echo(f"{'id':<18} {'status':<12} {'config':<10} {'profile':<8} name")
    for site_id, site_status, config_state, profile_state, name in rows:
        typer.echo(
            f"{site_id:<18} {site_status:<12} {config_state:<10} "
            f"{profile_state:<8} {name}"
        )


@app.command()
def login_sites():
    """List sites that need a manual login and which sessions are saved."""
    from src.searcher.adapters import ADAPTER_REGISTRY
    from src.searcher.sessions import has_session

    cfg = _load_config()
    configured = {s.strip().lower() for s in cfg.browser.login_sites}
    needed = configured | {name for name, cls in ADAPTER_REGISTRY.items()
                            if getattr(cls, "requires_login", False)}

    typer.echo("\nSites needing a manual login:\n")
    for site in sorted(needed):
        state = "session saved" if has_session(site) else "NOT logged in"
        typer.echo(f"  {site:<12} {state}")
    typer.echo("\nLog in with:  python scripts/login.py --site <id>")
    typer.echo("Verify with:  python scripts/login.py --site <id> --check")


@app.command()
def schedule_install():
    """Install automated scheduled tasks (Windows Task Scheduler / cron)."""
    config = _load_config()
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
    config = _load_config()
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
    config = _load_config()
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
    asyncio.run(doctor_async(site, offline))


async def doctor_async(site: str | None, offline: bool):
    config = _load_config()
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
    output_dir: str = typer.Option("./reports", "--output-dir", help="Output directory for results"),
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
    max_sites: int | None = typer.Option(None, "--max-sites", help="Optional cap; omit for all suitable shops"),
    sites: str | None = typer.Option(None, "--sites", help="Comma-separated shop ids; overrides automatic selection"),
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
            sites=_split_sites(sites),
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
    sites=None,
):
    config = _load_config()
    config.search.winners_count = winners
    if country:
        config.search.user_country = country.upper()
    if max_sites is not None:
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
    if condition == Condition.ANY and filters.condition:
        condition = filters.condition

    typer.echo(f"Searching for: {prompt}")
    typer.echo(f"Condition: {condition}, Category: {category}, Winners: {winners}")

    ctx = await build_context(
        config,
        brand_filter=filters.brand,
        llm_class=LLMClient,
        storage_class=StorageManager,
        browser_manager_class=BrowserManager,
        processor_class=ResultProcessor,
    )
    result = await run_pipeline(
        prompt,
        condition,
        category,
        filters,
        sites,
        ctx,
        output_dir=output_dir,
        searcher_class=PlaywrightSearcher,
    )

    typer.echo(f"Found {len(result.deals)} deals")
    for d in result.deals[:winners]:
        typer.echo(f"  {d.site_name:<10} {d.price_eur:>9.2f} EUR {d.condition:<10} {d.title[:50]}")

    typer.echo(f"Results in {result.results_dir}/")


@app.command("discover-web")
def discover_web(
    prompt: str = typer.Option(..., "--prompt", "-p", help="Product query to search for"),
    limit: int = typer.Option(10, "--limit", help="Maximum result domains"),
    output_dir: str = typer.Option("data", "--output-dir", help="Where to write the proposal JSON"),
):
    """Find shops outside the catalogue without opening them."""
    from src.research.site_discovery import discover_domains, save_discovery_report

    domains = discover_domains(prompt, max_results=limit)
    if not domains:
        typer.echo("No domains found.", err=True)
        raise typer.Exit(1)

    path = save_discovery_report(prompt, domains, output_dir)
    known = [item for item in domains if item.known_id]
    new = [item for item in domains if not item.known_id]
    typer.echo(f"\nKnown catalogue shops ({len(known)}):")
    for item in known:
        typer.echo(f"  {item.known_id:<16} {item.status:<12} {item.url}")
    typer.echo(f"\nNew domains ({len(new)}):")
    for item in new:
        typer.echo(f"  {item.domain:<28} {item.title[:60]}")
        typer.echo(f"    {item.url}")
    typer.echo(f"\nProposal written to: {path}")
    typer.echo(
        "Review a new domain, add a SiteSpec, then run: "
        "python scripts/discover_sites.py discover --site <id>"
    )


@app.command()
def monitor(
    prompt_file: str | None = typer.Option(None, "--prompt-file", "-f", help="YAML file with prompt (auto mode)"),
    interval_hours: int = typer.Option(12, "--interval", "-i", help="Interval between runs in hours"),
    max_runs: int = typer.Option(0, "--max-runs", "-m", help="Maximum runs (0 = infinite)"),
    output_dir: str = typer.Option("reports/monitoring", "--output-dir", help="Output directory for reports"),
    price_drop_threshold: float = typer.Option(10.0, "--price-drop-threshold", help="Alert threshold for price drops (%)"),
):
    """Run continuous monitoring with intelligent change detection."""
    monitor_fn(prompt_file, interval_hours, max_runs, output_dir, price_drop_threshold)


@app.command()
def watch(
    urls: list[str] | None = typer.Option(None, "--url", "-u", help="Product URL to watch (repeatable)"),
    watchlist: str | None = typer.Option(None, "--watchlist", "-w", help="File with one URL per line"),
    output_dir: str = typer.Option("reports/watch", "--output-dir", help="Output directory"),
    alternatives: bool = typer.Option(True, "--alternatives/--no-alternatives", help="Search for 2-3 counter-products"),
):
    """Watch specific product URLs: track price/stock and find alternatives."""
    watch_fn(urls or [], watchlist, output_dir, alternatives)


@app.command()
def research_specs(
    item: str = typer.Option(..., "--item", "-i", help="Item name to research (e.g. 'Citroen eC3')"),
    category: str | None = typer.Option(None, "--category", "-cat", help="Category: auto, electronics, appliances, home, hobby, general"),
    output_dir: str = typer.Option("reports/specs", "--output-dir", help="Output directory for specs JSON"),
):
    """Research specs and reviews for an item (foundation for replacement finder)."""
    import json
    from pathlib import Path

    from src.intelligence.specs_researcher import ItemSpecsResearcher
    from src.storage.manager import StorageManager

    config = _load_config()
    storage = StorageManager(config.storage.db_path)
    researcher = ItemSpecsResearcher(storage=storage, config=config)

    specs = researcher.research(item, category=category)

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-z0-9]+", "-", item.lower()).strip("-")
    out_path = out_dir / f"specs_{safe_name}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(specs.to_dict(), f, indent=2, ensure_ascii=False)

    typer.echo(f"Specs researched for: {specs.item_name}")
    typer.echo(f"  Category: {specs.category}")
    typer.echo(f"  Brand: {specs.brand or 'n/a'}  Model: {specs.model or 'n/a'}  Year: {specs.year or 'n/a'}")
    if specs.price_eur:
        typer.echo(f"  Price: {specs.price_eur:.2f} EUR")
    if specs.power_kw:
        typer.echo(f"  Power: {specs.power_kw} kW ({specs.power_hp or 'n/a'} hp)")
    if specs.battery_kwh:
        typer.echo(f"  Battery: {specs.battery_kwh} kWh  Range: {specs.range_km or 'n/a'} km")
    if specs.weight_kg:
        typer.echo(f"  Weight: {specs.weight_kg} kg")
    if specs.review.summary:
        typer.echo(f"  Review: {specs.review.summary}")
    if specs.review.pros:
        typer.echo(f"  Pros: {', '.join(specs.review.pros)}")
    if specs.review.cons:
        typer.echo(f"  Cons: {', '.join(specs.review.cons)}")
    typer.echo(f"  Sources: {len(specs.source_urls)}")
    typer.echo(f"  Saved to: {out_path}")


@app.command()
async def find_replacement(
    item: str = typer.Option("", "--item", "-i", help="Reference item (e.g. 'Citroen eC3')"),
    interactive: bool = typer.Option(False, "--interactive", "-I", help="Interactive wizard mode"),
    category: str | None = typer.Option(None, "--category", "-cat", help="Category override"),
    condition: str = typer.Option("any", "--condition", "-c", help="Filter: new, used, refurbished, open_box, any"),
    max_price: str | None = typer.Option(None, "--max-price", help="Maximum price in EUR"),
    min_price: str | None = typer.Option(None, "--min-price", help="Minimum price in EUR"),
    winners: int = typer.Option(3, "--winners", "-w", help="How many top candidates to show"),
    output_dir: str = typer.Option("reports/replacement", "--output-dir", help="Output directory"),
):
    """Find replacement alternatives for a reference item.

    Researches the reference item's specs, searches for similar items,
    scores them by spec match, and ranks the best alternatives.
    """
    import json
    from pathlib import Path

    from src.cli.search_service import build_context, run_pipeline
    from src.intelligence.comparison_engine import ComparisonEngine
    from src.intelligence.specs_researcher import ItemSpecsResearcher
    from src.llm.client import LLMClient
    from src.searcher.filter_extractor import extract_filters_from_specs, to_search_filters
    from src.storage.manager import StorageManager

    config = _load_config()
    storage = StorageManager(config.storage.db_path)
    llm = LLMClient(config)

    # Interactive wizard mode
    if interactive or not item:
        from src.cli.wizard import run_wizard

        wizard_result = run_wizard()
        item = wizard_result["item"]
        category = wizard_result["category"] or category
        condition = wizard_result["condition"] or condition
        min_price = str(wizard_result["min_price"]) if wizard_result["min_price"] is not None else min_price
        max_price = str(wizard_result["max_price"]) if wizard_result["max_price"] is not None else max_price

    if not item:
        typer.echo("Error: --item is required (or use --interactive)", err=True)
        raise typer.Exit(1)

    # Step 1: Research reference item specs
    typer.echo(f"Researching specs for: {item}")
    researcher = ItemSpecsResearcher(storage=storage, config=config)
    specs = researcher.research(item, category=category)
    specs_dict = specs.to_dict()

    # Step 2: Convert specs to search filters
    extracted = extract_filters_from_specs(specs_dict)
    if min_price:
        extracted.min_price = float(min_price)
    if max_price:
        extracted.max_price = float(max_price)
    if condition != Condition.ANY:
        extracted.condition = condition
    search_filters = to_search_filters(extracted)

    typer.echo(f"  Category: {specs.category}  Brand: {specs.brand or 'n/a'}  Model: {specs.model or 'n/a'}")
    if specs.price_eur:
        typer.echo(f"  Reference price: {specs.price_eur:.2f} EUR")
    if specs.power_kw:
        typer.echo(f"  Reference power: {specs.power_kw} kW")
    if specs.battery_kwh:
        typer.echo(f"  Reference battery: {specs.battery_kwh} kWh")

    # Step 3: Search for candidates
    typer.echo("\nSearching for alternatives...")

    ctx = await build_context(
        config,
        brand_filter=search_filters.brand,
        llm_class=LLMClient,
        storage_class=StorageManager,
        browser_manager_class=BrowserManager,
        processor_class=ResultProcessor,
    )
    result = await run_pipeline(
        f"{specs.brand or ''} {specs.model or item}".strip(),
        condition,
        specs.category or "any",
        search_filters,
        None,
        ctx,
        searcher_class=PlaywrightSearcher,
    )
    deals = result.deals

    typer.echo(f"Found {len(deals)} candidate(s)")

    # Step 4: Score and compare
    engine = ComparisonEngine()
    comparison = engine.compare(specs_dict, deals)

    # Step 5: Output results
    typer.echo("\n" + "=" * 60)
    typer.echo(f"REPLACEMENT ALTERNATIVES FOR: {item}")
    typer.echo("=" * 60)

    if comparison.winner:
        w = comparison.winner
        typer.echo(f"\nWinner: {w['title']}")
        typer.echo(f"  Site: {w['site_name']}  Price: {w['effective_price_eur']:.2f} EUR  Score: {w['score']}/100")
        for reason in w["reasons"][:5]:
            typer.echo(f"  - {reason}")

    for ru in comparison.runner_ups:
        typer.echo(f"\nRunner-up #{ru['rank']}: {ru['title']}")
        typer.echo(f"  Site: {ru['site_name']}  Price: {ru['effective_price_eur']:.2f} EUR  Score: {ru['score']}/100")
        for reason in ru["reasons"][:3]:
            typer.echo(f"  - {reason}")

    # Save results
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^a-z0-9]+", "-", item.lower()).strip("-")
    out_path = out_dir / f"replacement_{safe_name}.json"
    result_data = {
        "reference": specs_dict,
        "comparison": {
            "winner": comparison.winner,
            "runner_ups": comparison.runner_ups,
            "table": comparison.comparison_table,
            "total_candidates": comparison.total_candidates,
        },
    }
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result_data, f, indent=2, ensure_ascii=False)
    typer.echo(f"\nSaved to: {out_path}")


@app.command()
def cache(
    stats: bool = typer.Option(False, "--stats", "-s", help="Show cache statistics"),
    clear: bool = typer.Option(False, "--clear", help="Clear all cache entries"),
):
    """Manage the search response cache."""
    from src.searcher.search_cache import SearchCache

    cache = SearchCache()

    if clear:
        count = cache.clear()
        typer.echo(f"Cleared {count} cache entr{'y' if count == 1 else 'ies'}")
        return

    if stats:
        s = cache.stats()
        typer.echo(f"Cache entries: {s['entries']}")
        typer.echo(f"Total cached deals: {s['total_deals']}")
        typer.echo(f"Cache directory: {s['cache_dir']}")
        typer.echo(f"TTL: {s['ttl_seconds']} seconds")
        return

    typer.echo("Use --stats or --clear")


alert_rule_app = typer.Typer()


@alert_rule_app.command("add")
def alert_rule_add(
    url: str = typer.Option(..., "--url", "-u", help="Product URL"),
    title: str = typer.Option(..., "--title", "-t", help="Item title"),
    target_price: float = typer.Option(..., "--target-price", help="Target price in EUR"),
    condition: str = typer.Option("any", "--condition", "-c", help="Condition filter"),
    channels: str | None = typer.Option(None, "--channels", help="Comma-separated channel names"),
    cooldown_minutes: int = typer.Option(60, "--cooldown-minutes", help="Cooldown in minutes"),
):
    """Add a price alert rule."""
    from src.storage.manager import StorageManager

    config = _load_config()
    storage = StorageManager(config.storage.db_path)
    ch_list = [c.strip() for c in channels.split(",")] if channels else []
    storage.save_price_alert_rule(
        url, title, target_price, condition=condition, channels=ch_list,
        cooldown_minutes=cooldown_minutes,
    )
    typer.echo(f"Alert rule added for {url} (target {target_price} EUR)")


@alert_rule_app.command("list")
def alert_rule_list():
    """List price alert rules."""
    from src.storage.manager import StorageManager

    config = _load_config()
    storage = StorageManager(config.storage.db_path)
    rules = storage.list_price_alert_rules(active_only=False)
    if not rules:
        typer.echo("No alert rules.")
        return
    typer.echo("Price alert rules:")
    for r in rules:
        state = "active" if r["is_active"] else "inactive"
        typer.echo(
            f"  {r['url']} — {r['title']} <= {r['target_price_eur']} EUR "
            f"[{state}, cooldown {r['cooldown_minutes']}min, channels {r['channels']}]"
        )


@alert_rule_app.command("remove")
def alert_rule_remove(
    url: str = typer.Option(..., "--url", "-u", help="Product URL"),
):
    """Remove an alert rule by URL."""
    from src.storage.manager import StorageManager

    config = _load_config()
    storage = StorageManager(config.storage.db_path)
    ok = storage.remove_price_alert_rule(url)
    typer.echo(f"Removed rule for {url}" if ok else f"No rule for {url}")


@alert_rule_app.command("enable")
def alert_rule_enable(
    url: str = typer.Option(..., "--url", "-u", help="Product URL"),
):
    """Enable an alert rule by URL."""
    from src.storage.manager import StorageManager

    config = _load_config()
    storage = StorageManager(config.storage.db_path)
    ok = storage.set_rule_active(url, True)
    typer.echo(f"Rule for {url} enabled" if ok else f"No rule for {url}")


@alert_rule_app.command("disable")
def alert_rule_disable(
    url: str = typer.Option(..., "--url", "-u", help="Product URL"),
):
    """Disable an alert rule by URL."""
    from src.storage.manager import StorageManager

    config = _load_config()
    storage = StorageManager(config.storage.db_path)
    ok = storage.set_rule_active(url, False)
    typer.echo(f"Rule for {url} disabled" if ok else f"No rule for {url}")


@alert_rule_app.command("evaluate")
def alert_rule_evaluate():
    """Evaluate all active alert rules and send triggered alerts now."""
    config = _load_config()
    storage = StorageManager(config.storage.db_path)
    notification_manager = build_notification_manager(config)
    from src.intelligence.price_tracker import AlertRuleEngine

    engine = AlertRuleEngine(storage, notification_manager)
    alerts = engine.evaluate_rules()
    typer.echo(f"Evaluated rules; {len(alerts)} alert(s) triggered.")


app.add_typer(alert_rule_app, name="alert-rule")


@app.command()
def dashboard(
    port: int = typer.Option(8765, "--port", "-p", help="Port to serve the dashboard on"),
    results_dir: str = typer.Option("reports", "--results-dir", "-d", help="Results directory to serve"),
):
    """Start the web dashboard for viewing search results."""
    import webbrowser

    from src.dashboard.app import run_server

    typer.echo(f"Starting dashboard at http://127.0.0.1:{port} (serving {results_dir})")
    typer.echo("Press Ctrl+C to stop.")
    webbrowser.open(f"http://127.0.0.1:{port}")
    run_server(port=port, results_dir=results_dir)


if __name__ == "__main__":
    app()