from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class HistoryPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

        toolbar = QHBoxLayout()
        self.btn_refresh = QPushButton("刷新历史")
        self.btn_rename = QPushButton("重命名实验")
        self.btn_delete = QPushButton("删除实验")
        toolbar.addWidget(self.btn_refresh)
        toolbar.addWidget(self.btn_rename)
        toolbar.addWidget(self.btn_delete)
        toolbar.addStretch()
        self.summary_label = QLabel("暂无历史实验")

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["实验ID", "名称", "状态", "配方", "开始时间", "结束时间"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)

        layout.addLayout(toolbar)
        layout.addWidget(self.summary_label)
        layout.addWidget(self.table)

    def set_experiments(self, experiments: list[dict[str, object]], selected_experiment_id: int | None = None) -> None:
        self.table.blockSignals(True)
        self.table.setRowCount(len(experiments))
        selected_row = -1
        for row, experiment in enumerate(experiments):
            experiment_id = int(experiment["id"])
            self.table.setItem(row, 0, QTableWidgetItem(str(experiment_id)))
            self.table.setItem(row, 1, QTableWidgetItem(str(experiment.get("name", ""))))
            self.table.setItem(row, 2, QTableWidgetItem(str(experiment.get("status", ""))))
            self.table.setItem(row, 3, QTableWidgetItem(str(experiment.get("recipe_name") or "--")))
            self.table.setItem(row, 4, QTableWidgetItem(str(experiment.get("started_at", ""))))
            self.table.setItem(row, 5, QTableWidgetItem(str(experiment.get("finished_at") or "--")))
            if selected_experiment_id == experiment_id:
                selected_row = row

        if selected_row >= 0:
            self.table.selectRow(selected_row)
        else:
            self.table.clearSelection()
        self.table.blockSignals(False)

    def set_summary(self, text: str) -> None:
        self.summary_label.setText(text)

    def selected_experiment_id(self) -> int | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        try:
            return int(item.text())
        except ValueError:
            return None
