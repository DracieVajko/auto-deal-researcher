"""Trends analysis - category-level price trends, market signals."""

import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class CategoryTrend:
    category: str
    trend: str  # dropping, rising, stable, volatile
    change_pct: float
    volatility: float
    min_price: float
    max_price: float
    avg_price: float
    data_points: int
    sample_items: list[dict]


class TrendsAnalyzer:
    """Analyzes price trends across categories and sites."""
    
    def __init__(self, storage):
        self.storage = storage
    
    def analyze_category(self, category: str, days: int = 30) -> dict:
        """Analyze price trends for a category."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        # Get all deals in category from price history
        # Note: deals table uses url as primary key, not id
        rows = self.storage.db.execute("""
            SELECT ph.*, d.category, d.site_name
            FROM price_history ph
            JOIN deals d ON ph.url = d.url
            WHERE ph.timestamp >= ? AND d.category = ?
            ORDER BY ph.timestamp ASC
        """, (cutoff, category)).fetchall()
        
        if not rows:
            return {"category": category, "trend": "insufficient_data", "data_points": 0}
        
        # Group by product (URL)
        product_prices = {}
        for row in rows:
            url = row["url"]
            if url not in product_prices:
                product_prices[url] = []
            product_prices[url].append({
                "price": row["price_eur"],
                "timestamp": row["timestamp"],
                "condition": row["condition"],
            })
        
        # Calculate trends per product
        trends = []
        for url, prices in product_prices.items():
            if len(prices) < 2:
                continue
            
            prices_sorted = sorted(prices, key=lambda x: x["timestamp"])
            first_price = prices_sorted[0]["price"]
            last_price = prices_sorted[-1]["price"]

            if first_price == 0:
                continue

            change_pct = ((last_price - first_price) / first_price) * 100
            
            # Calculate volatility
            series = [p["price"] for p in prices_sorted]
            mean_price = sum(series) / len(series)
            volatility = statistics.stdev(series) / mean_price if mean_price > 0 and len(series) > 1 else 0
            
            trends.append({
                "url": url,
                "first_price": first_price,
                "last_price": last_price,
                "change_pct": round(change_pct, 2),
                "volatility": round(volatility, 3),
                "data_points": len(series),
            })
        
        if not trends:
            return {"category": category, "trend": "insufficient_data", "products": 0}
        
        # Aggregate category trend
        avg_change = sum(t["change_pct"] for t in trends) / len(trends)
        avg_volatility = sum(t["volatility"] for t in trends) / len(trends)
        
        if avg_change <= -5:
            trend = "dropping"
        elif avg_change >= 5:
            trend = "rising"
        elif max(t["volatility"] for t in trends) > 0.15:
            trend = "volatile"
        else:
            trend = "stable"
        
        return {
            "category": category,
            "trend": trend,
            "avg_change_pct": round(avg_change, 2),
            "avg_volatility": round(avg_volatility, 3),
            "products_tracked": len(trends),
            "dropping_count": sum(1 for t in trends if t["change_pct"] < -5),
            "rising_count": sum(1 for t in trends if t["change_pct"] > 5),
            "stable_count": sum(1 for t in trends if -5 <= t["change_pct"] <= 5),
            "details": trends[:10],  # top 10
        }
    
    def get_all_category_trends(self, days: int = 30) -> dict:
        """Get trends for all categories."""
        categories = set()
        rows = self.storage.db.execute("SELECT DISTINCT category FROM deals WHERE category != 'any'").fetchall()
        categories = {row[0] for row in rows}
        
        results = {}
        for cat in categories:
            results[cat] = self.analyze_category(cat, days)
        
        return results
    
    def get_price_drops(self, threshold_pct: float = 10.0, days: int = 7) -> list[dict]:
        """Find significant price drops across all products."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        rows = self.storage.db.execute("""
            SELECT ph.url AS url, ph.price_eur AS price_eur,
                   ph.timestamp AS timestamp, ph.condition AS condition,
                   d.title AS title, d.site_name AS site_name
            FROM price_history ph
            JOIN deals d ON ph.url = d.url
            WHERE ph.timestamp >= ?
            ORDER BY ph.timestamp DESC
        """, (cutoff,)).fetchall()

        # Group by URL
        url_prices = {}
        for row in rows:
            url = row["url"]
            if url not in url_prices:
                url_prices[url] = []
            url_prices[url].append({
                "price": row["price_eur"],
                "timestamp": row["timestamp"],
                "condition": row["condition"],
                "title": row["title"],
                "site": row["site_name"],
            })

        drops = []
        for url, prices in url_prices.items():
            if len(prices) < 2:
                continue

            prices_sorted = sorted(prices, key=lambda x: x["timestamp"])
            first = prices_sorted[0]
            last = prices_sorted[-1]

            if first["price"] == 0:
                continue

            change_pct = ((last["price"] - first["price"]) / first["price"]) * 100

            if change_pct <= -threshold_pct:
                drops.append({
                    "url": url,
                    "title": last["title"],
                    "site": last["site"],
                    "old_price": first["price"],
                    "new_price": last["price"],
                    "change_pct": round(change_pct, 2),
                    "condition": last["condition"],
                })

        return sorted(drops, key=lambda x: x["change_pct"])  # most negative first
    
    def get_new_lows(self, days: int = 30) -> list[dict]:
        """Find products at their lowest price in the period."""
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        rows = self.storage.db.execute("""
            SELECT ph.url AS url, ph.price_eur AS price_eur,
                   ph.timestamp AS timestamp, ph.condition AS condition,
                   d.title AS title, d.site_name AS site_name
            FROM price_history ph
            JOIN deals d ON ph.url = d.url
            WHERE ph.timestamp >= ?
            ORDER BY ph.timestamp ASC
        """, (cutoff,)).fetchall()

        # Group by URL and find min price
        url_min = {}
        for row in rows:
            url = row["url"]
            if url not in url_min or row["price_eur"] < url_min[url]["price"]:
                url_min[url] = {
                    "price": row["price_eur"],
                    "timestamp": row["timestamp"],
                    "title": row["title"],
                    "site": row["site_name"],
                    "condition": row["condition"],
                }

        # Filter to only those at their minimum
        new_lows = []
        for url, data in url_min.items():
            # Check if this is the absolute minimum ever
            min_ever = self.storage.db.execute(
                "SELECT MIN(price_eur) FROM price_history WHERE url = ?", (url,)
            ).fetchone()
            if min_ever and min_ever[0] == data["price"]:
                new_lows.append({
                    "url": url,
                    "title": data["title"],
                    "price": data["price"],
                    "site": data["site"],
                    "condition": data["condition"],
                })

        return new_lows