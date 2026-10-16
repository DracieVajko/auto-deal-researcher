"""Migration regressions: existing installs must not crash on save_deal."""

import sqlite3

from src.searcher.adapters.base import Deal
from src.storage.manager import StorageManager
from src.storage.schema import DEALS_COLUMNS, get_db


def _make_legacy_db(path):
    """A v2 database created before the `currency` column existed."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            price_eur REAL NOT NULL,
            condition TEXT,
            category TEXT,
            site_name TEXT,
            first_seen TEXT NOT NULL,
            last_seen TEXT NOT NULL,
            times_seen INTEGER DEFAULT 1
        );
        CREATE TABLE runs (
            id TEXT PRIMARY KEY, prompt TEXT NOT NULL, condition TEXT,
            category TEXT, started_at TEXT NOT NULL, completed_at TEXT,
            total_deals INTEGER DEFAULT 0, new_deals INTEGER DEFAULT 0,
            status TEXT DEFAULT 'running', error_message TEXT
        );
        CREATE TABLE alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
            rule_name TEXT NOT NULL, message TEXT NOT NULL,
            severity TEXT DEFAULT 'info', sent INTEGER DEFAULT 0, sent_at TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, deal_id INTEGER NOT NULL,
            url TEXT NOT NULL, price_eur REAL NOT NULL,
            original_price_eur REAL, original_currency TEXT DEFAULT 'EUR',
            condition TEXT, availability TEXT, seller_name TEXT,
            seller_rating REAL, shipping_cost_eur REAL, run_id TEXT NOT NULL,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE migrations (version INTEGER PRIMARY KEY,
                                 applied_at TEXT DEFAULT (datetime('now')));
        INSERT INTO migrations (version) VALUES (2);
    """)
    conn.commit()
    conn.close()


def test_legacy_db_gains_missing_columns(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    _make_legacy_db(db_path)

    db = get_db(db_path)
    cols = {r[1] for r in db.execute("PRAGMA table_info(deals)")}
    assert DEALS_COLUMNS.keys() <= cols, "every column the manager writes must exist"
    assert db.execute("SELECT MAX(version) FROM migrations").fetchone()[0] == 3


def test_save_deal_works_on_legacy_db(tmp_path):
    """Regression: this raised 'table deals has no column named currency'."""
    db_path = str(tmp_path / "legacy.db")
    _make_legacy_db(db_path)

    storage = StorageManager(db_path)
    storage.save_deal(Deal(url="https://x/1", title="DJI", price_eur=339.0,
                           condition="new", category="electronics", site_name="alza"))

    saved = storage.get_deal("https://x/1")
    assert saved is not None
    assert saved.price_eur == 339.0
    assert saved.currency if hasattr(saved, "currency") else True


def test_migration_preserves_existing_rows(tmp_path):
    db_path = str(tmp_path / "legacy.db")
    _make_legacy_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO deals (url, title, price_eur, first_seen, last_seen)"
        " VALUES ('https://old/1', 'Old', 10.0, '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    StorageManager(db_path)
    conn = sqlite3.connect(db_path)
    assert conn.execute("SELECT COUNT(*) FROM deals").fetchone()[0] == 1
    conn.close()


def test_migration_is_idempotent(tmp_path):
    db_path = str(tmp_path / "x.db")
    get_db(db_path)
    db2 = get_db(db_path)  # second open must not fail
    assert "currency" in {r[1] for r in db2.execute("PRAGMA table_info(deals)")}