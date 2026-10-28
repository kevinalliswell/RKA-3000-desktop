from __future__ import annotations

from pathlib import Path

import qtawesome as qta
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rka_desktop import __version__
from rka_desktop.comm.config import CommConfig
from rka_desktop.comm.multi_device_gateway import MultiDeviceGateway
from rka_desktop.controllers.experiment_controller import (
    ControllerTransition,
    ExperimentController,
)
from rka_desktop.controllers.history_export_controller import (
    HistoryExportController,
    HistoryTransition,
)
from rka_desktop.controllers.recipe_controller import RecipeController, RecipeTransition
from rka_desktop.core.config import Settings
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.db.database import DatabaseManager
from rka_desktop.hardware.device_gateway import DeviceGateway
from rka_desktop.models.entities import DeviceSnapshot, Measurement
from rka_desktop.reporting.report_service import ReportService
from rka_desktop.repositories import (
    AlarmRepository,
    AuditLogRepository,
    ExperimentRepository,
    RecipeRepository,
)
from rka_desktop.services.export_service import ExportService
from rka_desktop.ui.alarm_page import AlarmPage
from rka_desktop.ui.analysis_page import AnalysisPage
from rka_desktop.ui.dialog_service import DialogService
from rka_desktop.ui.history_page import HistoryPage
from rka_desktop.ui.log_page import LogPage
from rka_desktop.ui.log_service import LogService
from rka_desktop.ui.main_window_presenter import MainWindowPresenter
from rka_desktop.ui.monitor_page import MonitorPage
from rka_desktop.ui.multi_device_page import MultiDevicePage
from rka_desktop.ui.recipe_page import RecipePage
from rka_desktop.ui.runtime_coordinator import RuntimeCoordinator
from rka_desktop.ui.settings_page import SettingsPage
from rka_desktop.ui.theme import ACCENT, apply_theme, make_primary
from rka_desktop.ui.workspace_pages import (
    HelpPage,
    OverviewPage,
    PreflightPage,
    ReportsPage,
    title,
)


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
        self.theme_mode = "dark"

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

    def _build_header(self) -> QFrame:
        header = QFrame()
        header.setObjectName("appHeader")
        header.setFixedHeight(62)
        row = QHBoxLayout(header)
        row.setContentsMargins(18, 0, 18, 0)
        row.setSpacing(12)

        logo = QLabel()
        logo.setPixmap(qta.icon("mdi.molecule", color=ACCENT).pixmap(30, 30))
        row.addWidget(logo)

        titles = QVBoxLayout()
        titles.setSpacing(0)
        title = QLabel("RKA-3000 · 实验控制工作台")
        title.setObjectName("appTitle")
        subtitle = QLabel("铁矿石氧化还原动力学试验系统")
        subtitle.setObjectName("appSubtitle")
        titles.addWidget(title)
        titles.addWidget(subtitle)
        row.addLayout(titles)
        row.addStretch()

        self.lbl_runtime_state = QLabel("●  待机")
        self.lbl_runtime_state.setObjectName("runtimeState")
        row.addWidget(self.lbl_runtime_state)

        self.btn_theme = QPushButton("☀  浅色")
        self.btn_theme.setToolTip("切换深色 / 浅色界面")
        self.btn_theme.clicked.connect(self._toggle_theme)
        row.addWidget(self.btn_theme)

        version = QLabel(f"v{__version__}")
        version.setObjectName("appVersion")
        row.addWidget(version)
        return header

    def _toggle_theme(self) -> None:
        self.theme_mode = "light" if self.theme_mode == "dark" else "dark"
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, self.theme_mode)
        self.btn_theme.setText("☾  深色" if self.theme_mode == "light" else "☀  浅色")

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("centralRoot")
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(218)
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 18, 12, 18)
        side.setSpacing(3)
        brand = QLabel("R  RKA-3000")
        brand.setObjectName("sideBrand")
        side.addWidget(brand)
        sub = QLabel("实验控制工作台")
        sub.setObjectName("sideSub")
        side.addWidget(sub)
        side.addSpacing(22)
        self.nav_buttons: dict[str, QPushButton] = {}
        groups = (
            ("工作台", (("overview", "实时总览", "mdi.view-dashboard-outline"),
                       ("preflight", "实验准备", "mdi.clipboard-check-outline"),
                       ("current", "当前实验", "mdi.monitor-dashboard"))),
            ("实验管理", (("recipes", "实验配方", "mdi.flask-outline"),
                         ("history", "历史实验", "mdi.history"),
                         ("alarms", "报警事件", "mdi.bell-alert-outline"))),
            ("系统与结果", (("devices", "设备诊断", "mdi.lan"),
                           ("audit", "操作审计", "mdi.text-box-search-outline"),
                           ("analysis", "数据分析", "mdi.chart-bell-curve-cumulative"),
                           ("reports", "报告中心", "mdi.file-chart-outline"),
                           ("settings", "系统设置", "mdi.cog-outline"),
                           ("help", "使用帮助", "mdi.help-circle-outline"))),
        )
        for group_name, items in groups:
            label = QLabel(group_name)
            label.setObjectName("navGroup")
            side.addWidget(label)
            for key, caption, icon in items:
                button = QPushButton(qta.icon(icon, color="#91a2b9"), f"  {caption}")
                button.setObjectName("navItem")
                button.setCheckable(True)
                button.setProperty("pageKey", key)
                button.clicked.connect(lambda checked=False, page=key: self.navigate(page))
                side.addWidget(button)
                self.nav_buttons[key] = button
            side.addSpacing(10)
        side.addStretch()
        mode_label = QLabel("●  仿真模式" if self.settings.simulation_mode else "●  实机模式")
        mode_label.setObjectName("sideMode")
        side.addWidget(mode_label)
        outer.addWidget(sidebar)

        work_area = QWidget()
        work = QVBoxLayout(work_area)
        work.setContentsMargins(0, 0, 0, 0)
        work.setSpacing(0)
        work.addWidget(self._build_header())
        outer.addWidget(work_area, 1)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(12)
        work.addWidget(content, 1)

        self.toolbar_widget = QFrame()
        self.toolbar_widget.setObjectName("workspaceToolbar")
        toolbar = QHBoxLayout(self.toolbar_widget)
        toolbar.setContentsMargins(0, 0, 0, 0)
        toolbar.setSpacing(8)
        self.btn_connect = QPushButton(qta.icon("mdi.lan-connect", color="#334155"), " 连接设备")
        self.recipe_combo = QComboBox()
        self.recipe_combo.setMinimumWidth(280)
        self.btn_refresh_recipe = QPushButton(qta.icon("mdi.refresh", color="#334155"), "")
        self.btn_start = make_primary(QPushButton(qta.icon("mdi.play", color="white"), " 实验准备"))
        self.btn_pause = QPushButton(qta.icon("mdi.pause", color="#334155"), " 暂停")
        self.btn_resume = QPushButton(qta.icon("mdi.play-outline", color="#334155"), " 恢复")
        self.btn_stop = QPushButton(qta.icon("mdi.stop", color="#334155"), " 停止")
        self.btn_export_csv = QPushButton(qta.icon("mdi.file-delimited-outline", color="#334155"), " 导出CSV")
        self.btn_export_excel = QPushButton(qta.icon("mdi.file-excel-outline", color="#334155"), " 导出Excel")

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
        layout.addWidget(self.toolbar_widget)

        self.tabs = QTabWidget()
        self.recipe_page = RecipePage()
        self.monitor_page = MonitorPage()
        self.multi_gateway = MultiDeviceGateway.from_config(
            CommConfig(simulation_mode=self.settings.simulation_mode)
        )
        self.multi_gateway.connect()
        self.multi_device_page = MultiDevicePage(self.multi_gateway)
        self.multi_device_page.set_diagnostics_only()
        self.analysis_page = AnalysisPage(self.experiment_repository)
        self.history_page = HistoryPage()
        self.alarm_page = AlarmPage()
        self.log_page = LogPage()
        self.settings_page = SettingsPage(self.settings)
        for widget, heading, description in (
            (self.recipe_page, "实验配方", "建立和维护温度、保温时间及气体流量步骤"),
            (self.monitor_page, "当前实验", "实时测量、执行阶段、曲线和控制反馈"),
            (self.multi_device_page, "设备诊断", "温控、质量流量计和天平状态"),
            (self.analysis_page, "数据分析", "失重法还原度和关键动力学指标"),
            (self.history_page, "历史实验", "记录查询、管理与原始数据导出"),
            (self.alarm_page, "报警事件", "报警确认与联锁复位"),
            (self.log_page, "操作审计", "实验与设备操作记录"),
        ):
            widget.layout().insertWidget(0, title(heading, description))
        self.settings_page.layout().insertRow(0, title("系统设置", "当前运行环境及设备映射配置"))

        # 监控 hosts experiment monitoring with device status as a secondary view —
        # device communication is a supporting service, not a headline feature.
        self.monitor_tabs = QTabWidget()
        self.monitor_tabs.addTab(self.monitor_page, "实验监控")
        self.monitor_tabs.addTab(self.multi_device_page, "设备状态")

        _ico = lambda name: qta.icon(name, color="#64748B", color_active=ACCENT)
        self.tabs.addTab(self.recipe_page, _ico("mdi.flask-outline"), "配方")
        self.tabs.addTab(self.monitor_tabs, _ico("mdi.monitor-dashboard"), "监控")
        self.tabs.addTab(self.analysis_page, _ico("mdi.chart-bell-curve-cumulative"), "数据分析")
        self.tabs.addTab(self.history_page, _ico("mdi.history"), "历史")
        self.tabs.addTab(self.alarm_page, _ico("mdi.bell-alert-outline"), "报警")
        self.tabs.addTab(self.log_page, _ico("mdi.text-box-search-outline"), "日志")
        self.tabs.addTab(self.settings_page, _ico("mdi.cog-outline"), "设置")
        self.tabs.tabBar().hide()
        self.tabs.setDocumentMode(True)
        self.overview_page = OverviewPage()
        self.preflight_page = PreflightPage()
        self.reports_page = ReportsPage()
        self.help_page = HelpPage()
        self.page_stack = QStackedWidget()
        self.page_stack.addWidget(self.overview_page)
        self.page_stack.addWidget(self.preflight_page)
        self.page_stack.addWidget(self.tabs)
        self.page_stack.addWidget(self.reports_page)
        self.page_stack.addWidget(self.help_page)
        layout.addWidget(self.page_stack, 1)
        self.multi_device_page.refresh()
        self.multi_device_page.start()
        self.analysis_page.refresh_experiments()
        self._refresh_logs()
        self._refresh_alarm_history()

        mode = "仿真模式" if self.settings.simulation_mode else "实机模式"
        self.statusBar().showMessage(f"就绪 · {mode} · 串口 {self.settings.serial_port}")

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
        self.navigate("overview")

    def _bind_events(self) -> None:
        self.btn_connect.clicked.connect(self.connect_device)
        self.btn_refresh_recipe.clicked.connect(self._refresh_recipe_combo)
        self.recipe_combo.currentIndexChanged.connect(self._on_recipe_selected)
        self.btn_start.clicked.connect(lambda: self.navigate("preflight"))
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
        self.history_page.btn_rename.clicked.connect(self.rename_experiment)
        self.history_page.btn_delete.clicked.connect(self.delete_experiment)
        self.log_page.btn_refresh.clicked.connect(self._refresh_logs)
        self.overview_page.btn_prepare.clicked.connect(lambda: self.navigate("preflight"))
        self.overview_page.btn_current.clicked.connect(lambda: self.navigate("current"))
        self.overview_page.btn_history.clicked.connect(lambda: self.navigate("history"))
        self.preflight_page.btn_start.clicked.connect(self._start_from_preflight)
        self.reports_page.btn_analysis.clicked.connect(lambda: self.navigate("analysis"))
        self.reports_page.btn_history.clicked.connect(lambda: self.navigate("history"))
        self.reports_page.btn_report.clicked.connect(self.export_analysis_report)

    def navigate(self, page: str) -> None:
        """Map the prototype's twelve destinations to real application pages."""
        if page == "overview":
            self.page_stack.setCurrentWidget(self.overview_page)
        elif page == "preflight":
            self.page_stack.setCurrentWidget(self.preflight_page)
            self.preflight_page.recipe_label.setText(self.recipe_combo.currentText())
            self.preflight_page._refresh_step()
        elif page == "reports":
            self.page_stack.setCurrentWidget(self.reports_page)
        elif page == "help":
            self.page_stack.setCurrentWidget(self.help_page)
        else:
            tab_index = {"recipes": 0, "current": 1, "analysis": 2, "history": 3,
                         "alarms": 4, "audit": 5, "settings": 6, "devices": 1}.get(page)
            if tab_index is None:
                raise ValueError(f"Unknown page: {page}")
            self.tabs.setCurrentIndex(tab_index)
            if page in ("current", "devices"):
                self.monitor_tabs.setCurrentIndex(0 if page == "current" else 1)
            self.page_stack.setCurrentWidget(self.tabs)
        for key, button in self.nav_buttons.items():
            button.setChecked(key == page)
        self.toolbar_widget.setVisible(page in {"recipes", "preflight", "current", "history"})
        if page == "alarms":
            self._refresh_alarm_history()
        self.current_page = page

    def _start_from_preflight(self) -> None:
        missing = self.preflight_page.missing_fields()
        if missing:
            self.dialogs.warning("准备未完成", "请填写或确认：" + "、".join(missing))
            return
        self.start_experiment()
        if self.experiment_id is not None and self.runtime.is_running:
            try:
                self.experiment_repository.set_sample_params(
                    self.experiment_id,
                    self.preflight_page.mass.value(),
                    self.preflight_page.tfe.value(),
                    self.preflight_page.feo.value(),
                )
                name = self.preflight_page.sample_name.text().strip()
                self.experiment_repository.rename_experiment(self.experiment_id, name)
                self.audit_repository.log_action(
                    self.preflight_page.operator.text().strip(), "PREFLIGHT_CONFIRMED",
                    f"#{self.experiment_id} · {name}",
                )
                self._refresh_history()
            except Exception as exc:  # noqa: BLE001
                self.dialogs.warning("试样信息保存失败", str(exc))
            self.navigate("current")

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
            self._refresh_logs()
        except Exception as exc:  # noqa: BLE001
            self.dialogs.warning("生成失败", str(exc))

    def _refresh_logs(self) -> None:
        self.log_page.set_logs(self.audit_repository.list_audit_logs(limit=200))

    def _refresh_alarm_history(self) -> None:
        self.alarm_page.set_alarm_history(self.alarm_repository.list_alarm_history(limit=200))

    def rename_experiment(self) -> None:
        exp_id = self.history_page.selected_experiment_id()
        if exp_id is None:
            self.dialogs.info("提示", "请先在历史列表选择实验")
            return
        new_name, ok = QInputDialog.getText(self, "重命名实验", "新的实验名称：")
        if not ok:
            return
        new_name = new_name.strip()
        if not new_name:
            self.dialogs.warning("无效名称", "实验名称不能为空")
            return
        self.experiment_repository.rename_experiment(exp_id, new_name)
        self.audit_repository.log_action("operator", "EXPERIMENT_RENAME", f"#{exp_id} -> {new_name}")
        self._refresh_history()
        self.analysis_page.refresh_experiments()
        self._refresh_logs()

    def delete_experiment(self) -> None:
        exp_id = self.history_page.selected_experiment_id()
        if exp_id is None:
            self.dialogs.info("提示", "请先在历史列表选择实验")
            return
        if self.runtime.is_running and self.experiment_id == exp_id:
            self.dialogs.warning("无法删除", "该实验正在运行中")
            return
        if not self.dialogs.confirm("确认删除", f"删除实验 #{exp_id} 及其全部测量与报警数据？此操作不可撤销。"):
            return
        self.experiment_repository.delete_experiment(exp_id)
        self.audit_repository.log_action("operator", "EXPERIMENT_DELETE", f"#{exp_id}")
        self._refresh_history()
        self.analysis_page.refresh_experiments()
        self._refresh_logs()

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
        except Exception as exc:  # noqa: BLE001
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
        self.overview_page.run_state.setText(f"运行中 · 实验 #{transition.experiment_id}")
        self.lbl_runtime_state.setText("●  运行中")
        self.navigate("current")

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
            except Exception as exc:  # noqa: BLE001
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
        except Exception as exc:  # noqa: BLE001
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

        self.overview_page.update_snapshot(snapshot)
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
        self._refresh_history_detail()

    def _on_history_selected(self) -> None:
        transition = self.history_controller.select_experiment(self.history_page.selected_experiment_id())
        self._apply_history_transition(transition)
        self._refresh_history_detail()

    def _refresh_history_detail(self) -> None:
        experiment_id = self.history_page.selected_experiment_id()
        measurements = self.experiment_repository.fetch_measurements(experiment_id) if experiment_id else []
        alarms = self.alarm_repository.list_alarm_history(experiment_id) if experiment_id else []
        self.history_page.set_measurements(measurements)
        self.history_page.set_alarm_history(alarms)

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
        if any("报警" in entry or "联锁" in entry for entry in transition.logs):
            self._refresh_alarm_history()
        if transition.final_status is not None:
            self.overview_page.run_state.setText(
                f"最近实验 · {transition.final_status}"
            )
            self.lbl_runtime_state.setText("●  待机")
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
