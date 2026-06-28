import sqlite3

from rka_desktop.db.database import DatabaseManager
from rka_desktop.db.migrations import SCHEMA_VERSION


def test_init_schema_sets_schema_version(tmp_path):
    db_file = tmp_path / "schema.db"
    db = DatabaseManager(db_file)
    db.init_schema()

    assert db.get_schema_version() == SCHEMA_VERSION


def test_init_schema_upgrades_existing_database_without_schema_meta(tmp_path):
    db_file = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_file)
    conn.execute("CREATE TABLE experiments (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL)")
    conn.commit()
    conn.close()

    db = DatabaseManager(db_file)
    db.init_schema()

    assert db.get_schema_version() == SCHEMA_VERSION
    # the legacy experiments table gains the new sample-param columns
    check = sqlite3.connect(db_file)
    cols = {row[1] for row in check.execute("PRAGMA table_info(experiments)")}
    check.close()
    assert {"initial_mass_g", "tfe_pct", "feo_pct"} <= cols
