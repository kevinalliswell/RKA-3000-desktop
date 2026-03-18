from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rka_desktop.core.config import Settings
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.db.database import DatabaseManager
from rka_desktop.models.entities import DeviceSnapshot, Measurement
from rka_desktop.services.acquisition_service import AcquisitionWorker, alarm_text
from rka_desktop.services.experiment_engine import ExperimentEngine, ExperimentState
from rka_desktop.services.export_service import ExportService
from rka_desktop.services.recipe_runtime_service import build_recipe_runtime
from rka_desktop.ui.alarm_page import AlarmPage
from rka_desktop.ui.monitor_page import MonitorPage
from rka_desktop.ui.recipe_page import RecipePage
from rka_desktop.ui.settings_page import SettingsPage

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, db: DatabaseManager, client: ModbusRtuClient) -> None:
        super().__init__()
        self.settings = settings
        self.db = db
        self.client = client
        self.export_service = ExportService(db)

        self.worker: AcquisitionWorker | None = None
        self.engine: ExperimentEngine | None = None
        self.experiment_id: int | None = None
        self._alarm_active_word = 0

        self.setWindowTitle(f"{settings.app_name} - v1.1")
        self.resize(1380, 840)

        self._build_ui()
        self._bind_events()
        self._refresh_recipe_combo()
        self.recipe_page.add_default_row()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        toolbar = QHBoxLayout()
        self.btn_connect = QPushButton("连接设备")
        self.recipe_combo = QComboBox()
        self.recipe_combo.setMinimumWidth(280)
        self.btn_refresh_recipe = QPushButton("刷新配方")
        self.btn_start = QPushButton("开始实验")
        self.btn_pause = QPushButton("暂停实验")
        self.btn_resume = QPushButton("恢复实验")
        self.btn_stop = QPushButton("停止实验")
        self.btn_export_csv = QPushButton("导出CSV")
        self.btn_export_excel = QPushButton("导出Excel")

        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_stop.setEnabled(False)

        toolbar.addWidget(self.btn_connect)
        toolbar.addWidget(QLabel("实验配方"))
        toolbar.addWidget(self.recipe_combo)
        toolbar.addWidget(self.btn_refresh_recipe)
        toolbar.addWidget(self.btn_start)
        toolbar.addWidget(self.btn_pause)
        toolbar.addWidget(self.btn_resume)
        toolbar.addWidget(self.btn_stop)
        toolbar.addWidget(self.btn_export_csv)
        toolbar.addWidget(self.btn_export_excel)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.tabs = QTabWidget()
        self.recipe_page = RecipePage()
        self.monitor_page = MonitorPage()
        self.alarm_page = AlarmPage()
        self.settings_page = SettingsPage(self.settings)

        self.tabs.addTab(self.recipe_page, "配方")
        self.tabs.addTab(self.monitor_page, "监控")
        self.tabs.addTab(self.alarm_page, "报警")
        self.tabs.addTab(self.settings_page, "设置")
        layout.addWidget(self.tabs)

    def _bind_events(self) -> None:
        self.btn_connect.clicked.connect(self.connect_device)
        self.btn_refresh_recipe.clicked.connect(self._refresh_recipe_combo)
        self.recipe_combo.currentIndexChanged.connect(self._on_recipe_selected)
        self.btn_start.clicked.connect(self.start_experiment)
        self.btn_pause.clicked.connect(self.pause_experiment)
        self.btn_resume.clicked.connect(self.resume_experiment)
        self.btn_stop.clicked.connect(self.stop_experiment)
        self.btn_export_csv.clicked.connect(self.export_csv)
        self.btn_export_excel.clicked.connect(self.export_excel)

        self.recipe_page.btn_recipe_add.clicked.connect(self.recipe_page.add_default_row)
        self.recipe_page.btn_recipe_remove.clicked.connect(self.recipe_page.remove_current_row)
        self.recipe_page.btn_recipe_save.clicked.connect(self._save_new_recipe)
        self.recipe_page.btn_recipe_update.clicked.connect(self._update_current_recipe)

        self.alarm_page.btn_ack_alarm.clicked.connect(self.acknowledge_alarm)

    def connect_device(self) -> None:
        if self.client.connect():
            self._append_log("设备连接成功")
            self.db.log_action("operator", "DEVICE_CONNECT", self.settings.serial_port)
            self.monitor_page.show_connected()
            return

        QMessageBox.critical(self, "连接失败", "串口或Modbus连接失败，请检查配置")
        self._append_log("设备连接失败")

    def start_experiment(self) -> None:
        if self.worker is not None:
            return

        recipe_id = self.recipe_combo.currentData()
        if recipe_id in (None, 0):
            QMessageBox.warning(self, "缺少配方", "请先选择已保存的配方")
            return

        if QMessageBox.question(self, "确认启动", "确定按当前配方开始实验吗？") != QMessageBox.StandardButton.Yes:
            return

        if not self.client.connect():
            QMessageBox.warning(self, "无法启动", "请先连接设备")
            return

        recipe = self.db.get_recipe(int(recipe_id))
        recipe_steps = self.db.get_recipe_steps(int(recipe_id))
        if not recipe_steps:
            QMessageBox.warning(self, "缺少步骤", "当前配方没有可执行步骤")
            return
        recipe_name = recipe["name"] if recipe else f"配方{recipe_id}"
        self.experiment_id = self.db.create_experiment(name=f"实验-{recipe_name}", recipe_id=int(recipe_id))
        self.engine = ExperimentEngine(build_recipe_runtime(recipe_steps))
        start_update = self.engine.start()

        self._alarm_active_word = 0
        self.monitor_page.reset_runtime()
        self.monitor_page.update_execution_state(start_update.status_text, start_update.active_setpoints_text)
        self.alarm_page.set_current_alarm("当前报警: 无")
        self.alarm_page.set_pending_alarms([])

        self.worker = AcquisitionWorker(
            client=self.client,
            experiment_id=self.experiment_id,
            poll_interval_ms=self.settings.poll_interval_ms,
        )
        self.worker.snapshot_received.connect(self._on_snapshot)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.db.log_action("operator", "EXPERIMENT_START", f"id={self.experiment_id},recipe_id={recipe_id}")
        self._append_log(f"实验开始，ID={self.experiment_id}，配方={recipe_name}")
        self.tabs.setCurrentWidget(self.monitor_page)

    def pause_experiment(self) -> None:
        if self.worker is None or self.engine is None or self.experiment_id is None:
            return

        update = self.engine.pause()
        self.db.set_experiment_status(self.experiment_id, ExperimentState.PAUSED.value)
        self.db.log_action("operator", "EXPERIMENT_PAUSE", f"id={self.experiment_id}")
        self.monitor_page.update_execution_state(update.status_text, update.active_setpoints_text)
        self._append_log(update.status_text)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(True)

    def resume_experiment(self) -> None:
        if self.worker is None or self.engine is None or self.experiment_id is None:
            return

        update = self.engine.resume()
        self.db.set_experiment_status(self.experiment_id, ExperimentState.RUNNING.value)
        self.db.log_action("operator", "EXPERIMENT_RESUME", f"id={self.experiment_id}")
        self.monitor_page.update_execution_state(update.status_text, update.active_setpoints_text)
        self._append_log(update.status_text)
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)

    def stop_experiment(self) -> None:
        if self.worker is None:
            return

        if QMessageBox.question(self, "确认停止", "确定停止当前实验吗？") != QMessageBox.StandardButton.Yes:
            return

        self._finalize_experiment_stop()

    def _finalize_experiment_stop(self) -> None:
        if self.engine is not None:
            update = self.engine.stop()
            self.monitor_page.update_execution_state(update.status_text, update.active_setpoints_text)
            self.engine = None

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
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.alarm_page.btn_ack_alarm.setEnabled(False)

    def acknowledge_alarm(self) -> None:
        if self.experiment_id is None:
            QMessageBox.information(self, "提示", "当前无运行中的实验")
            return

        if QMessageBox.question(self, "确认报警", "确定将当前待处理报警标记为已确认吗？") != QMessageBox.StandardButton.Yes:
            return

        ok = self.db.acknowledge_latest_alarm(self.experiment_id, actor="operator")
        if ok:
            self._append_log("报警已确认")
            self.db.log_action("operator", "ALARM_ACK", f"experiment_id={self.experiment_id}")
        else:
            self._append_log("没有待确认报警")

        self._refresh_alarm_page()

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
            self._finalize_experiment_stop()
            self.client.close()
        finally:
            event.accept()

    def _on_snapshot(self, payload: tuple[DeviceSnapshot, Measurement]) -> None:
        snapshot, measurement = payload
        self.db.insert_measurement(measurement)

        self.monitor_page.update_snapshot(snapshot)
        self.monitor_page.push_measurement(measurement)
        self.monitor_page.update_chart(snapshot)
        if self.engine is not None:
            update = self.engine.on_measurement(measurement)
            self.monitor_page.update_execution_state(update.status_text, update.active_setpoints_text)
            if update.step_changed:
                self._append_log(update.status_text)
            if update.completed:
                self._append_log("执行引擎判定实验完成")
                self._finalize_experiment_stop()
                return
        self._handle_alarm(snapshot)

    def _on_error(self, message: str) -> None:
        self._append_log(f"采集异常: {message}")

    def _handle_alarm(self, snapshot: DeviceSnapshot) -> None:
        alarm_msg = alarm_text(snapshot)
        self.alarm_page.set_current_alarm(f"当前报警: {alarm_msg}")

        if snapshot.alarm_word != 0:
            self.monitor_page.update_alarm_text(f"状态: {alarm_msg}", "color: #b71c1c; font-weight: bold;")
            self.alarm_page.btn_ack_alarm.setEnabled(True)
            if snapshot.alarm_word != self._alarm_active_word:
                self._alarm_active_word = snapshot.alarm_word
                if self.experiment_id is not None:
                    code = f"ALM-{snapshot.alarm_word:04X}"
                    message = f"报警触发，报警字={snapshot.alarm_word}"
                    self.db.create_alarm(self.experiment_id, code=code, level="HIGH", message=message)
                    self.db.log_action("system", "ALARM_RAISED", f"experiment_id={self.experiment_id},{code}")
                self._append_log(f"报警触发：报警字={snapshot.alarm_word}")
            self._refresh_alarm_page()
            return

        self.monitor_page.update_alarm_text("状态: 正常", "color: #1b5e20;")
        if self._alarm_active_word != 0:
            self._append_log("报警解除")
        self._alarm_active_word = 0
        self._refresh_alarm_page()

    def _refresh_alarm_page(self) -> None:
        if self.experiment_id is None:
            self.alarm_page.set_pending_alarms([])
            self.alarm_page.btn_ack_alarm.setEnabled(False)
            return

        unacked = self.db.list_unacknowledged_alarms(self.experiment_id)
        self.alarm_page.set_pending_alarms(unacked)
        self.alarm_page.btn_ack_alarm.setEnabled(bool(unacked))

    def _refresh_recipe_combo(self) -> None:
        previous_id = self.recipe_combo.currentData()
        self.recipe_combo.blockSignals(True)
        self.recipe_combo.clear()
        self.recipe_combo.addItem("请选择配方", 0)

        for recipe in self.db.list_recipes():
            self.recipe_combo.addItem(f"#{recipe['id']} {recipe['name']}", int(recipe["id"]))

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
        self.recipe_page.load_recipe(recipe["name"] if recipe else "", steps)

    def _save_new_recipe(self) -> None:
        name = self.recipe_page.recipe_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "参数错误", "请填写配方名称")
            return

        steps = self._collect_recipe_steps()
        if not steps:
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

        name = self.recipe_page.recipe_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "参数错误", "请填写配方名称")
            return

        steps = self._collect_recipe_steps()
        if not steps:
            return

        self.db.update_recipe(int(recipe_id), name, steps)
        self.db.log_action("operator", "RECIPE_UPDATE", f"recipe_id={recipe_id},name={name}")
        self._append_log(f"配方已更新，ID={recipe_id}")
        self._refresh_recipe_combo()
        idx = self.recipe_combo.findData(recipe_id)
        if idx >= 0:
            self.recipe_combo.setCurrentIndex(idx)

    def _collect_recipe_steps(self) -> list[dict[str, object]]:
        try:
            steps = self.recipe_page.collect_steps()
        except ValueError as exc:
            QMessageBox.warning(self, "参数错误", f"存在非法数字: {exc}")
            return []

        if not steps:
            QMessageBox.warning(self, "参数错误", "请至少配置一个步骤")
            return []
        return steps

    def _append_log(self, text: str) -> None:
        logger.info(text)
        self.monitor_page.append_log(text)
