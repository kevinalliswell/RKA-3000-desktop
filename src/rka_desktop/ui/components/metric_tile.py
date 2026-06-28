"""MetricTile — a reusable KPI block: a labelled value with optional unit and icon."""

from __future__ import annotations

import qtawesome as qta
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from rka_desktop.ui.theme import ACCENT


class MetricTile(QFrame):
    def __init__(
        self,
        label: str,
        value: str = "--",
        unit: str = "",
        icon: str | None = None,
        accent: str = ACCENT,
    ) -> None:
        super().__init__()
        self.setObjectName("metricTile")
        self.setProperty("accent", accent)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 13, 16, 13)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(7)
        if icon:
            badge = QLabel()
            badge.setObjectName("metricIcon")
            badge.setPixmap(qta.icon(icon, color=accent).pixmap(16, 16))
            top.addWidget(badge)
        self._label = QLabel(label)
        self._label.setObjectName("metricLabel")
        top.addWidget(self._label)
        top.addStretch()
        root.addLayout(top)

        value_row = QHBoxLayout()
        value_row.setSpacing(5)
        self._value = QLabel(value)
        self._value.setObjectName("metricValue")
        value_row.addWidget(self._value, 0, Qt.AlignmentFlag.AlignBottom)
        if unit:
            self._unit = QLabel(unit)
            self._unit.setObjectName("metricUnit")
            value_row.addWidget(self._unit, 0, Qt.AlignmentFlag.AlignBottom)
        value_row.addStretch()
        root.addLayout(value_row)

    def set_value(self, value: str) -> None:
        self._value.setText(str(value))

    def value(self) -> str:
        return self._value.text()
