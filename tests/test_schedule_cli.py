"""Tests for src.cli.commands.schedule (schedule add/list/enable/disable/remove)."""

import os
import tempfile

import pytest
from typer.testing import CliRunner

from src.cli.commands.schedule import schedule_app


def _run(args, db_path):
    runner = CliRunner()
    return runner.invoke(
        schedule_app,
        args + ["--db", db_path],
    )


@pytest.fixture
def empty_prompt_dirs(monkeypatch, tmp_path):
    single = tmp_path / "single"
    watchdog = tmp_path / "watchdog"
    single.mkdir()
    watchdog.mkdir()
    from src.scheduler import file_jobs

    monkeypatch.setattr(file_jobs, "SINGLE_DIR", single)
    monkeypatch.setattr(file_jobs, "WATCHDOG_DIR", watchdog)
    return single, watchdog


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        yield path
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def test_schedule_add_once_asap(db_path):
    result = _run(
        ["add", "--prompt", "dji drone pod 350 eur", "--mode", "once", "--trigger", "asap"],
        db_path,
    )
    assert result.exit_code == 0, result.output
    assert "Pridaná úloha" in result.output
    assert "dji drone pod 350 eur" in result.output


def test_schedule_add_watchdog_every(db_path):
    result = _run(
        [
            "add",
            "--prompt", "levne letenky",
            "--mode", "watchdog",
            "--trigger", "every",
            "--trigger-value", "60",
            "--every-unit", "hours",
            "--repeats", "24",
        ],
        db_path,
    )
    assert result.exit_code == 0, result.output
    assert "watchdog" in result.output


def test_schedule_add_invalid_mode_errors(db_path):
    result = _run(
        ["add", "--prompt", "x", "--mode", "neco"],
        db_path,
    )
    assert result.exit_code != 0
    assert "neznamy mode" in result.output


def test_schedule_list_shows_jobs(db_path, empty_prompt_dirs):
    _run(["add", "--prompt", "prva", "--mode", "once", "--trigger", "asap"], db_path)
    _run(["add", "--prompt", "druha", "--mode", "once", "--trigger", "asap"], db_path)
    result = _run(["list"], db_path)
    assert result.exit_code == 0, result.output
    assert "prva" in result.output
    assert "druha" in result.output


def test_schedule_disable_enable_remove(db_path):
    add = _run(["add", "--prompt", "tmp", "--mode", "once", "--trigger", "asap"], db_path)
    assert add.exit_code == 0
    job_id = add.output.split("Pridaná úloha ")[1].split(":")[0].strip()

    res = _run(["disable", job_id], db_path)
    assert res.exit_code == 0, res.output
    assert "zakázaná" in res.output

    res = _run(["enable", job_id], db_path)
    assert res.exit_code == 0, res.output
    assert "povolená" in res.output

    res = _run(["remove", job_id], db_path)
    assert res.exit_code == 0, res.output
    assert "odstránená" in res.output

    res = _run(["remove", job_id], db_path)
    assert res.exit_code != 0
    assert "neexistuje" in res.output


def test_schedule_list_empty(db_path, empty_prompt_dirs):
    result = _run(["list"], db_path)
    assert result.exit_code == 0
    assert "Žiadne" in result.output
