def test_storage_models_import():
    from src.history.watchlist import WatchlistItem
    from src.searcher.adapters.base import Deal
    from src.storage.manager import PriceHistoryEntry

    assert Deal is not None
    assert PriceHistoryEntry is not None
    assert WatchlistItem is not None
