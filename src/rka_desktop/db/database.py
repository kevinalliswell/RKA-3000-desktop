from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from rka_desktop.db.migrations import apply_migrations, get_schema_version
from rka_desktop.models.entities import Measurement


class DatabaseManager:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        ddl = """
        CREATE TABLE IF NOT EXISTS recipes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS recipe_steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL,
            step_no INTEGER NOT NULL,
            target_temp_c REAL NOT NULL,
            ramp_rate_cpm REAL NOT NULL,
            hold_seconds INTEGER NOT NULL,
            n2_lpm REAL NOT NULL,
            h2_lpm REAL NOT NULL,
            co_lpm REAL NOT NULL,
            notes TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(recipe_id) REFERENCES recipes(id)
        );

        CREATE TABLE IF NOT EXISTS experiments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            status TEXT NOT NULL,
            recipe_id INTEGER,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            FOREIGN KEY(recipe_id) REFERENCES recipes(id)
        );

        CREATE TABLE IF NOT EXISTS measurements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER NOT NULL,
            sampled_at TEXT NOT NULL,
            temperature_c REAL NOT NULL,
            weight_g REAL NOT NULL,
            pressure_mpa REAL NOT NULL,
            n2_lpm REAL NOT NULL,
            h2_lpm REAL NOT NULL,
            co_lpm REAL NOT NULL,
            FOREIGN KEY(experiment_id) REFERENCES experiments(id)
        );

        CREATE TABLE IF NOT EXISTS alarms (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER,
            code TEXT NOT NULL,
            level TEXT NOT NULL,
            message TEXT NOT NULL,
            created_at TEXT NOT NULL,
            acknowledged_at TEXT,
            acknowledged_by TEXT,
            FOREIGN KEY(experiment_id) REFERENCES experiments(id)
        );

        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            detail TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_measurements_experiment_sampled
        ON measurements(experiment_id, sampled_at);

        CREATE INDEX IF NOT EXISTS idx_alarms_experiment_created
        ON alarms(experiment_id, created_at);
        """

        with self._lock, self._connect() as conn:
            conn.executescript(ddl)
            self._ensure_column(conn, "experiments", "recipe_id", "INTEGER")
            self._ensure_column(conn, "alarms", "acknowledged_by", "TEXT")
            apply_migrations(conn)
            conn.commit()

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        cols = {row[1] for row in rows}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    def create_experiment(self, name: str, recipe_id: int | None = None) -> int:
        sql = """
        INSERT INTO experiments(name, status, recipe_id, started_at)
        VALUES(?, 'RUNNING', ?, ?)
        """
        now = datetime.now().isoformat()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(sql, (name, recipe_id, now))
            conn.commit()
            return int(cursor.lastrowid)

    def finish_experiment(self, experiment_id: int) -> None:
        sql = """
        UPDATE experiments
        SET status = 'FINISHED', finished_at = ?
        WHERE id = ?
        """
        now = datetime.now().isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(sql, (now, experiment_id))
            conn.commit()

    def set_experiment_status(self, experiment_id: int, status: str) -> None:
        sql = """
        UPDATE experiments
        SET status = ?
        WHERE id = ?
        """
        with self._lock, self._connect() as conn:
            conn.execute(sql, (status, experiment_id))
            conn.commit()

    def get_latest_experiment_id(self) -> int | None:
        sql = "SELECT id FROM experiments ORDER BY id DESC LIMIT 1"
        with self._lock, self._connect() as conn:
            row = conn.execute(sql).fetchone()
            return int(row["id"]) if row else None

    def get_schema_version(self) -> int:
        with self._lock, self._connect() as conn:
            return get_schema_version(conn)

    def insert_measurement(self, m: Measurement) -> None:
        sql = """
        INSERT INTO measurements(
            experiment_id, sampled_at, temperature_c, weight_g, pressure_mpa,
            n2_lpm, h2_lpm, co_lpm
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        """
        with self._lock, self._connect() as conn:
            conn.execute(
                sql,
                (
                    m.experiment_id,
                    m.sampled_at.isoformat(),
                    m.temperature_c,
                    m.weight_g,
                    m.pressure_mpa,
                    m.n2_lpm,
                    m.h2_lpm,
                    m.co_lpm,
                ),
            )
            conn.commit()

    def fetch_measurements(self, experiment_id: int) -> list[dict[str, Any]]:
        sql = """
        SELECT sampled_at, temperature_c, weight_g, pressure_mpa, n2_lpm, h2_lpm, co_lpm
        FROM measurements
        WHERE experiment_id = ?
        ORDER BY sampled_at ASC
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, (experiment_id,)).fetchall()
            return [dict(row) for row in rows]

    def list_experiments(self, limit: int = 100) -> list[dict[str, Any]]:
        sql = """
        SELECT e.id, e.name, e.status, e.recipe_id, e.started_at, e.finished_at, r.name AS recipe_name
        FROM experiments e
        LEFT JOIN recipes r ON r.id = e.recipe_id
        ORDER BY e.id DESC
        LIMIT ?
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
            return [dict(row) for row in rows]

    def get_experiment_detail(self, experiment_id: int) -> dict[str, Any] | None:
        sql = """
        SELECT e.id, e.name, e.status, e.recipe_id, e.started_at, e.finished_at, r.name AS recipe_name
        FROM experiments e
        LEFT JOIN recipes r ON r.id = e.recipe_id
        WHERE e.id = ?
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(sql, (experiment_id,)).fetchone()
            return dict(row) if row else None

    def get_experiment_summary(self, experiment_id: int) -> dict[str, Any] | None:
        sql = """
        SELECT
            experiment_id,
            COUNT(*) AS sample_count,
            MIN(sampled_at) AS first_sampled_at,
            MAX(sampled_at) AS last_sampled_at,
            MIN(temperature_c) AS min_temperature_c,
            MAX(temperature_c) AS max_temperature_c,
            MIN(weight_g) AS min_weight_g,
            MAX(weight_g) AS max_weight_g
        FROM measurements
        WHERE experiment_id = ?
        GROUP BY experiment_id
        """
        with self._lock, self._connect() as conn:
            row = conn.execute(sql, (experiment_id,)).fetchone()
            return dict(row) if row else None

    def create_recipe(self, name: str, steps: list[dict[str, Any]]) -> int:
        now = datetime.now().isoformat()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO recipes(name, created_at, updated_at) VALUES(?, ?, ?)",
                (name, now, now),
            )
            recipe_id = int(cursor.lastrowid)
            self._replace_recipe_steps(conn, recipe_id, steps)
            conn.commit()
            return recipe_id

    def update_recipe(self, recipe_id: int, name: str, steps: list[dict[str, Any]]) -> None:
        now = datetime.now().isoformat()
        with self._lock, self._connect() as conn:
            conn.execute("UPDATE recipes SET name = ?, updated_at = ? WHERE id = ?", (name, now, recipe_id))
            self._replace_recipe_steps(conn, recipe_id, steps)
            conn.commit()

    def _replace_recipe_steps(self, conn: sqlite3.Connection, recipe_id: int, steps: list[dict[str, Any]]) -> None:
        conn.execute("DELETE FROM recipe_steps WHERE recipe_id = ?", (recipe_id,))
        sql = """
        INSERT INTO recipe_steps(
            recipe_id, step_no, target_temp_c, ramp_rate_cpm, hold_seconds,
            n2_lpm, h2_lpm, co_lpm, notes, created_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        now = datetime.now().isoformat()
        for idx, step in enumerate(steps, start=1):
            conn.execute(
                sql,
                (
                    recipe_id,
                    int(step.get("step_no", idx)),
                    float(step["target_temp_c"]),
                    float(step["ramp_rate_cpm"]),
                    int(step["hold_seconds"]),
                    float(step["n2_lpm"]),
                    float(step["h2_lpm"]),
                    float(step["co_lpm"]),
                    str(step.get("notes", "")),
                    now,
                ),
            )

    def list_recipes(self) -> list[dict[str, Any]]:
        sql = "SELECT id, name, updated_at FROM recipes ORDER BY id DESC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql).fetchall()
            return [dict(row) for row in rows]

    def get_recipe(self, recipe_id: int) -> dict[str, Any] | None:
        sql = "SELECT id, name, created_at, updated_at FROM recipes WHERE id = ?"
        with self._lock, self._connect() as conn:
            row = conn.execute(sql, (recipe_id,)).fetchone()
            return dict(row) if row else None

    def get_recipe_steps(self, recipe_id: int) -> list[dict[str, Any]]:
        sql = """
        SELECT step_no, target_temp_c, ramp_rate_cpm, hold_seconds, n2_lpm, h2_lpm, co_lpm, notes
        FROM recipe_steps
        WHERE recipe_id = ?
        ORDER BY step_no ASC
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, (recipe_id,)).fetchall()
            return [dict(row) for row in rows]

    def create_alarm(self, experiment_id: int | None, code: str, level: str, message: str) -> int:
        sql = """
        INSERT INTO alarms(experiment_id, code, level, message, created_at)
        VALUES(?, ?, ?, ?, ?)
        """
        now = datetime.now().isoformat()
        with self._lock, self._connect() as conn:
            cursor = conn.execute(sql, (experiment_id, code, level, message, now))
            conn.commit()
            return int(cursor.lastrowid)

    def acknowledge_latest_alarm(self, experiment_id: int, actor: str = "operator") -> bool:
        sql = """
        SELECT id
        FROM alarms
        WHERE experiment_id = ? AND acknowledged_at IS NULL
        ORDER BY id DESC
        LIMIT 1
        """
        now = datetime.now().isoformat()
        with self._lock, self._connect() as conn:
            row = conn.execute(sql, (experiment_id,)).fetchone()
            if not row:
                return False
            conn.execute(
                "UPDATE alarms SET acknowledged_at = ?, acknowledged_by = ? WHERE id = ?",
                (now, actor, int(row["id"])),
            )
            conn.commit()
            return True

    def list_unacknowledged_alarms(self, experiment_id: int) -> list[dict[str, Any]]:
        sql = """
        SELECT id, code, level, message, created_at
        FROM alarms
        WHERE experiment_id = ? AND acknowledged_at IS NULL
        ORDER BY id DESC
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, (experiment_id,)).fetchall()
            return [dict(row) for row in rows]

    def list_alarm_history(self, experiment_id: int | None = None, limit: int = 100) -> list[dict[str, Any]]:
        sql = """
        SELECT id, experiment_id, code, level, message, created_at, acknowledged_at, acknowledged_by
        FROM alarms
        {where_clause}
        ORDER BY id DESC
        LIMIT ?
        """
        params: tuple[Any, ...]
        if experiment_id is None:
            params = (limit,)
            final_sql = sql.format(where_clause="")
        else:
            params = (experiment_id, limit)
            final_sql = sql.format(where_clause="WHERE experiment_id = ?")

        with self._lock, self._connect() as conn:
            rows = conn.execute(final_sql, params).fetchall()
            return [dict(row) for row in rows]

    def log_action(self, actor: str, action: str, detail: str = "") -> None:
        sql = "INSERT INTO audit_logs(actor, action, detail, created_at) VALUES(?, ?, ?, ?)"
        now = datetime.now().isoformat()
        with self._lock, self._connect() as conn:
            conn.execute(sql, (actor, action, detail, now))
            conn.commit()

    def list_audit_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        sql = """
        SELECT id, actor, action, detail, created_at
        FROM audit_logs
        ORDER BY id DESC
        LIMIT ?
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, (limit,)).fetchall()
            return [dict(row) for row in rows]
