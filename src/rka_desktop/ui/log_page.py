from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
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
        self.sections = QTabWidget()
        self.tables: dict[str, QTableWidget] = {}
        for key, label in (("all", "全部事件"), ("control", "控制操作"), ("safety", "报警与安全")):
            table = QTableWidget(0, len(_HEADERS))
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setHorizontalHeaderLabels(_HEADERS)
            table.verticalHeader().setVisible(False)
            table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
            self.sections.addTab(table, label)
            self.tables[key] = table
        self.table = self.tables["all"]
        layout.addWidget(self.btn_refresh)
        layout.addWidget(self.sections)

    def set_logs(self, logs: list[dict[str, Any]]) -> None:
        safety_words = ("ALARM", "INTERLOCK", "STOP", "FAULT", "EMERGENCY", "SAFETY")
        safety_logs = [entry for entry in logs if any(
            word in str(entry.get("action", "")).upper() for word in safety_words
        )]
        categories = {"all": logs, "safety": safety_logs,
                      "control": [entry for entry in logs if entry not in safety_logs]}
        for key, entries in categories.items():
            table = self.tables[key]
            table.setRowCount(len(entries))
            for row, entry in enumerate(entries):
                values = (
                    entry.get("created_at", ""), entry.get("actor", ""),
                    entry.get("action", ""), entry.get("detail", ""),
                )
                for col, value in enumerate(values):
                    table.setItem(row, col, QTableWidgetItem(str(value)))
