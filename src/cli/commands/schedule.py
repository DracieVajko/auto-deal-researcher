"""Schedule commands: define and run scheduled searches (single / watchdog).

Examples:

    # Single search, as soon as the monitor starts
    python -m src.cli schedule add --prompt "dji drone pod 350 eur" --mode once --trigger asap

    # Prompt from a YAML file, daily at 05:00 local time
    python -m src.cli schedule add --prompt-file prompts/auto.yaml --mode once \
        --trigger at --trigger-value 05:00

    # Watchdog every 6 hours, stop after 24 runs
    python -m src.cli schedule add --prompt "levne letenky" --mode watchdog \
        --trigger every --trigger-value 6 --every-unit hours --repeats 24

    # Manual drain (run due jobs, unload the model, exit)
    python -m src.cli schedule service --exit-when-idle

    # Permanent daemon (Ctrl+C to stop)
    python -m src.cli schedule service

    # Daily Windows task at 05:00 local time
    python -m src.cli schedule install-startup --at 05:00
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path

import typer
import yaml

from src.config import load_config
from src.scheduler.plan import compute_next_run
from src.scheduler.queue import RunQueue
from src.scheduler.service import SchedulerService
from src.storage.manager import StorageManager
from src.utils.time import local_timezone

schedule_app = typer.Typer(
    help="Plánované vyhľadávanie (systemový monitor / price watchdog)."
)


def _storage(db_path: str | None) -> StorageManager:
    if db_path is None:
        db_path = load_config().storage.db_path
    return StorageManager(db_path)


@schedule_app.command("add")
def schedule_add(
    prompt: str | None = typer.Option(None, "--prompt", "-p", help="Vyhľadávací dotaz"),
    prompt_file: str | None = typer.Option(
        None, "--prompt-file", help="YAML súbor s kľúčom 'prompt' (napr. prompts/auto.yaml)"
    ),
    mode: str = typer.Option(
        "once", "--mode", help="once = jednorazovo, watchdog = opakovane"
    ),
    trigger: str = typer.Option(
        "asap", "--trigger", help="asap = co najskôr, at = v konkrétnu čas, every = každých N"
    ),
    trigger_value: str | None = typer.Option(
        None, "--trigger-value", help="HH:MM pre 'at' (napr. 08:00), N pre 'every' (napr. 60)"
    ),
    every_unit: str = typer.Option(
        "minutes", "--every-unit", help="minutes | hours"
    ),
    repeats: int | None = typer.Option(
        None, "--repeats", help="Max. počet opakovaní pre watchdog (predvolene neobmedzené)"
    ),
    condition: str = typer.Option("any", "--condition", "-c", help="Podmienka (new, used, ...)"),
    category: str = typer.Option("any", "--category", "-cat", help="Kategória"),
    db: str | None = typer.Option(None, "--db", help="Cesta k databáze (predvolene z config.yaml)"),
):
    """Pridať geplánované vyhľadávanie."""
    if prompt_file:
        data = yaml.safe_load(Path(prompt_file).read_text(encoding="utf-8")) or {}
        prompt = str(data.get("prompt") or "").strip()
    if not prompt:
        typer.echo("Error: zadaj --prompt alebo --prompt-file", err=True)
        raise typer.Exit(1)
    if mode not in ("once", "watchdog"):
        typer.echo(f"Error: neznamy mode {mode!r}; pouzte once alebo watchdog", err=True)
        raise typer.Exit(1)
    storage = _storage(db)
    job_id = f"job_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}"
    now = datetime.now(UTC).isoformat()
    next_run = compute_next_run(
        trigger, trigger_value, now, unit=every_unit, tz=local_timezone()
    )
    storage.save_scheduled_job(
        job_id=job_id,
        prompt=prompt,
        condition=condition,
        category=category,
        mode=mode,
        trigger=trigger,
        trigger_value=trigger_value,
        every_unit=every_unit,
        repeats=repeats,
        max_runs=0 if mode == "watchdog" else 1,
        enabled=True,
        next_run_at=next_run,
    )
    typer.echo(f"Pridaná úloha {job_id}: {prompt!r}  (režim={mode}, spustenie {next_run})")


@schedule_app.command("list")
def schedule_list(
    db: str | None = typer.Option(None, "--db", help="Cesta k databáze"),
):
    """Vypíska geplantých úloh a ich ďalšie spustenie."""
    storage = _storage(db)
    jobs = storage.list_scheduled_jobs()
    if not jobs:
        typer.echo("Ziadne geplánované úlohy.")
        return
    typer.echo(f"{'ID':<24} {'Režim':<10} {'Trigger':<8} {'Ďalšie spustenie':<28} {'Prompt'}")
    typer.echo("-" * 90)
    for j in jobs:
        mark = "OK " if j["enabled"] else "OFF"
        typer.echo(
            f"{j['id']:<24} {mark}   {j['mode']:<9} {j['trigger']:<7} "
            f"{j['next_run_at']!s:<28} {j['prompt']}"
        )


@schedule_app.command("enable")
def schedule_enable(
    job_id: str = typer.Argument(..., help="ID úlohy"),
    db: str | None = typer.Option(None, "--db", help="Cesta k databáze"),
):
    """Povoliť úlohu."""
    storage = _storage(db)
    if storage.enable_scheduled_job(job_id):
        typer.echo(f"Úloha {job_id} povolená.")
    else:
        typer.echo(f"Úloha {job_id} neexistuje.", err=True)
        raise typer.Exit(1)


@schedule_app.command("disable")
def schedule_disable(
    job_id: str = typer.Argument(..., help="ID úlohy"),
    db: str | None = typer.Option(None, "--db", help="Cesta k databáze"),
):
    """Zakázať úlohu (bez zrušenia)."""
    storage = _storage(db)
    if storage.disable_scheduled_job(job_id):
        typer.echo(f"Úloha {job_id} zakázaná.")
    else:
        typer.echo(f"Úloha {job_id} neexistuje.", err=True)
        raise typer.Exit(1)


@schedule_app.command("remove")
def schedule_remove(
    job_id: str = typer.Argument(..., help="ID úlohy"),
    db: str | None = typer.Option(None, "--db", help="Cesta k databáze"),
):
    """Odstrániť úlohu."""
    storage = _storage(db)
    if storage.remove_scheduled_job(job_id):
        typer.echo(f"Úloha {job_id} odstránená.")
    else:
        typer.echo(f"Úloha {job_id} neexistuje.", err=True)
        raise typer.Exit(1)


@schedule_app.command("service")
def schedule_service(
    db: str | None = typer.Option(None, "--db", help="Cesta k databáze"),
    poll: float = typer.Option(30.0, "--poll", help="Interval kontroly v sekundách"),
    exit_when_idle: bool = typer.Option(
        False,
        "--exit-when-idle",
        help="Po dokončení všetkých due úloh ukončiť (denný režim namiesto daemona).",
    ),
):
    """Spustiť monitor (jeden beh naraz; zvyšok čaká vo fronte)."""

    def make_searcher():
        from src.browser.manager import BrowserManager
        from src.llm.client import LLMClient
        from src.searcher.playwright_searcher import PlaywrightSearcher

        config = load_config()
        llm = LLMClient(config)
        browser_mgr = BrowserManager(config)
        return PlaywrightSearcher(config, llm, storage, browser_mgr)

    storage = _storage(db)
    # Preload local models if configured.
    preload_llm = None
    try:
        from src.llm.client import LLMClient
        preload_llm = LLMClient(load_config())
        asyncio.run(preload_llm.preload_models())
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Preload skipped: {exc}")
    svc = SchedulerService(
        storage,
        make_searcher,
        queue=RunQueue(),
        poll_interval=poll,
        release_after_job=not exit_when_idle,
    )
    if exit_when_idle:
        typer.echo("Monitor spustený v dennom režime (ukončí sa po dokončení práce)...")
    else:
        typer.echo("Monitor spustený (Ctrl+C na ukončenie)...")
    try:
        asyncio.run(svc.run(exit_when_idle=exit_when_idle))
    finally:
        # Daily mode: free the preloaded model once the batch is done.
        if exit_when_idle and preload_llm is not None:
            asyncio.run(preload_llm.release_models())


@schedule_app.command("install-startup")
def schedule_install_startup(
    at: str = typer.Option("05:00", "--at", help="Denný čas spustenia (HH:MM)"),
):
    """Zaregistrovať denný beh monitora (Windows Task Scheduler)."""
    import sys

    if sys.platform != "win32":
        typer.echo("Automatické spustenie sa zatiaľ podporuje len na Windows.", err=True)
        raise typer.Exit(1)
    from src.scheduler.tasks import install_startup

    install_startup(daily_at=at)
    typer.echo(f"Monitor zaregistrovaný na denný beh o {at}.")


@schedule_app.command("uninstall-startup")
def schedule_uninstall_startup():
    """Zrušiť registráciu monitora zo spustenia so systémom."""
    import sys

    if sys.platform != "win32":
        typer.echo("Automatické spustenie sa zatiaľ podporuje len na Windows.", err=True)
        raise typer.Exit(1)
    from src.scheduler.tasks import uninstall_startup

    uninstall_startup()
    typer.echo("Registráciu monitora zrušené.")
