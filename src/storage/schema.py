"""Database schema and migrations using sqlite-utils."""

import sqlite3
from pathlib import Path
from sqlite_utils import Database


SCHEMA_VERSION = 2


def init_db(db_path: str | Path) -> Database:
    """Initialize database, run migrations if needed."""
    db = Database(db_path)
    _run_migrations(db)
    return db


def _run_migrations(db: Database) -> None:
    """Run pending migrations."""
    # Ensure migrations table exists
    if "migrations" not in db.table_names():
        db.execute("""
            CREATE TABLE migrations (
                version INTEGER PRIMARY KEY,
                applied_at TEXT DEFAULT (datetime('now'))
            )
        """)
        db["migrations"].insert({"version": 0})

    current_version = db.execute("SELECT MAX(version) FROM migrations").fetchone()[0] or 0

    if current_version < 1:
        _migration_001_initial(db)
        current_version = 1

    if current_version < 2:
        _migration_002_price_history(db)
        current_version = 2

    # Update version
    db["migrations"].insert({"version": current_version}, pk="version", replace=True)


def _migration_001_initial(db: Database) -> None:
    """Initial schema from v1."""
    # deals table (existing, enhanced)
    if "deals" not in db.table_names():
        db.execute("""
            CREATE TABLE deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                price_eur REAL NOT NULL,
                currency TEXT DEFAULT 'EUR',
                condition TEXT,
                category TEXT,
                site_name TEXT,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                times_seen INTEGER DEFAULT 1,
                availability TEXT,
                seller_name TEXT,
                seller_rating REAL,
                shipping_cost_eur REAL,
                metadata TEXT  -- JSON
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_deals_url ON deals(url)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_deals_last_seen ON deals(last_seen)")

    # runs table for search runs
    if "runs" not in db.table_names():
        db.execute("""
            CREATE TABLE runs (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                condition TEXT,
                category TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                total_deals INTEGER DEFAULT 0,
                new_deals INTEGER DEFAULT 0,
                status TEXT DEFAULT 'running',  -- running, completed, failed
                error_message TEXT
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_runs_started ON runs(started_at)")

    # alerts table for notifications
    if "alerts" not in db.table_names():
        db.execute("""
            CREATE TABLE alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                rule_name TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT DEFAULT 'info',  -- info, warning, critical
                sent INTEGER DEFAULT 0,
                sent_at TEXT,
                created_at TEXT DEFAULT (datetime('now'))
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_alerts_run ON alerts(run_id)")


def _migration_002_price_history(db: Database) -> None:
    """Add price_history table for tracking price changes over time."""
    if "price_history" not in db.table_names():
        db.execute("""
            CREATE TABLE price_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id INTEGER NOT NULL,
                url TEXT NOT NULL,
                price_eur REAL NOT NULL,
                original_price_eur REAL,
                original_currency TEXT DEFAULT 'EUR',
                condition TEXT,
                availability TEXT,
                seller_name TEXT,
                seller_rating REAL,
                shipping_cost_eur REAL,
                run_id TEXT NOT NULL,
                timestamp TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (deal_id) REFERENCES deals(id),
                FOREIGN KEY (run_id) REFERENCES runs(id)
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_price_history_url ON price_history(url)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_price_history_run ON price_history(run_id)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_price_history_timestamp ON price_history(timestamp)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_price_history_deal ON price_history(deal_id)")

    # Add columns to deals if missing (safe to run multiple times)
    cols = {row[1] for row in db.execute("PRAGMA table_info(deals)").fetchall()}
    if "original_currency" not in cols:
        db.execute("ALTER TABLE deals ADD COLUMN original_currency TEXT DEFAULT 'EUR'")
    if "availability" not in cols:
        db.execute("ALTER TABLE deals ADD COLUMN availability TEXT")
    if "seller_name" not in cols:
        db.execute("ALTER TABLE deals ADD COLUMN seller_name TEXT")
    if "seller_rating" not in cols:
        db.execute("ALTER TABLE deals ADD COLUMN seller_rating REAL")
    if "shipping_cost_eur" not in cols:
        db.execute("ALTER TABLE deals ADD COLUMN shipping_cost_eur REAL")
    if "metadata" not in cols:
        db.execute("ALTER TABLE deals ADD COLUMN metadata TEXT")


def get_db(db_path: str | Path = "data/deals.db") -> Database:
    """Get initialized database instance."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    return init_db(db_path)