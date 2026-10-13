"""Auto Deal Searcher CLI - main entry point."""

import asyncio
import os

import typer

from src.browser.manager import BrowserManager
from src.config import load_config
from src.diagnostics.doctor import Doctor, print_doctor_results
from src.intelligence.change_detector import ChangeDetector
from src.intelligence.price_tracker import PriceTracker
from src.llm.client import LLMClient
from src.output.processor import ResultProcessor
from src.searcher.playwright_searcher import PlaywrightSearcher
from src.storage.manager import StorageManager
from src.utils.time import utcnow_stamp

app = typer.Typer(help="Auto Deal Searcher — find deals across marketplaces")


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


def _load_prompt_from_file(prompt_file: str) -> str:
    """Load search prompt from a YAML file (sync helper for use in threads)."""
    import yaml

    with open(prompt_file, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("prompt", "")


def _write_text_file(path: str, text: str) -> None:
    """Write text to a file (sync helper for use in threads)."""
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


async def _run_async(prompt, prompt_file, condition, category, winners, output_format):
    config = load_config()

    # Resolve prompt
    if prompt_file:
        prompt = await asyncio.to_thread(_load_prompt_from_file, prompt_file)
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
    asyncio.run(_monitor_async(prompt_file, interval_hours, max_runs, output_dir, price_drop_threshold))


async def _monitor_async(prompt_file: str | None, interval_hours: int, max_runs: int, output_dir: str, price_drop_threshold: float):
    os.makedirs(output_dir, exist_ok=True)
    
    config = load_config()

    # Resolve prompt
    if prompt_file:
        prompt = await asyncio.to_thread(_load_prompt_from_file, prompt_file)
    else:
        typer.echo("Error: Provide --prompt-file for monitoring mode", err=True)
        raise typer.Exit(1)

    llm = LLMClient(config)
    storage = StorageManager(config.storage.db_path)
    browser_mgr = BrowserManager(config)
    price_tracker = PriceTracker(storage)
    change_detector = ChangeDetector(storage)

    run_count = 0
    previous_run_id = None

    try:
        while max_runs == 0 or run_count < max_runs:
            run_count += 1
            run_id = f"monitor_{utcnow_stamp()}"
            
            typer.echo(f"\n{'='*60}")
            typer.echo(f"Monitor Run #{run_count} — {run_id}")
            typer.echo(f"{'='*60}")

            # Create run record
            storage.create_run(run_id, prompt, "any", "any")

            async with PlaywrightSearcher(config, llm, storage, browser_mgr) as searcher:
                deals = await searcher.search(prompt, "any", "any")

            # Record price sightings
            for deal in deals:
                price_tracker.record_sighting(deal, run_id)

            # Generate change report
            report = change_detector.generate_run_report(run_id, prompt, deals, previous_run_id)

            # Update run record
            storage.complete_run(run_id, len(deals), report.new_count, "completed")

            # Print report
            typer.echo(report.to_markdown())

            # Save report to file
            report_path = os.path.join(output_dir, f"{run_id}.md")
            await asyncio.to_thread(_write_text_file, report_path, report.to_markdown())
            typer.echo(f"Report saved to: {report_path}")

            # Save new deals
            for deal in deals:
                storage.save_deal(deal, run_id)

            previous_run_id = run_id

            if max_runs > 0 and run_count >= max_runs:
                break

            typer.echo(f"Sleeping for {interval_hours} hours...")
            await asyncio.sleep(interval_hours * 3600)

    except KeyboardInterrupt:
        typer.echo("\nMonitoring stopped by user")
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise


if __name__ == "__main__":
    app()