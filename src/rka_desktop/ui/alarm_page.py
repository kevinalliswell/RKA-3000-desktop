from __future__ import annotations

from PySide6.QtWidgets import (
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class AlarmPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        self.current_alarm_label = QLabel("当前报警: 无")
        self.current_interlock_label = QLabel("当前联锁: 无联锁")
        self.btn_ack_alarm = QPushButton("确认报警")
        self.btn_reset_interlock = QPushButton("联锁复位")
        self.btn_ack_alarm.setEnabled(False)
        self.btn_reset_interlock.setEnabled(False)

        self.pending_table = QTableWidget(0, 4)
        self.pending_table.setHorizontalHeaderLabels(["编码", "级别", "消息", "创建时间"])
        self.pending_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

        layout.addWidget(self.current_alarm_label)
        layout.addWidget(self.current_interlock_label)
        layout.addWidget(self.btn_ack_alarm)
        layout.addWidget(self.btn_reset_interlock)
        layout.addWidget(self.pending_table)

    def set_current_alarm(self, text: str) -> None:
        self.current_alarm_label.setText(text)

    def set_current_interlock(self, text: str) -> None:
        self.current_interlock_label.setText(text)

    def set_pending_alarms(self, alarms: list[dict[str, object]]) -> None:
        self.pending_table.setRowCount(len(alarms))
        for row, alarm in enumerate(alarms):
            self.pending_table.setItem(row, 0, QTableWidgetItem(str(alarm.get("code", ""))))
            self.pending_table.setItem(row, 1, QTableWidgetItem(str(alarm.get("level", ""))))
            self.pending_table.setItem(row, 2, QTableWidgetItem(str(alarm.get("message", ""))))
            self.pending_table.setItem(row, 3, QTableWidgetItem(str(alarm.get("created_at", ""))))
