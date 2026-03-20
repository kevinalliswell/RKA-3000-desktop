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

from rka_desktop.core.alarm_rules import (
    decode_alarm_word,
    has_active_interlock,
    has_interlock_alarm,
    interlock_text_from_word,
    is_interlock_resettable,
)
from rka_desktop.core.config import Settings
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.controllers.experiment_controller import ControllerTransition, ExperimentController
from rka_desktop.db.database import DatabaseManager
from rka_desktop.hardware.device_gateway import DeviceGateway
from rka_desktop.models.entities import DeviceSnapshot, Measurement
from rka_desktop.services.acquisition_service import AcquisitionWorker, alarm_text
from rka_desktop.services.experiment_engine import ExperimentState
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
        self.export_service = ExportService(db)

        self.worker: AcquisitionWorker | None = None
        self._alarm_active_word = 0
        self._interlock_active_word = 0
        self._estop_active = False
        self._run_control_feedback_inconsistent = False

        self.setWindowTitle(f"{settings.app_name} - v1.1")
        self.resize(1380, 840)

        self._build_ui()
        self._bind_events()
        self._refresh_recipe_combo()
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

        self._alarm_active_word = 0
        self._interlock_active_word = 0
        self._estop_active = False
        self._run_control_feedback_inconsistent = False
        self.monitor_page.reset_runtime()
        self.alarm_page.set_current_alarm("当前报警: 无")
        self.alarm_page.set_current_interlock("当前联锁: 无联锁")
        self.alarm_page.set_pending_alarms([])
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

        self.btn_start.setEnabled(False)
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.tabs.setCurrentWidget(self.monitor_page)

    def pause_experiment(self) -> None:
        transition = self.controller.pause_experiment()
        if transition is None:
            return
        self._apply_controller_transition(transition)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(True)

    def resume_experiment(self) -> None:
        if self.worker is None or self.engine is None or self.experiment_id is None:
            return
        if self._alarm_active_word != 0:
            QMessageBox.warning(self, "无法恢复", "当前仍有活动报警，请先排除报警")
            return
        if self._interlock_active_word != 0 or self._estop_active:
            QMessageBox.warning(self, "无法恢复", "联锁尚未解除，请先执行复位或解除急停")
            return
        if self.engine.state == ExperimentState.INTERRUPTED and self.db.list_unacknowledged_alarms(self.experiment_id):
            QMessageBox.warning(self, "无法恢复", "报警已解除，但仍有未确认报警")
            return
        transition = self.controller.resume_experiment()
        if transition is None:
            return
        self._apply_controller_transition(transition)
        self.btn_pause.setEnabled(True)
        self.btn_resume.setEnabled(False)

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

        ok = self.db.acknowledge_latest_alarm(self.experiment_id, actor="operator")
        if ok:
            self._append_log("报警已确认")
            self.db.log_action("operator", "ALARM_ACK", f"experiment_id={self.experiment_id}")
        else:
            self._append_log("没有待确认报警")

        self._refresh_alarm_page()
        if (
            ok
            and self.engine is not None
            and self.engine.state == ExperimentState.INTERRUPTED
            and self.experiment_id is not None
        ):
            self._update_recovery_actions()

    def reset_interlock(self) -> None:
        if self.experiment_id is None:
            QMessageBox.information(self, "提示", "当前无运行中的实验")
            return
        if self._alarm_active_word != 0:
            QMessageBox.warning(self, "无法复位", "当前仍有活动报警，请先排除报警")
            return
        if self.db.list_unacknowledged_alarms(self.experiment_id):
            QMessageBox.warning(self, "无法复位", "仍有未确认报警，请先确认")
            return
        if self._interlock_active_word == 0 and not self._estop_active:
            QMessageBox.information(self, "提示", "当前没有需要复位的联锁")
            return
        if not is_interlock_resettable(self._interlock_active_word, profile_name=self.settings.mapping_profile):
            QMessageBox.warning(self, "无法复位", "当前联锁状态不允许软件复位，请先解除急停/硬件闭锁")
            return
        if QMessageBox.question(self, "确认复位", "确定下发联锁复位命令吗？") != QMessageBox.StandardButton.Yes:
            return

        if not self._issue_run_control_command("reset", "联锁复位"):
            return
        self.db.log_action("operator", "INTERLOCK_RESET", f"id={self.experiment_id},word={self._interlock_active_word:04X}")
        self._append_log("已请求联锁复位，等待状态解除")
        self.alarm_page.btn_reset_interlock.setEnabled(False)
        self._update_recovery_actions()

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
        feedback = self.gateway.evaluate_run_control_feedback(snapshot.run_control_word)
        feedback_style = "color: #1b5e20;" if feedback.is_consistent else "color: #b71c1c; font-weight: bold;"
        self.monitor_page.update_control_state(
            snapshot.run_control_word,
            snapshot.estop_status,
            feedback.message,
            feedback_style,
        )
        self._handle_run_control_feedback(feedback.message, feedback.is_consistent)
        self.monitor_page.push_measurement(measurement)
        self.monitor_page.update_chart(snapshot)
        self._handle_alarm(snapshot)
        self._handle_interlock(snapshot)
        transition = self.controller.process_measurement(measurement)
        if transition is not None:
            self._apply_controller_transition(transition)
            if self.engine is not None and self.engine.state == ExperimentState.INTERRUPTED:
                self._update_recovery_actions()
            return

    def _on_error(self, message: str) -> None:
        transition = self.controller.fail_active_experiment(
            f"采集异常，实验已故障停止: {message}",
            audit_action="ACQUISITION_FAILED",
            detail=f"id={self.experiment_id},error={message}" if self.experiment_id is not None else f"error={message}",
        )
        self._apply_controller_transition(transition)

    def _handle_alarm(self, snapshot: DeviceSnapshot) -> None:
        alarm_msg = alarm_text(snapshot, profile_name=self.settings.mapping_profile)
        self.alarm_page.set_current_alarm(f"当前报警: {alarm_msg}")

        if snapshot.alarm_word != 0:
            active_alarms = decode_alarm_word(snapshot.alarm_word, profile_name=self.settings.mapping_profile)
            self.monitor_page.update_alarm_text(f"状态: {alarm_msg}", "color: #b71c1c; font-weight: bold;")
            self.alarm_page.btn_ack_alarm.setEnabled(True)
            if snapshot.alarm_word != self._alarm_active_word:
                self._alarm_active_word = snapshot.alarm_word
                if self.experiment_id is not None:
                    for alarm in active_alarms:
                        self.db.create_alarm(
                            self.experiment_id,
                            code=alarm.code,
                            level=alarm.level,
                            message=alarm.message,
                        )
                    self.db.log_action("system", "ALARM_RAISED", f"experiment_id={self.experiment_id},word={snapshot.alarm_word:04X}")
                self._append_log(f"报警触发：报警字={snapshot.alarm_word}")
            if (
                self.engine is not None
                and self.experiment_id is not None
                and self.engine.state == ExperimentState.RUNNING
                and has_interlock_alarm(snapshot.alarm_word, profile_name=self.settings.mapping_profile)
            ):
                self._interrupt_experiment(f"id={self.experiment_id},alarm={snapshot.alarm_word}")
            self._refresh_alarm_page()
            return

        self.monitor_page.update_alarm_text("状态: 正常", "color: #1b5e20;")
        if self._alarm_active_word != 0:
            self._append_log("报警解除")
        self._alarm_active_word = 0
        self._refresh_alarm_page()
        self._update_recovery_actions()

    def _handle_interlock(self, snapshot: DeviceSnapshot) -> None:
        self._estop_active = bool(snapshot.estop_status)
        interlock_text = interlock_text_from_word(snapshot.interlock_word, profile_name=self.settings.mapping_profile)
        self.alarm_page.set_current_interlock(f"当前联锁: {interlock_text}")

        if snapshot.interlock_word != 0 or snapshot.estop_status:
            self.monitor_page.update_interlock_text(
                f"联锁: {interlock_text}",
                "color: #b71c1c; font-weight: bold;",
            )
            if snapshot.interlock_word != self._interlock_active_word:
                self._interlock_active_word = snapshot.interlock_word
                self._append_log(f"联锁激活：状态字=0x{snapshot.interlock_word:04X}")
                if self.experiment_id is not None:
                    self.db.log_action("system", "INTERLOCK_ACTIVE", f"id={self.experiment_id},word={snapshot.interlock_word:04X}")
            if self.engine is not None and self.experiment_id is not None and self.engine.state == ExperimentState.RUNNING:
                self._interrupt_experiment(f"id={self.experiment_id},interlock={snapshot.interlock_word:04X}")
            self._update_recovery_actions()
            return

        self.monitor_page.update_interlock_text("联锁: 无联锁", "color: #1b5e20;")
        if self._interlock_active_word != 0:
            self._append_log("联锁解除")
            if self.experiment_id is not None:
                self.db.log_action("system", "INTERLOCK_CLEARED", f"id={self.experiment_id}")
        self._interlock_active_word = 0
        self._update_recovery_actions()

    def _refresh_alarm_page(self) -> None:
        if self.experiment_id is None:
            self.alarm_page.set_pending_alarms([])
            self.alarm_page.btn_ack_alarm.setEnabled(False)
            self.alarm_page.btn_reset_interlock.setEnabled(False)
            return

        unacked = self.db.list_unacknowledged_alarms(self.experiment_id)
        self.alarm_page.set_pending_alarms(unacked)
        self.alarm_page.btn_ack_alarm.setEnabled(bool(unacked))
        self.alarm_page.btn_reset_interlock.setEnabled(False)

    def _handle_run_control_feedback(self, feedback_message: str, is_consistent: bool) -> None:
        if is_consistent:
            if self._run_control_feedback_inconsistent:
                self._append_log("运行控制反馈已恢复一致")
                if self.experiment_id is not None:
                    self.db.log_action("system", "RUN_CONTROL_FEEDBACK_RESTORED", f"id={self.experiment_id}")
            self._run_control_feedback_inconsistent = False
            return

        if self._run_control_feedback_inconsistent:
            return

        self._run_control_feedback_inconsistent = True
        self._append_log(feedback_message)
        if self.experiment_id is not None:
            self.db.log_action(
                "system",
                "RUN_CONTROL_FEEDBACK_MISMATCH",
                f"id={self.experiment_id},detail={feedback_message}",
            )

    def _interrupt_experiment(self, detail: str) -> None:
        transition = self.controller.interrupt_experiment(detail)
        if transition is None:
            return
        self._apply_controller_transition(transition)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(False)

    def _update_recovery_actions(self) -> None:
        if self.engine is None or self.engine.state != ExperimentState.INTERRUPTED:
            self.alarm_page.btn_reset_interlock.setEnabled(False)
            return

        setpoints_text = self.monitor_page.lbl_setpoints.text().removeprefix("步骤设定: ")
        unacked = bool(self.experiment_id is not None and self.db.list_unacknowledged_alarms(self.experiment_id))
        has_interlock = has_active_interlock(self._interlock_active_word, profile_name=self.settings.mapping_profile)
        reset_allowed = (
            self._alarm_active_word == 0
            and not unacked
            and has_interlock
            and not self._estop_active
            and is_interlock_resettable(self._interlock_active_word, profile_name=self.settings.mapping_profile)
        )
        resume_allowed = self._alarm_active_word == 0 and not unacked and not has_interlock and not self._estop_active

        if self._alarm_active_word != 0:
            status_text = "报警处理中，联锁保持中"
        elif unacked and has_interlock:
            status_text = "报警已解除，待确认后可执行联锁复位"
        elif unacked:
            status_text = "报警已解除，待确认后可恢复实验"
        elif self._estop_active:
            status_text = "急停仍处于触发状态，禁止恢复"
        elif has_interlock:
            status_text = "联锁保持中，可执行复位"
        else:
            status_text = "联锁已解除，可恢复实验"

        self.monitor_page.update_execution_state(status_text, setpoints_text)
        self.btn_pause.setEnabled(False)
        self.btn_resume.setEnabled(resume_allowed)
        self.alarm_page.btn_reset_interlock.setEnabled(reset_allowed)

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

    def _issue_run_control_command(self, command: str, action_label: str) -> bool:
        try:
            word = self.gateway.issue_run_control(command)
            self._append_log(f"已下发运行控制命令: {action_label} ({word:#06x})")
            return True
        except Exception as exc:
            transition = self.controller.fail_active_experiment(
                f"运行控制命令下发失败[{action_label}]，实验已故障停止: {exc}",
                audit_action="RUN_CONTROL_FAILED",
                detail=(
                    f"id={self.experiment_id},command={command},error={exc}"
                    if self.experiment_id is not None
                    else f"command={command},error={exc}"
                ),
            )
            self._apply_controller_transition(transition)
            return False

    def _apply_controller_transition(self, transition: ControllerTransition) -> None:
        if transition.update is not None:
            self.monitor_page.update_execution_state(transition.update.status_text, transition.update.active_setpoints_text)
        for log in transition.logs:
            self._append_log(log)
        if transition.final_status is not None:
            self._reset_runtime_ui()

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
        self._interlock_active_word = 0
        self._estop_active = False
        self._run_control_feedback_inconsistent = False
