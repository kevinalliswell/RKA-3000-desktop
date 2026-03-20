from __future__ import annotations

from typing import Any

from rka_desktop.db.database import DatabaseManager


class AuditLogRepository:
    def __init__(self, db: DatabaseManager) -> None:
        self._db = db

    def log_action(self, actor: str, action: str, detail: str = "") -> None:
        self._db.log_action(actor, action, detail)

    def list_audit_logs(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._db.list_audit_logs(limit=limit)
