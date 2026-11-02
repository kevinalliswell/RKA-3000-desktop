"""SQLite-backed implementations of the application store ports."""

from __future__ import annotations

from typing import Any

from rka_desktop.domain.entities import Measurement
from rka_desktop.infrastructure.sqlite.database import DatabaseManager


class SqliteRecipeStore:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def list_recipes(self) -> list[dict[str, Any]]:
        return self._db.list_recipes()

    def get_recipe(self, recipe_id: int) -> dict[str, Any] | None:
        return self._db.get_recipe(recipe_id)

    def get_recipe_steps(self, recipe_id: int) -> list[dict[str, Any]]:
        return self._db.get_recipe_steps(recipe_id)

    def create_recipe(self, name: str, steps: list[dict[str, Any]], meta: dict[str, Any] | None = None, *,
                      reason: str = "", actor: str = "") -> int:
        return self._db.create_recipe(name, steps, meta, reason=reason, actor=actor)

    def update_recipe(self, recipe_id: int, name: str, steps: list[dict[str, Any]], meta: dict[str, Any] | None = None, *,
                      reason: str = "", actor: str = "") -> int:
        return self._db.update_recipe(recipe_id, name, steps, meta, reason=reason, actor=actor)

    def delete_recipe(self, recipe_id: int) -> None:
        self._db.delete_recipe(recipe_id)

    def count_experiments_for_recipe(self, recipe_id: int) -> int:
        return self._db.count_experiments_for_recipe(recipe_id)

    def list_recipe_versions(self, recipe_id: int) -> list[dict[str, Any]]:
        return self._db.list_recipe_versions(recipe_id)


class SqliteExperimentStore:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def create_experiment(self, name: str, recipe_id: int | None = None, fields: dict[str, Any] | None = None) -> int:
        return self._db.create_experiment(name, recipe_id=recipe_id, fields=fields)

    def update_experiment(self, experiment_id: int, fields: dict[str, Any]) -> None:
        self._db.update_experiment(experiment_id, fields)

    def finish_experiment(self, experiment_id: int, status: str) -> None:
        self._db.finish_experiment(experiment_id, status=status)

    def set_experiment_status(self, experiment_id: int, status: str) -> None:
        self._db.set_experiment_status(experiment_id, status)

    def set_sample_params(self, experiment_id: int, initial_mass_g: float, tfe_pct: float, feo_pct: float) -> None:
        self._db.set_experiment_sample_params(experiment_id, initial_mass_g, tfe_pct, feo_pct)

    def insert_measurements(self, measurements: list[Measurement]) -> int:
        return self._db.insert_measurements(measurements)

    def fetch_measurements(self, experiment_id: int) -> list[dict[str, Any]]:
        return self._db.fetch_measurements(experiment_id)

    def fetch_measurement_timestamps(self, experiment_id: int) -> list[str]:
        return self._db.fetch_measurement_timestamps(experiment_id)

    def fetch_measurements_page(self, experiment_id: int, *, limit: int, offset: int) -> list[dict[str, Any]]:
        return self._db.fetch_measurements_page(experiment_id, limit=limit, offset=offset)

    def count_measurements(self, experiment_id: int) -> int:
        return self._db.count_measurements(experiment_id)

    def rename_experiment(self, experiment_id: int, name: str) -> None:
        self._db.rename_experiment(experiment_id, name)

    def delete_experiment(self, experiment_id: int) -> None:
        self._db.delete_experiment(experiment_id)

    def get_latest_experiment_id(self) -> int | None:
        return self._db.get_latest_experiment_id()

    def list_experiments(self, limit: int = 100, *, category: str | None = None, query: str | None = None,
                         recipe_id: int | None = None) -> list[dict[str, Any]]:
        return self._db.list_experiments(limit=limit, category=category, query=query, recipe_id=recipe_id)

    def count_experiments_by_category(self) -> dict[str, int]:
        return self._db.count_experiments_by_category()

    def get_experiment_detail(self, experiment_id: int) -> dict[str, Any] | None:
        return self._db.get_experiment_detail(experiment_id)

    def get_experiment_summary(self, experiment_id: int) -> dict[str, Any] | None:
        return self._db.get_experiment_summary(experiment_id)


class SqliteAlarmStore:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def create_alarm(self, experiment_id: int | None, code: str, level: str, message: str) -> int:
        return self._db.create_alarm(experiment_id, code=code, level=level, message=message)

    def acknowledge_alarm(self, alarm_id: int, actor: str, note: str) -> bool:
        return self._db.acknowledge_alarm(alarm_id, actor, note)

    def get_alarm(self, alarm_id: int) -> dict[str, Any] | None:
        return self._db.get_alarm(alarm_id)

    def acknowledge_latest_alarm(self, experiment_id: int, actor: str = "operator", note: str = "") -> bool:
        return self._db.acknowledge_latest_alarm(experiment_id, actor=actor, note=note)

    def list_unacknowledged_alarms(self, experiment_id: int | None = None) -> list[dict[str, Any]]:
        return self._db.list_unacknowledged_alarms(experiment_id)

    def count_alarms(self, experiment_id: int) -> int:
        return self._db.count_alarms(experiment_id)

    def list_alarm_history(self, experiment_id: int | None = None, limit: int = 100, *,
                           acknowledged: bool | None = None) -> list[dict[str, Any]]:
        return self._db.list_alarm_history(experiment_id=experiment_id, limit=limit, acknowledged=acknowledged)


class SqliteAuditStore:
    def __init__(self, db: DatabaseManager, *, retain: int = 2000) -> None:
        self._db = db
        self._retain = retain
        self._writes = 0

    def log_action(self, actor: str, action: str, detail: str = "", *, experiment_id: int | None = None,
                   category: str | None = None, reason: str | None = None, result: str | None = None) -> None:
        self._db.log_action(actor, action, detail, experiment_id=experiment_id, category=category, reason=reason, result=result)
        self._writes += 1
        if self._writes % 100 == 0:
            self._db.prune_audit_logs(self._retain)

    def list_audit_logs(self, limit: int = 100, *, experiment_id: int | None = None, category: str | None = None,
                        actor: str | None = None) -> list[dict[str, Any]]:
        return self._db.list_audit_logs(limit=limit, experiment_id=experiment_id, category=category, actor=actor)

    def count_audit(self, experiment_id: int, action: str | None = None) -> int:
        return self._db.count_audit(experiment_id, action)


class SqliteLimitStore:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def latest_policy(self) -> dict[str, Any] | None:
        return self._db.latest_limit_policy()

    def save_policy(self, limits: dict[str, float], reason: str, actor: str, *, version: int | None = None) -> int:
        return self._db.save_limit_policy(limits, reason, actor, version=version)

    def list_policies(self, limit: int = 20) -> list[dict[str, Any]]:
        return self._db.list_limit_policies(limit)


class SqliteReportStore:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def add_report(self, experiment_id: int, path: str, actor: str) -> int:
        return self._db.add_report(experiment_id, path, actor)

    def next_version(self, experiment_id: int) -> int:
        return self._db.next_report_version(experiment_id)

    def list_reports(self, experiment_id: int | None = None, limit: int = 200) -> list[dict[str, Any]]:
        return self._db.list_reports(experiment_id, limit)
