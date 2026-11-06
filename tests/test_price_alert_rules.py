"""Tests for AlertRuleEngine (price alert thresholds with notification delivery)."""

from datetime import UTC, datetime

from src.intelligence.price_tracker import AlertRuleEngine
from src.searcher.adapters.base import Deal
from src.searcher.pricing import ShippingQuote, build_price_quote
from src.storage.manager import StorageManager


class FakeNotificationManager:
    """Captures sent alerts instead of delivering them."""

    def __init__(self):
        self.sent: list = []
        self.channels = []

    async def send_alert(self, alert, channels=None):
        self.sent.append(alert)
        return True


def _make_storage(tmp_path):
    s = StorageManager(str(tmp_path / "alerts.db"))
    s.create_run("run1", "test", "any", "any")
    return s


def _save_sighting(s, url, price_eur, shipping_cost=0.0):
    deal = Deal(url=url, title="Test item", price_eur=price_eur, condition="used", category="electronics", site_name="test")
    if shipping_cost:
        deal.price_quote = build_price_quote(price_eur, shipping=ShippingQuote(cost_eur=shipping_cost))
    s.save_deal(deal, "run1")


def test_evaluate_rule_triggers_at_or_below_target(tmp_path):
    s = _make_storage(tmp_path)
    s.save_price_alert_rule(
        "https://bazos.sk/i/1", "DJI drone", target_price_eur=150.0, condition="used",
    )
    _save_sighting(s, "https://bazos.sk/i/1", 140.0)

    nm = FakeNotificationManager()
    engine = AlertRuleEngine(s, nm)
    alerts = engine.evaluate_rules()

    assert len(alerts) == 1
    assert alerts[0].title.startswith("Price alert:")
    assert alerts[0].metadata["target_price_eur"] == 150.0
    assert alerts[0].metadata["current_price_eur"] == 140.0
    assert len(nm.sent) == 1


def test_evaluate_rule_no_trigger_when_above_target(tmp_path):
    s = _make_storage(tmp_path)
    s.save_price_alert_rule(
        "https://bazos.sk/i/1", "DJI drone", target_price_eur=100.0, condition="used",
    )
    _save_sighting(s, "https://bazos.sk/i/1", 150.0)

    nm = FakeNotificationManager()
    engine = AlertRuleEngine(s, nm)
    alerts = engine.evaluate_rules()

    assert alerts == []
    assert nm.sent == []


def test_evaluate_rule_uses_effective_price_incl_shipping(tmp_path):
    s = _make_storage(tmp_path)
    s.save_price_alert_rule(
        "https://bazos.sk/i/1", "DJI drone", target_price_eur=90.0, condition="used",
    )
    # Listed 80 + shipping 10 = effective 90 -> should trigger (<= target)
    deal = Deal(url="https://bazos.sk/i/1", title="DJI drone", price_eur=80.0, condition="used", category="electronics", site_name="test")
    deal.price_quote = build_price_quote(80.0, shipping=ShippingQuote(cost_eur=10.0))
    s.save_deal(deal, "run1")

    nm = FakeNotificationManager()
    engine = AlertRuleEngine(s, nm)
    alerts = engine.evaluate_rules()

    assert len(alerts) == 1
    assert alerts[0].metadata["current_price_eur"] == 90.0


def test_evaluate_rule_no_price_yet_skipped(tmp_path):
    s = _make_storage(tmp_path)
    s.save_price_alert_rule(
        "https://bazos.sk/i/1", "DJI drone", target_price_eur=150.0, condition="used",
    )
    # No sightings for this URL

    nm = FakeNotificationManager()
    engine = AlertRuleEngine(s, nm)
    alerts = engine.evaluate_rules()

    assert alerts == []
    assert nm.sent == []


def test_evaluate_rule_cooldown_blocks_retrigger(tmp_path):
    s = _make_storage(tmp_path)
    s.save_price_alert_rule(
        "https://bazos.sk/i/1", "DJI drone", target_price_eur=150.0, condition="used",
        cooldown_minutes=60,
    )
    _save_sighting(s, "https://bazos.sk/i/1", 140.0)

    nm = FakeNotificationManager()
    engine = AlertRuleEngine(s, nm)

    # First trigger
    alerts = engine.evaluate_rules()
    assert len(alerts) == 1
    assert len(nm.sent) == 1

    # Mark triggered just now
    now = datetime.now(UTC).isoformat()
    s.db.execute(
        "UPDATE alert_rules SET last_triggered = ? WHERE url = ?",
        (now, "https://bazos.sk/i/1"),
    )

    # Immediately again -> cooldown blocks
    alerts = engine.evaluate_rules()
    assert alerts == []
    assert len(nm.sent) == 1  # no additional send


def test_evaluate_rule_inactive_skipped(tmp_path):
    s = _make_storage(tmp_path)
    s.save_price_alert_rule(
        "https://bazos.sk/i/1", "DJI drone", target_price_eur=150.0, condition="used",
    )
    s.set_rule_active("https://bazos.sk/i/1", False)
    _save_sighting(s, "https://bazos.sk/i/1", 140.0)

    nm = FakeNotificationManager()
    engine = AlertRuleEngine(s, nm)
    alerts = engine.evaluate_rules()

    assert alerts == []
    assert nm.sent == []


def test_evaluate_rule_multiple_rules(tmp_path):
    s = _make_storage(tmp_path)
    s.save_price_alert_rule("https://bazos.sk/i/1", "Drone", target_price_eur=150.0, condition="used")
    s.save_price_alert_rule("https://bazos.sk/i/2", "Camera", target_price_eur=50.0, condition="used")
    _save_sighting(s, "https://bazos.sk/i/1", 140.0)   # triggers (<=150)
    _save_sighting(s, "https://bazos.sk/i/2", 60.0)    # no trigger (>50)

    nm = FakeNotificationManager()
    engine = AlertRuleEngine(s, nm)
    alerts = engine.evaluate_rules()

    assert len(alerts) == 1
    assert alerts[0].metadata["url"] == "https://bazos.sk/i/1"
    assert len(nm.sent) == 1
