from __future__ import annotations

import logging
from collections import deque
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

try:
    from PySide6.QtCharts import QChart, QChartView, QLineSeries, QValueAxis

    CHARTS_AVAILABLE = True
except Exception:  # pragma: no cover
    CHARTS_AVAILABLE = False

from rka_desktop.core.config import Settings
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.db.database import DatabaseManager
from rka_desktop.models.entities import DeviceSnapshot, Measurement
from rka_desktop.services.acquisition_service import AcquisitionWorker, alarm_text
from rka_desktop.services.export_service import ExportService

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, db: DatabaseManager, client: ModbusRtuClient) -> None:
        super().__init__()
        self.settings = settings
        self.db = db
        self.client = client
        self.export_service = ExportService(db)

        self.worker: AcquisitionWorker | None = None
        self.experiment_id: int | None = None
        self._recent = deque(maxlen=50)
        self._sample_index = 0
        self._alarm_active_word = 0

        self.setWindowTitle(f"{settings.app_name} - v1.1")
        self.resize(1380, 840)

        self._build_ui()
        self._refresh_recipe_combo()
        self._add_recipe_row()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)

        layout = QVBoxLayout(central)

        top = QHBoxLayout()
        self.btn_connect = QPushButton("连接设备")
        self.recipe_combo = QComboBox()
        self.recipe_combo.setMinimumWidth(280)
        self.btn_refresh_recipe = QPushButton("刷新配方")
        self.btn_start = QPushButton("开始实验")
        self.btn_stop = QPushButton("停止实验")
        self.btn_ack_alarm = QPushButton("确认报警")
        self.btn_export_csv = QPushButton("导出CSV")
        self.btn_export_excel = QPushButton("导出Excel")

        self.btn_stop.setEnabled(False)
        self.btn_ack_alarm.setEnabled(False)

        self.btn_connect.clicked.connect(self.connect_device)
        self.btn_refresh_recipe.clicked.connect(self._refresh_recipe_combo)
        self.recipe_combo.currentIndexChanged.connect(self._on_recipe_selected)
        self.btn_start.clicked.connect(self.start_experiment)
        self.btn_stop.clicked.connect(self.stop_experiment)
        self.btn_ack_alarm.clicked.connect(self.acknowledge_alarm)
        self.btn_export_csv.clicked.connect(self.export_csv)
        self.btn_export_excel.clicked.connect(self.export_excel)

        top.addWidget(self.btn_connect)
        top.addWidget(QLabel("实验配方"))
        top.addWidget(self.recipe_combo)
        top.addWidget(self.btn_refresh_recipe)
        top.addWidget(self.btn_start)
        top.addWidget(self.btn_stop)
        top.addWidget(self.btn_ack_alarm)
        top.addWidget(self.btn_export_csv)
        top.addWidget(self.btn_export_excel)
        top.addStretch()
        layout.addLayout(top)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self._build_recipe_panel())
        splitter.addWidget(self._build_monitor_panel())
        splitter.setSizes([430, 950])
        layout.addWidget(splitter)

    def _build_recipe_panel(self) -> QWidget:
        panel = QGroupBox("配方编辑器")
        layout = QVBoxLayout(panel)

        form = QHBoxLayout()
        self.recipe_name_input = QLineEdit()
        self.recipe_name_input.setPlaceholderText("输入配方名称，例如：高温还原-标准流程")

        self.btn_recipe_add = QPushButton("新增步骤")
        self.btn_recipe_remove = QPushButton("删除步骤")
        self.btn_recipe_save = QPushButton("保存新配方")
        self.btn_recipe_update = QPushButton("更新当前配方")

        self.btn_recipe_add.clicked.connect(self._add_recipe_row)
        self.btn_recipe_remove.clicked.connect(self._remove_recipe_row)
        self.btn_recipe_save.clicked.connect(self._save_new_recipe)
        self.btn_recipe_update.clicked.connect(self._update_current_recipe)

        form.addWidget(self.recipe_name_input)
        form.addWidget(self.btn_recipe_add)
        form.addWidget(self.btn_recipe_remove)
        layout.addLayout(form)

        self.recipe_table = QTableWidget(0, 8)
        self.recipe_table.setHorizontalHeaderLabels(
            ["步骤", "目标温度℃", "升温速率℃/min", "保温秒", "N2", "H2", "CO", "备注"]
        )
        self.recipe_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.recipe_table)

        actions = QHBoxLayout()
        actions.addWidget(self.btn_recipe_save)
        actions.addWidget(self.btn_recipe_update)
        actions.addStretch()
        layout.addLayout(actions)

        return panel

    def _build_monitor_panel(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)

        metrics = QGridLayout()
        self.lbl_temp = QLabel("温度: -- ℃")
        self.lbl_weight = QLabel("重量: -- g")
        self.lbl_pressure = QLabel("压力: -- MPa")
        self.lbl_flow = QLabel("流量 N2/H2/CO: --/--/-- L/min")
        self.lbl_alarm = QLabel("状态: 未连接")

        metrics.addWidget(self.lbl_temp, 0, 0)
        metrics.addWidget(self.lbl_weight, 0, 1)
        metrics.addWidget(self.lbl_pressure, 1, 0)
        metrics.addWidget(self.lbl_flow, 1, 1)
        metrics.addWidget(self.lbl_alarm, 2, 0, 1, 2)
        layout.addLayout(metrics)

        if CHARTS_AVAILABLE:
            self.temp_series = QLineSeries()
            self.temp_series.setName("温度")
            self.weight_series = QLineSeries()
            self.weight_series.setName("重量")

            self.chart = QChart()
            self.chart.addSeries(self.temp_series)
            self.chart.addSeries(self.weight_series)
            self.chart.legend().setVisible(True)
            self.chart.setTitle("实时趋势（温度/重量）")

            self.axis_x = QValueAxis()
            self.axis_x.setTitleText("采样点")
            self.axis_x.setRange(0, 120)

            self.axis_y = QValueAxis()
            self.axis_y.setTitleText("数值")
            self.axis_y.setRange(0, 1200)

            self.chart.addAxis(self.axis_x, Qt.AlignmentFlag.AlignBottom)
            self.chart.addAxis(self.axis_y, Qt.AlignmentFlag.AlignLeft)
            self.temp_series.attachAxis(self.axis_x)
            self.temp_series.attachAxis(self.axis_y)
            self.weight_series.attachAxis(self.axis_x)
            self.weight_series.attachAxis(self.axis_y)

            self.chart_view = QChartView(self.chart)
            layout.addWidget(self.chart_view)
        else:
            self.temp_series = None
            self.weight_series = None
            self.axis_x = None
            self.axis_y = None
            placeholder = QLabel("当前运行环境缺少 QtCharts，实时曲线不可用。")
            layout.addWidget(placeholder)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["时间", "温度℃", "重量g", "压力MPa", "N2", "H2", "CO"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        layout.addWidget(self.log_view)

        return panel

    def connect_device(self) -> None:
        if self.client.connect():
            self._append_log("设备连接成功")
            self.db.log_action("operator", "DEVICE_CONNECT", self.settings.serial_port)
            self.lbl_alarm.setText("状态: 已连接")
            self.lbl_alarm.setStyleSheet("")
        else:
            QMessageBox.critical(self, "连接失败", "串口或Modbus连接失败，请检查配置")
            self._append_log("设备连接失败")

    def start_experiment(self) -> None:
        if self.worker is not None:
            return

        recipe_id = self.recipe_combo.currentData()
        if recipe_id in (None, 0):
            QMessageBox.warning(self, "缺少配方", "请先选择已保存的配方")
            return

        if not self.client.connect():
            QMessageBox.warning(self, "无法启动", "请先连接设备")
            return

        recipe = self.db.get_recipe(int(recipe_id))
        recipe_name = recipe["name"] if recipe else f"配方{recipe_id}"
        self.experiment_id = self.db.create_experiment(name=f"实验-{recipe_name}", recipe_id=int(recipe_id))

        self._recent.clear()
        self._sample_index = 0
        self._alarm_active_word = 0

        if CHARTS_AVAILABLE and self.temp_series is not None and self.weight_series is not None:
            self.temp_series.clear()
            self.weight_series.clear()
            if self.axis_x is not None:
                self.axis_x.setRange(0, 120)
            if self.axis_y is not None:
                self.axis_y.setRange(0, 1200)

        self.worker = AcquisitionWorker(
            client=self.client,
            experiment_id=self.experiment_id,
            poll_interval_ms=self.settings.poll_interval_ms,
        )
        self.worker.snapshot_received.connect(self._on_snapshot)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.db.log_action("operator", "EXPERIMENT_START", f"id={self.experiment_id},recipe_id={recipe_id}")
        self._append_log(f"实验开始，ID={self.experiment_id}，配方={recipe_name}")

    def stop_experiment(self) -> None:
        if self.worker is None:
            return

        self.worker.stop()
        self.worker = None

        if self.experiment_id is not None:
            exp_id = self.experiment_id
            self.db.finish_experiment(exp_id)
            self.db.log_action("operator", "EXPERIMENT_STOP", f"id={exp_id}")
            self._append_log(f"实验结束，ID={exp_id}")
            self.experiment_id = None

        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_ack_alarm.setEnabled(False)

    def acknowledge_alarm(self) -> None:
        if self.experiment_id is None:
            QMessageBox.information(self, "提示", "当前无运行中的实验")
            return

        ok = self.db.acknowledge_latest_alarm(self.experiment_id, actor="operator")
        if ok:
            self._append_log("报警已确认")
            self.db.log_action("operator", "ALARM_ACK", f"experiment_id={self.experiment_id}")
        else:
            self._append_log("没有待确认报警")

        unacked = self.db.list_unacknowledged_alarms(self.experiment_id)
        self.btn_ack_alarm.setEnabled(bool(unacked))

    def export_csv(self) -> None:
        self._export_data("csv")

    def export_excel(self) -> None:
        self._export_data("excel")

    def _export_data(self, fmt: str) -> None:
        exp_id = self.experiment_id or self.db.get_latest_experiment_id()
        if exp_id is None:
            QMessageBox.information(self, "提示", "没有可导出的实验数据")
            return

        default_dir = Path("exports")
        default_dir.mkdir(parents=True, exist_ok=True)

        if fmt == "csv":
            file_name = str(default_dir / f"experiment_{exp_id}.csv")
            path, _ = QFileDialog.getSaveFileName(self, "导出CSV", file_name, "CSV Files (*.csv)")
            if not path:
                return
            try:
                out = self.export_service.export_measurements_csv(exp_id, Path(path))
                self._append_log(f"导出CSV成功: {out}")
                self.db.log_action("operator", "EXPORT_CSV", f"experiment_id={exp_id},path={out}")
            except Exception as exc:
                QMessageBox.warning(self, "导出失败", str(exc))
                self._append_log(f"导出CSV失败: {exc}")
            return

        file_name = str(default_dir / f"experiment_{exp_id}.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, "导出Excel", file_name, "Excel Files (*.xlsx)")
        if not path:
            return
        try:
            out = self.export_service.export_measurements_excel(exp_id, Path(path))
            self._append_log(f"导出Excel成功: {out}")
            self.db.log_action("operator", "EXPORT_EXCEL", f"experiment_id={exp_id},path={out}")
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            self._append_log(f"导出Excel失败: {exc}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            self.stop_experiment()
            self.client.close()
        finally:
            event.accept()

    def _on_snapshot(self, payload: tuple[DeviceSnapshot, Measurement]) -> None:
        snapshot, measurement = payload
        self.db.insert_measurement(measurement)

        self.lbl_temp.setText(f"温度: {snapshot.temperature_c:.2f} ℃")
        self.lbl_weight.setText(f"重量: {snapshot.weight_g:.3f} g")
        self.lbl_pressure.setText(f"压力: {snapshot.pressure_mpa:.4f} MPa")
        self.lbl_flow.setText(
            f"流量 N2/H2/CO: {snapshot.n2_lpm:.2f}/{snapshot.h2_lpm:.2f}/{snapshot.co_lpm:.2f} L/min"
        )

        self._recent.appendleft(measurement)
        self._refresh_table()
        self._update_chart(snapshot)
        self._handle_alarm(snapshot)

    def _on_error(self, message: str) -> None:
        self._append_log(f"采集异常: {message}")

    def _update_chart(self, snapshot: DeviceSnapshot) -> None:
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

    def _handle_alarm(self, snapshot: DeviceSnapshot) -> None:
        alarm_msg = alarm_text(snapshot)
        self.lbl_alarm.setText(f"状态: {alarm_msg}")

        if snapshot.alarm_word != 0:
            self.lbl_alarm.setStyleSheet("color: #b71c1c; font-weight: bold;")
            self.btn_ack_alarm.setEnabled(True)
            if snapshot.alarm_word != self._alarm_active_word:
                self._alarm_active_word = snapshot.alarm_word
                if self.experiment_id is not None:
                    code = f"ALM-{snapshot.alarm_word:04X}"
                    level = "HIGH"
                    message = f"报警触发，报警字={snapshot.alarm_word}"
                    self.db.create_alarm(self.experiment_id, code=code, level=level, message=message)
                    self.db.log_action("system", "ALARM_RAISED", f"experiment_id={self.experiment_id},{code}")
                self._append_log(f"报警触发：报警字={snapshot.alarm_word}")
            return

        self.lbl_alarm.setStyleSheet("color: #1b5e20;")
        if self._alarm_active_word != 0:
            self._append_log("报警解除")
        self._alarm_active_word = 0

        if self.experiment_id is not None:
            unacked = self.db.list_unacknowledged_alarms(self.experiment_id)
            self.btn_ack_alarm.setEnabled(bool(unacked))
        else:
            self.btn_ack_alarm.setEnabled(False)

    def _refresh_table(self) -> None:
        self.table.setRowCount(len(self._recent))
        for row, m in enumerate(self._recent):
            self.table.setItem(row, 0, QTableWidgetItem(m.sampled_at.strftime("%H:%M:%S")))
            self.table.setItem(row, 1, QTableWidgetItem(f"{m.temperature_c:.2f}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{m.weight_g:.3f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{m.pressure_mpa:.4f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{m.n2_lpm:.2f}"))
            self.table.setItem(row, 5, QTableWidgetItem(f"{m.h2_lpm:.2f}"))
            self.table.setItem(row, 6, QTableWidgetItem(f"{m.co_lpm:.2f}"))

    def _refresh_recipe_combo(self) -> None:
        previous_id = self.recipe_combo.currentData()
        self.recipe_combo.blockSignals(True)
        self.recipe_combo.clear()
        self.recipe_combo.addItem("请选择配方", 0)

        recipes = self.db.list_recipes()
        for r in recipes:
            self.recipe_combo.addItem(f"#{r['id']} {r['name']}", int(r["id"]))

        if previous_id:
            index = self.recipe_combo.findData(previous_id)
            if index >= 0:
                self.recipe_combo.setCurrentIndex(index)
        self.recipe_combo.blockSignals(False)

    def _on_recipe_selected(self, _index: int) -> None:
        recipe_id = self.recipe_combo.currentData()
        if recipe_id in (None, 0):
            return

        recipe = self.db.get_recipe(int(recipe_id))
        steps = self.db.get_recipe_steps(int(recipe_id))

        self.recipe_name_input.setText(recipe["name"] if recipe else "")
        self.recipe_table.setRowCount(0)
        for step in steps:
            row = self.recipe_table.rowCount()
            self.recipe_table.insertRow(row)
            self._set_recipe_cell(row, 0, str(step["step_no"]))
            self._set_recipe_cell(row, 1, str(step["target_temp_c"]))
            self._set_recipe_cell(row, 2, str(step["ramp_rate_cpm"]))
            self._set_recipe_cell(row, 3, str(step["hold_seconds"]))
            self._set_recipe_cell(row, 4, str(step["n2_lpm"]))
            self._set_recipe_cell(row, 5, str(step["h2_lpm"]))
            self._set_recipe_cell(row, 6, str(step["co_lpm"]))
            self._set_recipe_cell(row, 7, str(step.get("notes", "")))

    def _add_recipe_row(self) -> None:
        row = self.recipe_table.rowCount()
        self.recipe_table.insertRow(row)
        self._set_recipe_cell(row, 0, str(row + 1))
        self._set_recipe_cell(row, 1, "900")
        self._set_recipe_cell(row, 2, "10")
        self._set_recipe_cell(row, 3, "600")
        self._set_recipe_cell(row, 4, "8.0")
        self._set_recipe_cell(row, 5, "1.0")
        self._set_recipe_cell(row, 6, "0.8")
        self._set_recipe_cell(row, 7, "")

    def _remove_recipe_row(self) -> None:
        row = self.recipe_table.currentRow()
        if row < 0:
            row = self.recipe_table.rowCount() - 1
        if row >= 0:
            self.recipe_table.removeRow(row)

    def _save_new_recipe(self) -> None:
        name = self.recipe_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "参数错误", "请填写配方名称")
            return

        steps = self._collect_recipe_steps()
        if not steps:
            QMessageBox.warning(self, "参数错误", "请至少配置一个步骤")
            return

        recipe_id = self.db.create_recipe(name, steps)
        self.db.log_action("operator", "RECIPE_CREATE", f"recipe_id={recipe_id},name={name}")
        self._append_log(f"配方已保存，ID={recipe_id}")
        self._refresh_recipe_combo()
        idx = self.recipe_combo.findData(recipe_id)
        if idx >= 0:
            self.recipe_combo.setCurrentIndex(idx)

    def _update_current_recipe(self) -> None:
        recipe_id = self.recipe_combo.currentData()
        if recipe_id in (None, 0):
            QMessageBox.warning(self, "参数错误", "请先选择一个已存在的配方")
            return

        name = self.recipe_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "参数错误", "请填写配方名称")
            return

        steps = self._collect_recipe_steps()
        if not steps:
            QMessageBox.warning(self, "参数错误", "请至少配置一个步骤")
            return

        self.db.update_recipe(int(recipe_id), name, steps)
        self.db.log_action("operator", "RECIPE_UPDATE", f"recipe_id={recipe_id},name={name}")
        self._append_log(f"配方已更新，ID={recipe_id}")
        self._refresh_recipe_combo()
        idx = self.recipe_combo.findData(recipe_id)
        if idx >= 0:
            self.recipe_combo.setCurrentIndex(idx)

    def _collect_recipe_steps(self) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for row in range(self.recipe_table.rowCount()):
            try:
                steps.append(
                    {
                        "step_no": int(self._cell_text(row, 0, str(row + 1))),
                        "target_temp_c": float(self._cell_text(row, 1, "0")),
                        "ramp_rate_cpm": float(self._cell_text(row, 2, "0")),
                        "hold_seconds": int(float(self._cell_text(row, 3, "0"))),
                        "n2_lpm": float(self._cell_text(row, 4, "0")),
                        "h2_lpm": float(self._cell_text(row, 5, "0")),
                        "co_lpm": float(self._cell_text(row, 6, "0")),
                        "notes": self._cell_text(row, 7, ""),
                    }
                )
            except ValueError as exc:
                QMessageBox.warning(self, "参数错误", f"第 {row + 1} 行存在非法数字: {exc}")
                return []
        return steps

    def _cell_text(self, row: int, col: int, default: str) -> str:
        item = self.recipe_table.item(row, col)
        if item is None:
            return default
        text = item.text().strip()
        return text if text else default

    def _set_recipe_cell(self, row: int, col: int, text: str) -> None:
        self.recipe_table.setItem(row, col, QTableWidgetItem(text))

    def _append_log(self, text: str) -> None:
        logger.info(text)
        self.log_view.append(text)
