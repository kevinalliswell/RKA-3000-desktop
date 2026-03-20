from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)


class RecipePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)

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
        layout.addLayout(header)

        self.recipe_table = QTableWidget(0, 8)
        self.recipe_table.setHorizontalHeaderLabels(
            ["步骤", "目标温度℃", "升温速率℃/min", "保温秒", "N2", "H2", "CO", "备注"]
        )
        self.recipe_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.recipe_table)

        footer = QHBoxLayout()
        footer.addWidget(self.btn_recipe_save)
        footer.addWidget(self.btn_recipe_update)
        footer.addStretch()
        layout.addLayout(footer)

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
