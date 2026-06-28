from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

_HEADERS = ("时间", "操作者", "动作", "详情")


class LogPage(QWidget):
    """日志: shows the audit-log trail of operator actions."""

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.btn_refresh = QPushButton("刷新日志")
        self.table = QTableWidget(0, len(_HEADERS))
        self.table.setHorizontalHeaderLabels(_HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.btn_refresh)
        layout.addWidget(self.table)

    def set_logs(self, logs: list[dict[str, Any]]) -> None:
        self.table.setRowCount(len(logs))
        for row, entry in enumerate(logs):
            values = (
                entry.get("created_at", ""),
                entry.get("actor", ""),
                entry.get("action", ""),
                entry.get("detail", ""),
            )
            for col, value in enumerate(values):
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
