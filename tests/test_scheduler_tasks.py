"""Tests for src.scheduler.tasks (schedule install / uninstall / startup)."""

from src.scheduler import tasks


class _Task:
    name = "test-task"
    enabled = True
    times = ("08:00", "20:00")
    prompt_file = "prompts/auto.yaml"


class _Schedule:
    def __init__(self) -> None:
        self.tasks = [_Task()]


class _Config:
    def __init__(self) -> None:
        self.schedule = _Schedule()


def _fake_config():
    return _Config()


def test_install_schedule_windows(monkeypatch):
    calls: list[str] = []

    def fake_run(cmd, check=True):
        cmd_str = " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
        calls.append(cmd_str)

    monkeypatch.setattr(tasks.subprocess, "run", fake_run)
    monkeypatch.setattr(tasks.sys, "platform", "win32")

    tasks.install_schedule(_fake_config())

    assert len(calls) == 2  # two times
    assert "Register-ScheduledTask" in calls[0]
    assert "AutoDealSearcher-" in calls[0]
    assert "-m src.cli run --prompt-file" in calls[0]


def test_install_startup_uses_hidden_window(monkeypatch):
    calls: list[str] = []

    def fake_run(cmd, check=True):
        cmd_str = " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
        calls.append(cmd_str)

    monkeypatch.setattr(tasks.subprocess, "run", fake_run)
    monkeypatch.setattr(tasks.sys, "platform", "win32")
    # Force the fallback path (no pythonw.exe) so -WindowStyle Hidden is used.
    monkeypatch.setattr(tasks.os.path, "exists", lambda p: not str(p).endswith("pythonw.exe"))

    tasks.install_startup()

    assert len(calls) == 1
    ps_cmd = calls[0]
    assert "-WindowStyle Hidden" in ps_cmd
    assert "schedule service" in ps_cmd
    assert "Register-ScheduledTask" in ps_cmd


def test_install_startup_prefers_pythonw(monkeypatch):
    calls: list[str] = []

    def fake_run(cmd, check=True):
        cmd_str = " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
        calls.append(cmd_str)

    monkeypatch.setattr(tasks.subprocess, "run", fake_run)
    monkeypatch.setattr(tasks.sys, "platform", "win32")
    monkeypatch.setattr(tasks.os.path, "exists", lambda p: str(p).endswith("pythonw.exe"))

    tasks.install_startup()

    ps_cmd = calls[0]
    assert "pythonw.exe" in ps_cmd
    assert "-WindowStyle Hidden" not in ps_cmd  # pythonw needs no console flag


def test_uninstall_startup_removes_task(monkeypatch):
    calls: list[str] = []

    def fake_run(cmd, check=True):
        cmd_str = " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
        calls.append(cmd_str)

    monkeypatch.setattr(tasks.subprocess, "run", fake_run)
    monkeypatch.setattr(tasks.sys, "platform", "win32")

    tasks.uninstall_startup()

    assert len(calls) == 1
    assert "AutoDealSearcher-Monitor" in calls[0]
    assert "Unregister-ScheduledTask" in calls[0]


def test_install_startup_non_windows_noop(monkeypatch):
    calls: list[str] = []

    def fake_run(cmd, check=True):
        cmd_str = " ".join(cmd) if isinstance(cmd, (list, tuple)) else cmd
        calls.append(cmd_str)

    monkeypatch.setattr(tasks.subprocess, "run", fake_run)
    monkeypatch.setattr(tasks.sys, "platform", "linux")

    tasks.install_startup()
    tasks.uninstall_startup()

    assert calls == []
