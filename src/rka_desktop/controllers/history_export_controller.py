from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rka_desktop.repositories.audit_repository import AuditLogRepository
from rka_desktop.repositories.experiment_repository import ExperimentRepository
from rka_desktop.services.export_service import ExportService


@dataclass
class HistoryViewState:
    experiments: list[dict[str, Any]] = field(default_factory=list)
    selected_experiment_id: int | None = None
    summary_text: str = "暂无历史实验"
    export_enabled: bool = False


@dataclass
class HistoryTransition:
    success: bool = True
    logs: list[str] = field(default_factory=list)
    exported_path: Path | None = None
    user_message: str | None = None
    user_message_level: str | None = None
    view_state: HistoryViewState | None = None


class HistoryExportController:
    def __init__(
        self,
        experiment_repository: ExperimentRepository,
        audit_repository: AuditLogRepository,
        export_service: ExportService,
    ) -> None:
        self.experiment_repository = experiment_repository
        self.audit_repository = audit_repository
        self.export_service = export_service

    def load_history(self, selected_experiment_id: int | None = None, limit: int = 100) -> HistoryTransition:
        experiments = self.experiment_repository.list_experiments(limit=limit)
        resolved_id = self._resolve_selected_experiment_id(selected_experiment_id, experiments)
        return HistoryTransition(view_state=self._build_view_state(experiments, resolved_id))

    def select_experiment(self, experiment_id: int | None, limit: int = 100) -> HistoryTransition:
        return self.load_history(selected_experiment_id=experiment_id, limit=limit)

    def export_experiment(
        self,
        fmt: str,
        *,
        active_experiment_id: int | None,
        selected_experiment_id: int | None,
        file_path: Path,
        limit: int = 100,
    ) -> HistoryTransition:
        experiment_id = active_experiment_id or selected_experiment_id or self.experiment_repository.get_latest_experiment_id()
        if experiment_id is None:
            return HistoryTransition(success=False, user_message="没有可导出的实验数据", user_message_level="info")

        if fmt == "csv":
            out = self.export_service.export_measurements_csv(experiment_id, file_path)
            self.audit_repository.log_action("operator", "EXPORT_CSV", f"experiment_id={experiment_id},path={out}")
            logs = [f"导出CSV成功: {out}"]
        else:
            out = self.export_service.export_measurements_excel(experiment_id, file_path)
            self.audit_repository.log_action("operator", "EXPORT_EXCEL", f"experiment_id={experiment_id},path={out}")
            logs = [f"导出Excel成功: {out}"]

        experiments = self.experiment_repository.list_experiments(limit=limit)
        view_state = self._build_view_state(experiments, experiment_id)
        return HistoryTransition(success=True, logs=logs, exported_path=out, view_state=view_state)

    def default_export_path(
        self,
        fmt: str,
        *,
        active_experiment_id: int | None,
        selected_experiment_id: int | None,
        export_dir: Path,
    ) -> tuple[int | None, Path]:
        experiment_id = active_experiment_id or selected_experiment_id or self.experiment_repository.get_latest_experiment_id()
        if experiment_id is None:
            suffix = "csv" if fmt == "csv" else "xlsx"
            return None, export_dir / f"experiment_unknown.{suffix}"
        suffix = "csv" if fmt == "csv" else "xlsx"
        return experiment_id, export_dir / f"experiment_{experiment_id}.{suffix}"

    def _resolve_selected_experiment_id(
        self,
        selected_experiment_id: int | None,
        experiments: list[dict[str, Any]],
    ) -> int | None:
        if selected_experiment_id and any(int(item["id"]) == selected_experiment_id for item in experiments):
            return selected_experiment_id
        if experiments:
            return int(experiments[0]["id"])
        return None

    def _build_view_state(
        self,
        experiments: list[dict[str, Any]],
        selected_experiment_id: int | None,
    ) -> HistoryViewState:
        summary_text = self._build_summary(selected_experiment_id)
        return HistoryViewState(
            experiments=experiments,
            selected_experiment_id=selected_experiment_id,
            summary_text=summary_text,
            export_enabled=selected_experiment_id is not None,
        )

    def _build_summary(self, experiment_id: int | None) -> str:
        if experiment_id is None:
            return "暂无历史实验"

        detail = self.experiment_repository.get_experiment_detail(experiment_id)
        if detail is None:
            return "未找到实验详情"

        summary = self.experiment_repository.get_experiment_summary(experiment_id)
        if not summary:
            return (
                f"实验 #{experiment_id} | 状态 {detail['status']} | "
                f"配方 {detail.get('recipe_name') or '--'} | 暂无测量数据"
            )

        return (
            f"实验 #{experiment_id} | 状态 {detail['status']} | 配方 {detail.get('recipe_name') or '--'} | "
            f"样本数 {summary['sample_count']} | 温度范围 {summary['min_temperature_c']}~{summary['max_temperature_c']} ℃ | "
            f"重量范围 {summary['min_weight_g']}~{summary['max_weight_g']} g"
        )
