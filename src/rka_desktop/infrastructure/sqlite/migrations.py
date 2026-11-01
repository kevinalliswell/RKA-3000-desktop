from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 2


def apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO schema_meta(key, value)
        VALUES('schema_version', '0')
        """
    )
    conn.execute(
        """
        UPDATE schema_meta
        SET value = ?
        WHERE key = 'schema_version'
        """,
        (str(SCHEMA_VERSION),),
    )


def get_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        """
        SELECT value
        FROM schema_meta
        WHERE key = 'schema_version'
        """
    ).fetchone()
    if row is None:
        return 0
    return int(row[0])

