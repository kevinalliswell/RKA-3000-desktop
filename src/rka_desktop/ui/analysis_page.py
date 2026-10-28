from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rka_desktop.analysis.reduction_kinetics import (
    ReductionResult,
    SampleParams,
    compute_reduction,
)
from rka_desktop.ui.components import Card, MetricTile
from rka_desktop.ui.theme import (
    ACCENT,
    accent_pen,
    make_primary,
    style_axis,
    style_chart,
    style_chart_view,
)

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis

    CHARTS_AVAILABLE = True
except Exception:  # noqa: BLE001  # pragma: no cover
    CHARTS_AVAILABLE = False


def _to_series(measurements: list[dict[str, Any]]) -> list[tuple[float, float]]:
    """Convert stored measurements into (t_seconds, weight_g) from the first sample."""
    series: list[tuple[float, float]] = []
    t0: datetime | None = None
    for row in measurements:
        weight = row.get("weight_g")
        sampled_at = row.get("sampled_at")
        if weight is None or sampled_at is None:
            continue
        try:
            ts = datetime.fromisoformat(str(sampled_at))
        except ValueError:
            continue
        if t0 is None:
            t0 = ts
        series.append(((ts - t0).total_seconds(), float(weight)))
    return series


class AnalysisPage(QWidget):
    """数据分析: reduction-degree kinetics (失重法) for a selected experiment."""

    def __init__(self, experiment_repository) -> None:
        super().__init__()
        self._repo = experiment_repository
        self._last_result: ReductionResult | None = None

        layout = QVBoxLayout(self)
        self.sections = QTabWidget()
        work_page = QWidget()
        work_layout = QVBoxLayout(work_page)

        # --- selector + sample params ---
        controls = QGroupBox("试样参数（失重法）")
        form = QGridLayout(controls)
        self.experiment_combo = QComboBox()
        self.experiment_combo.setMinimumWidth(280)
        self.btn_refresh = QPushButton("刷新实验")

        self.spin_m0 = QDoubleSpinBox()
        self.spin_m0.setRange(0.0, 100000.0)
        self.spin_m0.setDecimals(3)
        self.spin_m0.setSuffix(" g")
        self.spin_tfe = QDoubleSpinBox()
        self.spin_tfe.setRange(0.0, 100.0)
        self.spin_tfe.setDecimals(2)
        self.spin_tfe.setSuffix(" %")
        self.spin_feo = QDoubleSpinBox()
        self.spin_feo.setRange(0.0, 100.0)
        self.spin_feo.setDecimals(2)
        self.spin_feo.setSuffix(" %")

        self.btn_save = QPushButton("保存参数")
        self.btn_compute = make_primary(QPushButton("计算还原度"))
        self.btn_report = QPushButton("生成报告")
        self.btn_report.setEnabled(False)

        selector_row = QHBoxLayout()
        selector_row.addWidget(QLabel("实验"))
        selector_row.addWidget(self.experiment_combo)
        selector_row.addWidget(self.btn_refresh)
        selector_row.addStretch()
        form.addLayout(selector_row, 0, 0, 1, 4)
        params = QFormLayout()
        params.addRow("初始质量 m₀", self.spin_m0)
        params.addRow("全铁 TFe", self.spin_tfe)
        params.addRow("FeO", self.spin_feo)
        form.addLayout(params, 1, 0, 1, 2)
        action_col = QVBoxLayout()
        action_col.addWidget(self.btn_save)
        action_col.addWidget(self.btn_compute)
        action_col.addWidget(self.btn_report)
        action_col.addStretch()
        form.addLayout(action_col, 1, 2, 1, 2)
        work_layout.addWidget(controls)

        # --- charts ---
        if CHARTS_AVAILABLE:
            self.degree_series = QLineSeries()
            self.degree_series.setName("还原度 R(t)")
            self.degree_series.setPen(accent_pen(ACCENT, 2))
            degree_chart = QChart()
            degree_chart.addSeries(self.degree_series)
            degree_chart.setTitle("还原度曲线 R(t)")
            self._degree_axis_x = QValueAxis()
            self._degree_axis_x.setTitleText("时间 (min)")
            self._degree_axis_y = QValueAxis()
            self._degree_axis_y.setTitleText("还原度 (%)")
            self._degree_axis_y.setRange(0, 100)
            degree_chart.addAxis(self._degree_axis_x, Qt.AlignBottom)
            degree_chart.addAxis(self._degree_axis_y, Qt.AlignLeft)
            self.degree_series.attachAxis(self._degree_axis_x)
            self.degree_series.attachAxis(self._degree_axis_y)
            style_chart(degree_chart)
            style_axis(self._degree_axis_x, label_format="%.0f", ticks=6)
            style_axis(self._degree_axis_y, label_format="%.0f", ticks=6)

            self.rate_series = QLineSeries()
            self.rate_series.setName("还原速率 dR/dt")
            self.rate_series.setPen(accent_pen("#0EA5E9", 2))
            rate_chart = QChart()
            rate_chart.addSeries(self.rate_series)
            rate_chart.setTitle("还原速率曲线 dR/dt")
            self._rate_axis_x = QValueAxis()
            self._rate_axis_x.setTitleText("时间 (min)")
            self._rate_axis_y = QValueAxis()
            self._rate_axis_y.setTitleText("速率 (%/min)")
            rate_chart.addAxis(self._rate_axis_x, Qt.AlignBottom)
            rate_chart.addAxis(self._rate_axis_y, Qt.AlignLeft)
            self.rate_series.attachAxis(self._rate_axis_x)
            self.rate_series.attachAxis(self._rate_axis_y)
            style_chart(rate_chart)
            style_axis(self._rate_axis_x, label_format="%.0f", ticks=6)
            style_axis(self._rate_axis_y, label_format="%.1f", ticks=6)

            charts_row = QHBoxLayout()
            charts_row.setSpacing(12)
            for chart in (degree_chart, rate_chart):
                view = QChartView(chart)
                view.setMinimumHeight(300)
                style_chart_view(view)
                charts_row.addWidget(view)
            work_layout.addLayout(charts_row)

        # --- indices (modular KPI tiles) ---
        indices = Card("关键指标")
        tiles_row = QHBoxLayout()
        tiles_row.setSpacing(12)
        self.tile_final = MetricTile("终态还原度", "--", "%", icon="mdi.check-decagram-outline")
        self.tile_t40 = MetricTile("到 40% 时间", "--", "min", icon="mdi.timer-outline")
        self.tile_t60 = MetricTile("到 60% 时间", "--", "min", icon="mdi.timer-sand")
        self.tile_rate40 = MetricTile("40% 还原速率", "--", "%/min", icon="mdi.speedometer")
        for tile in (self.tile_final, self.tile_t40, self.tile_t60, self.tile_rate40):
            tiles_row.addWidget(tile)
        indices.add_layout(tiles_row)
        work_layout.addWidget(indices)

        self.lbl_status = QLabel("")
        work_layout.addWidget(self.lbl_status)

        method_page = QWidget()
        method_layout = QVBoxLayout(method_page)
        method_note = QLabel(
            "还原度及速率结果依赖 m₀、TFe、FeO、起始时点和称重序列。"
            "计算前应检查缺失样本、报警区间、提前终止及配方偏离。"
            "正式方法符合性、算法版本与人工算例仍需实验负责人验证。"
        )
        method_note.setWordWrap(True)
        method_layout.addWidget(method_note)
        method_layout.addStretch()
        self.sections.addTab(work_page, "指标工作台")
        self.sections.addTab(method_page, "计算依据与限制")
        layout.addWidget(self.sections)

        self.btn_refresh.clicked.connect(self.refresh_experiments)
        self.experiment_combo.currentIndexChanged.connect(self._load_params_for_selection)
        self.btn_save.clicked.connect(self._save_params)
        self.btn_compute.clicked.connect(self.compute)

    # --- data ---
    def refresh_experiments(self) -> None:
        current = self.experiment_combo.currentData()
        self.experiment_combo.blockSignals(True)
        self.experiment_combo.clear()
        for exp in self._repo.list_experiments(limit=200):
            label = f"#{exp['id']} {exp.get('name', '')} [{exp.get('status', '')}]"
            self.experiment_combo.addItem(label, exp["id"])
        self.experiment_combo.blockSignals(False)
        if current is not None:
            idx = self.experiment_combo.findData(current)
            if idx >= 0:
                self.experiment_combo.setCurrentIndex(idx)
        self._load_params_for_selection()

    def selected_experiment_id(self) -> int | None:
        data = self.experiment_combo.currentData()
        return int(data) if data is not None else None

    # backwards-compatible private alias
    _selected_experiment_id = selected_experiment_id

    @property
    def result(self) -> ReductionResult | None:
        return self._last_result

    def _load_params_for_selection(self) -> None:
        exp_id = self._selected_experiment_id()
        if exp_id is None:
            return
        detail = self._repo.get_experiment_detail(exp_id) or {}
        self.spin_m0.setValue(float(detail.get("initial_mass_g") or 0.0))
        self.spin_tfe.setValue(float(detail.get("tfe_pct") or 0.0))
        self.spin_feo.setValue(float(detail.get("feo_pct") or 0.0))

    def _save_params(self) -> None:
        exp_id = self._selected_experiment_id()
        if exp_id is None:
            self.lbl_status.setText("请先选择实验")
            return
        self._repo.set_sample_params(
            exp_id, self.spin_m0.value(), self.spin_tfe.value(), self.spin_feo.value()
        )
        self.lbl_status.setText(f"已保存实验 #{exp_id} 的试样参数")

    def compute(self) -> ReductionResult | None:
        exp_id = self._selected_experiment_id()
        if exp_id is None:
            self.lbl_status.setText("请先选择实验")
            return None
        series = _to_series(self._repo.fetch_measurements(exp_id))
        if not series:
            self.lbl_status.setText("该实验没有可用的称重数据")
            return None
        try:
            params = SampleParams(
                initial_mass_g=self.spin_m0.value(),
                tfe_pct=self.spin_tfe.value(),
                feo_pct=self.spin_feo.value(),
            )
            result = compute_reduction(series, params)
        except ValueError as exc:
            self.lbl_status.setText(f"参数错误: {exc}")
            return None

        self._last_result = result
        self._render(result)
        self.btn_report.setEnabled(True)
        self.lbl_status.setText(f"已计算实验 #{exp_id}，共 {len(result.points)} 个采样点")
        return result

    def _render(self, result: ReductionResult) -> None:
        self._update_indices(result)
        if not CHARTS_AVAILABLE:
            return
        self.degree_series.clear()
        self.rate_series.clear()
        max_t = 0.0
        max_rate = 0.0
        for point in result.points:
            self.degree_series.append(point.t_min, point.reduction_degree_pct)
            self.rate_series.append(point.t_min, point.rate_pct_per_min)
            max_t = max(max_t, point.t_min)
            max_rate = max(max_rate, point.rate_pct_per_min)
        self._degree_axis_x.setRange(0, max(max_t, 1.0))
        self._rate_axis_x.setRange(0, max(max_t, 1.0))
        self._rate_axis_y.setRange(0, max(max_rate * 1.2, 1.0))

    def _update_indices(self, result: ReductionResult) -> None:
        self.tile_final.set_value(f"{result.final_degree_pct:.2f}")
        self.tile_t40.set_value(
            "--" if result.time_to_40_min is None else f"{result.time_to_40_min:.2f}"
        )
        self.tile_t60.set_value(
            "--" if result.time_to_60_min is None else f"{result.time_to_60_min:.2f}"
        )
        self.tile_rate40.set_value(
            "--" if result.rate_at_40_pct is None else f"{result.rate_at_40_pct:.3f}"
        )
