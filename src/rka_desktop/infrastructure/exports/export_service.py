"""CSV / Excel exports of experiment data using the standard library and openpyxl.

Column names and order match the pre-migration pandas exports so downstream spreadsheets
keep working: ``sampled_at, temperature_c, weight_g, pressure_mpa, n2_lpm, h2_lpm, co_lpm``.
"""

from __future__ import annotations

import csv
from collections.abc import Callable
from pathlib import Path
from typing import Any

from openpyxl import Workbook

MEASUREMENT_COLUMNS = ("sampled_at", "temperature_c", "weight_g", "pressure_mpa", "n2_lpm", "h2_lpm", "co_lpm")
SUMMARY_COLUMNS = (
    "experiment_id", "sample_count", "first_sampled_at", "last_sampled_at",
    "min_temperature_c", "max_temperature_c", "min_weight_g", "max_weight_g",
)


class NothingToExport(ValueError):
    pass


def _write_atomic(path: Path, writer: Callable[[Path], None]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".part")
    try:
        writer(temp)
        temp.replace(path)
    finally:
        temp.unlink(missing_ok=True)
    return path


def write_measurements_csv(rows: list[dict[str, Any]], path: Path) -> Path:
    if not rows:
        raise NothingToExport("当前实验没有可导出的测量数据")

    def writer(target: Path) -> None:
        with target.open("w", encoding="utf-8-sig", newline="") as stream:
            out = csv.writer(stream)
            out.writerow(MEASUREMENT_COLUMNS)
            for row in rows:
                out.writerow([row.get(column) for column in MEASUREMENT_COLUMNS])

    return _write_atomic(path, writer)


def write_measurements_excel(rows: list[dict[str, Any]], path: Path) -> Path:
    if not rows:
        raise NothingToExport("当前实验没有可导出的测量数据")

    def writer(target: Path) -> None:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "measurements"
        sheet.append(list(MEASUREMENT_COLUMNS))
        for row in rows:
            sheet.append([row.get(column) for column in MEASUREMENT_COLUMNS])
        workbook.save(target)

    return _write_atomic(path, writer)


def write_summary_csv(summary: dict[str, Any] | None, path: Path) -> Path:
    if not summary:
        raise NothingToExport("当前实验没有可导出的摘要数据")

    def writer(target: Path) -> None:
        with target.open("w", encoding="utf-8-sig", newline="") as stream:
            out = csv.writer(stream)
            out.writerow(SUMMARY_COLUMNS)
            out.writerow([summary.get(column) for column in SUMMARY_COLUMNS])

    return _write_atomic(path, writer)
