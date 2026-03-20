from datetime import datetime

from rka_desktop.controllers.history_export_controller import HistoryExportController
from rka_desktop.core.config import Settings
from rka_desktop.db.database import DatabaseManager
from rka_desktop.models.entities import Measurement
from rka_desktop.services.export_service import ExportService


def _build_history_controller(tmp_path, db_name: str = "history_controller.db"):
    settings = Settings(
        db_path=str(tmp_path / db_name),
        simulation_mode=True,
    )
    db = DatabaseManager(settings.db_file)
    db.init_schema()
    controller = HistoryExportController(db, ExportService(db))
    return db, controller


def _seed_experiment_with_measurement(db: DatabaseManager) -> int:
    recipe_id = db.create_recipe(
        "历史配方",
        [
            {
                "step_no": 1,
                "target_temp_c": 900.0,
                "ramp_rate_cpm": 10.0,
                "hold_seconds": 60,
                "n2_lpm": 8.0,
                "h2_lpm": 1.0,
                "co_lpm": 0.8,
                "notes": "",
            }
        ],
    )
    exp_id = db.create_experiment("历史实验", recipe_id=recipe_id)
    db.insert_measurement(
        Measurement(
            experiment_id=exp_id,
            sampled_at=datetime(2026, 1, 1, 12, 0, 0),
            temperature_c=900.0,
            weight_g=100.0,
            pressure_mpa=0.0,
            n2_lpm=8.0,
            h2_lpm=1.0,
            co_lpm=0.8,
        )
    )
    db.finish_experiment(exp_id, status="COMPLETED")
    return exp_id


def test_history_controller_loads_history_and_summary(tmp_path):
    db, controller = _build_history_controller(tmp_path, "history_load.db")
    exp_id = _seed_experiment_with_measurement(db)

    transition = controller.load_history()

    assert transition.view_state is not None
    assert transition.view_state.selected_experiment_id == exp_id
    assert len(transition.view_state.experiments) == 1
    assert "样本数 1" in transition.view_state.summary_text


def test_history_controller_exports_selected_experiment(tmp_path):
    db, controller = _build_history_controller(tmp_path, "history_export.db")
    exp_id = _seed_experiment_with_measurement(db)
    out_path = tmp_path / "exports" / "experiment_1.csv"

    transition = controller.export_experiment(
        "csv",
        active_experiment_id=None,
        selected_experiment_id=exp_id,
        file_path=out_path,
    )

    assert transition.success is True
    assert transition.exported_path == out_path
    assert out_path.exists()
    assert transition.view_state is not None
    assert transition.view_state.selected_experiment_id == exp_id
