from __future__ import annotations

from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.chart import LineChart, Reference

from rka_desktop.analysis.reduction_kinetics import ReductionResult


class ReportService:
    """Generates an Excel reduction-kinetics report (summary + data + chart)."""

    def generate_excel_report(
        self,
        experiment: dict[str, Any],
        result: ReductionResult,
        file_path: Path,
    ) -> Path:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        wb = Workbook()

        summary = wb.active
        summary.title = "报告"
        summary["A1"] = "铁矿石还原动力学实验报告（失重法）"
        rows = [
            ("实验编号", experiment.get("id")),
            ("实验名称", experiment.get("name")),
            ("状态", experiment.get("status")),
            ("初始质量 m0 (g)", experiment.get("initial_mass_g")),
            ("全铁 TFe (%)", experiment.get("tfe_pct")),
            ("FeO (%)", experiment.get("feo_pct")),
            ("终态还原度 (%)", round(result.final_degree_pct, 3)),
            ("到 40% 时间 (min)", result.time_to_40_min),
            ("到 60% 时间 (min)", result.time_to_60_min),
            ("40% 还原速率 (%/min)", result.rate_at_40_pct),
        ]
        for i, (label, value) in enumerate(rows, start=3):
            summary[f"A{i}"] = label
            summary[f"B{i}"] = value

        data = wb.create_sheet("数据")
        data.append(["时间 (min)", "还原度 R (%)", "还原速率 dR/dt (%/min)"])
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
            chart.title = "还原度曲线 R(t)"
            chart.x_axis.title = "时间 (min)"
            chart.y_axis.title = "还原度 (%)"
            values = Reference(data, min_col=2, min_row=1, max_row=n + 1)
            cats = Reference(data, min_col=1, min_row=2, max_row=n + 1)
            chart.add_data(values, titles_from_data=True)
            chart.set_categories(cats)
            data.add_chart(chart, "E2")

        wb.save(file_path)
        return file_path
