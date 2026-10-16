"""Auto Deal Searcher - Typer app factory."""

import asyncio

import typer

from src.browser.manager import BrowserManager
from src.cli.commands.history import history_app
from src.cli.commands.monitor import monitor as monitor_fn
from src.config import load_config
from src.diagnostics.doctor import Doctor, print_doctor_results
from src.llm.client import LLMClient
from src.output.processor import ResultProcessor
from src.scheduler.tasks import install_schedule, uninstall_schedule
from src.searcher.playwright_searcher import PlaywrightSearcher
from src.storage.manager import StorageManager

app = typer.Typer(help="Auto Deal Searcher — find deals across marketplaces")
app.add_typer(history_app, name="history")


@app.command()
def run(
    prompt: str | None = typer.Option(None, "--prompt", "-p", help="Search prompt (single-run mode)"),
    prompt_file: str | None = typer.Option(None, "--prompt-file", "-f", help="YAML file with prompt (auto mode)"),
    condition: str = typer.Option("any", "--condition", "-c", help="Filter: new, used, refurbished, open_box, any"),
    category: str = typer.Option("any", "--category", "-cat", help="Filter: electronics, appliances, auto, any"),
    winners: int | None = typer.Option(None, "--winners", "-w", help="Override winners_count from config"),
    output_format: str | None = typer.Option(None, "--format", help="Override output format: json, markdown, both"),
):
    """Run a single search cycle."""
    asyncio.run(_run_async(prompt, prompt_file, condition, category, winners, output_format))


async def _run_async(prompt, prompt_file, condition, category, winners, output_format):
    config = load_config()

    # Resolve prompt
    if prompt_file:
        import yaml
        with open(prompt_file) as f:
            data = yaml.safe_load(f)
            prompt = data.get("prompt", "")
    if not prompt:
        typer.echo("Error: Provide --prompt or --prompt-file", err=True)
        raise typer.Exit(1)

    # Override config
    if winners:
        config.search.winners_count = winners
    if output_format:
        config.output.format = output_format

    llm = LLMClient(config)
    storage = StorageManager(config.storage.db_path)
    browser_mgr = BrowserManager(config)
    processor = ResultProcessor(config)

    async with PlaywrightSearcher(config, llm, storage, browser_mgr) as searcher:
        deals = await searcher.search(prompt, condition, category)

    # Prune missing (deals not found this run)
    storage.prune_missing(max_age_days=config.search.prune_after_days or 30)

    # Save new deals
    for deal in deals:
        storage.save_deal(deal)

    # Output
    processor.save_results(deals, config.output.directory)
    typer.echo(f"Found {len(deals)} deals. Results in {config.output.directory}/")


@app.command()
def diamond_search(
    prompt: str = typer.Option(..., "--prompt", "-p", help="Search prompt"),
    condition: str = typer.Option("any", "--condition", "-c", help="Filter: new, used, refurbished, open_box, any"),
    category: str = typer.Option("any", "--category", "-cat", help="Filter: electronics, appliances, auto, any"),
    winners: int = typer.Option(3, "--winners", "-w", help="How many ranked deals to keep"),
    output_dir: str = typer.Option("./results", "--output-dir", help="Where to write the ranking"),
):
    """Run the full 7-agent Diamond Search pipeline."""
    asyncio.run(_diamond_search_async(prompt, condition, category, winners, output_dir))


async def _diamond_search_async(prompt, condition, category, winners, output_dir):
    config = load_config()
    if not config.search.diamond_search.enabled:
        typer.echo("Error: diamond_search.enabled is false in config.yaml", err=True)
        raise typer.Exit(1)

    llm = LLMClient(config)
    storage = StorageManager(config.storage.db_path)
    browser_mgr = BrowserManager(config)
    processor = ResultProcessor(config)
    config.search.winners_count = winners

    async with PlaywrightSearcher(config, llm, storage, browser_mgr) as searcher:
        if not searcher.diamond_search_enabled:
            typer.echo("Error: Diamond Search agents unavailable", err=True)
            raise typer.Exit(1)
        deals = await searcher.search_with_diamond(prompt, condition, category)

    for deal in deals:
        storage.save_deal(deal)

    processor.save_results(deals, output_dir)

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
    our = {getattr(l, "model", "") for l in llm.llm_config.local}
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