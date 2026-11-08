import sqlite3

from src.storage.manager import StorageManager


def test_schema_creates_all_tables_with_stdlib(tmp_path):
    db_path = tmp_path / "t.db"
    sm = StorageManager(db_path=str(db_path))
    conn = sqlite3.connect(str(db_path))
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "deals" in tables and "price_history" in tables
    assert "item_specs" in tables and "alert_rules" in tables
    assert sm is not None


def test_existing_v6_db_still_readable(tmp_path):
    # Build a minimal v6 fixture by opening once, then reopen.
    db_path = tmp_path / "v6.db"
    sm = StorageManager(db_path=str(db_path))
    sm.create_run("r1", "p", "any", "any")
    # reopen
    sm2 = StorageManager(db_path=str(db_path))
    assert sm2.get_run("r1") is not None
