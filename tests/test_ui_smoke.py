import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from rka_desktop.core.config import Settings
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.db.database import DatabaseManager
from rka_desktop.services.experiment_engine import ExperimentEngine
from rka_desktop.services.recipe_runtime_service import build_recipe_runtime
from rka_desktop.ui.main_window import MainWindow


def test_main_window_smoke(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = Settings(
        db_path=str(tmp_path / "ui.db"),
        simulation_mode=True,
    )
    db = DatabaseManager(settings.db_file)
    db.init_schema()
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)

    window = MainWindow(settings=settings, db=db, client=client)

    assert window.tabs.count() == 4
    assert window.recipe_page.recipe_table.columnCount() == 8
    assert window.alarm_page.btn_ack_alarm.isEnabled() is False
    assert window.alarm_page.btn_reset_interlock.isEnabled() is False
    assert window.btn_pause.isEnabled() is False
    assert window.btn_resume.isEnabled() is False

    window.close()
    app.quit()


class _FakeWorker:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def test_main_window_faults_active_experiment_on_acquisition_error(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = Settings(
        db_path=str(tmp_path / "ui_fault.db"),
        simulation_mode=True,
    )
    db = DatabaseManager(settings.db_file)
    db.init_schema()
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)
    window = MainWindow(settings=settings, db=db, client=client)

    exp_id = db.create_experiment("fault-exp")
    window.experiment_id = exp_id
    window.engine = ExperimentEngine(
        build_recipe_runtime(
            [
                {
                    "step_no": 1,
                    "target_temp_c": 900,
                    "ramp_rate_cpm": 10,
                    "hold_seconds": 30,
                    "n2_lpm": 4.0,
                    "h2_lpm": 1.0,
                    "co_lpm": 0.5,
                    "notes": "",
                }
            ]
        )
    )
    window.engine.start()
    worker = _FakeWorker()
    window.worker = worker

    window._on_error("serial timeout")

    detail = db.get_experiment_detail(exp_id)
    assert detail is not None
    assert detail["status"] == "FAULTED"
    assert worker.stopped is True
    assert window.worker is None
    assert window.engine is None

    window.close()
    app.quit()
