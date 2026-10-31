"""Watchlist management - target price alerts, history tracking, personal watchlist."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from src.notifications import NotificationManager
from src.storage.manager import StorageManager

logger = logging.getLogger(__name__)


@dataclass
class WatchlistItem:
    """Item on user's watchlist with target price and alerts."""
    url: str
    title: str
    target_price_eur: float
    current_price_eur: Optional[float] = None
    condition: str = "any"
    category: str = "any"
    site_name: str = ""
    url_hash: str = ""
    added_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_checked: Optional[str] = None
    last_price_eur: Optional[float] = None
    price_history: list[dict] = field(default_factory=list)  # [{timestamp, price_eur, condition, site}]
    alert_enabled: bool = True
    alert_threshold_pct: float = 5.0  # alert when price drops >= this %
    target_price_reached: bool = False
    last_notified_price: Optional[float] = None
    
    def __post_init__(self):
        if not self.url_hash:
            import hashlib
            self.url_hash = hashlib.md5(self.url.encode()).hexdigest()[:12]


class WatchlistManager:
    """Manages user's watchlist with price tracking and alerts."""
    
    STORAGE_FILE = "data/watchlist.json"
    
    def __init__(self, storage: "StorageManager" = None, notifications: "NotificationManager" = None):
        self.storage = storage
        self.notifications = notifications
        self.items: dict[str, "WatchlistItem"] = {}
        self._load()
    
    def _load(self):
        """Load watchlist from file."""
        path = Path(self.STORAGE_FILE)
        if not path.exists():
            return
        
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            for item_data in data.get("items", []):
                item = WatchlistItem(**item_data)
                self.items[item.url_hash] = item
        except Exception as e:
            logger.warning(f"Failed to load watchlist: {e}")
    
    def _save(self):
        """Save watchlist to file."""
        path = Path(self.STORAGE_FILE)
        path.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "items": [
                {
                    "url": item.url,
                    "title": item.title,
                    "target_price_eur": item.target_price_eur,
                    "current_price_eur": item.current_price_eur,
                    "condition": item.condition,
                    "category": item.category,
                    "site_name": item.site_name,
                    "url_hash": item.url_hash,
                    "added_at": item.added_at,
                    "last_checked": item.last_checked,
                    "last_price_eur": item.last_price_eur,
                    "price_history": item.price_history,
                    "alert_enabled": item.alert_enabled,
                    "alert_threshold_pct": item.alert_threshold_pct,
                    "target_price_reached": item.target_price_reached,
                    "last_notified_price": item.last_notified_price,
                }
                for item in self.items.values()
            ]
        }
        
        try:
            with open(self.STORAGE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Failed to save watchlist: {e}")
    
    def add_item(
        self,
        url: str,
        title: str,
        target_price_eur: float,
        condition: str = "any",
        category: str = "any",
        site_name: str = "",
        alert_threshold_pct: float = 5.0,
    ) -> "WatchlistItem":
        """Add item to watchlist."""
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        
        if url_hash in self.items:
            # Update existing
            item = self.items[url_hash]
            item.target_price_eur = target_price_eur
            item.condition = condition
            item.category = category
            item.site_name = url.split("/")[2] if "://" in url else ""
            item.target_price_reached = False
            return item
        
        item = WatchlistItem(
            url=url,
            title=title,
            target_price_eur=target_price_eur,
            condition=condition,
            category=category,
            site_name=url.split("/")[2] if "://" in url else "",
            url_hash=hashlib.md5(url.encode()).hexdigest()[:12],
        )
        self.items[url_hash] = item
        self._save()
        return item
    
    def remove_item(self, url: str) -> bool:
        """Remove item from watchlist."""
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        if url_hash in self.items:
            del self.items[url_hash]
            self._save()
            return True
        return False
    
    def get_item(self, url: str) -> Optional["WatchlistItem"]:
        import hashlib
        url_hash = hashlib.md5(url.encode()).hexdigest()[:12]
        return self.items.get(url_hash)
    
    def get_all(self) -> list:
        return list(self.items.values())
    
    async def check_prices(self, searcher, llm) -> list[dict]:
        """Check all watchlist items for price changes."""
        alerts = []
        
        for item in self.items.values():
            if not item.alert_enabled:
                continue
            
            try:
                # Search for the item
                deals = await self._search_item(item)
                
                if not deals:
                    continue
                
                # Find best match
                best_match = self._find_best_match(item, deals)
                if not best_match:
                    continue
                
                # Update price history
                price_eur = best_match.price_eur
                now = datetime.now().isoformat()
                
                item.price_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "price_eur": best_match.price_eur,
                    "condition": best_match.condition,
                    "site": best_match.site_name,
                })
                
                # Keep only last 100 entries
                if len(item.price_history) > 100:
                    item.price_history = item.price_history[-100:]
                
                previous_price = item.last_price_eur
                item.current_price_eur = best_match.price_eur
                item.last_checked = datetime.now().isoformat()

                # Check for price drop (compare against previous price)
                if previous_price is not None and best_match.price_eur < previous_price:
                    drop_pct = ((previous_price - best_match.price_eur) / previous_price) * 100

                    if drop_pct >= item.alert_threshold_pct and best_match.price_eur <= item.target_price_eur:
                        # Price dropped significantly AND at or below target
                        await self._send_alert(item, best_match, drop_pct)
                        item.target_price_reached = True
                        item.last_notified_price = best_match.price_eur

                # Update last price after comparison
                item.last_price_eur = best_match.price_eur

                # Check if target price reached
                if best_match.price_eur <= item.target_price_eur and not item.target_price_reached:
                    item.target_price_reached = True
                    await self._send_target_reached_alert(item, best_match)
                
                self._save()
                
            except Exception as e:
                logger.error(f"Error checking price for {item.title}: {e}")
        
        return []
    
    async def _search_item(self, item: "WatchlistItem") -> list:
        """Search for item using searcher."""
        # This would use the searcher - implementation depends on searcher interface
        # For now, return empty list
        return []
    
    def _find_best_match(self, item: "WatchlistItem", deals: list) -> Optional[object]:
        """Find best matching deal from search results."""
        # Simple matching by title similarity
        best_match = None
        best_score = 0
        
        for deal in deals:
            # Simple title similarity
            title_words = set(item.title.lower().split())
            deal_words = set(deal.title.lower().split())
            common = len(title_words & deal_words)
            total = len(title_words | deal_words)
            score = common / len(title_words | deal_words) if title_words else 0
            
            if score > 0.5 and score > best_score:
                best_score = score
                best_match = deal
        
        return best_match
    
    async def _send_alert(self, item, deal, drop_pct: float):
        """Send price drop alert."""
        if not self.notifications:
            return
        
        alert = {
            "title": f"💰 Price Drop: {deal.title}",
            "message": f"Price dropped {((self.items[deal.url_hash].last_price_eur - deal.price_eur) / deal.price_eur) * 100:.1f}%!\n"
                       f"Now: {deal.price_eur}€ (was {self.items[deal.url_hash].last_price_eur}€)\n"
                       f"Target: {self.items[deal.url_hash].target_price_eur}€\n"
                       f"Condition: {deal.condition}\n"
                       f"Link: {deal.url}",
            "severity": "info",
            "metadata": {
                "url": deal.url,
                "old_price": self.items[deal.url_hash].last_price_eur,
                "new_price": deal.price_eur,
                "drop_pct": ((self.items[deal.url_hash].last_price_eur - deal.price_eur) / deal.price_eur) * 100,
                "target_price": self.items[deal.url_hash].target_price_eur,
            },
        }
        
        # Would send via notification manager
        logger.info(f"Price alert: {deal.title} dropped {drop_pct:.1f}%")
    
    async def _send_target_reached_alert(self, item, deal):
        """Send alert when target price reached."""
        logger.info(f"Target price reached for {item.title}: {deal.price_eur}€")
    
    def get_items_below_price(self, max_price: float) -> list:
        """Get all items currently below a price threshold."""
        results = []
        for item in self.items.values():
            if item.current_price_eur and item.current_price_eur <= max_price:
                results.append({
                    "title": item.title,
                    "price": item.current_price_eur,
                    "target": item.target_price_eur,
                    "url": item.url,
                })
        return sorted(results, key=lambda x: x["price"])
    
    def get_price_trend(self, url: str, days: int = 30) -> dict:
        """Get price trend for an item."""
        item = self.get_item(url)
        if not item or not item.price_history:
            return {"trend": "insufficient_data"}
        
        cutoff = datetime.now() - timedelta(days=days)
        recent = [p for p in item.price_history if p["timestamp"] >= (datetime.now() - timedelta(days=days)).isoformat()]
        
        if len(recent) < 2:
            return {"trend": "insufficient_data"}
        
        prices = [p["price_eur"] for p in recent]
        first, last = prices[0], prices[-1]
        change = ((last - first) / first) * 100
        
        if change <= -5:
            trend = "dropping"
        elif change >= 5:
            trend = "rising"
        else:
            trend = "stable"
        
        return {
            "trend": "dropping" if change <= -5 else "rising" if change >= 5 else "stable",
            "change_pct": round(change, 2),
            "min_price": min(p["price_eur"] for p in recent),
            "max_price": max(p["price_eur"] for p in recent),
            "avg_price": sum(p["price_eur"] for p in recent) / len(recent),
            "data_points": len(recent),
        }
