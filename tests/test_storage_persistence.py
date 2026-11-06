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
from src.searcher.pricing import PriceKind, ShippingQuote, build_price_quote
from src.storage.manager import StorageManager
from src.utils.time import utcnow

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
    
    now = utcnow()
    
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

    drops = storage.detect_price_drops(threshold_pct=10.0, days=30)
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
        ((utcnow() - timedelta(days=2)).isoformat(), URL),
    )
    storage.save_deal(make_deal(price=80.0, url="https://x/2"), "run1")  # effective = 80.0

    lows = storage.detect_new_lows(days=30)
    urls = [d["url"] for d in lows]
    assert URL in urls
    # Effective price 120 is the low for this URL (only sighting), not 100 raw
    item = next(d for d in lows if d["url"] == URL)
    assert item["price"] == 120.0


def test_detect_fake_promos(storage):
    """Detect when a listing's 'original price' is inflated vs historical prices."""
    # Historical: same item sold at 80 EUR previously (no discount)
    storage.save_deal(make_deal(price=80.0), "run1")

    # Current listing: claims regular=200, sells for 100 — fake promo
    deal = make_deal(price=100.0)
    deal.price_quote = build_price_quote(
        100.0, shipping=ShippingQuote(is_free=True),
        kind=PriceKind.PROMO,
        regular_price_eur=200.0,
        evidence=["Was 200.00 EUR"],
    )
    storage.save_deal(deal, "run2")

    flags = storage.detect_fake_promos(threshold_pct=30.0, days=30)
    assert len(flags) == 1
    assert flags[0]["url"] == URL
    assert flags[0]["kind"] == "promo"
    assert flags[0]["regular_price_eur"] == 200.0
    assert flags[0]["effective_price_eur"] == 100.0
    assert flags[0]["change_pct"] < -30.0  # regular price is 60% above historical max


def test_detect_fake_promos_no_false_positive(storage):
    """A genuine discount should not be flagged as fake."""
    # Historical: same item sold at 120 EUR previously
    storage.save_deal(make_deal(price=120.0), "run1")

    # Current listing: regular=150, sells for 100 — real discount vs history
    deal = make_deal(price=100.0)
    deal.price_quote = build_price_quote(
        100.0, shipping=ShippingQuote(is_free=True),
        kind=PriceKind.PROMO,
        regular_price_eur=150.0,
        evidence=["Was 150.00 EUR"],
    )
    storage.save_deal(deal, "run2")

    flags = storage.detect_fake_promos(threshold_pct=30.0, days=30)
    assert len(flags) == 0  # no false positive - regular 150 is only 25% above historical 120


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


def test_price_tracker_check_price_drops_returns_alerts(storage):
    """PriceTracker.check_price_drops returns Alert objects for effective-price drops."""
    deal = make_deal(price=100.0)
    deal.price_quote = build_price_quote(100.0, shipping=ShippingQuote(is_free=True))
    storage.save_deal(deal, "run1")

    now = utcnow()
    storage.db.execute(
        "UPDATE price_history SET timestamp = ? WHERE url = ?",
        ((now - timedelta(days=2)).isoformat(), URL),
    )
    storage.db.execute(
        "INSERT INTO price_history (deal_id, url, price_eur, effective_price_eur, timestamp, original_price_eur, original_currency, condition, availability, seller_name, seller_rating, shipping_cost_eur, run_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, URL, 70.0, 70.0, (now - timedelta(days=1)).isoformat(), 70.0, "EUR", "used", "unknown", "", 0.0, "EUR", "run1"),
    )

    alerts = PriceTracker(storage).check_price_drops(threshold_pct=20.0, days=30)
    assert len(alerts) == 1
    assert alerts[0].title == "Price drop: DJI drone"
    assert alerts[0].severity == "warning"
    assert alerts[0].metadata["change_pct"] == -30.0  # (70-100)/100
    assert alerts[0].metadata["old_price"] == 100.0
    assert alerts[0].metadata["new_price"] == 70.0


def test_price_tracker_check_new_lows_returns_alerts(storage):
    """PriceTracker.check_new_lows returns Alert objects for new lows."""
    deal = make_deal(price=100.0)
    deal.price_quote = build_price_quote(100.0, shipping=ShippingQuote(is_free=True))
    storage.save_deal(deal, "run1")

    now = utcnow()
    storage.db.execute(
        "UPDATE price_history SET timestamp = ? WHERE url = ?",
        ((now - timedelta(days=2)).isoformat(), URL),
    )
    storage.save_deal(make_deal(price=60.0), "run1")  # new low

    alerts = PriceTracker(storage).check_new_lows(days=30)
    assert len(alerts) >= 1
    new_low = next(a for a in alerts if "new low" in a.title.lower())
    assert new_low.metadata["price"] == 60.0


def test_price_tracker_check_fake_promos_returns_alerts(storage):
    """PriceTracker.check_fake_promos returns Alert objects for inflated regular prices."""
    # Historical: item sold at 80 EUR
    storage.save_deal(make_deal(price=80.0), "run1")

    # Current: claims regular=200, sells for 100 — fake promo
    deal = make_deal(price=100.0)
    deal.price_quote = build_price_quote(
        100.0, shipping=ShippingQuote(is_free=True),
        kind=PriceKind.PROMO,
        regular_price_eur=200.0,
        evidence=["Was 200.00 EUR"],
    )
    storage.save_deal(deal, "run2")

    alerts = PriceTracker(storage).check_fake_promos(threshold_pct=30.0, days=30)
    assert len(alerts) == 1
    assert alerts[0].title.startswith("Fake promo:")
    assert alerts[0].severity == "warning"
    assert alerts[0].metadata["regular_price_eur"] == 200.0
    assert alerts[0].metadata["effective_price_eur"] == 100.0
    assert alerts[0].metadata["change_pct"] < -30.0


def test_save_item_specs_first_insert(tmp_path):
    s = StorageManager(str(tmp_path / "specs.db"))
    s.save_item_specs(
        "Citroen eC3",
        "auto",
        {"power_kw": 83.0, "battery_kwh": 44.0},
        {"summary": "Good EV", "pros": ["cheap"], "cons": [], "source_count": 1},
        ["https://example.com/specs"],
    )
    row = s.get_item_specs("Citroen eC3")
    assert row is not None
    assert row["item_name"] == "Citroen eC3"
    assert row["category"] == "auto"
    assert row["specs"]["power_kw"] == 83.0
    assert row["specs"]["battery_kwh"] == 44.0
    assert row["review"]["summary"] == "Good EV"
    assert row["source_urls"] == ["https://example.com/specs"]


def test_save_item_specs_update_existing(tmp_path):
    s = StorageManager(str(tmp_path / "specs.db"))
    s.save_item_specs("Citroen eC3", "auto", {"power_kw": 83.0}, {"summary": "v1"}, ["https://a.com"])
    s.save_item_specs("Citroen eC3", "auto", {"power_kw": 90.0}, {"summary": "v2"}, ["https://b.com"])
    row = s.get_item_specs("Citroen eC3")
    assert row["specs"]["power_kw"] == 90.0
    assert row["review"]["summary"] == "v2"
    assert row["source_urls"] == ["https://b.com"]


def test_save_item_specs_missing_returns_none(tmp_path):
    s = StorageManager(str(tmp_path / "specs.db"))
    assert s.get_item_specs("nonexistent") is None


def test_save_price_alert_rule_insert_get_list_remove(tmp_path):
    """Price alert rules: insert, get, list, remove."""
    s = StorageManager(str(tmp_path / "alerts.db"))
    s.save_price_alert_rule(
        "https://bazos.sk/i/1",
        "DJI drone",
        target_price_eur=150.0,
        condition="used",
        channels=["console", "webhook"],
        cooldown_minutes=30,
    )
    rule = s.get_price_alert_rule("https://bazos.sk/i/1")
    assert rule is not None
    assert rule["url"] == "https://bazos.sk/i/1"
    assert rule["title"] == "DJI drone"
    assert rule["target_price_eur"] == 150.0
    assert rule["condition"] == "used"
    assert rule["channels"] == ["console", "webhook"]
    assert rule["cooldown_minutes"] == 30
    assert rule["is_active"] is True

    rules = s.list_price_alert_rules()
    assert len(rules) == 1

    # Update: change target price
    s.save_price_alert_rule(
        "https://bazos.sk/i/1",
        "DJI drone",
        target_price_eur=120.0,
        condition="used",
        channels=["console"],
        cooldown_minutes=60,
    )
    rule = s.get_price_alert_rule("https://bazos.sk/i/1")
    assert rule["target_price_eur"] == 120.0
    assert rule["cooldown_minutes"] == 60

    # Deactivate
    s.set_rule_active("https://bazos.sk/i/1", False)
    rule = s.get_price_alert_rule("https://bazos.sk/i/1")
    assert rule["is_active"] is False

    # Remove
    assert s.remove_price_alert_rule("https://bazos.sk/i/1") is True
    assert s.get_price_alert_rule("https://bazos.sk/i/1") is None
    assert s.remove_price_alert_rule("https://bazos.sk/i/1") is False  # already gone


def test_get_latest_effective_price(tmp_path):
    """get_latest_effective_price returns latest effective price for a URL."""
    s = StorageManager(str(tmp_path / "prices.db"))
    s.create_run("run1", "test", "any", "any")

    # No sightings -> None
    assert s.get_latest_effective_price("https://bazos.sk/i/1") is None

    # First sighting
    s.save_deal(make_deal(price=100.0), "run1")
    assert s.get_latest_effective_price(URL) == 100.0

    # Second sighting with shipping -> effective price
    deal = make_deal(price=80.0)
    deal.price_quote = build_price_quote(80.0, shipping=ShippingQuote(cost_eur=10.0))  # effective 90
    s.save_deal(deal, "run1")

    # Wait: make_deal(price=80) reuses URL; price_history gets a second row.
    assert s.get_latest_effective_price(URL) == 90.0