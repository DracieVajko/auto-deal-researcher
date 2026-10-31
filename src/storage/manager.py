"""SQLite storage manager for deal deduplication and history."""

import json
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from src.searcher.adapters.base import Deal
from src.storage.schema import get_db
from src.utils.time import today_iso, utcnow, utcnow_iso, utcnow_stamp


@dataclass
class StoredDeal:
    url: str
    title: str
    price_eur: float
    condition: str
    category: str
    site_name: str
    first_seen: str      # ISO date
    last_seen: str       # ISO date
    times_seen: int = 1
    availability: str = "unknown"
    seller_name: str = ""
    seller_rating: float = 0.0
    shipping_cost_eur: float = 0.0
    original_currency: str = "EUR"
    metadata: str = "{}"


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
class RunRecord:
    id: str
    prompt: str
    condition: str
    category: str
    started_at: str
    completed_at: str | None
    total_deals: int
    new_deals: int
    status: str
    error_message: str | None


def _row_to_stored_deal(row) -> StoredDeal:
    """Map a deals row to StoredDeal, tolerating extra/missing columns.

    The deals table has an autoincrement ``id`` primary key while ``url`` is
    only UNIQUE, so rows must be selected by url explicitly and the extra
    columns (id, currency) dropped.
    """
    data = dict(row)
    return StoredDeal(
        url=data["url"],
        title=data["title"],
        price_eur=data["price_eur"],
        condition=data.get("condition") or "unknown",
        category=data.get("category") or "general",
        site_name=data.get("site_name") or "",
        first_seen=data.get("first_seen") or "",
        last_seen=data.get("last_seen") or "",
        times_seen=data.get("times_seen") or 1,
        availability=data.get("availability") or "unknown",
        seller_name=data.get("seller_name") or "",
        seller_rating=data.get("seller_rating") or 0.0,
        shipping_cost_eur=data.get("shipping_cost_eur") or 0.0,
        original_currency=data.get("original_currency") or "EUR",
        metadata=data.get("metadata") or "{}",
    )


class StorageManager:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = get_db(db_path)

    def get_deal(self, url: str) -> StoredDeal | None:
        """Alias for get_deal_by_url (backward compatibility)."""
        return self.get_deal_by_url(url)

    def get_deal_by_url(self, url: str) -> StoredDeal | None:
        row = self.db.execute("SELECT * FROM deals WHERE url = ?", (url,)).fetchone()
        return _row_to_stored_deal(row) if row else None

    def get_deal_by_id(self, deal_id: int) -> StoredDeal | None:
        row = self.db.execute("SELECT * FROM deals WHERE id = ?", (deal_id,)).fetchone()
        return _row_to_stored_deal(row) if row else None

    def save_deal(self, deal: Deal, run_id: str = ""):
        existing = self.get_deal_by_url(deal.url)
        today = today_iso()

        deal_data = {
            "url": deal.url,
            "title": deal.title,
            "price_eur": deal.price_eur,
            "currency": deal.currency,
            "condition": deal.condition,
            "category": deal.category,
            "site_name": deal.site_name,
            "availability": getattr(deal, "availability", "unknown"),
            "seller_name": getattr(deal, "seller_name", ""),
            "seller_rating": getattr(deal, "seller_rating", 0.0),
            "shipping_cost_eur": getattr(deal, "shipping_cost_eur", 0.0),
            "original_currency": getattr(deal, "original_currency", "EUR"),
            "metadata": json.dumps(getattr(deal, "metadata", {}) or {}, ensure_ascii=False),
        }

        if existing:
            # Update existing deal (row is addressed by its UNIQUE url)
            self.db.execute(
                """
                UPDATE deals SET
                    title = ?, price_eur = ?, currency = ?, condition = ?,
                    category = ?, site_name = ?, last_seen = ?, times_seen = ?,
                    availability = ?, seller_name = ?, seller_rating = ?,
                    shipping_cost_eur = ?, original_currency = ?, metadata = ?
                WHERE url = ?
                """,
                (
                    deal_data["title"], deal_data["price_eur"], deal_data["currency"],
                    deal_data["condition"], deal_data["category"], deal_data["site_name"],
                    today, existing.times_seen + 1, deal_data["availability"],
                    deal_data["seller_name"], deal_data["seller_rating"],
                    deal_data["shipping_cost_eur"], deal_data["original_currency"],
                    deal_data["metadata"], deal.url,
                ),
            )
        else:
            # Insert new deal
            self.db.execute(
                """
                INSERT INTO deals (
                    url, title, price_eur, currency, condition, category, site_name,
                    first_seen, last_seen, times_seen, availability, seller_name,
                    seller_rating, shipping_cost_eur, original_currency, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    deal_data["url"], deal_data["title"], deal_data["price_eur"],
                    deal_data["currency"], deal_data["condition"], deal_data["category"],
                    deal_data["site_name"], today, today, 1, deal_data["availability"],
                    deal_data["seller_name"], deal_data["seller_rating"],
                    deal_data["shipping_cost_eur"], deal_data["original_currency"],
                    deal_data["metadata"],
                ),
            )

        # Record price history
        if run_id:
            self.record_price_sighting(deal, run_id)

    def record_price_sighting(self, deal: Deal, run_id: str) -> int | None:
        """Record a price sighting in price_history table."""
        # price_history.deal_id is NOT NULL, so the deal row must exist first.
        row = self.db.execute("SELECT id FROM deals WHERE url = ?", (deal.url,)).fetchone()
        if row is None:
            self.save_deal(deal)
            row = self.db.execute("SELECT id FROM deals WHERE url = ?", (deal.url,)).fetchone()

        sighting = {
            "deal_id": row["id"],
            "url": deal.url,
            "price_eur": deal.price_eur,
            "original_price_eur": getattr(deal, "original_price_eur", deal.price_eur),
            "original_currency": getattr(deal, "original_currency", "EUR"),
            "condition": deal.condition,
            "availability": getattr(deal, "availability", "unknown"),
            "seller_name": getattr(deal, "seller_name", ""),
            "seller_rating": getattr(deal, "seller_rating", 0.0),
            "shipping_cost_eur": getattr(deal, "shipping_cost_eur", 0.0),
            "run_id": f"manual_{utcnow_stamp()}" if not run_id else run_id,
            "timestamp": utcnow_iso(),
        }
        result = self.db["price_history"].insert(sighting)
        return result.last_pk if result else None

    def get_price_history(self, url: str, days: int = 30) -> list[dict]:
        """Get price history for a specific product URL."""
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        rows = self.db.execute("""
            SELECT * FROM price_history 
            WHERE url = ? AND timestamp >= ?
            ORDER BY timestamp DESC
        """, (url, cutoff)).fetchall()
        return [dict(row) for row in rows]

    def get_price_history_for_deal(self, deal_id: int) -> list[dict]:
        rows = self.db.execute("""
            SELECT * FROM price_history 
            WHERE deal_id = ?
            ORDER BY timestamp DESC
        """, (deal_id,)).fetchall()
        return [dict(row) for row in rows]

    def detect_price_drops(self, threshold_pct: float = 5.0, days: int = 7) -> list[dict]:
        """Find products with price drops >= threshold% in last N days."""
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        rows = self.db.execute("""
            SELECT ph.*, d.title, d.site_name
            FROM price_history ph
            JOIN deals d ON ph.url = d.url
            WHERE ph.timestamp >= ?
            ORDER BY ph.timestamp DESC
        """, (cutoff,)).fetchall()

        # Group by URL and find drops
        url_prices = {}
        for row in rows:
            url = row["url"]
            if url not in url_prices:
                url_prices[url] = []
            url_prices[url].append(dict(row))

        drops = []
        for url, prices in url_prices.items():
            if len(prices) >= 2:
                # Compare latest with earliest in window
                latest = prices[0]
                earliest = prices[-1]
                if earliest["price_eur"] > 0:
                    change_pct = ((latest["price_eur"] - earliest["price_eur"]) / earliest["price_eur"]) * 100
                    if change_pct <= -threshold_pct:
                        drops.append({
                            "url": url,
                            "title": latest.get("title", ""),
                            "site_name": latest.get("site_name", ""),
                            "old_price": earliest["price_eur"],
                            "new_price": latest["price_eur"],
                            "change_pct": round(change_pct, 2),
                            "old_timestamp": earliest["timestamp"],
                            "new_timestamp": latest["timestamp"],
                        })
        return drops

    def detect_new_lows(self, days: int = 30) -> list[dict]:
        """Find products at their lowest price in N days."""
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        rows = self.db.execute("""
            SELECT ph.*, d.title, d.site_name,
                   MIN(ph.price_eur) OVER (PARTITION BY ph.url) as min_price
            FROM price_history ph
            JOIN deals d ON ph.url = d.url
            WHERE ph.timestamp >= ?
        """, (cutoff,)).fetchall()

        new_lows = []
        for row in rows:
            if row["price_eur"] == row["min_price"]:
                # Check if this is the first time at this low price
                earlier = self.db.execute("""
                    SELECT 1 FROM price_history 
                    WHERE url = ? AND price_eur <= ? AND timestamp < ?
                    LIMIT 1
                """, (row["url"], row["price_eur"], row["timestamp"])).fetchone()
                if not earlier:
                    new_lows.append({
                        "url": row["url"],
                        "title": row["title"],
                        "site_name": row["site_name"],
                        "price": row["price_eur"],
                        "timestamp": row["timestamp"],
                    })
        return new_lows

    def get_price_trend(self, url: str, days: int = 30) -> dict:
        """Compute trend: dropping, rising, stable, volatile."""
        cutoff = (utcnow() - timedelta(days=days)).isoformat()
        rows = self.db.execute("""
            SELECT price_eur, timestamp FROM price_history 
            WHERE url = ? AND timestamp >= ?
            ORDER BY timestamp ASC
        """, (url, cutoff)).fetchall()

        if len(rows) < 2:
            return {"trend": "insufficient_data", "points": len(rows)}

        prices = [r["price_eur"] for r in rows]
        first_price = prices[0]
        last_price = prices[-1]
        change_pct = ((last_price - first_price) / first_price) * 100 if first_price > 0 else 0

        # Calculate volatility (std dev / mean)
        import statistics
        mean_price = statistics.mean(prices)
        volatility = statistics.stdev(prices) / mean_price if mean_price > 0 and len(prices) > 1 else 0

        if change_pct <= -5:
            trend = "dropping"
        elif change_pct >= 5:
            trend = "rising"
        elif volatility > 0.1:
            trend = "volatile"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "change_pct": round(change_pct, 2),
            "volatility": round(volatility, 3),
            "min_price": min(prices),
            "max_price": max(prices),
            "data_points": len(prices),
        }

    def mark_seen_today(self, urls: list[str]):
        """Call after each run for all URLs found in this run."""
        today = today_iso()
        self.db.conn.executemany(
            "UPDATE deals SET last_seen = ? WHERE url = ?",
            [(today, url) for url in urls],
        )

    def prune_missing(self, max_age_days: int = 30, grace_period_days: int = 7) -> dict:
        """
        Mark deals as 'missing' if not seen in last grace_period_days runs.
        Hard delete if missing for max_age_days.
        Preserve price history even when deal is pruned.
        """
        cutoff = (utcnow().date() - timedelta(days=max_age_days)).isoformat()
        grace_cutoff = (utcnow().date() - timedelta(days=grace_period_days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            # Count deals to be pruned
            to_prune = conn.execute(
                "SELECT COUNT(*) FROM deals WHERE last_seen < ?", (cutoff,)
            ).fetchone()[0]

            # Hard delete old deals (price_history preserved)
            conn.execute("DELETE FROM deals WHERE last_seen < ?", (cutoff,))

            # Mark recently missing (could add a status column if needed)
            conn.execute(
                "UPDATE deals SET availability = 'missing' WHERE last_seen < ? AND last_seen >= ?",
                (grace_cutoff, cutoff),
            )

        return {
            "pruned": to_prune,
            "cutoff_date": cutoff,
            "grace_cutoff": grace_cutoff,
        }

    def get_all_deals(self) -> list[StoredDeal]:
        rows = self.db.execute("SELECT * FROM deals ORDER BY last_seen DESC").fetchall()
        return [_row_to_stored_deal(row) for row in rows]

    def is_known(self, url: str) -> bool:
        return self.get_deal_by_url(url) is not None

    # Run tracking
    def create_run(self, run_id: str, prompt: str, condition: str, category: str) -> None:
        self.db["runs"].insert({
            "id": run_id,
            "prompt": prompt,
            "condition": condition,
            "category": category,
            "started_at": utcnow_iso(),
            "completed_at": None,
            "total_deals": 0,
            "new_deals": 0,
            "status": "running",
        }, pk="id")

    def complete_run(self, run_id: str, total_deals: int, new_deals: int, status: str = "completed", error: str = "") -> None:
        self.db["runs"].update(run_id, {
            "completed_at": utcnow_iso(),
            "total_deals": total_deals,
            "new_deals": new_deals,
            "status": status,
            "error_message": error,
        })

    def get_last_completed_run(self) -> RunRecord | None:
        row = self.db.execute("""
            SELECT * FROM runs 
            WHERE status = 'completed' 
            ORDER BY completed_at DESC LIMIT 1
        """).fetchone()
        return RunRecord(**row) if row else None

    def get_run(self, run_id: str) -> RunRecord | None:
        row = self.db["runs"].get(run_id)
        return RunRecord(**row) if row else None

    def get_all_runs(self, limit: int = 50) -> list[RunRecord]:
        rows = self.db["runs"].rows_where(order_by="started_at DESC", limit=limit)
        return [RunRecord(**row) for row in rows]

    # Alerts
    def add_alert(self, run_id: str, rule_name: str, message: str, severity: str = "info") -> int:
        result = self.db["alerts"].insert({
            "run_id": run_id,
            "rule_name": rule_name,
            "message": message,
            "severity": severity,
            "sent": 0,
        })
        return result.last_pk

    def get_unsent_alerts(self) -> list[dict]:
        return list(self.db["alerts"].rows_where("sent = 0", order_by="created_at"))

    def mark_alert_sent(self, alert_id: int) -> None:
        self.db["alerts"].update(alert_id, {"sent": 1, "sent_at": utcnow_iso()})
