from __future__ import annotations

from PySide6.QtWidgets import (
    QAbstractItemView,
    QFormLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from rka_desktop.core.config import Settings


def information_page(text: str) -> QWidget:
    page = QWidget()
    layout = QVBoxLayout(page)
    label = QLabel(text)
    label.setWordWrap(True)
    layout.addWidget(label)
    layout.addStretch()
    return page


class SettingsPage(QWidget):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings
        outer = QVBoxLayout(self)
        self.sections = QTabWidget()

        general_page = QWidget()
        form = QFormLayout(general_page)
        self.lbl_app_env = QLabel()
        self.lbl_serial_port = QLabel()
        self.lbl_baudrate = QLabel()
        self.lbl_unit_id = QLabel()
        self.lbl_mapping_profile = QLabel()
        self.lbl_poll_interval = QLabel()
        self.lbl_acquisition_batch = QLabel()
        self.lbl_heatup_grace = QLabel()
        self.lbl_step_total_grace = QLabel()
        self.lbl_simulation = QLabel()
        for caption, widget in (
            ("运行环境", self.lbl_app_env), ("串口", self.lbl_serial_port),
            ("波特率", self.lbl_baudrate), ("设备地址", self.lbl_unit_id),
            ("映射 Profile", self.lbl_mapping_profile),
            ("轮询周期(ms)", self.lbl_poll_interval),
            ("采集批量写入", self.lbl_acquisition_batch),
            ("升温超时宽限(s)", self.lbl_heatup_grace),
            ("步骤总超时宽限(s)", self.lbl_step_total_grace),
            ("模拟模式", self.lbl_simulation),
        ):
            form.addRow(caption, widget)
        self.sections.addTab(general_page, "界面与采样")

        self.sections.addTab(information_page(
            "串口配置由部署环境提供。修改设备端口、波特率或映射 Profile 后，"
            "须重新启动程序并进行设备身份、寄存器和回读验证。"
        ), "串口配置")
        self.sections.addTab(information_page(
            "独立硬件急停、断气、惰性处置及联锁尚需现场验收。"
            "软件连接状态不能替代物理安全条件；报警确认也不能解除真实故障。"
        ), "安全边界")
        self.sections.addTab(information_page(
            "当前桌面程序尚未提供账户认证和角色权限。正式接入管理员气体策略前，"
            "必须由后端验证身份、操作权限与审计记录。"
        ), "角色权限")

        limits_page = QWidget()
        limits_layout = QVBoxLayout(limits_page)
        warning = QLabel(
            "原型中的气体使用上限为浏览器演示数据。当前桌面后端未提供版本化策略、"
            "管理员审批或真机下发校验；本页仅展示规划中的气体，不可编辑。"
        )
        warning.setWordWrap(True)
        limits_layout.addWidget(warning)
        self.gas_limit_table = QTableWidget(7, 3)
        self.gas_limit_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.gas_limit_table.verticalHeader().hide()
        self.gas_limit_table.setHorizontalHeaderLabels(("气体", "原型 MFC 通道", "桌面端状态"))
        self.gas_limit_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for row, (gas, channel, status) in enumerate((
            ("N₂", "1 · 与 Ar 共用", "现有采集链路"),
            ("Ar", "1 · 与 N₂ 共用", "待映射"),
            ("CO", "2", "现有采集链路"),
            ("CO₂", "3", "待映射"),
            ("H₂", "4", "现有采集链路"),
            ("CH₄", "5", "待映射"),
            ("O₂", "6", "待映射"),
        )):
            for col, value in enumerate((gas, channel, status)):
                self.gas_limit_table.setItem(row, col, QTableWidgetItem(value))
        limits_layout.addWidget(self.gas_limit_table)
        self.sections.addTab(limits_page, "气体使用上限")
        outer.addWidget(self.sections)
        self.refresh()

    def refresh(self) -> None:
        self.lbl_app_env.setText(self._settings.app_env)
        self.lbl_serial_port.setText(self._settings.serial_port)
        self.lbl_baudrate.setText(str(self._settings.baudrate))
        self.lbl_unit_id.setText(str(self._settings.modbus_unit_id))
        self.lbl_mapping_profile.setText(self._settings.mapping_profile)
        self.lbl_poll_interval.setText(str(self._settings.poll_interval_ms))
        self.lbl_acquisition_batch.setText(str(self._settings.acquisition_batch_size))
        self.lbl_heatup_grace.setText(str(self._settings.step_heatup_grace_seconds))
        self.lbl_step_total_grace.setText(str(self._settings.step_total_grace_seconds))
        self.lbl_simulation.setText("是" if self._settings.simulation_mode else "否")
