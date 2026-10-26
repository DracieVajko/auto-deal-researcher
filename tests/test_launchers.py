"""Launcher scripts: thin entry points around the ask wizard."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(name: str) -> bytes:
    return (ROOT / "scripts" / name).read_bytes()


def test_search_bat_is_ascii_and_launches_ask():
    raw = _read("search.bat")
    raw.decode("ascii")  # no codepage traps
    assert b"\r\n" in raw
    text = raw.decode("ascii")
    assert "src.cli ask" in text
    assert "py -3" in text  # the setup.bat discovery fallback


def test_search_sh_launches_ask_on_linux_and_macos():
    text = _read("search.sh").decode("utf-8")
    assert text.startswith("#!/usr/bin/env bash")
    assert "src.cli ask" in text
    assert "python3" in text


def test_run_once_forwards_filters_only_when_given():
    text = _read("run_once.ps1").decode("utf-8")
    assert '[string]$Condition = ""' in text
    assert '[string]$Category = ""' in text
    assert 'if ($Condition) { $args += @("--condition", $Condition) }' in text
    assert 'if ($Category) { $args += @("--category", $Category) }' in text
    assert "exit $LASTEXITCODE" in text
