"""Price tracking and trend analysis for deals."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime

from src.notifications.base import Alert
from src.notifications.manager import NotificationManager
from src.searcher.adapters.base import Deal
from src.storage.manager import StorageManager


def _effective_price(deal) -> float:
    return float(getattr(deal, "effective_price_eur", 0.0) or deal.price_eur)


@dataclass
class PriceHistoryEntry:
    id: int
    deal_id: int
    url: str
    price_eur: float
    original_price_eur: float | None
    original_currency: str
    condition: str
    availability: str
    seller_name: str
    seller_rating: float
    shipping_cost_eur: float
    run_id: str
    timestamp: str


@dataclass
class PriceDropAlert:
    url: str
    title: str
    site_name: str
    old_price: float
    new_price: float
    change_pct: float
    old_timestamp: str
    new_timestamp: str


@dataclass
class NewLowAlert:
    url: str
    title: str
    site_name: str
    price: float
    timestamp: str


@dataclass
class PriceTrend:
    trend: str  # dropping, rising, stable, volatile, insufficient_data
    change_pct: float
    volatility: float
    min_price: float
    max_price: float
    data_points: int


class PriceTracker:
    """Tracks price history and detects price drops/trends."""

    def __init__(self, storage: StorageManager):
        self.storage = storage

    def record_sighting(self, deal: Deal, run_id: str) -> int | None:
        """Record a price sighting, return the history entry ID."""
        return self.storage.record_price_sighting(deal, run_id)

    def get_price_trend_for_deal(self, deal_id: int, days: int = 30) -> dict:
        deal = self.storage.get_deal_by_id(deal_id)
        if deal:
            return self.storage.get_price_trend(deal.url, days)
        return {"trend": "insufficient_data", "data_points": 0}

    def get_price_history(self, url: str, days: int = 30) -> list[dict]:
        """Return the stored price history for one URL."""
        return self.storage.get_price_history(url, days)

    def get_deals_nearing_target(self, target_price_eur: float, margin_pct: float = 5.0) -> list[dict]:
        """Find deals within margin_pct% of target price."""
        deals = self.storage.get_all_deals()
        results = []
        for deal in deals:
            price = _effective_price(deal)
            if price <= target_price_eur * (1 + margin_pct / 100):
                results.append({
                    "url": deal.url,
                    "title": deal.title,
                    "price_eur": deal.price_eur,
                    "effective_price_eur": price,
                    "site_name": deal.site_name,
                    "target_price": target_price_eur,
                    "difference_pct": round((price - target_price_eur) / target_price_eur * 100, 2),
                })
        return sorted(results, key=lambda x: x["effective_price_eur"])

    def get_deals_below_price(self, max_price_eur: float, condition: str = "any") -> list[dict]:
        """Get all deals below a certain effective price."""
        deals = self.storage.get_all_deals()
        results = []
        for deal in deals:
            price = _effective_price(deal)
            if price <= max_price_eur and (condition == "any" or deal.condition == condition):
                results.append({
                    "url": deal.url,
                    "title": deal.title,
                    "price_eur": deal.price_eur,
                    "effective_price_eur": price,
                    "site_name": deal.site_name,
                    "condition": deal.condition,
                })
        return sorted(results, key=lambda x: x["effective_price_eur"])

    # ------------------------------------------------------------------
    # Alert generation
    # ------------------------------------------------------------------

    def check_price_drops(self, threshold_pct: float = 5.0, days: int = 7) -> list[Alert]:
        """Return Alert objects for products whose effective price dropped.

        Uses :meth:`StorageManager.detect_price_drops` which compares the
        latest effective price against the earliest sighting in the window.
        """
        alerts: list[Alert] = []
        for drop in self.storage.detect_price_drops(threshold_pct=threshold_pct, days=days):
            alerts.append(
                Alert(
                    title=f"Price drop: {drop['title']}",
                    message=(
                        f"{drop['site_name']}: {drop['title']} dropped "
                        f"{abs(drop['change_pct'])}% — "
                        f"{drop['old_price']:.2f} € → {drop['new_price']:.2f} €"
                    ),
                    severity="warning",
                    metadata={
                        "url": drop["url"],
                        "title": drop["title"],
                        "site_name": drop["site_name"],
                        "old_price": drop["old_price"],
                        "new_price": drop["new_price"],
                        "change_pct": drop["change_pct"],
                        "old_timestamp": drop["old_timestamp"],
                        "new_timestamp": drop["new_timestamp"],
                    },
                )
            )
        return alerts

    def check_new_lows(self, days: int = 30) -> list[Alert]:
        """Return Alert objects for products at their lowest effective price."""
        alerts: list[Alert] = []
        for low in self.storage.detect_new_lows(days=days):
            alerts.append(
                Alert(
                    title=f"New low: {low['title']}",
                    message=(
                        f"{low['site_name']}: {low['title']} at new low "
                        f"{low['price']:.2f} €"
                    ),
                    severity="info",
                    metadata={
                        "url": low["url"],
                        "title": low["title"],
                        "site_name": low["site_name"],
                        "price": low["price"],
                        "timestamp": low["timestamp"],
                    },
                )
            )
        return alerts

    def check_fake_promos(self, threshold_pct: float = 30.0, days: int = 30) -> list[Alert]:
        """Return Alert objects for listings with inflated regular prices.

        A fake promo is when a listing's regular ("was") price is
        significantly higher than historical effective prices.
        """
        alerts: list[Alert] = []
        for promo in self.storage.detect_fake_promos(
            threshold_pct=threshold_pct, days=days
        ):
            alerts.append(
                Alert(
                    title=f"Fake promo: {promo['title']}",
                    message=(
                        f"{promo['site_name']}: {promo['title']} claims "
                        f"regular price {promo['regular_price_eur']:.2f} € but "
                        f"historically sold for up to {promo['effective_price_eur']:.2f} €"
                    ),
                    severity="warning",
                    metadata={
                        "url": promo["url"],
                        "title": promo["title"],
                        "site_name": promo["site_name"],
                        "price": promo["price"],
                        "kind": promo["kind"],
                        "regular_price_eur": promo["regular_price_eur"],
                        "effective_price_eur": promo["effective_price_eur"],
                        "change_pct": promo["change_pct"],
                        "old_timestamp": promo["old_timestamp"],
                        "new_timestamp": promo["new_timestamp"],
                    },
                )
            )
        return alerts


class AlertRuleEngine:
    """Evaluates user-defined price alert rules against latest sightings.

    A rule triggers when the latest *effective* price for a URL is at or
    below the user's target price. A per-rule cooldown prevents repeated
    alerts for the same threshold crossing.
    """

    def __init__(
        self,
        storage: StorageManager,
        notification_manager: NotificationManager | None = None,
    ):
        self.storage = storage
        self.notification_manager = notification_manager

    def evaluate_rules(self) -> list[Alert]:
        """Evaluate all active active rules and send triggered alerts.

        Returns the list of triggered ``Alert`` objects.
        """
        rules = self.storage.list_price_alert_rules(active_only=True)
        alerts: list[Alert] = []
        now = datetime.now(UTC)

        for rule in rules:
            url = rule["url"]
            target = rule["target_price_eur"]

            current_price = self.storage.get_latest_effective_price(url)
            if current_price is None or current_price > target:
                # No sighting yet, or price still above target.
                continue

            # Cooldown check
            last_triggered = rule["last_triggered"]
            if last_triggered is not None:
                try:
                    last = datetime.fromisoformat(last_triggered)
                except ValueError:
                    last = None
                if last is not None and (now - last).total_seconds() < rule[
                    "cooldown_minutes"
                ] * 60:
                    continue  # still in cooldown

            # Build and send alert
            alert = Alert(
                title=f"Price alert: {rule['title']}",
                message=(
                    f"{url} is now {current_price:.2f} €, at or below your "
                    f"target of {target:.2f} €."
                ),
                severity="info",
                metadata={
                    "url": url,
                    "title": rule["title"],
                    "target_price_eur": target,
                    "current_price_eur": current_price,
                    "condition": rule["condition"],
                },
            )
            alerts.append(alert)

            if self.notification_manager is not None:
                try:
                    asyncio.run(
                        self.notification_manager.send_alert(
                            alert, channels=rule["channels"] or None
                        )
                    )
                except Exception:  # noqa: BLE001, S110 - notification failure must not abort
                    pass

            # Record trigger time
            self.storage.set_rule_last_triggered(url, now.isoformat())

        return alerts