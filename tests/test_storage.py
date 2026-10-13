def test_storage_models_import():
    from src.storage.models import Deal, PriceHistory, WatchlistItem
    assert Deal is not None
    assert PriceHistory is not None
    assert WatchlistItem is not None
