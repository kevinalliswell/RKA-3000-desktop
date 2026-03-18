from datetime import datetime

import pytest

from rka_desktop.db.database import DatabaseManager
from rka_desktop.models.entities import Measurement

pandas = pytest.importorskip("pandas")

from rka_desktop.services.export_service import ExportService


def test_export_csv_and_excel(tmp_path):
    db_file = tmp_path / "export.db"
    db = DatabaseManager(db_file)
    db.init_schema()

    exp_id = db.create_experiment("exp-export")
    db.insert_measurement(
        Measurement(
            experiment_id=exp_id,
            sampled_at=datetime.now(),
            temperature_c=920.0,
            weight_g=86.5,
            pressure_mpa=0.02,
            n2_lpm=4.1,
            h2_lpm=1.0,
            co_lpm=0.7,
        )
    )

    service = ExportService(db)
    csv_path = tmp_path / "exp.csv"
    xlsx_path = tmp_path / "exp.xlsx"

    service.export_measurements_csv(exp_id, csv_path)
    service.export_measurements_excel(exp_id, xlsx_path)

    assert csv_path.exists()
    assert xlsx_path.exists()


def test_export_summary_csv(tmp_path):
    db_file = tmp_path / "summary.db"
    db = DatabaseManager(db_file)
    db.init_schema()

    exp_id = db.create_experiment("exp-summary")
    db.insert_measurement(
        Measurement(
            experiment_id=exp_id,
            sampled_at=datetime.now(),
            temperature_c=900.0,
            weight_g=80.0,
            pressure_mpa=0.02,
            n2_lpm=4.0,
            h2_lpm=1.1,
            co_lpm=0.6,
        )
    )

    service = ExportService(db)
    summary_path = tmp_path / "summary.csv"
    service.export_experiment_summary_csv(exp_id, summary_path)

    assert summary_path.exists()
