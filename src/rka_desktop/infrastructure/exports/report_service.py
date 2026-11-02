from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference

from rka_desktop.domain.kinetics import ReductionResult


class ReportService:
    """Generates an Excel reduction-kinetics report (summary + data + chart)."""

    def generate_excel_report(
        self,
        experiment: dict[str, Any],
        result: ReductionResult,
        file_path: Path,
        extras: dict[str, Any] | None = None,
    ) -> Path:
        extras = extras or {}
        oxidation = extras.get("degree_kind") == "oxidation"
        word = "氧化度" if oxidation else "还原度"
        stem = "氧化" if oxidation else "还原"
        file_path.parent.mkdir(parents=True, exist_ok=True)
        wb = Workbook()

        summary = wb.active
        summary.title = "报告"
        summary["A1"] = "铁矿石氧化动力学实验报告（增重法）" if oxidation else "铁矿石还原动力学实验报告（失重法）"
        window = extras.get("window") or {}
        rows = [
            ("实验编号", experiment.get("code") or experiment.get("id")),
            ("报告版本", f"v{extras['report_version']}" if extras.get("report_version") else None),
            ("实验名称", experiment.get("name")),
            ("样品", experiment.get("sample_name")),
            ("操作者", experiment.get("operator")),
            ("配方 · 版本", f"{experiment.get('recipe_name') or ''} v{experiment.get('recipe_version') or '-'}"),
            ("开始 / 结束", f"{experiment.get('started_at') or ''} / {experiment.get('finished_at') or ''}"),
            ("结束方式", experiment.get("end_detail") or experiment.get("end_reason")),
            ("状态", experiment.get("status")),
            ("初始质量 m0 (g)", experiment.get("initial_mass_g")),
            ("全铁 TFe (%)", experiment.get("tfe_pct")),
            ("FeO (%)", experiment.get("feo_pct")),
            ("测定区间", f"{window.get('start') or '全程'} — {window.get('end') or ''}"),
            (f"终态{word} (%)", round(result.final_degree_pct, 3)),
            ("到 40% 时间 (min)", result.time_to_40_min),
            ("到 60% 时间 (min)", result.time_to_60_min),
            (f"40% {stem}速率 (%/min)", result.rate_at_40_pct),
            ("复核备注", experiment.get("archive_note")),
            ("归档", f"{experiment.get('archived_by') or ''} {experiment.get('archived_at') or ''}".strip()),
        ]
        for i, (label, value) in enumerate(rows, start=3):
            summary[f"A{i}"] = label
            summary[f"B{i}"] = value

        data = wb.create_sheet("数据")
        data.append(["时间 (min)", f"{word} (%)", f"{stem}速率 (%/min)"])
        for point in result.points:
            data.append(
                [
                    round(point.t_min, 4),
                    round(point.reduction_degree_pct, 4),
                    round(point.rate_pct_per_min, 4),
                ]
            )

        n = len(result.points)
        if n >= 2:
            chart = LineChart()
            chart.title = f"{word}曲线"
            chart.x_axis.title = "时间 (min)"
            chart.y_axis.title = f"{word} (%)"
            values = Reference(data, min_col=2, min_row=1, max_row=n + 1)
            cats = Reference(data, min_col=1, min_row=2, max_row=n + 1)
            chart.add_data(values, titles_from_data=True)
            chart.set_categories(cats)
            data.add_chart(chart, "E2")

        fits = extras.get("fits") or []
        if fits:
            sheet = wb.create_sheet("模型拟合")
            sheet.append(["模型", "g(α)", "k (1/min)", "n", "R²"])
            for fit in sorted(fits, key=lambda f: -f["r2"]):
                sheet.append([fit["name"], fit["g_expr"], round(fit["k_per_min"], 6), fit.get("n"), round(fit["r2"], 4)])
        alarms = extras.get("alarms") or []
        sheet = wb.create_sheet("报警与事件")
        sheet.append(["时间", "代码", "级别", "内容", "确认人", "确认时间", "处理说明"])
        for alarm in alarms:
            sheet.append([alarm.get("created_at"), alarm.get("code"), alarm.get("level"), alarm.get("message"),
                          alarm.get("acknowledged_by"), alarm.get("acknowledged_at"), alarm.get("ack_note")])
        audit = extras.get("audit") or []
        sheet = wb.create_sheet("操作记录")
        sheet.append(["时间", "操作者", "操作", "对象 / 参数", "原因", "结果"])
        for row in reversed(audit):
            sheet.append([row.get("created_at"), row.get("actor"), row.get("action"), row.get("detail"), row.get("reason"),
                          row.get("result")])
        wb.save(file_path)
        return file_path
