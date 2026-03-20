from __future__ import annotations

from typing import Any

from rka_desktop.db.database import DatabaseManager


class ExperimentRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def create_experiment(self, name: str, recipe_id: int | None = None) -> int:
        return self._db.create_experiment(name, recipe_id=recipe_id)

    def finish_experiment(self, experiment_id: int, status: str) -> None:
        self._db.finish_experiment(experiment_id, status=status)

    def set_experiment_status(self, experiment_id: int, status: str) -> None:
        self._db.set_experiment_status(experiment_id, status)

    def get_latest_experiment_id(self) -> int | None:
        return self._db.get_latest_experiment_id()

    def list_experiments(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._db.list_experiments(limit=limit)

    def get_experiment_detail(self, experiment_id: int) -> dict[str, Any] | None:
        return self._db.get_experiment_detail(experiment_id)

    def get_experiment_summary(self, experiment_id: int) -> dict[str, Any] | None:
        return self._db.get_experiment_summary(experiment_id)
