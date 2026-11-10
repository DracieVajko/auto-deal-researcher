"""Schedule commands: definujte a spúšťajte geplánované vyhľadávanie (monitor/watchdog).

Príklady:

    python -m src.cli schedule add --prompt "dji drone pod 350 eur" --mode once --trigger asap
    python -m src.cli schedule add --prompt "levne letenky" --mode watchdog --trigger every --trigger-value 60 --every-unit hours --repeats 24
    python -m src.cli schedule add --prompt "dji drone" --mode once --trigger at --trigger-value 08:00
    python -m src.cli schedule service              # daemon (spúšťa sa so systémom)
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import typer

from src.config import load_config
from src.scheduler.plan import compute_next_run
from src.scheduler.queue import RunQueue
from src.scheduler.service import SchedulerService
from src.storage.manager import StorageManager

schedule_app = typer.Typer(
    help="Plánované vyhľadávanie (systemový monitor / price watchdog)."
)


def _storage(db_path: str | None) -> StorageManager:
    if db_path is None:
        db_path = load_config().storage.db_path
    return StorageManager(db_path)


@schedule_app.command("add")
def schedule_add(
    prompt: str = typer.Option(..., "--prompt", "-p", help="Vyhľadávací dotaz"),
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
    if mode not in ("once", "watchdog"):
        typer.echo(f"Error: neznamy mode {mode!r}; pouzte once alebo watchdog", err=True)
        raise typer.Exit(1)
    storage = _storage(db)
    job_id = f"job_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S_%f')}"
    now = datetime.now(UTC).isoformat()
    next_run = compute_next_run(
        trigger, trigger_value, now, unit=every_unit
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
):
    """Spustiť daemon monitora (beží doneokola; jeden beh naraz, zvyšok čaká vo fronte)."""

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
    try:
        from src.llm.client import LLMClient
        _llm = LLMClient(load_config())
        asyncio.run(_llm.preload_models())
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Preload skipped: {exc}")
    svc = SchedulerService(storage, make_searcher, queue=RunQueue(), poll_interval=poll)
    typer.echo("Monitor spustený (Ctrl+C na ukončenie)...")
    asyncio.run(svc.run())


@schedule_app.command("install-startup")
def schedule_install_startup():
    """Zaregistrovať monitor, aby sa spúšťal spolu so systémom (Windows Task Scheduler, pri prihlásení)."""
    import sys

    if sys.platform != "win32":
        typer.echo("Automatické spustenie sa zatiaľ podporuje len na Windows.", err=True)
        raise typer.Exit(1)
    from src.scheduler.tasks import install_startup

    install_startup()
    typer.echo("Monitor zaregistrovaný do spustenia so systémom.")


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
