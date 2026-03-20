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
from rka_desktop.controllers.experiment_controller import ControllerTransition, ExperimentController, RuntimeViewState
from rka_desktop.controllers.recipe_controller import RecipeTransition, RecipeViewState, RecipeController
from rka_desktop.db.database import DatabaseManager
from rka_desktop.hardware.device_gateway import DeviceGateway
from rka_desktop.models.entities import DeviceSnapshot, Measurement
from rka_desktop.services.acquisition_service import AcquisitionWorker
from rka_desktop.services.export_service import ExportService
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
        self.gateway = DeviceGateway(client)
        self.controller = ExperimentController(settings=settings, db=db, gateway=self.gateway)
        self.recipe_controller = RecipeController(db)
        self.export_service = ExportService(db)

        self.worker: AcquisitionWorker | None = None

        self.setWindowTitle(f"{settings.app_name} - v1.1")
        self.resize(1380, 840)

        self._build_ui()
        self._bind_events()
        self._refresh_recipe_combo()
        if self.recipe_page.recipe_table.rowCount() == 0:
            self.recipe_page.add_default_row()

    @property
    def engine(self):
        return self.controller.engine

    @engine.setter
    def engine(self, value) -> None:
        self.controller.engine = value

    @property
    def experiment_id(self):
        return self.controller.experiment_id

    @experiment_id.setter
    def experiment_id(self, value) -> None:
        self.controller.experiment_id = value

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
        self.alarm_page.btn_reset_interlock.clicked.connect(self.reset_interlock)

    def connect_device(self) -> None:
        if self.gateway.connect():
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

        if not self.gateway.connect():
            QMessageBox.warning(self, "无法启动", "请先连接设备")
            return

        try:
            transition = self.controller.start_experiment(int(recipe_id))
        except ValueError as exc:
            QMessageBox.warning(self, "缺少步骤", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "无法启动", str(exc))
            return

        if not transition.success or transition.experiment_id is None:
            self._apply_controller_transition(transition)
            QMessageBox.warning(self, "缺少步骤", "当前配方没有可执行步骤")
            return

        self.monitor_page.reset_runtime()
        self._apply_controller_transition(transition)

        self.worker = AcquisitionWorker(
            client=self.gateway,
            db=self.db,
            experiment_id=transition.experiment_id,
            poll_interval_ms=self.settings.poll_interval_ms,
            batch_size=self.settings.acquisition_batch_size,
        )
        self.worker.snapshot_received.connect(self._on_snapshot)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.start()
        self.tabs.setCurrentWidget(self.monitor_page)

    def pause_experiment(self) -> None:
        transition = self.controller.pause_experiment()
        if transition is None:
            return
        self._apply_controller_transition(transition)

    def resume_experiment(self) -> None:
        if self.worker is None or self.engine is None or self.experiment_id is None:
            return
        transition = self.controller.resume_experiment()
        if transition is None:
            return
        self._apply_controller_transition(transition)

    def stop_experiment(self) -> None:
        if self.worker is None:
            return

        if QMessageBox.question(self, "确认停止", "确定停止当前实验吗？") != QMessageBox.StandardButton.Yes:
            return
        transition = self.controller.stop_experiment()
        if transition is None:
            return
        self._apply_controller_transition(transition)

    def acknowledge_alarm(self) -> None:
        if self.experiment_id is None:
            QMessageBox.information(self, "提示", "当前无运行中的实验")
            return

        if QMessageBox.question(self, "确认报警", "确定将当前待处理报警标记为已确认吗？") != QMessageBox.StandardButton.Yes:
            return

        transition = self.controller.acknowledge_alarm()
        self._apply_controller_transition(transition)

    def reset_interlock(self) -> None:
        if QMessageBox.question(self, "确认复位", "确定下发联锁复位命令吗？") != QMessageBox.StandardButton.Yes:
            return

        transition = self.controller.reset_interlock()
        self._apply_controller_transition(transition)

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
            if self.controller.has_active_experiment:
                transition = self.controller.stop_experiment()
                if transition is not None:
                    self._apply_controller_transition(transition)
            elif self.worker is not None:
                self.worker.stop()
                self.worker = None
            self.gateway.close()
        finally:
            event.accept()

    def _on_snapshot(self, payload: tuple[DeviceSnapshot, Measurement]) -> None:
        snapshot, measurement = payload

        self.monitor_page.update_snapshot(snapshot)
        self.monitor_page.push_measurement(measurement)
        self.monitor_page.update_chart(snapshot)
        transition = self.controller.handle_snapshot(snapshot, measurement)
        self._apply_controller_transition(transition)

    def _on_error(self, message: str) -> None:
        transition = self.controller.handle_acquisition_error(message)
        self._apply_controller_transition(transition)

    def _refresh_recipe_combo(self) -> None:
        transition = self.recipe_controller.refresh_recipe_list(self.recipe_combo.currentData())
        self._apply_recipe_transition(transition)

    def _on_recipe_selected(self, _index: int) -> None:
        transition = self.recipe_controller.load_recipe(self.recipe_combo.currentData())
        self._apply_recipe_transition(transition)

    def _save_new_recipe(self) -> None:
        name = self.recipe_page.recipe_name_input.text().strip()
        steps = self._collect_recipe_steps()
        if not steps:
            return
        transition = self.recipe_controller.save_recipe(name, steps)
        self._apply_recipe_transition(transition)

    def _update_current_recipe(self) -> None:
        name = self.recipe_page.recipe_name_input.text().strip()
        steps = self._collect_recipe_steps()
        if not steps:
            return
        transition = self.recipe_controller.update_recipe(self.recipe_combo.currentData(), name, steps)
        self._apply_recipe_transition(transition)

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

    def _apply_controller_transition(self, transition: ControllerTransition) -> None:
        if transition.final_status is not None:
            self._reset_runtime_ui()
        if transition.view_state is None and transition.update is not None:
            self.monitor_page.update_execution_state(transition.update.status_text, transition.update.active_setpoints_text)
        if transition.view_state is not None:
            self._apply_view_state(transition.view_state)
        for log in transition.logs:
            self._append_log(log)
        if transition.user_message:
            if transition.user_message_level == "info":
                QMessageBox.information(self, "提示", transition.user_message)
            else:
                QMessageBox.warning(self, "提示", transition.user_message)

    def _apply_view_state(self, view_state: RuntimeViewState) -> None:
        if view_state.execution_text is not None and view_state.setpoints_text is not None:
            self.monitor_page.update_execution_state(view_state.execution_text, view_state.setpoints_text)
        if view_state.current_alarm_text is not None:
            self.alarm_page.set_current_alarm(view_state.current_alarm_text)
        if view_state.current_interlock_text is not None:
            self.alarm_page.set_current_interlock(view_state.current_interlock_text)
        if view_state.monitor_alarm_text is not None and view_state.monitor_alarm_style is not None:
            self.monitor_page.update_alarm_text(view_state.monitor_alarm_text, view_state.monitor_alarm_style)
        if view_state.monitor_interlock_text is not None and view_state.monitor_interlock_style is not None:
            self.monitor_page.update_interlock_text(view_state.monitor_interlock_text, view_state.monitor_interlock_style)
        if (
            view_state.run_control_word is not None
            and view_state.estop_status is not None
            and view_state.control_feedback_text is not None
            and view_state.control_feedback_style is not None
        ):
            self.monitor_page.update_control_state(
                view_state.run_control_word,
                view_state.estop_status,
                view_state.control_feedback_text,
                view_state.control_feedback_style,
            )
        self.alarm_page.set_pending_alarms(view_state.pending_alarms)
        if view_state.ack_alarm_enabled is not None:
            self.alarm_page.btn_ack_alarm.setEnabled(view_state.ack_alarm_enabled)
        if view_state.reset_interlock_enabled is not None:
            self.alarm_page.btn_reset_interlock.setEnabled(view_state.reset_interlock_enabled)
        if view_state.start_enabled is not None:
            self.btn_start.setEnabled(view_state.start_enabled)
        if view_state.pause_enabled is not None:
            self.btn_pause.setEnabled(view_state.pause_enabled)
        if view_state.resume_enabled is not None:
            self.btn_resume.setEnabled(view_state.resume_enabled)
        if view_state.stop_enabled is not None:
            self.btn_stop.setEnabled(view_state.stop_enabled)

    def _apply_recipe_transition(self, transition: RecipeTransition) -> None:
        if transition.view_state is not None:
            self._apply_recipe_view_state(transition.view_state)
        for log in transition.logs:
            self._append_log(log)
        if transition.user_message:
            if transition.user_message_level == "info":
                QMessageBox.information(self, "提示", transition.user_message)
            else:
                QMessageBox.warning(self, "参数错误", transition.user_message)

    def _apply_recipe_view_state(self, view_state: RecipeViewState) -> None:
        current_id = self.recipe_combo.currentData()
        self.recipe_combo.blockSignals(True)
        self.recipe_combo.clear()
        self.recipe_combo.addItem("请选择配方", 0)
        for option in view_state.options:
            self.recipe_combo.addItem(option.label, option.recipe_id)
        selected_id = view_state.selected_recipe_id or current_id or 0
        index = self.recipe_combo.findData(selected_id)
        if index >= 0:
            self.recipe_combo.setCurrentIndex(index)
        else:
            self.recipe_combo.setCurrentIndex(0)
        self.recipe_combo.blockSignals(False)

        if selected_id in (None, 0):
            self.recipe_page.load_recipe("", [])
            return
        self.recipe_page.load_recipe(view_state.recipe_name, view_state.steps)

    def _reset_runtime_ui(self) -> None:
        if self.worker is not None:
            self.worker.stop()
            self.worker = None
        self.btn_start.setEnabled(True)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)
        self.btn_stop.setEnabled(False)
        self.alarm_page.btn_ack_alarm.setEnabled(False)
        self.alarm_page.btn_reset_interlock.setEnabled(False)
        self.alarm_page.set_current_interlock("当前联锁: 无联锁")
