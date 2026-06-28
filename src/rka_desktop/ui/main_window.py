from __future__ import annotations
from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rka_desktop import __version__
from rka_desktop.comm.config import CommConfig
from rka_desktop.comm.multi_device_gateway import MultiDeviceGateway
from rka_desktop.core.config import Settings
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.controllers.experiment_controller import ControllerTransition, ExperimentController
from rka_desktop.controllers.history_export_controller import HistoryExportController, HistoryTransition
from rka_desktop.controllers.recipe_controller import RecipeTransition, RecipeController
from rka_desktop.db.database import DatabaseManager
from rka_desktop.hardware.device_gateway import DeviceGateway
from rka_desktop.models.entities import DeviceSnapshot, Measurement
from rka_desktop.repositories import AlarmRepository, AuditLogRepository, ExperimentRepository, RecipeRepository
from rka_desktop.reporting.report_service import ReportService
from rka_desktop.services.export_service import ExportService
from rka_desktop.ui.alarm_page import AlarmPage
from rka_desktop.ui.analysis_page import AnalysisPage
from rka_desktop.ui.dialog_service import DialogService
from rka_desktop.ui.history_page import HistoryPage
from rka_desktop.ui.log_service import LogService
from rka_desktop.ui.monitor_page import MonitorPage
from rka_desktop.ui.multi_device_page import MultiDevicePage
from rka_desktop.ui.main_window_presenter import MainWindowPresenter
from rka_desktop.ui.recipe_page import RecipePage
from rka_desktop.ui.runtime_coordinator import RuntimeCoordinator
from rka_desktop.ui.settings_page import SettingsPage


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, db: DatabaseManager, client: ModbusRtuClient) -> None:
        super().__init__()
        self.settings = settings
        self.db = db
        self.client = client
        self.recipe_repository = RecipeRepository(db)
        self.experiment_repository = ExperimentRepository(db)
        self.alarm_repository = AlarmRepository(db)
        self.audit_repository = AuditLogRepository(db)
        self.gateway = DeviceGateway(client)
        self.controller = ExperimentController(
            settings=settings,
            recipe_repository=self.recipe_repository,
            experiment_repository=self.experiment_repository,
            alarm_repository=self.alarm_repository,
            audit_repository=self.audit_repository,
            gateway=self.gateway,
        )
        self.recipe_controller = RecipeController(self.recipe_repository, self.audit_repository)
        self.export_service = ExportService(db)
        self.report_service = ReportService()
        self.history_controller = HistoryExportController(self.experiment_repository, self.audit_repository, self.export_service)

        self.setWindowTitle(f"{settings.app_name} - v{__version__}")
        self.resize(1380, 840)

        self._build_ui()
        self._build_menu()
        self._bind_events()
        self._refresh_recipe_combo()
        self._refresh_history()
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

    @property
    def worker(self):
        return self.runtime.worker

    @worker.setter
    def worker(self, value) -> None:
        self.runtime.worker = value

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
        self.multi_gateway = MultiDeviceGateway.from_config(
            CommConfig(simulation_mode=self.settings.simulation_mode)
        )
        self.multi_gateway.connect()
        self.multi_device_page = MultiDevicePage(self.multi_gateway)
        self.analysis_page = AnalysisPage(self.experiment_repository)
        self.history_page = HistoryPage()
        self.alarm_page = AlarmPage()
        self.settings_page = SettingsPage(self.settings)

        # 监控 hosts experiment monitoring with device status as a secondary view —
        # device communication is a supporting service, not a headline feature.
        self.monitor_tabs = QTabWidget()
        self.monitor_tabs.addTab(self.monitor_page, "实验监控")
        self.monitor_tabs.addTab(self.multi_device_page, "设备状态")

        self.tabs.addTab(self.recipe_page, "配方")
        self.tabs.addTab(self.monitor_tabs, "监控")
        self.tabs.addTab(self.analysis_page, "数据分析")
        self.tabs.addTab(self.history_page, "历史")
        self.tabs.addTab(self.alarm_page, "报警")
        self.tabs.addTab(self.settings_page, "设置")
        layout.addWidget(self.tabs)
        self.multi_device_page.refresh()
        self.multi_device_page.start()
        self.analysis_page.refresh_experiments()

        self.presenter = MainWindowPresenter(
            recipe_combo=self.recipe_combo,
            recipe_page=self.recipe_page,
            monitor_page=self.monitor_page,
            history_page=self.history_page,
            alarm_page=self.alarm_page,
            btn_start=self.btn_start,
            btn_pause=self.btn_pause,
            btn_resume=self.btn_resume,
            btn_stop=self.btn_stop,
            btn_export_csv=self.btn_export_csv,
            btn_export_excel=self.btn_export_excel,
            log_sink=self._append_log,
            stop_worker=self._stop_worker,
            active_experiment_id_provider=lambda: self.experiment_id,
        )
        self.dialogs = DialogService(self)
        self.runtime = RuntimeCoordinator(
            settings=self.settings,
            db=self.db,
            gateway=self.gateway,
            on_snapshot=self._on_snapshot,
            on_error=self._on_error,
        )
        self.logs = LogService(self.monitor_page, __name__)

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
        self.history_page.btn_refresh.clicked.connect(self._refresh_history)
        self.history_page.table.itemSelectionChanged.connect(self._on_history_selected)

        self.alarm_page.btn_ack_alarm.clicked.connect(self.acknowledge_alarm)
        self.alarm_page.btn_reset_interlock.clicked.connect(self.reset_interlock)

        self.analysis_page.btn_report.clicked.connect(self.export_analysis_report)

    def _build_menu(self) -> None:
        help_menu = self.menuBar().addMenu("帮助")
        help_menu.addAction("使用帮助", self._show_help)
        help_menu.addAction("关于", self._show_about)

    def _show_about(self) -> None:
        self.dialogs.info(
            "关于",
            f"{self.settings.app_name}\n版本 v{__version__}\n\n"
            "铁矿石氧化还原动力学试验系统上位机\n"
            "© 2026 RKA-3000",
        )

    def _show_help(self) -> None:
        self.dialogs.info(
            "使用帮助",
            "1. 配方: 新建/编辑实验步骤并保存。\n"
            "2. 监控: 实时查看实验数据；设备状态子页查看 MFC/温控/天平。\n"
            "3. 数据分析: 选择实验，录入试样参数(m₀/TFe/FeO)，计算还原度并生成报告。\n"
            "4. 历史: 查询历史实验，导出 CSV/Excel。\n"
            "5. 报警: 确认报警与联锁复位。",
        )

    def export_analysis_report(self) -> None:
        result = self.analysis_page.result
        exp_id = self.analysis_page.selected_experiment_id()
        if result is None or exp_id is None:
            self.dialogs.info("提示", "请先在数据分析页选择实验并计算还原度")
            return
        detail = self.experiment_repository.get_experiment_detail(exp_id) or {"id": exp_id}
        default_dir = Path("exports")
        default_dir.mkdir(parents=True, exist_ok=True)
        path = self.dialogs.select_save_path(
            "生成实验报告", default_dir / f"experiment_{exp_id}_report.xlsx", "Excel Files (*.xlsx)"
        )
        if path is None:
            return
        try:
            self.report_service.generate_excel_report(detail, result, Path(path))
            self.audit_repository.log_action("operator", "REPORT_EXPORT", str(path))
            self.dialogs.info("报告已生成", f"已保存到\n{path}")
        except Exception as exc:  # noqa: BLE001
            self.dialogs.warning("生成失败", str(exc))

    def connect_device(self) -> None:
        if self.gateway.connect():
            self._append_log("设备连接成功")
            self.audit_repository.log_action("operator", "DEVICE_CONNECT", self.settings.serial_port)
            self.presenter.show_connected()
            return

        self.dialogs.critical("连接失败", "串口或Modbus连接失败，请检查配置")
        self._append_log("设备连接失败")

    def start_experiment(self) -> None:
        if self.runtime.is_running:
            return

        recipe_id = self.recipe_combo.currentData()
        if recipe_id in (None, 0):
            self.dialogs.warning("缺少配方", "请先选择已保存的配方")
            return

        if not self.dialogs.confirm("确认启动", "确定按当前配方开始实验吗？"):
            return

        if not self.gateway.connect():
            self.dialogs.warning("无法启动", "请先连接设备")
            return

        try:
            transition = self.controller.start_experiment(int(recipe_id))
        except ValueError as exc:
            self.dialogs.warning("缺少步骤", str(exc))
            return
        except Exception as exc:
            self.dialogs.warning("无法启动", str(exc))
            return

        if not transition.success or transition.experiment_id is None:
            self._apply_controller_transition(transition)
            self.dialogs.warning("缺少步骤", "当前配方没有可执行步骤")
            return

        self.presenter.reset_monitor_runtime()
        self._apply_controller_transition(transition)
        self._refresh_history()
        self.runtime.start(transition.experiment_id)
        self.tabs.setCurrentWidget(self.monitor_page)

    def pause_experiment(self) -> None:
        transition = self.controller.pause_experiment()
        if transition is None:
            return
        self._apply_controller_transition(transition)

    def resume_experiment(self) -> None:
        if not self.runtime.is_running or self.engine is None or self.experiment_id is None:
            return
        transition = self.controller.resume_experiment()
        if transition is None:
            return
        self._apply_controller_transition(transition)

    def stop_experiment(self) -> None:
        if not self.runtime.is_running:
            return

        if not self.dialogs.confirm("确认停止", "确定停止当前实验吗？"):
            return
        transition = self.controller.stop_experiment()
        if transition is None:
            return
        self._apply_controller_transition(transition)

    def acknowledge_alarm(self) -> None:
        if self.experiment_id is None:
            self.dialogs.info("提示", "当前无运行中的实验")
            return

        if not self.dialogs.confirm("确认报警", "确定将当前待处理报警标记为已确认吗？"):
            return

        transition = self.controller.acknowledge_alarm()
        self._apply_controller_transition(transition)

    def reset_interlock(self) -> None:
        if not self.dialogs.confirm("确认复位", "确定下发联锁复位命令吗？"):
            return

        transition = self.controller.reset_interlock()
        self._apply_controller_transition(transition)

    def export_csv(self) -> None:
        self._export_data("csv")

    def export_excel(self) -> None:
        self._export_data("excel")

    def _export_data(self, fmt: str) -> None:
        default_dir = Path("exports")
        default_dir.mkdir(parents=True, exist_ok=True)
        selected_history_id = self.history_page.selected_experiment_id()
        exp_id, default_path = self.history_controller.default_export_path(
            fmt,
            active_experiment_id=self.experiment_id,
            selected_experiment_id=selected_history_id,
            export_dir=default_dir,
        )
        if exp_id is None:
            self.dialogs.info("提示", "没有可导出的实验数据")
            return

        if fmt == "csv":
            path = self.dialogs.select_save_path("导出CSV", default_path, "CSV Files (*.csv)")
            if path is None:
                return
            try:
                transition = self.history_controller.export_experiment(
                    "csv",
                    active_experiment_id=self.experiment_id,
                    selected_experiment_id=selected_history_id,
                    file_path=path,
                )
                self._apply_history_transition(transition)
            except Exception as exc:
                self.dialogs.warning("导出失败", str(exc))
                self._append_log(f"导出CSV失败: {exc}")
            return

        path = self.dialogs.select_save_path("导出Excel", default_path, "Excel Files (*.xlsx)")
        if path is None:
            return
        try:
            transition = self.history_controller.export_experiment(
                "excel",
                active_experiment_id=self.experiment_id,
                selected_experiment_id=selected_history_id,
                file_path=path,
            )
            self._apply_history_transition(transition)
        except Exception as exc:
            self.dialogs.warning("导出失败", str(exc))
            self._append_log(f"导出Excel失败: {exc}")

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            if self.controller.has_active_experiment:
                transition = self.controller.stop_experiment()
                if transition is not None:
                    self._apply_controller_transition(transition)
            elif self.runtime.is_running:
                self.runtime.stop()
            self.gateway.close()
            self.multi_device_page.stop()
            self.multi_gateway.close()
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

    def _refresh_history(self) -> None:
        transition = self.history_controller.load_history(self.history_page.selected_experiment_id())
        self._apply_history_transition(transition)

    def _on_history_selected(self) -> None:
        transition = self.history_controller.select_experiment(self.history_page.selected_experiment_id())
        self._apply_history_transition(transition)

    def _save_new_recipe(self) -> None:
        name = self.recipe_page.recipe_name_input.text().strip()
        transition = self.recipe_controller.save_recipe_input(name, self.recipe_page.collect_step_inputs())
        self._apply_recipe_transition(transition)

    def _update_current_recipe(self) -> None:
        name = self.recipe_page.recipe_name_input.text().strip()
        transition = self.recipe_controller.update_recipe_input(
            self.recipe_combo.currentData(),
            name,
            self.recipe_page.collect_step_inputs(),
        )
        self._apply_recipe_transition(transition)

    def _append_log(self, text: str) -> None:
        self.logs.append(text)

    def _apply_controller_transition(self, transition: ControllerTransition) -> None:
        self.presenter.apply_experiment_transition(transition)
        if transition.experiment_id is not None or transition.final_status is not None:
            self._refresh_history()
        if transition.user_message:
            if transition.user_message_level == "info":
                self.dialogs.info("提示", transition.user_message)
            else:
                self.dialogs.warning("提示", transition.user_message)

    def _apply_recipe_transition(self, transition: RecipeTransition) -> None:
        self.presenter.apply_recipe_transition(transition)
        if transition.user_message:
            if transition.user_message_level == "info":
                self.dialogs.info("提示", transition.user_message)
            else:
                self.dialogs.warning("参数错误", transition.user_message)

    def _apply_history_transition(self, transition: HistoryTransition) -> None:
        self.presenter.apply_history_transition(transition)
        if transition.user_message:
            if transition.user_message_level == "info":
                self.dialogs.info("提示", transition.user_message)
            else:
                self.dialogs.warning("提示", transition.user_message)

    def _stop_worker(self) -> None:
        self.runtime.stop()
