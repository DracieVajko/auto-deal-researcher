"""SQLite storage manager for deal deduplication and history."""

import sqlite3
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta
from src.searcher.adapters.base import Deal


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


class StorageManager:
    def __init__(self, db_path: str):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS deals (
                    url TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    price_eur REAL NOT NULL,
                    condition TEXT,
                    category TEXT,
                    site_name TEXT,
                    first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL,
                    times_seen INTEGER DEFAULT 1
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_last_seen ON deals(last_seen)")

    def get_deal(self, url: str) -> Optional[StoredDeal]:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT * FROM deals WHERE url=?", (url,)).fetchone()
            return StoredDeal(*row) if row else None

    def save_deal(self, deal: Deal):
        today = datetime.now().date().isoformat()
        existing = self.get_deal(deal.url)
        with sqlite3.connect(self.db_path) as conn:
            if existing:
                conn.execute("""
                    UPDATE deals SET price_eur=?, last_seen=?, times_seen=times_seen+1
                    WHERE url=?
                """, (deal.price_eur, today, deal.url))
            else:
                conn.execute("""
                    INSERT INTO deals (url, title, price_eur, condition, category, site_name, first_seen, last_seen)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (deal.url, deal.title, deal.price_eur, deal.condition, deal.category,
                      deal.site_name, today, today))

    def mark_seen_today(self, urls: list[str]):
        """Call after each run for all URLs found in this run."""
        today = datetime.now().date().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            for url in urls:
                conn.execute("UPDATE deals SET last_seen=? WHERE url=?", (today, url))

    def prune_missing(self, max_age_days: int = 30):
        """Delete deals not seen for max_age_days."""
        cutoff = (datetime.now().date() - timedelta(days=max_age_days)).isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM deals WHERE last_seen < ?", (cutoff,))

    def get_all_deals(self) -> list[StoredDeal]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute("SELECT * FROM deals ORDER BY last_seen DESC").fetchall()
            return [StoredDeal(*r) for r in rows]

    def is_known(self, url: str) -> bool:
        """Check if URL has been seen before."""
        return self.get_deal(url) is not None