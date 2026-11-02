"""History use cases: experiment listing/detail/measurements, rename/delete, alarms, audit, exports."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rka_desktop.application.ports import AlarmStore, AuditStore, ExperimentStore, Exporter
from rka_desktop.application.tasks import TaskContext, TaskRegistry

MAX_PAGE = 5000
EXPORT_KINDS = {"measurements_csv": "csv", "measurements_xlsx": "xlsx", "summary_csv": "csv"}
CATEGORIES = ("running", "pending", "archived", "aborted")
AUDIT_CATEGORIES = ("control", "safety", "config", "data", "system")
CODE_PATTERN = re.compile(r"^RKA-\d{4}-\d{4}-0*(\d+)$", re.IGNORECASE)


class ExperimentNotFound(LookupError):
    pass


class ExperimentBusy(ValueError):
    pass


class HistoryService:
    def __init__(self, experiments: ExperimentStore, alarms: AlarmStore, audit: AuditStore, tasks: TaskRegistry,
                 export_dir: Path, exporter: Exporter, *, active_experiment_id: Callable[[], int | None]) -> None:
        self._experiments = experiments
        self._alarms = alarms
        self._audit = audit
        self._tasks = tasks
        self._export_dir = export_dir
        self._exporter = exporter
        self._active_experiment_id = active_experiment_id

    def list_experiments(self, limit: int = 100, *, category: str | None = None, query: str | None = None) -> dict[str, Any]:
        if category is not None and category not in CATEGORIES:
            raise ValueError(f"未知的实验分类: {category}")
        text = (query or "").strip()[:60] or None
        if text and (match := CODE_PATTERN.match(text)):
            text = match.group(1)
        items = self._experiments.list_experiments(limit=max(1, min(limit, 1000)), category=category, query=text)
        return {"experiments": items, "counts": self._experiments.count_experiments_by_category()}

    def get_experiment(self, experiment_id: int) -> dict[str, Any]:
        detail = self._experiments.get_experiment_detail(experiment_id)
        if detail is None:
            raise ExperimentNotFound("实验不存在")
        summary = self._experiments.get_experiment_summary(experiment_id)
        events = self._audit.list_audit_logs(limit=200, experiment_id=experiment_id)
        alarms = self._alarms.list_alarm_history(experiment_id=experiment_id, limit=200)
        return {**detail, "summary": summary, "measurement_count": self._experiments.count_measurements(experiment_id),
                "events": events, "alarms": alarms}

    def measurements(self, experiment_id: int, *, limit: int = 1000, offset: int = 0) -> dict[str, Any]:
        if self._experiments.get_experiment_detail(experiment_id) is None:
            raise ExperimentNotFound("实验不存在")
        limit = max(1, min(limit, MAX_PAGE))
        offset = max(0, offset)
        items = self._experiments.fetch_measurements_page(experiment_id, limit=limit, offset=offset)
        total = self._experiments.count_measurements(experiment_id)
        return {"items": items, "total": total, "limit": limit, "offset": offset}

    def rename_experiment(self, experiment_id: int, name: Any) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise ValueError("实验名称不能为空")
        if len(name.strip()) > 100:
            raise ValueError("实验名称不能超过 100 字")
        detail = self._experiments.get_experiment_detail(experiment_id)
        if detail is None:
            raise ExperimentNotFound("实验不存在")
        if detail.get("review_state") == "archived":
            raise ExperimentBusy("实验已归档，只读")
        self._experiments.rename_experiment(experiment_id, name.strip())
        self._audit.log_action("operator", "EXPERIMENT_RENAME", f"→ {name.strip()}", experiment_id=experiment_id,
                               category="data", result="applied")
        return self.get_experiment(experiment_id)

    def delete_experiment(self, experiment_id: int) -> None:
        if self._experiments.get_experiment_detail(experiment_id) is None:
            raise ExperimentNotFound("实验不存在")
        if self._active_experiment_id() == experiment_id:
            raise ExperimentBusy("该实验正在运行中，不能删除")
        self._experiments.delete_experiment(experiment_id)
        # The experiment's own audit rows stay (experiment_id kept) so the deletion itself is traceable.
        self._audit.log_action("operator", "EXPERIMENT_DELETE", f"#{experiment_id}", experiment_id=experiment_id,
                               category="data", result="applied")

    def alarm_history(self, experiment_id: int | None = None, limit: int = 100, *,
                      acknowledged: bool | None = None) -> list[dict[str, Any]]:
        return self._alarms.list_alarm_history(experiment_id=experiment_id, limit=max(1, min(limit, 1000)),
                                               acknowledged=acknowledged)

    def audit_logs(self, limit: int = 200, *, experiment_id: int | None = None, category: str | None = None,
                   actor: str | None = None) -> list[dict[str, Any]]:
        if category is not None and category not in AUDIT_CATEGORIES:
            raise ValueError(f"未知的操作类型: {category}")
        return self._audit.list_audit_logs(limit=max(1, min(limit, 2000)), experiment_id=experiment_id, category=category,
                                           actor=(actor or "").strip()[:40] or None)

    def start_audit_export(self, *, experiment_id: int | None = None, category: str | None = None) -> dict[str, Any]:
        rows = self.audit_logs(2000, experiment_id=experiment_id, category=category)
        return self._tasks.submit("export", {"kind": "audit_csv", "rows": rows, "experiment_id": experiment_id},
                                  self._run_audit_export, dedupe_key=f"export:audit:{experiment_id}:{category}")

    def _run_audit_export(self, context: TaskContext, payload: dict[str, Any]) -> dict[str, Any]:
        context.progress(0.5, "写入文件")
        suffix = f"_{payload['experiment_id']}" if payload.get("experiment_id") else ""
        path = self._export_dir / f"audit{suffix}.csv"
        self._exporter.write_audit_csv(payload["rows"], path)
        self._audit.log_action("operator", "EXPORT_AUDIT_CSV", str(path), experiment_id=payload.get("experiment_id"),
                               category="data", result="applied")
        return {"path": str(path), "filename": path.name, "experiment_id": payload.get("experiment_id")}

    # ---------------------------------------------------------------- exports as tasks
    def start_export(self, kind: str, experiment_id: int) -> dict[str, Any]:
        if kind not in EXPORT_KINDS:
            raise ValueError(f"不支持的导出类型: {kind}")
        if self._experiments.get_experiment_detail(experiment_id) is None:
            raise ExperimentNotFound("实验不存在")
        return self._tasks.submit("export", {"kind": kind, "experiment_id": experiment_id}, self._run_export,
                                  dedupe_key=f"export:{kind}:{experiment_id}")

    def _run_export(self, context: TaskContext, payload: dict[str, Any]) -> dict[str, Any]:
        kind, experiment_id = payload["kind"], int(payload["experiment_id"])
        context.progress(0.1, "读取数据")
        suffix = EXPORT_KINDS[kind]
        stem = "summary" if kind == "summary_csv" else "experiment"
        path = self._export_dir / f"{stem}_{experiment_id}.{suffix}"
        if kind == "summary_csv":
            data = self._experiments.get_experiment_summary(experiment_id)
            context.check_cancelled()
            context.progress(0.6, "写入文件")
            self._exporter.write_summary_csv(data, path)
            action = "EXPORT_SUMMARY_CSV"
        else:
            rows = self._experiments.fetch_measurements(experiment_id)
            context.check_cancelled()
            context.progress(0.6, "写入文件")
            if kind == "measurements_csv":
                self._exporter.write_measurements_csv(rows, path)
                action = "EXPORT_CSV"
            else:
                self._exporter.write_measurements_excel(rows, path)
                action = "EXPORT_EXCEL"
        self._audit.log_action("operator", action, str(path), experiment_id=experiment_id, category="data", result="applied")
        return {"path": str(path), "filename": path.name, "experiment_id": experiment_id}
