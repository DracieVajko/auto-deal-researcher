"""Auto Deal Searcher CLI - main entry point."""

import asyncio
import typer
from pathlib import Path
from typing import Optional

from src.config import load_config
from src.llm.client import LLMClient
from src.storage.manager import StorageManager
from src.browser.manager import BrowserManager
from src.searcher.playwright_searcher import PlaywrightSearcher
from src.output.processor import ResultProcessor
from src.diagnostics.doctor import Doctor
from src.diagnostics.doctor import print_doctor_results

app = typer.Typer(help="Auto Deal Searcher — find deals across marketplaces")


@app.command()
def run(
    prompt: Optional[str] = typer.Option(None, "--prompt", "-p", help="Search prompt (single-run mode)"),
    prompt_file: Optional[str] = typer.Option(None, "--prompt-file", "-f", help="YAML file with prompt (auto mode)"),
    condition: str = typer.Option("any", "--condition", "-c", help="Filter: new, used, refurbished, open_box, any"),
    category: str = typer.Option("any", "--category", "-cat", help="Filter: electronics, appliances, auto, any"),
    winners: Optional[int] = typer.Option(None, "--winners", "-w", help="Override winners_count from config"),
    output_format: Optional[str] = typer.Option(None, "--format", help="Override output format: json, markdown, both"),
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
def schedule_install():
    """Install automated scheduled tasks (Windows Task Scheduler / cron)."""
    config = load_config()
    from src.scheduler.tasks import install_schedule
    install_schedule(config)
    typer.echo("Scheduled tasks installed.")


@app.command()
def schedule_uninstall():
    """Remove automated scheduled tasks."""
    from src.scheduler.tasks import uninstall_schedule
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
    site: Optional[str] = typer.Option(None, "--site", "-s", help="Check specific site only"),
    offline: bool = typer.Option(False, "--offline", help="Check config only, no network"),
):
    """Run site health diagnostics."""
    asyncio.run(_doctor_async(site, offline))


async def _doctor_async(site: Optional[str], offline: bool):
    config = load_config()
    doctor = Doctor(config)
    
    if site:
        result = await doctor.check_site(site, live=not offline)
        print_doctor_results([result])
    else:
        results = await doctor.check_all(live=not offline)
        print_doctor_results(results)


@app.command()
def config_check():
    """Validate config.yaml against schema."""
    config = load_config()
    typer.echo("✅ Config valid")
    typer.echo(f"  Sites enabled: {[s.name for s in config.search.websites if s.enabled]}")
    typer.echo(f"  LLM local: {config.llm.local[0].type if config.llm.local else 'none'}")
    typer.echo(f"  Winners: {config.search.winners_count}")


if __name__ == "__main__":
    app()