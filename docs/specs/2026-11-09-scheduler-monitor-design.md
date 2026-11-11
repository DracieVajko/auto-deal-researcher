# Dizajn: Systémový monitor (scheduler) s frontou behov

**Dátum:** 2026-11-09  
**Stav:** plánované  
**Cluster:** scheduling-and-monitoring (nový)

## Požiadavky (od užívateľa)

1. **Startup aplikácia** — spúšťa sa spolu so systémom (Windows) ako monitor na pozadí.
2. **Dva typy úloh:**
   - `once` — jednorané vyhľadanie (single search).
   - `watchdog` — opakované vyhľadanie cez viac dní (price watchdog).
3. **Jednoduché vytvorenie** — užívateľ zadá prompt a vyberie typ (single / watchdog).
4. **Plánovanie podľa nastavenia užívateľa:**
   - `asap` — co najskôr,
   - `at HH:MM` — v konkrétnu hodinu,
   - `every N` — každých N minút/hodín,
   - `repeats N` — N opakovaní (spolu s `every`).
5. **Žiadne prekrytie behov** — dva behy nesmú bežať naraz; druhý čaká vo fronte (waitlist) a spúšťa sa, keď prvý skončí.

## Architektonické rozhodnutia

- Stojí na existujúcom `StorageManager` (stdlib sqlite3) a schémach (migrácie). Pridáva sa **SCHEMA_VERSION 7** s tabuľkou `scheduled_jobs`.
- Nový balíček `src/scheduler/`:
  - `plan.py` — datatriedy `ScheduleSpec` (režim, trigger, hodnota triggera, max_behov) a `ScheduledJob`.
  - `queue.py` — `RunQueue`: seriózna fronta s `asyncio.Lock` (mutuálna exkluzívna »), waitlist pre druhý beh.
  - `service.py` — `SchedulerService`: slučka, ktorá načítava pripravené úlohy z DB, frontuje ich a spúšťa jeden po druhom cez `PlaywrightSearcher.search`. V dennom režime (`--exit-when-idle`) sa po vyprázdnení fronty ukončí.
- CRUD pre úlohy v `src/storage/manager.py` (`save_scheduled_job`, `list_scheduled_jobs`, `due_jobs`, `mark_job_run`, `remove_scheduled_job`, `enable/disable`).
- CLI pod `src/cli/commands/schedule.py`: `schedule add`, `schedule list`, `schedule enable|disable|remove`, `schedule service` (daemon), `schedule install-startup|uninstall-startup`.
- Zapojené do `src/cli/app.py` ako `schedule` podgrupa (`app.add_typer(schedule_app, name="schedule")`).
- Spustenie so systémom: na Windows registrovaná úloha Task Scheduler s denným triggerom `-Daily -At 05:00`, ktorá spustí `python -m src.cli schedule service --exit-when-idle`; služba vyrieši všetky due úlohy, uvoľní model a ukončí sa. `schedule service` bez flagu zostáva daemon.

## Mutuálna exkluzívna (waitlist)

`RunQueue` drží jednu aktívnu výhradu (`asyncio.Lock` + flag `is_running`). Ak beží jeden beh, ďalší pripravený úloha sa vloží do `deque` waitlistu. Po skončení behu worker automaticky berie ďalšiu z fronty. Není možné, aby bežili dva naraz.

## Uloženie behov

Každý spustený beh vytvorí záznam v existujúcej tabuľke `runs` (`run_id = sched_<timestamp>`) s `status = running`, po skončení `completed` / `failed`. História behov sa dá prehliadať (`schedule list` zobrazí posledné behy).

## Bezpečnosť a kompatibilita

- Žiadne nové runtime dependencies (stdlib + existujúce balíky: typer, playwright, sqlite3).
- Existujúce CLI príkazy a uložené výsledky zostávajú nedotknuté.
- mypy clean (`--python-version 3.12`), ruff clean na nových/menených súboroch, celá testová sada zelená.
- TDD: najprv testy, potom implementácia.
