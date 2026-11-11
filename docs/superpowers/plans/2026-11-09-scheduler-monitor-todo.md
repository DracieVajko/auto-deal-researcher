# Todo: Systémový monitor (scheduler)

## 1. Dizajn
- [x] docs/specs/2026-11-09-scheduler-monitor-design.md

## 2. Storage migrácia v7 + CRUD (ScheduledJob)
- [x] tests/test_storage_scheduler.py
- [x] src/storage/schema.py (SCHEMA_VERSION 7, tabuľka scheduled_jobs)
- [x] src/storage/manager.py (CRUD metódy)
- [x] test: mypy + ruff + pytest zelené

## 3. scheduler/plan.py (ScheduleSpec, ScheduledJob, next_run_at)
- [x] tests/test_scheduler_plan.py
- [x] src/scheduler/plan.py

## 4. scheduler/queue.py (RunQueue, seriózne + waitlist)
- [x] tests/test_scheduler_queue.py
- [x] src/scheduler/queue.py

## 5. scheduler/service.py (SchedulerService daemon)
- [ ] tests/test_scheduler_service.py
- [ ] src/scheduler/service.py

## 6. CLI (schedule add/list/enable/disable/remove/service/install-startup)
- [x] tests/test_schedule_cli.py
- [x] src/cli/commands/schedule.py
- [x] zapojiť do src/cli/app.py

## 7. Spustenie so systémom (startup)
- [x] src/scheduler/tasks.py (install_startup/uninstall_startup, Windows Task Scheduler -Daily -At 05:00)

## 8. File-based prompt folders (single / watchdog)
- [x] src/scheduler/file_jobs.py
- [x] tests/test_scheduler_file_jobs.py
- [x] schedule new / schedule files / schedule rm-file
- [x] README + config.example.yaml návod

## 9. Overenie
- [x] python -m pytest -q (839 passed, 11 skipped)
- [x] python -m mypy src/scheduler/file_jobs.py src/scheduler/service.py src/scheduler/plan.py
- [ ] ruff check na nových/menených súboroch
- [ ] commit
