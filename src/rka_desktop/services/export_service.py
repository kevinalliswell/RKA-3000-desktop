from __future__ import annotations

from pathlib import Path

import pandas as pd

from rka_desktop.db.database import DatabaseManager


class ExportService:
    def __init__(self, db: DatabaseManager) -> None:
        self.db = db

    def export_measurements_csv(self, experiment_id: int, file_path: Path) -> Path:
        rows = self.db.fetch_measurements(experiment_id)
        if not rows:
            raise ValueError("当前实验没有可导出的测量数据")

        file_path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(rows)
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        return file_path

    def export_measurements_excel(self, experiment_id: int, file_path: Path) -> Path:
        rows = self.db.fetch_measurements(experiment_id)
        if not rows:
            raise ValueError("当前实验没有可导出的测量数据")

        file_path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame(rows)
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="measurements")
        return file_path

    def export_experiment_summary_csv(self, experiment_id: int, file_path: Path) -> Path:
        summary = self.db.get_experiment_summary(experiment_id)
        if not summary:
            raise ValueError("当前实验没有可导出的摘要数据")

        file_path.parent.mkdir(parents=True, exist_ok=True)
        df = pd.DataFrame([summary])
        df.to_csv(file_path, index=False, encoding="utf-8-sig")
        return file_path
