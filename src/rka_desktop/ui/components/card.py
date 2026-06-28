"""Card — a reusable titled container block with a content body."""

from __future__ import annotations

from PySide6.QtWidgets import QHBoxLayout, QFrame, QLabel, QLayout, QVBoxLayout, QWidget


class Card(QFrame):
    def __init__(self, title: str | None = None) -> None:
        super().__init__()
        self.setObjectName("card")
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(16, 14, 16, 16)
        self._root.setSpacing(12)

        self._header_row: QHBoxLayout | None = None
        if title is not None:
            self._header_row = QHBoxLayout()
            self._title = QLabel(title)
            self._title.setObjectName("cardTitle")
            self._header_row.addWidget(self._title)
            self._header_row.addStretch()
            self._root.addLayout(self._header_row)

        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        self._root.addLayout(self.body)

    def add_header_widget(self, widget: QWidget) -> None:
        """Add a widget to the right side of the card's title row (e.g. a button)."""
        if self._header_row is None:
            self._header_row = QHBoxLayout()
            self._header_row.addStretch()
            self._root.insertLayout(0, self._header_row)
        self._header_row.addWidget(widget)

    def add_widget(self, widget: QWidget) -> None:
        self.body.addWidget(widget)

    def add_layout(self, layout: QLayout) -> None:
        self.body.addLayout(layout)
