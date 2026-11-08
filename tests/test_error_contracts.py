import pytest

from src.history.watchlist import Watchlist, WatchlistStorageError
from src.notifications.channels.system import SystemChannel


@pytest.mark.asyncio
async def test_system_channel_returns_false_on_subprocess_failure(monkeypatch):
    ch = SystemChannel()
    def boom(*a, **k):
        raise RuntimeError("no notify-send")
    monkeypatch.setattr("subprocess.run", boom)
    alert = type("A", (), {"title": "t", "message": "m", "severity": "info"})()
    assert await ch.send(alert) is False


def test_watchlist_save_failure_propagates(tmp_path, monkeypatch):
    w = Watchlist(path=tmp_path / "wl.json")
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr("pathlib.Path.write_text", boom)
    with pytest.raises(WatchlistStorageError):
        w.add_item("https://x/1", "X")


def test_coordinator_failure_returns_dict_not_str():
    from src.agents.coordinator import _extract_result
    r = _extract_result(RuntimeError("boom"))
    assert isinstance(r, dict)
    assert r.get("error") == "boom"


@pytest.mark.asyncio
async def test_crashed_site_appears_in_skipped(monkeypatch):
    from src.config.models import AppConfig, Category, Condition, SearchConfig, WebsiteConfig
    from src.searcher.playwright_searcher import PlaywrightSearcher

    def _config():
        config = AppConfig(search=SearchConfig(websites=[
            WebsiteConfig(
                name="alza_cz",
                base_url="https://www.alza.cz",
                adapter_class="alza",
                categories=[Category.ELECTRONICS],
                conditions=[Condition.NEW],
            )
        ]))
        config.search.diamond_search.enabled = False
        return config

    config = _config()
    searcher = PlaywrightSearcher(config, llm=object(), storage=object(), browser_manager=object())
    searcher.profiles = {}

    async def boom(*a, **k):
        raise RuntimeError("crash")

    monkeypatch.setattr(searcher, "_search_one_site", boom)
    await searcher._execute_round("pc", "new", "electronics", set())
    assert any(item["name"] == "alza_cz" for item in searcher._skipped_sites)