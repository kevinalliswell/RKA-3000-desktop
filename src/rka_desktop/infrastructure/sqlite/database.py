from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from rka_desktop.domain.entities import Measurement
from rka_desktop.domain.gases import GAS_COLUMNS
from rka_desktop.infrastructure.sqlite.migrations import SCHEMA_VERSION, apply_migrations, get_schema_version

# Columns that the application may set on an experiment row (anything else is rejected).
EXPERIMENT_FIELDS = {
    "name": "TEXT", "status": "TEXT", "recipe_id": "INTEGER", "finished_at": "TEXT",
    "initial_mass_g": "REAL", "tfe_pct": "REAL", "feo_pct": "REAL",
    "experiment_type": "TEXT", "inert_gas": "TEXT", "sample_name": "TEXT", "operator": "TEXT", "particle_size": "TEXT",
    "balance_mass_g": "REAL", "recipe_version": "INTEGER", "recipe_snapshot": "TEXT", "limits_version": "INTEGER",
    "limits_snapshot": "TEXT", "checklist": "TEXT", "gas_mode": "TEXT", "temperature_mode": "TEXT",
    "review_state": "TEXT", "end_reason": "TEXT", "end_detail": "TEXT", "reaction_started_at": "TEXT",
    "reaction_ended_at": "TEXT", "purge_required_s": "REAL", "purge_done_s": "REAL", "final_temperature_c": "REAL",
    "final_mass_g": "REAL", "archived_at": "TEXT", "archive_note": "TEXT", "archived_by": "TEXT", "kpi": "TEXT",
}
JSON_EXPERIMENT_FIELDS = {"recipe_snapshot", "limits_snapshot", "checklist", "kpi"}
RECIPE_META_COLUMNS = {
    "experiment_type": "TEXT NOT NULL DEFAULT 'reduction'", "inert_gas": "TEXT NOT NULL DEFAULT 'N2'",
    "purge_lpm": "REAL NOT NULL DEFAULT 0", "purge_seconds": "INTEGER NOT NULL DEFAULT 600",
    "version": "INTEGER NOT NULL DEFAULT 1", "description": "TEXT NOT NULL DEFAULT ''",
}
EXTRA_GAS_COLUMNS = ("ar_lpm", "co2_lpm", "ch4_lpm", "o2_lpm")
MEASUREMENT_COLUMNS = ("sampled_at", "temperature_c", "weight_g", "pressure_mpa", *GAS_COLUMNS, "phase")
STEP_COLUMNS = ("step_no", "name", "target_temp_c", "ramp_rate_cpm", "hold_seconds", *GAS_COLUMNS, "notes")
ACTIVE_DB_STATUSES = ("RUNNING", "PAUSED", "INTERRUPTED", "PURGING")

# History categories derived from status + review state.
CATEGORY_SQL = {
    "running": "e.status IN ('RUNNING','PAUSED','INTERRUPTED','PURGING')",
    "pending": "e.review_state = 'pending'",
    "archived": "e.review_state = 'archived' AND e.status NOT IN ('STOPPED','FAULTED')",
    "aborted": "e.review_state = 'archived' AND e.status IN ('STOPPED','FAULTED')",
}


def _now() -> str:
    return datetime.now().isoformat()


def experiment_code(row: dict[str, Any]) -> str:
    """Display number RKA-YYYY-MMDD-NNN derived from the start date and the row id."""
    try:
        started = datetime.fromisoformat(str(row.get("started_at")))
        return f"RKA-{started:%Y-%m%d}-{int(row['id']):03d}"
    except (TypeError, ValueError, KeyError):
        return f"RKA-{int(row.get('id') or 0):03d}"


def experiment_category(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "")
    if status in ACTIVE_DB_STATUSES:
        return "running"
    if row.get("review_state") == "pending":
        return "pending"
    return "aborted" if status in ("STOPPED", "FAULTED") else "archived"


class DatabaseManager:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._lock = Lock()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.last_backup: Path | None = None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------ schema
    def init_schema(self, *, backup_dir: Path | None = None) -> None:
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

        CREATE TABLE IF NOT EXISTS recipe_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            recipe_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            snapshot TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT '',
            actor TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
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

        CREATE TABLE IF NOT EXISTS gas_limit_policies (
            version INTEGER PRIMARY KEY,
            limits TEXT NOT NULL,
            reason TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            experiment_id INTEGER NOT NULL,
            version INTEGER NOT NULL,
            path TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_measurements_experiment_sampled
        ON measurements(experiment_id, sampled_at);

        CREATE INDEX IF NOT EXISTS idx_alarms_experiment_created
        ON alarms(experiment_id, created_at);
        """

        with self._lock, self._connect() as conn:
            previous = get_schema_version(conn)
            has_data = self._has_table(conn, "experiments") and bool(
                conn.execute("SELECT COUNT(*) FROM experiments").fetchone()[0])
            if previous < SCHEMA_VERSION and has_data and backup_dir is not None:
                self.last_backup = self._backup(conn, backup_dir, previous)
            conn.executescript(ddl)
            self._ensure_column(conn, "experiments", "recipe_id", "INTEGER")
            for column, col_type in EXPERIMENT_FIELDS.items():
                self._ensure_column(conn, "experiments", column, col_type)
            self._ensure_column(conn, "alarms", "acknowledged_by", "TEXT")
            self._ensure_column(conn, "alarms", "ack_note", "TEXT")
            for column, col_type in RECIPE_META_COLUMNS.items():
                self._ensure_column(conn, "recipes", column, col_type)
            self._ensure_column(conn, "recipe_steps", "name", "TEXT NOT NULL DEFAULT ''")
            for column in EXTRA_GAS_COLUMNS:
                self._ensure_column(conn, "recipe_steps", column, "REAL NOT NULL DEFAULT 0")
                self._ensure_column(conn, "measurements", column, "REAL NOT NULL DEFAULT 0")
            self._ensure_column(conn, "measurements", "phase", "TEXT NOT NULL DEFAULT 'run'")
            for column in ("experiment_id INTEGER", "category TEXT", "reason TEXT", "result TEXT"):
                name, col_type = column.split(" ", 1)
                self._ensure_column(conn, "audit_logs", name, col_type)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_experiment ON audit_logs(experiment_id, id)")
            if previous < 3:
                self._migrate_to_v3(conn)
            apply_migrations(conn)
            conn.commit()

    @staticmethod
    def _has_table(conn: sqlite3.Connection, name: str) -> bool:
        return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None

    def _backup(self, conn: sqlite3.Connection, backup_dir: Path, previous: int) -> Path:
        backup_dir.mkdir(parents=True, exist_ok=True)
        target = backup_dir / f"{self.db_path.stem}-schema{previous}-{datetime.now():%Y%m%d-%H%M%S}.db"
        with sqlite3.connect(target) as dest:
            conn.backup(dest)
        return target

    def _migrate_to_v3(self, conn: sqlite3.Connection) -> None:
        # Experiments that finished before the review/archive lifecycle existed are archived
        # as-is so that the new "previous experiment must be archived" rule does not block.
        conn.execute(
            """
            UPDATE experiments
            SET review_state = 'archived', archived_at = COALESCE(finished_at, started_at),
                archive_note = '0.9 之前的实验，升级数据库时自动归档', archived_by = 'system'
            WHERE review_state IS NULL AND status NOT IN ('RUNNING','PAUSED','INTERRUPTED','PURGING')
            """
        )
        # Every existing recipe gets a version-1 snapshot of its current content.
        for row in conn.execute("SELECT id FROM recipes").fetchall():
            recipe_id = int(row["id"])
            exists = conn.execute("SELECT 1 FROM recipe_versions WHERE recipe_id = ?", (recipe_id,)).fetchone()
            if not exists:
                snapshot = self._recipe_snapshot(conn, recipe_id)
                if snapshot:
                    conn.execute(
                        "INSERT INTO recipe_versions(recipe_id, version, snapshot, reason, actor, created_at) VALUES(?,?,?,?,?,?)",
                        (recipe_id, int(snapshot.get("version") or 1), json.dumps(snapshot, ensure_ascii=False),
                         "升级数据库时记录的初始版本", "system", _now()),
                    )

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, col_type: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        cols = {row[1] for row in rows}
        if column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")

    def get_schema_version(self) -> int:
        with self._lock, self._connect() as conn:
            return get_schema_version(conn)

    def recover_orphaned_experiments(self) -> list[int]:
        """Experiments still marked active at backend start cannot be running: end them for review."""
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM experiments WHERE status IN ({','.join('?' * len(ACTIVE_DB_STATUSES))})", ACTIVE_DB_STATUSES
            ).fetchall()
            ids = [int(row["id"]) for row in rows]
            for experiment_id in ids:
                conn.execute(
                    """UPDATE experiments SET status = 'FAULTED', finished_at = COALESCE(finished_at, ?),
                       review_state = 'pending', end_reason = 'recovered',
                       end_detail = '上次运行时程序异常退出，重启后标记为中止' WHERE id = ?""",
                    (_now(), experiment_id),
                )
            conn.commit()
            return ids

    # ------------------------------------------------------------------ experiments
    @staticmethod
    def _encode_fields(fields: dict[str, Any]) -> dict[str, Any]:
        unknown = set(fields) - set(EXPERIMENT_FIELDS)
        if unknown:
            raise ValueError(f"unknown experiment fields: {sorted(unknown)}")
        return {key: (json.dumps(value, ensure_ascii=False) if key in JSON_EXPERIMENT_FIELDS and value is not None else value)
                for key, value in fields.items()}

    def create_experiment(self, name: str, recipe_id: int | None = None, fields: dict[str, Any] | None = None) -> int:
        values = self._encode_fields(dict(fields or {}))
        columns = ["name", "status", "recipe_id", "started_at", *values]
        params = [name, "RUNNING", recipe_id, _now(), *values.values()]
        sql = f"INSERT INTO experiments({', '.join(columns)}) VALUES({', '.join('?' * len(columns))})"
        with self._lock, self._connect() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return int(cursor.lastrowid)

    def update_experiment(self, experiment_id: int, fields: dict[str, Any]) -> None:
        if not fields:
            return
        values = self._encode_fields(fields)
        assignments = ", ".join(f"{key} = ?" for key in values)
        with self._lock, self._connect() as conn:
            conn.execute(f"UPDATE experiments SET {assignments} WHERE id = ?", (*values.values(), experiment_id))
            conn.commit()

    def finish_experiment(self, experiment_id: int, status: str = "FINISHED") -> None:
        self.update_experiment(experiment_id, {"status": status, "finished_at": _now()})

    def set_experiment_status(self, experiment_id: int, status: str) -> None:
        self.update_experiment(experiment_id, {"status": status})

    def set_experiment_sample_params(self, experiment_id: int, initial_mass_g: float, tfe_pct: float, feo_pct: float) -> None:
        self.update_experiment(experiment_id, {"initial_mass_g": initial_mass_g, "tfe_pct": tfe_pct, "feo_pct": feo_pct})

    def get_latest_experiment_id(self) -> int | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT id FROM experiments ORDER BY id DESC LIMIT 1").fetchone()
            return int(row["id"]) if row else None

    def rename_experiment(self, experiment_id: int, name: str) -> None:
        self.update_experiment(experiment_id, {"name": name})

    def delete_experiment(self, experiment_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM measurements WHERE experiment_id = ?", (experiment_id,))
            conn.execute("DELETE FROM alarms WHERE experiment_id = ?", (experiment_id,))
            conn.execute("DELETE FROM reports WHERE experiment_id = ?", (experiment_id,))
            conn.execute("DELETE FROM experiments WHERE id = ?", (experiment_id,))
            conn.commit()

    @staticmethod
    def _decode_experiment(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        for key in JSON_EXPERIMENT_FIELDS:
            if key in data and isinstance(data[key], str):
                try:
                    data[key] = json.loads(data[key])
                except json.JSONDecodeError:
                    data[key] = None
        data["code"] = experiment_code(data)
        data["category"] = experiment_category(data)
        return data

    _LIST_COLUMNS = (
        "e.id, e.name, e.status, e.recipe_id, e.started_at, e.finished_at, e.experiment_type, e.inert_gas, "
        "e.sample_name, e.operator, e.recipe_version, e.review_state, e.end_reason, e.archived_at, e.kpi, "
        "e.initial_mass_g, e.final_mass_g, r.name AS recipe_name"
    )

    def list_experiments(self, limit: int = 100, *, category: str | None = None, query: str | None = None,
                         recipe_id: int | None = None) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if category:
            if category not in CATEGORY_SQL:
                raise ValueError(f"未知的实验分类: {category}")
            where.append(CATEGORY_SQL[category])
        if query:
            where.append("(e.name LIKE ? OR e.sample_name LIKE ? OR r.name LIKE ? OR CAST(e.id AS TEXT) = ?)")
            like = f"%{query}%"
            params += [like, like, like, query.lstrip("0") or query]
        if recipe_id is not None:
            where.append("e.recipe_id = ?")
            params.append(recipe_id)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""
        SELECT {self._LIST_COLUMNS}
        FROM experiments e LEFT JOIN recipes r ON r.id = e.recipe_id
        {clause}
        ORDER BY e.id DESC LIMIT ?
        """
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql, (*params, limit)).fetchall()
            return [self._decode_experiment(row) for row in rows]  # type: ignore[misc]

    def count_experiments_by_category(self) -> dict[str, int]:
        counts = {}
        with self._lock, self._connect() as conn:
            for key, condition in CATEGORY_SQL.items():
                counts[key] = int(conn.execute(f"SELECT COUNT(*) FROM experiments e WHERE {condition}").fetchone()[0])
        return counts

    def get_experiment_detail(self, experiment_id: int) -> dict[str, Any] | None:
        sql = """
        SELECT e.*, r.name AS recipe_name
        FROM experiments e
        LEFT JOIN recipes r ON r.id = e.recipe_id
        WHERE e.id = ?
        """
        with self._lock, self._connect() as conn:
            return self._decode_experiment(conn.execute(sql, (experiment_id,)).fetchone())

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

    # ------------------------------------------------------------------ measurements
    def insert_measurement(self, m: Measurement) -> None:
        self.insert_measurements([m])

    def insert_measurements(self, measurements: list[Measurement]) -> int:
        if not measurements:
            return 0
        columns = ("experiment_id", *MEASUREMENT_COLUMNS)
        sql = f"INSERT INTO measurements({', '.join(columns)}) VALUES({', '.join('?' * len(columns))})"
        with self._lock, self._connect() as conn:
            conn.executemany(sql, [self._measurement_params(measurement) for measurement in measurements])
            conn.commit()
            return len(measurements)

    @staticmethod
    def _measurement_params(m: Measurement) -> tuple[object, ...]:
        return (m.experiment_id, m.sampled_at.isoformat(), m.temperature_c, m.weight_g, m.pressure_mpa,
                *(float(getattr(m, column)) for column in GAS_COLUMNS), m.phase)

    def fetch_measurements(self, experiment_id: int) -> list[dict[str, Any]]:
        sql = f"SELECT {', '.join(MEASUREMENT_COLUMNS)} FROM measurements WHERE experiment_id = ? ORDER BY sampled_at ASC, id ASC"
        with self._lock, self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, (experiment_id,)).fetchall()]

    def fetch_measurement_timestamps(self, experiment_id: int) -> list[str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT sampled_at FROM measurements WHERE experiment_id = ? ORDER BY id ASC", (experiment_id,))
            return [str(row[0]) for row in rows.fetchall()]

    def fetch_measurements_page(self, experiment_id: int, *, limit: int, offset: int) -> list[dict[str, Any]]:
        sql = f"""
        SELECT id, {', '.join(MEASUREMENT_COLUMNS)}
        FROM measurements
        WHERE experiment_id = ?
        ORDER BY sampled_at ASC, id ASC
        LIMIT ? OFFSET ?
        """
        with self._lock, self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, (experiment_id, limit, offset)).fetchall()]

    def count_measurements(self, experiment_id: int) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM measurements WHERE experiment_id = ?", (experiment_id,)).fetchone()
            return int(row[0]) if row else 0

    # ------------------------------------------------------------------ recipes
    def _recipe_snapshot(self, conn: sqlite3.Connection, recipe_id: int) -> dict[str, Any] | None:
        row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        if row is None:
            return None
        steps = conn.execute(
            f"SELECT {', '.join(STEP_COLUMNS)} FROM recipe_steps WHERE recipe_id = ? ORDER BY step_no ASC", (recipe_id,)
        ).fetchall()
        data = dict(row)
        data["steps"] = [dict(step) for step in steps]
        return data

    def _write_recipe(self, conn: sqlite3.Connection, recipe_id: int, meta: dict[str, Any], steps: list[dict[str, Any]]) -> None:
        conn.execute("DELETE FROM recipe_steps WHERE recipe_id = ?", (recipe_id,))
        columns = ("recipe_id", *STEP_COLUMNS, "created_at")
        sql = f"INSERT INTO recipe_steps({', '.join(columns)}) VALUES({', '.join('?' * len(columns))})"
        now = _now()
        for idx, step in enumerate(steps, start=1):
            conn.execute(sql, (
                recipe_id, int(step.get("step_no", idx)), str(step.get("name") or ""), float(step["target_temp_c"]),
                float(step["ramp_rate_cpm"]), int(step["hold_seconds"]),
                *(float(step.get(column) or 0.0) for column in GAS_COLUMNS), str(step.get("notes") or ""), now,
            ))

    def _record_version(self, conn: sqlite3.Connection, recipe_id: int, version: int, reason: str, actor: str) -> None:
        snapshot = self._recipe_snapshot(conn, recipe_id)
        conn.execute(
            "INSERT INTO recipe_versions(recipe_id, version, snapshot, reason, actor, created_at) VALUES(?,?,?,?,?,?)",
            (recipe_id, version, json.dumps(snapshot, ensure_ascii=False), reason, actor, _now()),
        )

    @staticmethod
    def _recipe_meta(meta: dict[str, Any] | None) -> dict[str, Any]:
        meta = dict(meta or {})
        return {
            "experiment_type": str(meta.get("experiment_type") or "reduction"),
            "inert_gas": str(meta.get("inert_gas") or "N2"),
            "purge_lpm": float(meta.get("purge_lpm") or 0.0),
            "purge_seconds": int(meta.get("purge_seconds") if meta.get("purge_seconds") is not None else 600),
            "description": str(meta.get("description") or ""),
        }

    def create_recipe(self, name: str, steps: list[dict[str, Any]], meta: dict[str, Any] | None = None, *,
                      reason: str = "", actor: str = "") -> int:
        now = _now()
        values = self._recipe_meta(meta)
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                f"INSERT INTO recipes(name, created_at, updated_at, version, {', '.join(values)}) "
                f"VALUES(?, ?, ?, 1, {', '.join('?' * len(values))})",
                (name, now, now, *values.values()),
            )
            recipe_id = int(cursor.lastrowid)
            self._write_recipe(conn, recipe_id, values, steps)
            self._record_version(conn, recipe_id, 1, reason or "新建配方", actor)
            conn.commit()
            return recipe_id

    def update_recipe(self, recipe_id: int, name: str, steps: list[dict[str, Any]], meta: dict[str, Any] | None = None, *,
                      reason: str = "", actor: str = "") -> int:
        """Replace the recipe content and record it as a new version; returns the new version."""
        values = self._recipe_meta(meta)
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT version FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
            version = int(row["version"] or 1) + 1 if row else 1
            assignments = ", ".join(f"{key} = ?" for key in values)
            conn.execute(f"UPDATE recipes SET name = ?, updated_at = ?, version = ?, {assignments} WHERE id = ?",
                         (name, _now(), version, *values.values(), recipe_id))
            self._write_recipe(conn, recipe_id, values, steps)
            self._record_version(conn, recipe_id, version, reason, actor)
            conn.commit()
            return version

    def delete_recipe(self, recipe_id: int) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM recipe_steps WHERE recipe_id = ?", (recipe_id,))
            conn.execute("DELETE FROM recipe_versions WHERE recipe_id = ?", (recipe_id,))
            conn.execute("DELETE FROM recipes WHERE id = ?", (recipe_id,))
            conn.commit()

    def count_experiments_for_recipe(self, recipe_id: int) -> int:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) FROM experiments WHERE recipe_id = ?", (recipe_id,)).fetchone()
            return int(row[0]) if row else 0

    def list_recipes(self) -> list[dict[str, Any]]:
        sql = """SELECT id, name, created_at, updated_at, experiment_type, inert_gas, purge_lpm, purge_seconds, version,
                 description FROM recipes ORDER BY id DESC"""
        with self._lock, self._connect() as conn:
            return [dict(row) for row in conn.execute(sql).fetchall()]

    def get_recipe(self, recipe_id: int) -> dict[str, Any] | None:
        sql = """SELECT id, name, created_at, updated_at, experiment_type, inert_gas, purge_lpm, purge_seconds, version,
                 description FROM recipes WHERE id = ?"""
        with self._lock, self._connect() as conn:
            row = conn.execute(sql, (recipe_id,)).fetchone()
            return dict(row) if row else None

    def get_recipe_steps(self, recipe_id: int) -> list[dict[str, Any]]:
        sql = f"SELECT {', '.join(STEP_COLUMNS)} FROM recipe_steps WHERE recipe_id = ? ORDER BY step_no ASC"
        with self._lock, self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, (recipe_id,)).fetchall()]

    def list_recipe_versions(self, recipe_id: int) -> list[dict[str, Any]]:
        sql = "SELECT version, reason, actor, created_at, snapshot FROM recipe_versions WHERE recipe_id = ? ORDER BY version DESC"
        with self._lock, self._connect() as conn:
            rows = []
            for row in conn.execute(sql, (recipe_id,)).fetchall():
                data = dict(row)
                data["snapshot"] = json.loads(data["snapshot"]) if data.get("snapshot") else None
                rows.append(data)
            return rows

    # ------------------------------------------------------------------ alarms
    def create_alarm(self, experiment_id: int | None, code: str, level: str, message: str) -> int:
        sql = "INSERT INTO alarms(experiment_id, code, level, message, created_at) VALUES(?, ?, ?, ?, ?)"
        with self._lock, self._connect() as conn:
            cursor = conn.execute(sql, (experiment_id, code, level, message, _now()))
            conn.commit()
            return int(cursor.lastrowid)

    def acknowledge_alarm(self, alarm_id: int, actor: str, note: str) -> bool:
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                "UPDATE alarms SET acknowledged_at = ?, acknowledged_by = ?, ack_note = ? WHERE id = ? AND acknowledged_at IS NULL",
                (_now(), actor, note, alarm_id),
            )
            conn.commit()
            return bool(cursor.rowcount)

    def get_alarm(self, alarm_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM alarms WHERE id = ?", (alarm_id,)).fetchone()
            return dict(row) if row else None

    def acknowledge_latest_alarm(self, experiment_id: int, actor: str = "operator", note: str = "") -> bool:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT id FROM alarms WHERE experiment_id = ? AND acknowledged_at IS NULL ORDER BY id DESC LIMIT 1", (experiment_id,)
            ).fetchone()
        if not row:
            return False
        return self.acknowledge_alarm(int(row["id"]), actor, note)

    def list_unacknowledged_alarms(self, experiment_id: int | None = None) -> list[dict[str, Any]]:
        where = "acknowledged_at IS NULL" + (" AND experiment_id = ?" if experiment_id is not None else "")
        params: tuple[Any, ...] = (experiment_id,) if experiment_id is not None else ()
        sql = f"SELECT id, experiment_id, code, level, message, created_at FROM alarms WHERE {where} ORDER BY id DESC"
        with self._lock, self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def count_alarms(self, experiment_id: int) -> int:
        with self._lock, self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM alarms WHERE experiment_id = ?", (experiment_id,)).fetchone()[0])

    def list_alarm_history(self, experiment_id: int | None = None, limit: int = 100, *, acknowledged: bool | None = None) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if experiment_id is not None:
            where.append("experiment_id = ?")
            params.append(experiment_id)
        if acknowledged is True:
            where.append("acknowledged_at IS NOT NULL")
        elif acknowledged is False:
            where.append("acknowledged_at IS NULL")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""SELECT id, experiment_id, code, level, message, created_at, acknowledged_at, acknowledged_by, ack_note
                  FROM alarms {clause} ORDER BY id DESC LIMIT ?"""
        with self._lock, self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, (*params, limit)).fetchall()]

    # ------------------------------------------------------------------ audit
    def log_action(self, actor: str, action: str, detail: str = "", *, experiment_id: int | None = None,
                   category: str | None = None, reason: str | None = None, result: str | None = None) -> None:
        sql = """INSERT INTO audit_logs(actor, action, detail, created_at, experiment_id, category, reason, result)
                 VALUES(?, ?, ?, ?, ?, ?, ?, ?)"""
        with self._lock, self._connect() as conn:
            conn.execute(sql, (actor, action, detail, _now(), experiment_id, category, reason, result))
            conn.commit()

    def prune_audit_logs(self, keep: int) -> int:
        """Keep the newest ``keep`` rows that belong to no experiment; experiment records are never pruned."""
        with self._lock, self._connect() as conn:
            cursor = conn.execute(
                """DELETE FROM audit_logs WHERE experiment_id IS NULL AND id NOT IN (
                       SELECT id FROM audit_logs WHERE experiment_id IS NULL ORDER BY id DESC LIMIT ?)""",
                (max(0, keep),),
            )
            conn.commit()
            return int(cursor.rowcount or 0)

    def list_audit_logs(self, limit: int = 100, *, experiment_id: int | None = None, category: str | None = None,
                        actor: str | None = None) -> list[dict[str, Any]]:
        where: list[str] = []
        params: list[Any] = []
        if experiment_id is not None:
            where.append("experiment_id = ?")
            params.append(experiment_id)
        if category:
            where.append("category = ?")
            params.append(category)
        if actor:
            where.append("actor LIKE ?")
            params.append(f"%{actor}%")
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        sql = f"""SELECT id, actor, action, detail, created_at, experiment_id, category, reason, result
                  FROM audit_logs {clause} ORDER BY id DESC LIMIT ?"""
        with self._lock, self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, (*params, limit)).fetchall()]

    def count_audit(self, experiment_id: int, action: str | None = None) -> int:
        sql = "SELECT COUNT(*) FROM audit_logs WHERE experiment_id = ?" + (" AND action = ?" if action else "")
        params: tuple[Any, ...] = (experiment_id, action) if action else (experiment_id,)
        with self._lock, self._connect() as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    # ------------------------------------------------------------------ gas limit policies
    def latest_limit_policy(self) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM gas_limit_policies ORDER BY version DESC LIMIT 1").fetchone()
        if row is None:
            return None
        data = dict(row)
        data["limits"] = json.loads(data["limits"])
        return data

    def save_limit_policy(self, limits: dict[str, float], reason: str, actor: str, *, version: int | None = None) -> int:
        with self._lock, self._connect() as conn:
            current = conn.execute("SELECT MAX(version) FROM gas_limit_policies").fetchone()[0]
            new_version = version if version is not None else int(current or 0) + 1
            conn.execute("INSERT INTO gas_limit_policies(version, limits, reason, actor, created_at) VALUES(?,?,?,?,?)",
                         (new_version, json.dumps(limits), reason, actor, _now()))
            conn.commit()
            return new_version

    def list_limit_policies(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM gas_limit_policies ORDER BY version DESC LIMIT ?", (limit,)).fetchall()
        result = []
        for row in rows:
            data = dict(row)
            data["limits"] = json.loads(data["limits"])
            result.append(data)
        return result

    # ------------------------------------------------------------------ reports
    def add_report(self, experiment_id: int, path: str, actor: str) -> int:
        with self._lock, self._connect() as conn:
            current = conn.execute("SELECT MAX(version) FROM reports WHERE experiment_id = ?", (experiment_id,)).fetchone()[0]
            version = int(current or 0) + 1
            conn.execute("INSERT INTO reports(experiment_id, version, path, actor, created_at) VALUES(?,?,?,?,?)",
                         (experiment_id, version, path, actor, _now()))
            conn.commit()
            return version

    def next_report_version(self, experiment_id: int) -> int:
        with self._lock, self._connect() as conn:
            current = conn.execute("SELECT MAX(version) FROM reports WHERE experiment_id = ?", (experiment_id,)).fetchone()[0]
            return int(current or 0) + 1

    def list_reports(self, experiment_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
        clause = "WHERE experiment_id = ?" if experiment_id is not None else ""
        params: tuple[Any, ...] = (experiment_id, limit) if experiment_id is not None else (limit,)
        with self._lock, self._connect() as conn:
            rows = conn.execute(f"SELECT * FROM reports {clause} ORDER BY id DESC LIMIT ?", params).fetchall()
            return [dict(row) for row in rows]
