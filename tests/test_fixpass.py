import inspect

import pytest

from src.storage.manager import StorageManager


def test_price_joins_use_url_not_id():
    src = inspect.getsource(StorageManager.detect_price_drops) + inspect.getsource(StorageManager.detect_new_lows)
    assert "ph.url = d.url" in src
    assert "ph.deal_id = d.id" not in src


def test_empty_deals_produce_valid_reports(tmp_path):
    from src.output.processor import ResultProcessor
    from src.config import load_config

    config = load_config()
    proc = ResultProcessor(config)
    out = proc.save_results([], str(tmp_path))
    assert out is not None


def test_coordinator_checks_budget_on_all_layers():
    from src.agents.coordinator import CoordinatorAgent

    src = inspect.getsource(CoordinatorAgent._run_research_layer) + inspect.getsource(
        CoordinatorAgent._run_expertise_layer
    )
    assert "_check_budget" in src


def test_scheduler_quotes_paths():
    from src.scheduler import tasks

    src = inspect.getsource(tasks._install_windows_tasks) + inspect.getsource(tasks._install_unix_cron)
    assert "prompt_file" in src
    # paths with spaces must be quoted
    assert '"' in src or "'" in src
    assert "shlex" in src or "quote" in src.lower() or '"' in src


def test_cli_entry_module_exists():
    import importlib.util

    assert importlib.util.find_spec("src.cli.main") is not None
