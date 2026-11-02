import sqlite3

from rka_desktop.infrastructure.sqlite.database import DatabaseManager
from rka_desktop.infrastructure.sqlite.migrations import SCHEMA_VERSION


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


def test_upgrade_to_v3_archives_finished_experiments_backs_up_and_recovers_orphans(tmp_path):
    db_file = tmp_path / "v2.db"
    conn = sqlite3.connect(db_file)
    conn.executescript("""
        CREATE TABLE experiments (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, status TEXT NOT NULL,
                                  recipe_id INTEGER, started_at TEXT NOT NULL, finished_at TEXT);
        CREATE TABLE recipes (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, created_at TEXT NOT NULL,
                              updated_at TEXT NOT NULL);
        CREATE TABLE recipe_steps (id INTEGER PRIMARY KEY AUTOINCREMENT, recipe_id INTEGER NOT NULL, step_no INTEGER NOT NULL,
            target_temp_c REAL NOT NULL, ramp_rate_cpm REAL NOT NULL, hold_seconds INTEGER NOT NULL, n2_lpm REAL NOT NULL,
            h2_lpm REAL NOT NULL, co_lpm REAL NOT NULL, notes TEXT, created_at TEXT NOT NULL);
        CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_meta VALUES('schema_version', '2');
        INSERT INTO recipes(name, created_at, updated_at) VALUES('旧配方', '2026-01-01', '2026-01-01');
        INSERT INTO recipe_steps(recipe_id, step_no, target_temp_c, ramp_rate_cpm, hold_seconds, n2_lpm, h2_lpm, co_lpm, notes, created_at)
            VALUES(1, 1, 900, 10, 600, 3, 1, 0.8, '', '2026-01-01');
        INSERT INTO experiments(name, status, recipe_id, started_at, finished_at) VALUES('done', 'COMPLETED', 1, '2026-01-02T09:00:00', '2026-01-02T11:00:00');
        INSERT INTO experiments(name, status, recipe_id, started_at) VALUES('crashed', 'RUNNING', 1, '2026-01-03T09:00:00');
    """)
    conn.commit()
    conn.close()

    db = DatabaseManager(db_file)
    db.init_schema(backup_dir=tmp_path / "backups")
    assert db.get_schema_version() == SCHEMA_VERSION
    assert db.last_backup is not None and db.last_backup.is_file()
    done = db.get_experiment_detail(1)
    assert done["review_state"] == "archived" and done["category"] == "archived" and done["code"] == "RKA-2026-0102-001"
    assert db.get_experiment_detail(2)["review_state"] is None  # still marked running until the server recovers it
    assert db.recover_orphaned_experiments() == [2]
    crashed = db.get_experiment_detail(2)
    assert crashed["status"] == "FAULTED" and crashed["review_state"] == "pending" and crashed["end_reason"] == "recovered"
    recipe = db.get_recipe(1)
    assert recipe["experiment_type"] == "reduction" and recipe["inert_gas"] == "N2" and recipe["version"] == 1
    assert db.list_recipe_versions(1)[0]["snapshot"]["steps"][0]["co_lpm"] == 0.8
    assert db.get_recipe_steps(1)[0]["co2_lpm"] == 0.0

    db.init_schema(backup_dir=tmp_path / "backups")  # idempotent, no second backup
    assert len(list((tmp_path / "backups").iterdir())) == 1
