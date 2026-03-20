from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox, QWidget


class DialogService:
    def __init__(self, parent: QWidget) -> None:
        self.parent = parent

    def info(self, title: str, message: str) -> None:
        QMessageBox.information(self.parent, title, message)

    def warning(self, title: str, message: str) -> None:
        QMessageBox.warning(self.parent, title, message)

    def critical(self, title: str, message: str) -> None:
        QMessageBox.critical(self.parent, title, message)

    def confirm(self, title: str, message: str) -> bool:
        return QMessageBox.question(self.parent, title, message) == QMessageBox.StandardButton.Yes

    def select_save_path(self, title: str, default_path: Path, file_filter: str) -> Path | None:
        path, _ = QFileDialog.getSaveFileName(self.parent, title, str(default_path), file_filter)
        if not path:
            return None
        return Path(path)
