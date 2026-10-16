"""Selector health event-log tests."""

import json
from pathlib import Path

import pytest

from src.diagnostics.selector_health import SelectorHealthTracker


@pytest.fixture
def tracker(tmp_path, monkeypatch):
    monkeypatch.setattr(SelectorHealthTracker, "STORAGE_FILE", str(tmp_path / "health.json"))
    monkeypatch.setattr(SelectorHealthTracker, "EVENT_LOG", str(tmp_path / "events.log"))
    return SelectorHealthTracker()


def test_records_success_and_persists(tracker):
    tracker.record_search_start("alza", "AlzaAdapter")
    tracker.record_search_result("alza", True, 7, 1500.0)
    tracker.record_search_start("alza", "AlzaAdapter")
    tracker.record_search_result("alza", True, 5, 1200.0)

    site = tracker.get_site_health("alza")
    assert site.total_searches == 2
    assert site.successful_searches == 2
    assert site.avg_deals_per_search == 6.0
    assert site.is_healthy is True


def test_blocked_flag_is_logged(tracker):
    tracker.record_search_start("backmarket", "BackMarketAdapter")
    tracker.record_search_result("backmarket", False, 0, 800.0, blocked=True)

    events = SelectorHealthTracker.read_events()
    assert len(events) == 1
    assert events[0]["site"] == "backmarket"
    assert events[0]["blocked"] is True
    assert events[0]["deals_found"] if "deals_found" in events[0] else True


def test_event_schema_fields(tracker):
    tracker.record_search_start("bazos", "BazosAdapter")
    tracker.record_search_result("bazos", True, 3, 900.0)

    entry = SelectorHealthTracker.read_events()[-1]
    for field in ("ts", "site", "adapter_class", "success_rate", "total_searches",
                  "consecutive_failures", "avg_deals_per_search", "latency_ms",
                  "blocked", "is_healthy"):
        assert field in entry, f"missing field {field}"


def test_events_are_append_only(tracker):
    for i in range(3):
        tracker.record_search_start("alza", "AlzaAdapter")
        tracker.record_search_result("alza", True, i, 100.0)
    events = SelectorHealthTracker.read_events(limit=10)
    assert len(events) == 3
    assert [e["total_searches"] for e in events] == [1, 2, 3]


def test_read_events_respects_limit(tracker):
    for _ in range(5):
        tracker.record_search_start("alza", "AlzaAdapter")
        tracker.record_search_result("alza", True, 1, 100.0)
    assert len(SelectorHealthTracker.read_events(limit=2)) == 2


def test_read_events_skips_corrupt_lines(tracker):
    tracker.record_search_start("alza", "AlzaAdapter")
    tracker.record_search_result("alza", True, 1, 100.0)
    log = Path(tracker.EVENT_LOG)
    with open(log, "a", encoding="utf-8") as fh:
        fh.write("not json\n")
    events = SelectorHealthTracker.read_events()
    assert len(events) == 1


def test_read_events_missing_file_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(SelectorHealthTracker, "EVENT_LOG", str(tmp_path / "nope.log"))
    assert SelectorHealthTracker.read_events() == []


def test_unhealthy_sites_listed(tracker):
    tracker.record_search_start("bazos", "BazosAdapter")
    tracker.record_search_result("bazos", True, 3, 100.0)
    for _ in range(6):
        tracker.record_search_start("bazos", "BazosAdapter")
        tracker.record_search_result("bazos", False, 0, 100.0)
    assert "bazos" in tracker.get_unhealthy_sites()


def test_log_lines_are_valid_jsonl(tracker):
    tracker.record_search_start("alza", "AlzaAdapter")
    tracker.record_search_result("alza", True, 1, 100.0)
    lines = Path(tracker.EVENT_LOG).read_text(encoding="utf-8").strip().splitlines()
    assert all(json.loads(line)["site"] == "alza" for line in lines)