# ruff: noqa: S608
"""Database schema and migrations using stdlib sqlite3.

A thin ``Database``/``Table`` shim preserves the sqlite-utils-shaped access
(``db.table(name)``, ``db[name]``, ``db.execute()``, ``db.table_names()``)
that ``manager.py`` relies on, while the underlying connection is a plain
``sqlite3.Connection`` with ``row_factory = sqlite3.Row``.
"""

import sqlite3
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 7

# Columns added after the initial migration, applied idempotently to any
# database created by an older build.
DEALS_COLUMNS: dict[str, str] = {
    "currency": "TEXT DEFAULT 'EUR'",
    "original_currency": "TEXT DEFAULT 'EUR'",
    "availability": "TEXT",
    "seller_name": "TEXT",
    "seller_rating": "REAL",
    "shipping_cost_eur": "REAL",
    "metadata": "TEXT",
    "effective_price_eur": "REAL",
    "price_kind": "TEXT DEFAULT 'unknown'",
}

PRICE_HISTORY_COLUMNS: dict[str, str] = {
    "effective_price_eur": "REAL",
    "price_kind": "TEXT DEFAULT 'unknown'",
}

ITEM_SPECS_COLUMNS: dict[str, str] = {
    "item_name": "TEXT NOT NULL",
    "category": "TEXT DEFAULT 'general'",
    "specs_json": "TEXT NOT NULL DEFAULT '{}'",
    "review_json": "TEXT NOT NULL DEFAULT '{}'",
    "source_urls": "TEXT NOT NULL DEFAULT '[]'",
    "researched_at": "TEXT NOT NULL",
}

ALERT_RULES_COLUMNS: dict[str, str] = {
    "url": "TEXT PRIMARY KEY",
    "title": "TEXT NOT NULL",
    "target_price_eur": "REAL NOT NULL",
    "condition": "TEXT DEFAULT 'any'",
    "channels": "TEXT NOT NULL DEFAULT '[]'",
    "cooldown_minutes": "INTEGER DEFAULT 60",
    "added_at": "TEXT NOT NULL",
    "last_triggered": "TEXT",
    "is_active": "INTEGER DEFAULT 1",
}


class _InsertResult:
    """Mimics sqlite-utils' insert result (only ``last_pk`` is used)."""

    def __init__(self, last_pk: int | None) -> None:
        self.last_pk = last_pk


class Table:
    """Thin Table-like wrapper over a sqlite3 table."""

    def __init__(self, conn: sqlite3.Connection, name: str) -> None:
        self.conn = conn
        self.name = name

    @property
    def pk(self) -> list[str]:
        cols = self.conn.execute(f"PRAGMA table_info({self.name})").fetchall()
        pks = [r for r in cols if r["pk"]]
        pks.sort(key=lambda r: r["pk"])
        return [r["name"] for r in pks]

    def _pk_col(self) -> str:
        pks = self.pk
        return pks[0] if pks else "rowid"

    def insert(
        self,
        record: dict[str, Any],
        pk: str | list[str] | None = None,
        replace: bool = False,
        **_kwargs: Any,
    ) -> _InsertResult:
        columns = list(record.keys())
        placeholders = ",".join("?" for _ in columns)
        col_sql = ",".join(columns)
        values = [record[c] for c in columns]

        conflict_cols: list[str]
        if pk is None:
            conflict_cols = self.pk
        elif isinstance(pk, (list, tuple)):
            conflict_cols = list(pk)
        else:
            conflict_cols = [pk]

        if replace and conflict_cols:
            conflict_sql = ",".join(conflict_cols)
            update_cols = [c for c in columns if c not in conflict_cols]
            if update_cols:
                set_clause = ",".join(f"{c}=excluded.{c}" for c in update_cols)
                sql = (
                    f"INSERT INTO {self.name} ({col_sql}) VALUES ({placeholders}) "
                    f"ON CONFLICT({conflict_sql}) DO UPDATE SET {set_clause}"
                )
            else:
                sql = (
                    f"INSERT INTO {self.name} ({col_sql}) VALUES ({placeholders}) "
                    f"ON CONFLICT({conflict_sql}) DO NOTHING"
                )
        else:
            sql = f"INSERT INTO {self.name} ({col_sql}) VALUES ({placeholders})"

        cur = self.conn.execute(sql, values)
        self.conn.commit()
        last_pk = cur.lastrowid
        if last_pk == 0:
            last_pk = None
        return _InsertResult(last_pk)

    def update(self, pk_value: Any, record: dict[str, Any], **_kwargs: Any) -> None:
        pk_cols = self.pk
        if not pk_cols:
            pk_cols = [self._pk_col()]
        set_clause = ",".join(f"{c}=?" for c in record.keys())
        if len(pk_cols) == 1:
            sql = f"UPDATE {self.name} SET {set_clause} WHERE {pk_cols[0]}=?"
            params = [*list(record.values()), pk_value]
        else:
            # Composite pk not used by this codebase; fall back to first col.
            sql = f"UPDATE {self.name} SET {set_clause} WHERE {pk_cols[0]}=?"
            params = [*list(record.values()), pk_value]
        self.conn.execute(sql, params)
        self.conn.commit()

    def delete(self, pk_value: Any, **_kwargs: Any) -> None:
        pk_cols = self.pk
        if not pk_cols:
            pk_cols = [self._pk_col()]
        sql = f"DELETE FROM {self.name} WHERE {pk_cols[0]}=?"
        self.conn.execute(sql, (pk_value,))
        self.conn.commit()

    def get(self, pk_value: Any) -> sqlite3.Row | None:
        pk_cols = self.pk
        if not pk_cols:
            pk_cols = [self._pk_col()]
        sql = f"SELECT * FROM {self.name} WHERE {pk_cols[0]}=?"
        return self.conn.execute(sql, (pk_value,)).fetchone()

    def rows_where(
        self,
        where: str | None = None,
        where_args: Any = None,
        order_by: str | None = None,
        limit: int | None = None,
        offset: int | None = None,
        select: str = "*",
        **_kwargs: Any,
    ) -> list[sqlite3.Row]:
        sql = f"SELECT {select} FROM {self.name}"
        params: list[Any] = []
        if where:
            sql += f" WHERE {where}"
            if where_args:
                if isinstance(where_args, (list, tuple)):
                    params.extend(where_args)
                else:
                    params.append(where_args)
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit is not None:
            sql += f" LIMIT {int(limit)}"
        if offset is not None:
            sql += f" OFFSET {int(offset)}"
        return self.conn.execute(sql, params).fetchall()


class Database:
    """Stdlib-backed shim with sqlite-utils-shaped access."""

    def __init__(self, db_path: str | Path) -> None:
        self.conn = sqlite3.connect(str(db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.commit()

    def execute(self, sql: str, params: Any = ()) -> sqlite3.Cursor:
        cur = self.conn.execute(sql, params)
        self.conn.commit()
        return cur

    def table(self, name: str) -> Table:
        return Table(self.conn, name)

    def __getitem__(self, name: str) -> Table:
        return Table(self.conn, name)

    def table_names(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        self.conn.close()


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

    if current_version < 3:
        _migration_003_backfill_deals_columns(db)
        current_version = 3

    if current_version < 4:
        _migration_004_price_trust(db)
        current_version = 4

    if current_version < 5:
        _migration_005_item_specs(db)
        current_version = 5

    if current_version < 6:
        _migration_006_alert_rules(db)
        current_version = 6

    if current_version < 7:
        _migration_007_scheduled_jobs(db)
        current_version = 7

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


def _migration_003_backfill_deals_columns(db: Database) -> None:
    """Ensure every deals column the manager writes to actually exists.

    Databases created before `currency` was added carried the other columns
    but not that one, so save_deal() raised
    "table deals has no column named currency" on any pre-existing install.
    """
    _ensure_deals_columns(db)


def _migration_004_price_trust(db: Database) -> None:
    """Add the effective price and price kind to deals and price history."""
    _ensure_deals_columns(db)
    _ensure_table_columns(db, "price_history", PRICE_HISTORY_COLUMNS)


def _migration_005_item_specs(db: Database) -> None:
    """Create the item_specs table for cached specs research."""
    if "item_specs" not in db.table_names():
        db.execute("""
            CREATE TABLE item_specs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_name TEXT NOT NULL UNIQUE,
                category TEXT DEFAULT 'general',
                specs_json TEXT NOT NULL DEFAULT '{}',
                review_json TEXT NOT NULL DEFAULT '{}',
                source_urls TEXT NOT NULL DEFAULT '[]',
                researched_at TEXT NOT NULL
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_item_specs_name ON item_specs(item_name)")


def _migration_006_alert_rules(db: Database) -> None:
    """Create the alert_rules table for user-configurable price alert thresholds."""
    if "alert_rules" not in db.table_names():
        db.execute("""
            CREATE TABLE alert_rules (
                url TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                target_price_eur REAL NOT NULL,
                condition TEXT DEFAULT 'any',
                channels TEXT NOT NULL DEFAULT '[]',
                cooldown_minutes INTEGER DEFAULT 60,
                added_at TEXT NOT NULL,
                last_triggered TEXT,
                is_active INTEGER DEFAULT 1
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_alert_rules_active ON alert_rules(is_active)")


def _migration_007_scheduled_jobs(db: Database) -> None:
    """Create the scheduled_jobs table for the system monitor/scheduler."""
    if "scheduled_jobs" not in db.table_names():
        db.execute("""
            CREATE TABLE scheduled_jobs (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                condition TEXT DEFAULT 'any',
                category TEXT DEFAULT 'any',
                mode TEXT DEFAULT 'once',           -- once | watchdog
                trigger TEXT DEFAULT 'asap',        -- asap | at | every
                trigger_value TEXT,                 -- HH:MM for at; N for every
                every_unit TEXT DEFAULT 'minutes',  -- minutes | hours
                repeats INTEGER,                    -- NULL = infinite
                runs_done INTEGER DEFAULT 0,
                max_runs INTEGER DEFAULT 1,         -- 1 for once; 0 or N for watchdog
                enabled INTEGER DEFAULT 1,
                next_run_at TEXT,
                created_at TEXT,
                last_run_at TEXT,
                last_status TEXT
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_enabled ON scheduled_jobs(enabled)")
        db.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_next_run ON scheduled_jobs(next_run_at)")


def _ensure_table_columns(
    db: Database, table: str, columns: dict[str, str]
) -> list[str]:
    """Add any missing columns to *table*. Returns the names that were added."""
    if table not in db.table_names():
        return []
    existing = {row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    added = []
    for column, ddl in columns.items():
        if column not in existing:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            added.append(column)
    return added


def _ensure_deals_columns(db: Database) -> list[str]:
    """Add any missing deals columns. Returns the names that were added."""
    return _ensure_table_columns(db, "deals", DEALS_COLUMNS)


def get_db(db_path: str | Path = "data/deals.db") -> Database:
    """Get initialized database instance."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    db = init_db(db_path)
    db.conn.row_factory = sqlite3.Row
    db.conn.execute("PRAGMA foreign_keys = ON")
    return db
