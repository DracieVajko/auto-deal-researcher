"""Regression tests for the persistence layer.

These cover the failures found during the audit where the ``deals`` table has
an autoincrement ``id`` primary key while ``url`` is only UNIQUE, and where
sqlite-utils' ``execute()`` returns plain tuples instead of ``sqlite3.Row``.
"""

import sqlite3
from datetime import datetime, timedelta

import pytest

from src.history.trends import TrendsAnalyzer
from src.intelligence.change_detector import ChangeDetector
from src.intelligence.price_tracker import PriceTracker
from src.searcher.adapters.base import Deal
from src.searcher.pricing import ShippingQuote, build_price_quote
from src.storage.manager import StorageManager

URL = "https://bazos.sk/inzerat/1/drone"


def make_deal(price=100.0, url=URL, title="DJI drone"):
    return Deal(
        url=url,
        title=title,
        price_eur=price,
        condition="used",
        category="electronics",
        site_name="bazos",
    )


@pytest.fixture
def storage(tmp_path):
    s = StorageManager(str(tmp_path / "deals.db"))
    s.create_run("run1", "dji drone", "any", "any")
    return s


def test_rows_support_key_and_index_access(storage):
    storage.save_deal(make_deal(), "run1")
    row = storage.db.execute("SELECT url, title FROM deals").fetchone()
    assert row["url"] == URL
    assert row[0] == URL


def test_get_deal_missing_returns_none(storage):
    assert storage.get_deal("https://example.com/missing") is None


def test_price_history_stores_effective_price_and_kind(storage):
    deal = make_deal()
    deal.price_quote = build_price_quote(
        100.0, shipping=ShippingQuote(cost_eur=5.0)
    )

    storage.save_deal(deal, "run1")

    rows = storage.get_price_history(URL)
    assert rows[0]["effective_price_eur"] == 105.0
    assert rows[0]["price_kind"] == "regular"


def test_price_tracker_uses_effective_price(storage):
    deal = make_deal()
    deal.price_quote = build_price_quote(
        100.0, shipping=ShippingQuote(cost_eur=10.0)
    )
    storage.save_deal(deal, "run1")

    tracker = PriceTracker(storage)
    assert tracker.get_deals_below_price(105.0) == []
    result = tracker.get_deals_below_price(110.0)
    assert result[0]["effective_price_eur"] == 110.0


def test_save_and_get_deal_roundtrip(storage):
    storage.save_deal(make_deal(), "run1")
    stored = storage.get_deal(URL)
    assert stored is not None
    assert stored.title == "DJI drone"
    assert stored.price_eur == 100.0
    assert stored.times_seen == 1


def test_resave_increments_times_seen(storage):
    storage.save_deal(make_deal(), "run1")
    storage.save_deal(make_deal(price=90.0), "run1")
    stored = storage.get_deal(URL)
    assert stored.times_seen == 2
    assert stored.price_eur == 90.0
    assert storage.get_all_deals()[0].url == URL


def test_get_deal_by_id(storage):
    storage.save_deal(make_deal(), "run1")
    row = storage.db.execute("SELECT id FROM deals WHERE url = ?", (URL,)).fetchone()
    assert storage.get_deal_by_id(row["id"]).url == URL


def test_price_sighting_records_history(storage):
    storage.save_deal(make_deal(), "run1")
    storage.save_deal(make_deal(price=80.0), "run1")
    history = storage.get_price_history(URL)
    assert len(history) == 2
    assert {h["price_eur"] for h in history} == {100.0, 80.0}


def test_record_sighting_creates_missing_deal(storage):
    """deal_id is NOT NULL, so a sighting for an unknown deal must bootstrap it."""
    storage.record_price_sighting(make_deal(), "run1")
    assert storage.get_deal(URL) is not None


def test_mark_seen_today(storage):
    storage.save_deal(make_deal(), "run1")
    storage.mark_seen_today([URL])
    assert storage.get_deal(URL) is not None


def test_mark_seen_today_is_committed(storage):
    from src.utils.time import today_iso

    storage.save_deal(make_deal(), "run1")
    storage.db.execute(
        "UPDATE deals SET last_seen = '2000-01-01' WHERE url = ?", (URL,)
    )
    storage.mark_seen_today([URL])
    storage.db.conn.close()

    reopened = StorageManager(str(storage.db_path))
    assert reopened.get_deal(URL).last_seen == today_iso()


def test_price_trend_short_history_uses_data_points(storage):
    storage.save_deal(make_deal(), "run1")
    trend = storage.get_price_trend(URL)
    assert trend == {"trend": "insufficient_data", "data_points": 1}


def test_price_tracker_trend_uses_effective_price(storage):
    """Price tracker trend must use effective price (incl. shipping), not raw price."""
    deal = make_deal()
    deal.price_quote = build_price_quote(
        100.0, shipping=ShippingQuote(cost_eur=20.0)
    )  # effective = 120.0
    storage.save_deal(deal, "run1")
    storage.save_deal(make_deal(price=90.0), "run1")  # effective = 90.0

    tracker = PriceTracker(storage)
    trend = storage.get_price_trend(URL)

    # Effective price went 120 -> 90, a drop. Raw price went 100 -> 90.
    assert trend["data_points"] == 2
    assert trend["change_pct"] == round((90.0 - 120.0) / 120.0 * 100, 2)


def test_detect_price_drops_uses_effective_price(storage):
    """Price drop detection must use effective price (price + shipping)."""
    # First create the deal row so subsequent price_history rows have a parent
    storage.save_deal(make_deal(price=100.0), "run1")
    
    now = datetime.now()
    
    # Delete the auto-created price_history row and insert with distinct timestamps
    storage.db.execute("DELETE FROM price_history WHERE url = ?", (URL,))
    
    # Effective=120 at T0-2day
    storage.db.execute(
        "INSERT INTO price_history (deal_id, url, price_eur, effective_price_eur, timestamp, original_price_eur, original_currency, condition, availability, seller_name, seller_rating, shipping_cost_eur, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, URL, 100.0, 120.0, (now - timedelta(days=2)).isoformat(), 100.0, "EUR", "used", "unknown", "", 0.0, "EUR", "run1")
    )
    
    # Effective=90 at T0-1day
    storage.db.execute(
        "INSERT INTO price_history (deal_id, url, price_eur, effective_price_eur, timestamp, original_price_eur, original_currency, condition, availability, seller_name, seller_rating, shipping_cost_eur, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, URL, 90.0, 90.0, (now - timedelta(days=1)).isoformat(), 90.0, "EUR", "used", "unknown", "", 0.0, "EUR", "run1")
    )
    
    storage.save_deal(make_deal(price=100.0), "run2")  # effective=100, timestamp=T0

    drops = storage.detect_price_drops(threshold_pct=10.0, days=2)
    # Effective prices: 120 (2 days ago), 90 (1 day ago), 100 (now)
    # latest=100, earliest=120, change=(100-120)/120=-16.67%
    assert any(d["url"] == URL for d in drops)
    assert any(d["change_pct"] == round((100.0 - 120.0) / 120.0 * 100, 2) for d in drops)


def test_detect_new_lows_uses_effective_price(storage):
    """New low detection must use effective price."""
    deal = make_deal()
    deal.price_quote = build_price_quote(
        100.0, shipping=ShippingQuote(cost_eur=20.0)
    )  # effective = 120.0
    storage.save_deal(deal, "run1")
    storage.db.execute(
        "UPDATE price_history SET timestamp = ? WHERE url = ?",
        ((datetime.now() - timedelta(days=2)).isoformat(), URL),
    )
    storage.save_deal(make_deal(price=80.0, url="https://x/2"), "run1")  # effective = 80.0

    lows = storage.detect_new_lows(days=30)
    urls = [d["url"] for d in lows]
    assert URL in urls
    # Effective price 120 is the low for this URL (only sighting), not 100 raw
    item = next(d for d in lows if d["url"] == URL)
    assert item["price"] == 120.0


def _age_sightings(storage, days):
    storage.db.execute(
        "UPDATE price_history SET timestamp = ?", ((datetime.now() - timedelta(days=days)).isoformat(),)
    )


def test_trends_analyze_category(storage):
    """Previously raised NameError: url_prices / last were undefined."""
    storage.save_deal(make_deal(price=100.0), "run1")
    _age_sightings(storage, 10)
    storage.save_deal(make_deal(price=80.0), "run1")

    result = TrendsAnalyzer(storage).analyze_category("electronics", days=30)
    assert result["trend"] == "dropping"
    assert result["products_tracked"] == 1
    assert result["details"][0]["change_pct"] == -20.0
    assert result["details"][0]["url"] == URL


def test_trends_get_price_drops_uses_named_columns(storage):
    """Previously read title/site via wrong positional indices."""
    storage.save_deal(make_deal(price=100.0), "run1")
    _age_sightings(storage, 10)
    storage.save_deal(make_deal(price=80.0), "run1")

    drops = TrendsAnalyzer(storage).get_price_drops(days=30)
    assert len(drops) == 1
    assert drops[0]["title"] == "DJI drone"
    assert drops[0]["site"] == "bazos"
    assert drops[0]["old_price"] == 100.0
    assert drops[0]["new_price"] == 80.0


def test_trends_get_new_lows(storage):
    storage.save_deal(make_deal(price=100.0), "run1")
    _age_sightings(storage, 10)
    storage.save_deal(make_deal(price=80.0), "run1")

    lows = TrendsAnalyzer(storage).get_new_lows(days=30)
    assert len(lows) == 1
    assert lows[0]["url"] == URL
    assert lows[0]["price"] == 80.0


def test_change_detector_deals_for_run(storage):
    """Previously selected non-existent ph.site_name / ph.title columns."""
    storage.save_deal(make_deal(), "run1")
    found = ChangeDetector(storage)._get_deals_for_run("run1")
    assert URL in found
    assert found[URL]["title"] == "DJI drone"
    assert found[URL]["site_name"] == "bazos"


def test_price_tracker_get_price_trend_for_deal(storage):
    """Previously called the non-existent storage.get_deal_by_id."""
    storage.save_deal(make_deal(price=100.0), "run1")
    _age_sightings(storage, 10)
    storage.save_deal(make_deal(price=80.0), "run1")
    row = storage.db.execute("SELECT id FROM deals WHERE url = ?", (URL,)).fetchone()
    assert PriceTracker(storage).get_price_trend_for_deal(row["id"])["trend"] == "dropping"


def test_row_factory_is_sqlite3_row(storage):
    assert storage.db.conn.row_factory is sqlite3.Row