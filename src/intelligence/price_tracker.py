"""Price tracking and trend analysis for deals."""

from __future__ import annotations

from dataclasses import dataclass

from src.searcher.adapters.base import Deal
from src.storage.manager import StorageManager


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

    def record_sighting(self, deal: Deal, run_id: str) -> int:
        """Record a price sighting, return the history entry ID."""
        return self.storage.record_price_sighting(deal, run_id)

    def get_price_history(self, url: str, days: int = 30) -> list[dict]:
        """Get price history for a specific product URL."""
        return self.storage.get_price_history(url, days)

    def get_price_history_for_deal(self, deal_id: int) -> list[dict]:
        return self.storage.get_price_history_for_deal(deal_id)

    def detect_price_drops(self, threshold_pct: float = 5.0, days: int = 7) -> list[dict]:
        """Find products with price drops >= threshold% in last N days."""
        return self.storage.detect_price_drops(threshold_pct, days)

    def detect_new_lows(self, days: int = 30) -> list[dict]:
        """Find products at their lowest price in N days."""
        return self.storage.detect_new_lows(days)

    def get_price_trend(self, url: str, days: int = 30) -> dict:
        """Compute trend: dropping, rising, stable, volatile."""
        return self.storage.get_price_trend(url, days)

    def get_price_trend_for_deal(self, deal_id: int, days: int = 30) -> dict:
        deal = self.storage.get_deal_by_id(deal_id)
        if deal:
            return self.get_price_trend(deal.url, days)
        return {"trend": "unknown", "data_points": 0}

    def get_deals_nearing_target(self, target_price_eur: float, margin_pct: float = 5.0) -> list[dict]:
        """Find deals within margin_pct% of target price."""
        deals = self.storage.get_all_deals()
        results = []
        for deal in deals:
            if deal.price_eur <= target_price_eur * (1 + margin_pct / 100):
                results.append({
                    "url": deal.url,
                    "title": deal.title,
                    "price_eur": deal.price_eur,
                    "site_name": deal.site_name,
                    "target_price": target_price_eur,
                    "difference_pct": round((deal.price_eur - target_price_eur) / target_price_eur * 100, 2),
                })
        return sorted(results, key=lambda x: x["price_eur"])

    def get_deals_below_price(self, max_price_eur: float, condition: str = "any") -> list[dict]:
        """Get all deals below a certain price."""
        deals = self.storage.get_all_deals()
        results = []
        for deal in deals:
            if deal.price_eur <= max_price_eur and (condition == "any" or deal.condition == condition):
                results.append({
                    "url": deal.url,
                    "title": deal.title,
                    "price_eur": deal.price_eur,
                    "site_name": deal.site_name,
                    "condition": deal.condition,
                })
        return sorted(results, key=lambda x: x["price_eur"])