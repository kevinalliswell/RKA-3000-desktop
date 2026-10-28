from __future__ import annotations

from typing import Any

from rka_desktop.db.database import DatabaseManager


class AlarmRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def create_alarm(self, experiment_id: int | None, code: str, level: str, message: str) -> int:
        return self._db.create_alarm(experiment_id, code=code, level=level, message=message)

    def acknowledge_latest_alarm(self, experiment_id: int, actor: str = "operator") -> bool:
        return self._db.acknowledge_latest_alarm(experiment_id, actor=actor)

    def list_unacknowledged_alarms(self, experiment_id: int) -> list[dict[str, Any]]:
        return self._db.list_unacknowledged_alarms(experiment_id)

    def list_alarm_history(self, experiment_id: int | None = None, limit: int | None = 100) -> list[dict[str, Any]]:
        return self._db.list_alarm_history(experiment_id=experiment_id, limit=limit)
