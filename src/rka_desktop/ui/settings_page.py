from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QLabel, QWidget

from rka_desktop.core.config import Settings


class SettingsPage(QWidget):
    def __init__(self, settings: Settings) -> None:
        super().__init__()
        self._settings = settings

        layout = QFormLayout(self)
        self.lbl_app_env = QLabel()
        self.lbl_serial_port = QLabel()
        self.lbl_baudrate = QLabel()
        self.lbl_unit_id = QLabel()
        self.lbl_mapping_profile = QLabel()
        self.lbl_poll_interval = QLabel()
        self.lbl_heatup_grace = QLabel()
        self.lbl_step_total_grace = QLabel()
        self.lbl_simulation = QLabel()

        layout.addRow("运行环境", self.lbl_app_env)
        layout.addRow("串口", self.lbl_serial_port)
        layout.addRow("波特率", self.lbl_baudrate)
        layout.addRow("设备地址", self.lbl_unit_id)
        layout.addRow("映射 Profile", self.lbl_mapping_profile)
        layout.addRow("轮询周期(ms)", self.lbl_poll_interval)
        layout.addRow("升温超时宽限(s)", self.lbl_heatup_grace)
        layout.addRow("步骤总超时宽限(s)", self.lbl_step_total_grace)
        layout.addRow("模拟模式", self.lbl_simulation)

        self.refresh()

    def refresh(self) -> None:
        self.lbl_app_env.setText(self._settings.app_env)
        self.lbl_serial_port.setText(self._settings.serial_port)
        self.lbl_baudrate.setText(str(self._settings.baudrate))
        self.lbl_unit_id.setText(str(self._settings.modbus_unit_id))
        self.lbl_mapping_profile.setText(self._settings.mapping_profile)
        self.lbl_poll_interval.setText(str(self._settings.poll_interval_ms))
        self.lbl_heatup_grace.setText(str(self._settings.step_heatup_grace_seconds))
        self.lbl_step_total_grace.setText(str(self._settings.step_total_grace_seconds))
        self.lbl_simulation.setText("是" if self._settings.simulation_mode else "否")
