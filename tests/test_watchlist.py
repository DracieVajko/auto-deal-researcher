"""Watchlist persistence and CLI argument tests."""

from src.history.watchlist import WatchlistManager


def test_add_item_update_persists(tmp_path, monkeypatch):
    monkeypatch.setattr(
        WatchlistManager, "STORAGE_FILE", str(tmp_path / "watchlist.json")
    )
    manager = WatchlistManager()
    manager.add_item("https://x/1", "Item", 100.0)
    manager.add_item("https://x/1", "Item", 80.0)

    reloaded = WatchlistManager()
    assert reloaded.get_item("https://x/1").target_price_eur == 80.0


def test_cli_add_passes_threshold_as_threshold(monkeypatch):
    import src.cli.commands.history as module
    from src.config.models import AppConfig

    captured = {}

    class FakeWatchlist:
        def __init__(self, storage, notifications):
            pass

        def add_item(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

    monkeypatch.setattr(module, "WatchlistManager", FakeWatchlist)
    monkeypatch.setattr(module, "StorageManager", lambda path: None)
    monkeypatch.setattr(module, "NotificationManager", lambda: None)
    monkeypatch.setattr(module, "load_config", lambda: AppConfig())

    module.watchlist_cmd(
        action="add",
        url="https://x/1",
        title="Item",
        target_price=100.0,
        condition="any",
        category="any",
        threshold=7.0,
        days=30,
    )

    assert captured["kwargs"]["alert_threshold_pct"] == 7.0
    assert captured["args"][:2] == ("https://x/1", "Item")
