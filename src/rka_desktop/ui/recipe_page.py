from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)


class RecipePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.sections = QTabWidget()
        list_page = QWidget()
        list_layout = QVBoxLayout(list_page)
        list_actions = QHBoxLayout()
        self.btn_new_recipe = QPushButton("新建配方")
        self.btn_edit_selected = QPushButton("编辑所选配方")
        list_actions.addWidget(self.btn_new_recipe)
        list_actions.addWidget(self.btn_edit_selected)
        list_actions.addStretch()
        list_layout.addLayout(list_actions)
        self.list_table = QTableWidget(0, 2)
        self.list_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.list_table.setHorizontalHeaderLabels(("编号", "配方名称"))
        self.list_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.list_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        list_layout.addWidget(self.list_table)

        editor_page = QWidget()
        editor_layout = QVBoxLayout(editor_page)

        header = QHBoxLayout()
        self.recipe_name_input = QLineEdit()
        self.recipe_name_input.setPlaceholderText("输入配方名称，例如：高温还原-标准流程")

        self.btn_recipe_add = QPushButton("新增步骤")
        self.btn_recipe_remove = QPushButton("删除步骤")
        self.btn_recipe_save = QPushButton("保存新配方")
        self.btn_recipe_update = QPushButton("更新当前配方")

        header.addWidget(self.recipe_name_input)
        header.addWidget(self.btn_recipe_add)
        header.addWidget(self.btn_recipe_remove)
        editor_layout.addLayout(header)

        self.recipe_table = QTableWidget(0, 8)
        self.recipe_table.setHorizontalHeaderLabels(
            ["步骤", "目标温度℃", "升温速率℃/min", "保温秒", "N2", "H2", "CO", "备注"]
        )
        self.recipe_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        editor_layout.addWidget(self.recipe_table)

        footer = QHBoxLayout()
        footer.addWidget(self.btn_recipe_save)
        footer.addWidget(self.btn_recipe_update)
        footer.addStretch()
        editor_layout.addLayout(footer)

        version_page = QWidget()
        version_layout = QVBoxLayout(version_page)
        version_note = QLabel(
            "当前数据库会更新现有配方，尚未保存独立版本快照或审核记录。"
            "正式版本管理需补齐数据模型和审核流程。"
        )
        version_note.setWordWrap(True)
        version_layout.addWidget(version_note)
        version_layout.addStretch()
        self.sections.addTab(list_page, "配方列表")
        self.sections.addTab(editor_page, "阶段编辑")
        self.sections.addTab(version_page, "版本与审核")
        layout.addWidget(self.sections)

    def set_options(self, options: list[Any]) -> None:
        self.list_table.setRowCount(len(options))
        for row, option in enumerate(options):
            self.list_table.setItem(row, 0, QTableWidgetItem(str(option.recipe_id)))
            self.list_table.setItem(row, 1, QTableWidgetItem(option.label))

    def selected_list_recipe_id(self) -> int | None:
        item = self.list_table.item(self.list_table.currentRow(), 0)
        return int(item.text()) if item is not None else None

    def load_recipe(self, name: str, steps: list[dict[str, Any]]) -> None:
        self.recipe_name_input.setText(name)
        self.recipe_table.setRowCount(0)
        for step in steps:
            row = self.recipe_table.rowCount()
            self.recipe_table.insertRow(row)
            self.set_cell(row, 0, str(step["step_no"]))
            self.set_cell(row, 1, str(step["target_temp_c"]))
            self.set_cell(row, 2, str(step["ramp_rate_cpm"]))
            self.set_cell(row, 3, str(step["hold_seconds"]))
            self.set_cell(row, 4, str(step["n2_lpm"]))
            self.set_cell(row, 5, str(step["h2_lpm"]))
            self.set_cell(row, 6, str(step["co_lpm"]))
            self.set_cell(row, 7, str(step.get("notes", "")))

    def add_default_row(self) -> None:
        row = self.recipe_table.rowCount()
        self.recipe_table.insertRow(row)
        self.set_cell(row, 0, str(row + 1))
        self.set_cell(row, 1, "900")
        self.set_cell(row, 2, "10")
        self.set_cell(row, 3, "600")
        self.set_cell(row, 4, "8.0")
        self.set_cell(row, 5, "1.0")
        self.set_cell(row, 6, "0.8")
        self.set_cell(row, 7, "")

    def remove_current_row(self) -> None:
        row = self.recipe_table.currentRow()
        if row < 0:
            row = self.recipe_table.rowCount() - 1
        if row >= 0:
            self.recipe_table.removeRow(row)

    def collect_step_inputs(self) -> list[dict[str, str]]:
        steps: list[dict[str, str]] = []
        for row in range(self.recipe_table.rowCount()):
            steps.append(
                {
                    "step_no": self.cell_text(row, 0, str(row + 1)),
                    "target_temp_c": self.cell_text(row, 1, "0"),
                    "ramp_rate_cpm": self.cell_text(row, 2, "0"),
                    "hold_seconds": self.cell_text(row, 3, "0"),
                    "n2_lpm": self.cell_text(row, 4, "0"),
                    "h2_lpm": self.cell_text(row, 5, "0"),
                    "co_lpm": self.cell_text(row, 6, "0"),
                    "notes": self.cell_text(row, 7, ""),
                }
            )
        return steps

    def cell_text(self, row: int, col: int, default: str) -> str:
        item = self.recipe_table.item(row, col)
        if item is None:
            return default
        text = item.text().strip()
        return text if text else default

    def set_cell(self, row: int, col: int, text: str) -> None:
        self.recipe_table.setItem(row, col, QTableWidgetItem(text))
