import pytest

pytest.importorskip("PySide6")

from datetime import datetime, timedelta

from PySide6.QtWidgets import QApplication

from rka_desktop.core.config import Settings
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.db.database import DatabaseManager
from rka_desktop.models.entities import DeviceSnapshot, Measurement
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
    assert window.monitor_page.lbl_control_feedback.text() == "控制反馈: --"

    window.close()
    app.quit()


class _FakeWorker:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def _build_running_window(tmp_path, db_name: str = "ui_runtime.db"):
    app = QApplication.instance() or QApplication([])
    settings = Settings(
        db_path=str(tmp_path / db_name),
        simulation_mode=True,
    )
    db = DatabaseManager(settings.db_file)
    db.init_schema()
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)
    window = MainWindow(settings=settings, db=db, client=client)

    exp_id = db.create_experiment("runtime-exp")
    window.experiment_id = exp_id
    window.engine = ExperimentEngine(
        build_recipe_runtime(
            [
                {
                    "step_no": 1,
                    "target_temp_c": 900,
                    "ramp_rate_cpm": 10,
                    "hold_seconds": 0,
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
    return app, db, client, window, exp_id, worker


def test_main_window_faults_active_experiment_on_acquisition_error(tmp_path):
    app, db, client, window, exp_id, worker = _build_running_window(tmp_path, "ui_fault.db")

    window._on_error("serial timeout")

    detail = db.get_experiment_detail(exp_id)
    assert detail is not None
    assert detail["status"] == "FAULTED"
    assert client.last_run_control_command == "stop"
    assert worker.stopped is True
    assert window.worker is None
    assert window.engine is None

    window.close()
    app.quit()


def test_main_window_interrupt_syncs_pause_command(tmp_path):
    app, db, client, window, exp_id, worker = _build_running_window(tmp_path, "ui_interrupt.db")
    snapshot = DeviceSnapshot(
        temperature_c=900.0,
        weight_g=100.0,
        pressure_mpa=0.1,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
        alarm_word=0x0001,
        interlock_word=0,
        run_control_word=0,
        estop_status=0,
    )
    measurement = Measurement(
        experiment_id=exp_id,
        sampled_at=datetime(2026, 1, 1, 12, 0, 0),
        temperature_c=900.0,
        weight_g=100.0,
        pressure_mpa=0.1,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
    )

    window._on_snapshot((snapshot, measurement))

    detail = db.get_experiment_detail(exp_id)
    assert detail is not None
    assert detail["status"] == "INTERRUPTED"
    assert client.last_run_control_command == "pause"
    assert worker.stopped is False
    assert window.engine is not None
    assert "报警处理中" in window.monitor_page.lbl_execution.text()

    window.close()
    app.quit()


def test_main_window_completion_syncs_stop_command(tmp_path):
    app, db, client, window, exp_id, worker = _build_running_window(tmp_path, "ui_complete.db")
    sampled_at = datetime(2026, 1, 1, 12, 0, 0)

    first_snapshot = DeviceSnapshot(
        temperature_c=900.0,
        weight_g=100.0,
        pressure_mpa=0.1,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
        alarm_word=0,
        interlock_word=0,
        run_control_word=0,
        estop_status=0,
    )
    first_measurement = Measurement(
        experiment_id=exp_id,
        sampled_at=sampled_at,
        temperature_c=900.0,
        weight_g=100.0,
        pressure_mpa=0.1,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
    )
    second_measurement = Measurement(
        experiment_id=exp_id,
        sampled_at=sampled_at + timedelta(seconds=1),
        temperature_c=900.0,
        weight_g=99.5,
        pressure_mpa=0.1,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
    )

    window._on_snapshot((first_snapshot, first_measurement))
    window._on_snapshot((first_snapshot, second_measurement))

    detail = db.get_experiment_detail(exp_id)
    assert detail is not None
    assert detail["status"] == "COMPLETED"
    assert client.last_run_control_command == "stop"
    assert worker.stopped is True
    assert window.worker is None
    assert window.engine is None

    window.close()
    app.quit()


def test_main_window_marks_control_feedback_mismatch(tmp_path):
    app, db, _client, window, exp_id, worker = _build_running_window(tmp_path, "ui_feedback_mismatch.db")
    window.client.last_run_control_command = "start"
    window.client.last_run_control_word = 0x0001

    snapshot = DeviceSnapshot(
        temperature_c=900.0,
        weight_g=100.0,
        pressure_mpa=0.1,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
        alarm_word=0,
        interlock_word=0,
        run_control_word=0x0010,
        estop_status=0,
    )
    measurement = Measurement(
        experiment_id=exp_id,
        sampled_at=datetime(2026, 1, 1, 12, 0, 0),
        temperature_c=900.0,
        weight_g=100.0,
        pressure_mpa=0.1,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
    )

    window._on_snapshot((snapshot, measurement))

    assert "不一致" in window.monitor_page.lbl_control_feedback.text()
    assert worker.stopped is False

    window.close()
    app.quit()
