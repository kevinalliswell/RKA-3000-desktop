from __future__ import annotations

from collections import deque

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QGridLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from rka_desktop.models.entities import DeviceSnapshot, Measurement

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

        metrics = QGridLayout()
        self.lbl_temp = QLabel("温度: -- ℃")
        self.lbl_weight = QLabel("重量: -- g")
        self.lbl_pressure = QLabel("压力: -- MPa")
        self.lbl_flow = QLabel("流量 N2/H2/CO: --/--/-- L/min")
        self.lbl_alarm = QLabel("状态: 未连接")
        self.lbl_interlock = QLabel("联锁: --")
        self.lbl_run_control = QLabel("控制字: --")
        self.lbl_estop = QLabel("急停: --")
        self.lbl_execution = QLabel("执行状态: 未启动")
        self.lbl_setpoints = QLabel("步骤设定: --")

        metrics.addWidget(self.lbl_temp, 0, 0)
        metrics.addWidget(self.lbl_weight, 0, 1)
        metrics.addWidget(self.lbl_pressure, 1, 0)
        metrics.addWidget(self.lbl_flow, 1, 1)
        metrics.addWidget(self.lbl_alarm, 2, 0, 1, 2)
        metrics.addWidget(self.lbl_interlock, 3, 0, 1, 2)
        metrics.addWidget(self.lbl_run_control, 4, 0)
        metrics.addWidget(self.lbl_estop, 4, 1)
        metrics.addWidget(self.lbl_execution, 5, 0, 1, 2)
        metrics.addWidget(self.lbl_setpoints, 6, 0, 1, 2)
        layout.addLayout(metrics)

        if CHARTS_AVAILABLE:
            self.temp_series = QLineSeries()
            self.temp_series.setName("温度")
            self.weight_series = QLineSeries()
            self.weight_series.setName("重量")

            chart = QChart()
            chart.addSeries(self.temp_series)
            chart.addSeries(self.weight_series)
            chart.legend().setVisible(True)
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

            layout.addWidget(QChartView(chart))
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
        self.lbl_temp.setText(f"温度: {snapshot.temperature_c:.2f} ℃")
        self.lbl_weight.setText(f"重量: {snapshot.weight_g:.3f} g")
        self.lbl_pressure.setText(f"压力: {snapshot.pressure_mpa:.4f} MPa")
        self.lbl_flow.setText(
            f"流量 N2/H2/CO: {snapshot.n2_lpm:.2f}/{snapshot.h2_lpm:.2f}/{snapshot.co_lpm:.2f} L/min"
        )

    def update_alarm_text(self, text: str, style: str) -> None:
        self.lbl_alarm.setText(text)
        self.lbl_alarm.setStyleSheet(style)

    def update_interlock_text(self, text: str, style: str) -> None:
        self.lbl_interlock.setText(text)
        self.lbl_interlock.setStyleSheet(style)

    def update_control_state(self, run_control_word: int, estop_status: int) -> None:
        self.lbl_run_control.setText(f"控制字: 0x{run_control_word:04X}")
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
