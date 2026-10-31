"""Monitor command - continuous monitoring with change detection."""

import asyncio
import logging
import os

import typer

from src.browser.manager import BrowserManager
from src.config import load_config
from src.intelligence.change_detector import ChangeDetector
from src.intelligence.price_tracker import PriceTracker
from src.llm.client import LLMClient
from src.searcher.playwright_searcher import PlaywrightSearcher
from src.storage.manager import StorageManager
from src.notifications.manager import NotificationManager
from src.notifications.base import Alert
from src.notifications.channels.console import ConsoleChannel
from src.utils.time import utcnow_stamp

logger = logging.getLogger(__name__)


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


def monitor(
    prompt_file: str | None = None,
    interval_hours: int = 12,
    max_runs: int = 0,
    output_dir: str = "results/monitoring",
    price_drop_threshold: float = 10.0,
):
    """Run continuous monitoring with intelligent change detection (importable function for tests)."""
    return asyncio.run(_monitor_async(prompt_file, interval_hours, max_runs, output_dir, price_drop_threshold))


async def _monitor_async(
    prompt_file: str | None,
    interval_hours: int,
    max_runs: int,
    output_dir: str,
    price_drop_threshold: float,
):
    os.makedirs(output_dir, exist_ok=True)

    config = load_config()

    # Notification manager from config
    notif = NotificationManager(
        cooldown_seconds=getattr(config.notifications, "default_cooldown_seconds", 3600),
    )
    notif.add_channel(ConsoleChannel())
    try:
        from src.notifications.channels.system import SystemChannel
        notif.add_channel(SystemChannel())
    except Exception as exc:
        logger.debug("Email channel init skipped: %s", exc)
    try:
        from src.notifications.channels.email import EmailChannel
        notif.add_channel(EmailChannel())
    except Exception as exc:
        logger.debug("Webhook channel init skipped: %s", exc)
    try:
        from src.notifications.channels.webhook import WebhookChannel
        for ch in getattr(config.notifications, "channels", []) or []:
            if ch.type == "webhook":
                notif.add_channel(WebhookChannel(ch.name))
    except Exception:
        pass
    try:
        from src.notifications.channels.discord import DiscordChannel
        for ch in getattr(config.notifications, "channels", []) or []:
            if ch.type == "discord":
                notif.add_channel(DiscordChannel(ch.name))
    except Exception as exc:
        logger.debug("Discord channel init skipped: %s", exc)

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

            # Send notification
            try:
                alert = Alert(
                    title=f"Monitor run #{run_count}",
                    message=f"{len(deals)} deals found. New: {report.new_count}. Report: {report_path}",
                    severity="info",
                )
                await notif.send_alert(alert)
            except Exception as exc:
                logger.debug("Notification failed: %s", exc)

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
