"""Tests for the dashboard data module."""

import json

from src.dashboard.data import ResultsStore


def _write_result(tmp_path, timestamp, slug, prompt, deals, price_alerts=None):
    results_dir = tmp_path / "results"
    results_dir.mkdir(exist_ok=True)
    data = {
        "prompt": prompt,
        "generated_at": f"{timestamp}T120000Z",
        "count": len(deals),
        "deals": deals,
        "filtered_out_count": 0,
        "price_alerts": price_alerts or [],
    }
    path = results_dir / f"results_{timestamp}_{slug}.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_list_runs_empty(tmp_path):
    store = ResultsStore(tmp_path / "results")
    assert store.list_runs() == []


def test_list_runs_sorted_by_timestamp(tmp_path):
    _write_result(tmp_path, "20261101_120000", "run-a", "prompt a", [{"title": "A", "price_eur": 100}])
    _write_result(tmp_path, "20261103_120000", "run-b", "prompt b", [{"title": "B", "price_eur": 200}, {"title": "C", "price_eur": 300}])
    _write_result(tmp_path, "20261102_120000", "run-c", "prompt c", [])

    store = ResultsStore(tmp_path / "results")
    runs = store.list_runs()
    assert len(runs) == 3
    assert runs[0].timestamp == "20261103_120000"
    assert runs[0].prompt == "prompt b"
    assert runs[1].timestamp == "20261102_120000"
    assert runs[2].timestamp == "20261101_120000"


def test_list_runs_deal_counts(tmp_path):
    _write_result(tmp_path, "20261101_120000", "run-a", "prompt a", [{"title": "A", "price_eur": 100}])
    _write_result(tmp_path, "20261102_120000", "run-b", "prompt b", [{"title": "B", "price_eur": 200}, {"title": "C", "price_eur": 300}])

    store = ResultsStore(tmp_path / "results")
    runs = store.list_runs()
    assert runs[0].deal_count == 2
    assert runs[1].deal_count == 1


def test_get_run(tmp_path):
    _write_result(tmp_path, "20261101_120000", "run-a", "prompt a", [{"title": "A", "price_eur": 100, "site_name": "bazos", "condition": "used", "score": 85.0, "verdict": "buy", "url": "https://a.com", "domain": "electronics", "effective_price_eur": 100}])

    store = ResultsStore(tmp_path / "results")
    run = store.get_run("20261101_120000", "run-a")
    assert run is not None
    assert run.slug == "run-a"
    assert run.prompt == "prompt a"
    assert run.deal_count == 1
    assert run.deals[0].title == "A"
    assert run.deals[0].price_eur == 100.0
    assert run.deals[0].effective_price_eur == 100.0
    assert run.deals[0].condition == "used"
    assert run.deals[0].score == 85.0
    assert run.deals[0].verdict == "buy"
    assert run.deals[0].url == "https://a.com"


def test_get_run_missing(tmp_path):
    store = ResultsStore(tmp_path / "results")
    assert store.get_run("20261101_120000", "nonexistent") is None


def test_list_runs_missing_directory(tmp_path):
    store = ResultsStore(tmp_path / "nonexistent")
    assert store.list_runs() == []
