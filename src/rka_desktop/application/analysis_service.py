"""Reduction-kinetics analysis use cases and Excel report generation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rka_desktop.application.ports import AuditStore, ExperimentStore, ReportWriter
from rka_desktop.application.tasks import TaskContext, TaskRegistry
from rka_desktop.domain.kinetics import ReductionResult, SampleParams, compute_reduction, measurements_to_series


class AnalysisError(ValueError):
    pass


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnalysisError(f"{label}必须是数字")
    return float(value)


class AnalysisService:
    def __init__(self, experiments: ExperimentStore, audit: AuditStore, tasks: TaskRegistry, export_dir: Path,
                 report_writer: ReportWriter) -> None:
        self._experiments = experiments
        self._audit = audit
        self._tasks = tasks
        self._export_dir = export_dir
        self._reports = report_writer

    def sample_params(self, experiment_id: int) -> dict[str, Any]:
        detail = self._experiments.get_experiment_detail(experiment_id)
        if detail is None:
            raise LookupError("实验不存在")
        return {"experiment_id": experiment_id, "initial_mass_g": detail.get("initial_mass_g"),
                "tfe_pct": detail.get("tfe_pct"), "feo_pct": detail.get("feo_pct")}

    def save_sample_params(self, experiment_id: int, payload: dict[str, Any]) -> dict[str, Any]:
        if self._experiments.get_experiment_detail(experiment_id) is None:
            raise LookupError("实验不存在")
        params = self._parse_params(payload)
        self._experiments.set_sample_params(experiment_id, params.initial_mass_g, params.tfe_pct, params.feo_pct)
        self._audit.log_action("operator", "SAMPLE_PARAMS_SAVE", f"experiment_id={experiment_id}")
        return self.sample_params(experiment_id)

    def compute(self, experiment_id: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        detail = self._experiments.get_experiment_detail(experiment_id)
        if detail is None:
            raise LookupError("实验不存在")
        params = self._parse_params(payload) if payload else self._stored_params(detail)
        result = self._compute(experiment_id, params)
        return self._result_dict(experiment_id, params, result)

    def start_report(self, experiment_id: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        detail = self._experiments.get_experiment_detail(experiment_id)
        if detail is None:
            raise LookupError("实验不存在")
        params = self._parse_params(payload) if payload else self._stored_params(detail)
        return self._tasks.submit("report", {"experiment_id": experiment_id, "params": params.__dict__}, self._run_report,
                                  dedupe_key=f"report:{experiment_id}")

    def _run_report(self, context: TaskContext, payload: dict[str, Any]) -> dict[str, Any]:
        experiment_id = int(payload["experiment_id"])
        params = SampleParams(**payload["params"])
        context.progress(0.2, "计算还原度")
        result = self._compute(experiment_id, params)
        context.check_cancelled()
        context.progress(0.6, "生成 Excel 报告")
        detail = self._experiments.get_experiment_detail(experiment_id) or {"id": experiment_id}
        detail = {**detail, "initial_mass_g": params.initial_mass_g, "tfe_pct": params.tfe_pct, "feo_pct": params.feo_pct}
        path = self._export_dir / f"experiment_{experiment_id}_report.xlsx"
        self._reports.generate_excel_report(detail, result, path)
        self._audit.log_action("operator", "REPORT_EXPORT", str(path))
        return {"path": str(path), "filename": path.name, "experiment_id": experiment_id,
                "final_degree_pct": result.final_degree_pct}

    def _compute(self, experiment_id: int, params: SampleParams) -> ReductionResult:
        series = measurements_to_series(self._experiments.fetch_measurements(experiment_id))
        if not series:
            raise AnalysisError("该实验没有可用的称重数据")
        try:
            return compute_reduction(series, params)
        except ValueError as exc:
            raise AnalysisError(f"参数错误: {exc}") from exc

    def _parse_params(self, payload: dict[str, Any]) -> SampleParams:
        if not isinstance(payload, dict):
            raise AnalysisError("试样参数必须是对象")
        params = SampleParams(
            initial_mass_g=_number(payload.get("initial_mass_g"), "初始质量 m0"),
            tfe_pct=_number(payload.get("tfe_pct"), "全铁 TFe"),
            feo_pct=_number(payload.get("feo_pct"), "FeO"),
        )
        try:
            params.validate()
        except ValueError as exc:
            raise AnalysisError(f"参数错误: {exc}") from exc
        return params

    def _stored_params(self, detail: dict[str, Any]) -> SampleParams:
        if detail.get("initial_mass_g") is None or detail.get("tfe_pct") is None:
            raise AnalysisError("请先录入并保存试样参数（m0 / TFe / FeO）")
        return self._parse_params({"initial_mass_g": detail["initial_mass_g"], "tfe_pct": detail["tfe_pct"],
                                   "feo_pct": detail.get("feo_pct") or 0.0})

    def _result_dict(self, experiment_id: int, params: SampleParams, result: ReductionResult) -> dict[str, Any]:
        return {
            "experiment_id": experiment_id,
            "params": params.__dict__,
            "points": [{"t_min": p.t_min, "reduction_degree_pct": p.reduction_degree_pct, "rate_pct_per_min": p.rate_pct_per_min}
                       for p in result.points],
            "final_degree_pct": result.final_degree_pct,
            "time_to_40_min": result.time_to_40_min,
            "time_to_60_min": result.time_to_60_min,
            "rate_at_40_pct": result.rate_at_40_pct,
        }
