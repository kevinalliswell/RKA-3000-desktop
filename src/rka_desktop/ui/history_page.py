from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class HistoryPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.sections = QTabWidget()
        summary_page = QWidget()
        summary_layout = QVBoxLayout(summary_page)

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

        summary_layout.addLayout(toolbar)
        summary_layout.addWidget(self.summary_label)
        summary_layout.addWidget(self.table)

        self.measurement_table = QTableWidget(0, 7)
        self.measurement_table.setHorizontalHeaderLabels(
            ("采样时间", "温度 ℃", "质量 g", "压力 MPa", "N₂ L/min", "H₂ L/min", "CO L/min")
        )
        self.measurement_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.measurement_table.verticalHeader().hide()
        self.alarm_table = QTableWidget(0, 5)
        self.alarm_table.setHorizontalHeaderLabels(("时间", "编码", "级别", "消息", "确认状态"))
        self.alarm_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.alarm_table.verticalHeader().hide()
        self.sections.addTab(summary_page, "实验列表")
        self.sections.addTab(self.measurement_table, "原始数据")
        self.sections.addTab(self.alarm_table, "报警记录")
        layout.addWidget(self.sections)

    def set_measurements(self, measurements: list[dict[str, object]]) -> None:
        self.measurement_table.setRowCount(len(measurements))
        for row, measurement in enumerate(measurements):
            values = (
                measurement.get("sampled_at"), measurement.get("temperature_c"),
                measurement.get("weight_g"), measurement.get("pressure_mpa"),
                measurement.get("n2_lpm"), measurement.get("h2_lpm"),
                measurement.get("co_lpm"),
            )
            for col, value in enumerate(values):
                self.measurement_table.setItem(
                    row, col, QTableWidgetItem(str(value if value is not None and value != "" else "--"))
                )

    def set_alarm_history(self, alarms: list[dict[str, object]]) -> None:
        self.alarm_table.setRowCount(len(alarms))
        for row, alarm in enumerate(alarms):
            values = (
                alarm.get("created_at"), alarm.get("code"), alarm.get("level"),
                alarm.get("message"), "已确认" if alarm.get("acknowledged_at") else "待确认",
            )
            for col, value in enumerate(values):
                self.alarm_table.setItem(row, col, QTableWidgetItem(str(value or "--")))

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
