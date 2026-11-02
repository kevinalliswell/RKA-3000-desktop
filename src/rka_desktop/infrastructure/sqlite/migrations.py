from __future__ import annotations

import sqlite3

# 1-2: pre-0.9 schemas (sample params, schema_meta).
# 3: experiment lifecycle (review/archive, snapshots), multi-gas columns, recipe versions,
#    gas usage limit policies, report records, structured audit fields.
SCHEMA_VERSION = 3


def ensure_meta(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute("INSERT OR IGNORE INTO schema_meta(key, value) VALUES('schema_version', '0')")


def apply_migrations(conn: sqlite3.Connection) -> None:
    ensure_meta(conn)
    conn.execute("UPDATE schema_meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION),))


def get_schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute("SELECT value FROM schema_meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.OperationalError:
        return 0
    if row is None:
        return 0
    return int(row[0])
