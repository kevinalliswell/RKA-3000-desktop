from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rka_desktop.models.entities import DeviceSnapshot, Measurement
from rka_desktop.ui.components import Card, MetricTile
from rka_desktop.ui.theme import ACCENT, accent_pen, style_axis, style_chart, style_chart_view

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis

    CHARTS_AVAILABLE = True
except Exception:  # pragma: no cover
    CHARTS_AVAILABLE = False


class MonitorPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._sample_index = 0
        self._recent: deque[Measurement] = deque(maxlen=50)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # --- real-time data as modular KPI tiles ---
        data_card = Card("实时数据")
        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self.tile_temp = MetricTile("温度", "--", "℃", icon="mdi.thermometer", accent="#EF4444")
        self.tile_weight = MetricTile("重量", "--", "g", icon="mdi.scale", accent="#F59E0B")
        self.tile_pressure = MetricTile("压力", "--", "MPa", icon="mdi.gauge")
        self.tile_n2 = MetricTile("N₂", "--", "L/min", icon="mdi.gas-cylinder", accent="#10B981")
        self.tile_h2 = MetricTile("H₂", "--", "L/min", icon="mdi.gas-cylinder", accent="#3B82F6")
        self.tile_co = MetricTile("CO", "--", "L/min", icon="mdi.gas-cylinder", accent="#8B5CF6")
        for tile in (self.tile_temp, self.tile_weight, self.tile_pressure,
                     self.tile_n2, self.tile_h2, self.tile_co):
            tiles.addWidget(tile)
        data_card.add_layout(tiles)
        layout.addWidget(data_card)

        # --- run status block (text status rows) ---
        status_card = Card("运行状态")
        status_grid = QGridLayout()
        status_grid.setHorizontalSpacing(24)
        status_grid.setVerticalSpacing(6)
        self.lbl_alarm = QLabel("状态: 未连接")
        self.lbl_interlock = QLabel("联锁: --")
        self.lbl_run_control = QLabel("控制字: --")
        self.lbl_control_feedback = QLabel("控制反馈: --")
        self.lbl_estop = QLabel("急停: --")
        self.lbl_execution = QLabel("执行状态: 未启动")
        self.lbl_setpoints = QLabel("步骤设定: --")
        status_grid.addWidget(self.lbl_alarm, 0, 0)
        status_grid.addWidget(self.lbl_estop, 0, 1)
        status_grid.addWidget(self.lbl_interlock, 1, 0, 1, 2)
        status_grid.addWidget(self.lbl_run_control, 2, 0)
        status_grid.addWidget(self.lbl_control_feedback, 2, 1)
        status_grid.addWidget(self.lbl_execution, 3, 0, 1, 2)
        status_grid.addWidget(self.lbl_setpoints, 4, 0, 1, 2)
        status_card.add_layout(status_grid)
        layout.addWidget(status_card)

        if CHARTS_AVAILABLE:
            self.temp_series = QLineSeries()
            self.temp_series.setName("温度")
            self.temp_series.setPen(accent_pen(ACCENT, 2))
            self.weight_series = QLineSeries()
            self.weight_series.setName("重量")
            self.weight_series.setPen(accent_pen("#F59E0B", 2))

            chart = QChart()
            chart.addSeries(self.temp_series)
            chart.addSeries(self.weight_series)
            chart.setTitle("实时趋势（温度/重量）")

            self.axis_x = QValueAxis()
            self.axis_x.setTitleText("采样点")
            self.axis_x.setRange(0, 120)

            self.axis_y = QValueAxis()
            self.axis_y.setTitleText("数值")
            self.axis_y.setRange(0, 1200)

            chart.addAxis(self.axis_x, Qt.AlignmentFlag.AlignBottom)
            chart.addAxis(self.axis_y, Qt.AlignmentFlag.AlignLeft)
            self.temp_series.attachAxis(self.axis_x)
            self.temp_series.attachAxis(self.axis_y)
            self.weight_series.attachAxis(self.axis_x)
            self.weight_series.attachAxis(self.axis_y)

            style_chart(chart)
            style_axis(self.axis_x, label_format="%.0f", ticks=7)
            style_axis(self.axis_y, label_format="%.0f", ticks=7)
            chart.legend().setVisible(True)
            chart.legend().setAlignment(Qt.AlignmentFlag.AlignBottom)

            chart_view = QChartView(chart)
            chart_view.setMinimumHeight(260)
            style_chart_view(chart_view)
            layout.addWidget(chart_view)
        else:
            self.temp_series = None
            self.weight_series = None
            self.axis_x = None
            self.axis_y = None
            layout.addWidget(QLabel("当前运行环境缺少 QtCharts，实时曲线不可用。"))

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["时间", "温度℃", "重量g", "压力MPa", "N2", "H2", "CO"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

    def reset_runtime(self) -> None:
        self._sample_index = 0
        self._recent.clear()
        self.table.setRowCount(0)
        if CHARTS_AVAILABLE and self.temp_series is not None and self.weight_series is not None:
            self.temp_series.clear()
            self.weight_series.clear()
            if self.axis_x is not None:
                self.axis_x.setRange(0, 120)
            if self.axis_y is not None:
                self.axis_y.setRange(0, 1200)

    def show_connected(self) -> None:
        self.lbl_alarm.setText("状态: 已连接")
        self.lbl_alarm.setStyleSheet("")

    def update_execution_state(self, text: str, setpoints: str) -> None:
        self.lbl_execution.setText(f"执行状态: {text}")
        self.lbl_setpoints.setText(f"步骤设定: {setpoints}")

    def update_snapshot(self, snapshot: DeviceSnapshot) -> None:
        self.tile_temp.set_value(f"{snapshot.temperature_c:.1f}")
        self.tile_weight.set_value(f"{snapshot.weight_g:.3f}")
        self.tile_pressure.set_value(f"{snapshot.pressure_mpa:.4f}")
        self.tile_n2.set_value(f"{snapshot.n2_lpm:.2f}")
        self.tile_h2.set_value(f"{snapshot.h2_lpm:.2f}")
        self.tile_co.set_value(f"{snapshot.co_lpm:.2f}")

    def update_alarm_text(self, text: str, style: str) -> None:
        self.lbl_alarm.setText(text)
        self.lbl_alarm.setStyleSheet(style)

    def update_interlock_text(self, text: str, style: str) -> None:
        self.lbl_interlock.setText(text)
        self.lbl_interlock.setStyleSheet(style)

    def update_control_state(self, run_control_word: int, estop_status: int, feedback_text: str, feedback_style: str) -> None:
        self.lbl_run_control.setText(f"控制字: 0x{run_control_word:04X}")
        self.lbl_control_feedback.setText(feedback_text)
        self.lbl_control_feedback.setStyleSheet(feedback_style)
        self.lbl_estop.setText("急停: 触发" if estop_status else "急停: 正常")
        self.lbl_estop.setStyleSheet("color: #b71c1c; font-weight: bold;" if estop_status else "color: #1b5e20;")

    def push_measurement(self, measurement: Measurement) -> None:
        self._recent.appendleft(measurement)
        self._refresh_table()

    def update_chart(self, snapshot: DeviceSnapshot) -> None:
        if not CHARTS_AVAILABLE or self.temp_series is None or self.weight_series is None:
            return

        self._sample_index += 1
        x = float(self._sample_index)
        self.temp_series.append(x, float(snapshot.temperature_c))
        self.weight_series.append(x, float(snapshot.weight_g))

        max_points = 240
        if self.temp_series.count() > max_points:
            self.temp_series.removePoints(0, self.temp_series.count() - max_points)
        if self.weight_series.count() > max_points:
            self.weight_series.removePoints(0, self.weight_series.count() - max_points)

        if self.axis_x is not None:
            self.axis_x.setRange(max(0.0, x - max_points), max(float(max_points), x))

        if self.axis_y is not None:
            current_max = max(snapshot.temperature_c, snapshot.weight_g)
            self.axis_y.setRange(0.0, max(100.0, current_max * 1.2))

    def append_log(self, text: str) -> None:
        self.log_view.append(text)

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self._recent))
        for row, measurement in enumerate(self._recent):
            self.table.setItem(row, 0, QTableWidgetItem(measurement.sampled_at.strftime("%H:%M:%S")))
            self.table.setItem(row, 1, QTableWidgetItem(f"{measurement.temperature_c:.2f}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{measurement.weight_g:.3f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{measurement.pressure_mpa:.4f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{measurement.n2_lpm:.2f}"))
            self.table.setItem(row, 5, QTableWidgetItem(f"{measurement.h2_lpm:.2f}"))
            self.table.setItem(row, 6, QTableWidgetItem(f"{measurement.co_lpm:.2f}"))
