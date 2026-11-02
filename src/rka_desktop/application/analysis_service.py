"""Kinetics analysis, model fitting, archived KPIs, and versioned Excel reports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from rka_desktop.application.ports import AlarmStore, AuditStore, ExperimentStore, ReportStore, ReportWriter
from rka_desktop.application.tasks import TaskContext, TaskRegistry
from rka_desktop.domain.kinetics import (
    FIT_WINDOW,
    ModelFit,
    ReductionResult,
    SampleParams,
    compute_reduction,
    fit_models,
    measurements_to_series,
    series_window,
)

MAX_POINTS = 1200


class AnalysisError(ValueError):
    pass


class ExperimentArchived(ValueError):
    pass


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnalysisError(f"{label}必须是数字")
    return float(value)


def _thin(items: list[Any], limit: int = MAX_POINTS) -> list[Any]:
    if len(items) <= limit:
        return items
    step = len(items) / limit
    return [items[int(i * step)] for i in range(limit)] + [items[-1]]


def _fit_dict(fit: ModelFit) -> dict[str, Any]:
    return {"id": fit.model_id, "name": fit.name, "g_expr": fit.g_expr, "k_per_min": fit.k_per_min, "r2": fit.r2,
            "n": fit.n, "curve": [{"t_min": t, "alpha": a} for t, a in fit.curve]}


class AnalysisService:
    def __init__(self, experiments: ExperimentStore, audit: AuditStore, tasks: TaskRegistry, export_dir: Path,
                 report_writer: ReportWriter, reports: ReportStore, alarms: AlarmStore) -> None:
        self._experiments = experiments
        self._audit = audit
        self._tasks = tasks
        self._export_dir = export_dir
        self._writer = report_writer
        self._reports = reports
        self._alarms = alarms

    def _detail(self, experiment_id: int) -> dict[str, Any]:
        detail = self._experiments.get_experiment_detail(experiment_id)
        if detail is None:
            raise LookupError("实验不存在")
        return detail

    # ---------------------------------------------------------------- sample params
    def sample_params(self, experiment_id: int) -> dict[str, Any]:
        detail = self._detail(experiment_id)
        return {"experiment_id": experiment_id, "initial_mass_g": detail.get("initial_mass_g"),
                "tfe_pct": detail.get("tfe_pct"), "feo_pct": detail.get("feo_pct"),
                "locked": detail.get("review_state") == "archived"}

    def save_sample_params(self, experiment_id: int, payload: dict[str, Any], *, actor: Any = None) -> dict[str, Any]:
        detail = self._detail(experiment_id)
        if detail.get("review_state") == "archived":
            raise ExperimentArchived("实验已归档，试样参数只读")
        params = self._parse_params(payload)
        self._experiments.set_sample_params(experiment_id, params.initial_mass_g, params.tfe_pct, params.feo_pct)
        self._audit.log_action(str(actor or "operator")[:40], "SAMPLE_PARAMS_SAVE",
                               f"m0={params.initial_mass_g:g} TFe={params.tfe_pct:g} FeO={params.feo_pct:g}",
                               experiment_id=experiment_id, category="data", result="applied")
        return self.sample_params(experiment_id)

    # ---------------------------------------------------------------- kinetics
    def compute(self, experiment_id: int, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        detail = self._detail(experiment_id)
        params = self._parse_params(payload) if payload else self._stored_params(detail)
        result, window, kind = self._compute(detail, params)
        fits = fit_models([(p.t_min, p.reduction_degree_pct / 100.0) for p in result.points])
        best = max(fits, key=lambda f: f.r2) if fits else None
        return {
            "experiment_id": experiment_id,
            "params": params.__dict__,
            "degree_kind": kind,
            "window": window,
            "points": [{"t_min": p.t_min, "reduction_degree_pct": p.reduction_degree_pct, "rate_pct_per_min": p.rate_pct_per_min}
                       for p in _thin(list(result.points))],
            "final_degree_pct": result.final_degree_pct,
            "time_to_40_min": result.time_to_40_min,
            "time_to_60_min": result.time_to_60_min,
            "rate_at_40_pct": result.rate_at_40_pct,
            "fit_window": list(FIT_WINDOW),
            "fits": [_fit_dict(f) for f in fits],
            "best_fit": best.model_id if best else None,
        }

    def kpi(self, experiment_id: int) -> dict[str, Any] | None:
        """Frozen at archive time; None when parameters or data are missing."""
        try:
            result = self.compute(experiment_id)
        except (AnalysisError, LookupError):
            return None
        best = next((f for f in result["fits"] if f["id"] == result["best_fit"]), None)
        return {
            "degree_kind": result["degree_kind"], "final_degree_pct": result["final_degree_pct"],
            "time_to_40_min": result["time_to_40_min"], "time_to_60_min": result["time_to_60_min"],
            "rate_at_40_pct": result["rate_at_40_pct"], "window": result["window"],
            "best_fit": {k: v for k, v in best.items() if k != "curve"} if best else None,
            "computed_at": datetime.now().isoformat(),
        }

    def compare(self, experiment_id: int, limit: int = 10) -> list[dict[str, Any]]:
        detail = self._detail(experiment_id)
        recipe_id = detail.get("recipe_id")
        if recipe_id is None:
            return []
        rows = self._experiments.list_experiments(limit=200, recipe_id=int(recipe_id))
        # This experiment plus completed, archived runs of the same recipe (aborted runs are not comparable).
        rows = [row for row in rows if row["id"] == experiment_id or row["category"] == "archived"]
        items = []
        for row in rows:
            kpi = row.get("kpi") or {}
            if row["id"] == experiment_id and not kpi:
                kpi = self.kpi(experiment_id) or {}
            items.append({"id": row["id"], "code": row["code"], "sample_name": row.get("sample_name") or row.get("name"),
                          "recipe_version": row.get("recipe_version"), "time_to_40_min": kpi.get("time_to_40_min"),
                          "time_to_60_min": kpi.get("time_to_60_min"), "final_degree_pct": kpi.get("final_degree_pct"),
                          "current": row["id"] == experiment_id})
        return items[:limit]

    def _compute(self, detail: dict[str, Any], params: SampleParams) -> tuple[ReductionResult, dict[str, Any], str]:
        rows = self._experiments.fetch_measurements(int(detail["id"]))
        kind = detail.get("experiment_type") or "reduction"
        start, end = detail.get("reaction_started_at"), detail.get("reaction_ended_at")
        if start:
            rows = series_window(rows, start, end)
            window = {"source": "reaction", "start": start, "end": end}
        else:
            rows = [row for row in rows if (row.get("phase") or "run") == "run"]
            window = {"source": "all", "start": None, "end": None}
        series = measurements_to_series(rows)
        if not series:
            raise AnalysisError("该实验没有可用的称重数据")
        try:
            return compute_reduction(series, params, kind=kind), window, kind
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

    # ---------------------------------------------------------------- reports
    def start_report(self, experiment_id: int, *, actor: Any = None) -> dict[str, Any]:
        detail = self._detail(experiment_id)
        if detail.get("review_state") != "archived":
            raise ExperimentArchived("只有已归档的实验能生成报告，请先在分析与归档中完成复核")
        params = self._stored_params(detail)
        return self._tasks.submit("report", {"experiment_id": experiment_id, "params": params.__dict__,
                                             "actor": str(actor or "operator")[:40]},
                                  self._run_report, dedupe_key=f"report:{experiment_id}")

    def _run_report(self, context: TaskContext, payload: dict[str, Any]) -> dict[str, Any]:
        experiment_id = int(payload["experiment_id"])
        params = SampleParams(**payload["params"])
        context.progress(0.2, "计算指标与模型拟合")
        detail = self._detail(experiment_id)
        result, window, kind = self._compute(detail, params)
        fits = fit_models([(p.t_min, p.reduction_degree_pct / 100.0) for p in result.points])
        context.check_cancelled()
        context.progress(0.6, "生成 Excel 报告")
        version = self._reports.next_version(experiment_id)
        path = self._export_dir / f"{detail['code']}_report_v{version}.xlsx"
        extras = {
            "degree_kind": kind, "window": window, "fits": [_fit_dict(f) for f in fits],
            "alarms": self._alarms.list_alarm_history(experiment_id=experiment_id, limit=200),
            "audit": self._audit.list_audit_logs(limit=500, experiment_id=experiment_id), "report_version": version,
        }
        self._writer.generate_excel_report({**detail, **params.__dict__}, result, path, extras)
        recorded = self._reports.add_report(experiment_id, str(path), payload.get("actor") or "operator")
        self._audit.log_action(payload.get("actor") or "operator", "REPORT_EXPORT", f"v{recorded} {path.name}",
                               experiment_id=experiment_id, category="data", result="applied")
        return {"path": str(path), "filename": path.name, "experiment_id": experiment_id, "version": recorded,
                "final_degree_pct": result.final_degree_pct}

    def list_reports(self) -> list[dict[str, Any]]:
        """Recent experiments with their report status; only archived ones can have reports."""
        reports: dict[int, list[dict[str, Any]]] = {}
        for row in self._reports.list_reports(limit=500):
            reports.setdefault(int(row["experiment_id"]), []).append(row)
        items = []
        for row in self._experiments.list_experiments(limit=100):
            versions = reports.get(int(row["id"]), [])
            items.append({**row, "reports": versions, "latest_report": versions[0] if versions else None,
                          "can_generate": row.get("review_state") == "archived" and row.get("initial_mass_g") is not None})
        return items
