import pytest

pytest.importorskip("PySide6")

from datetime import datetime, timedelta
from pathlib import Path

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

    assert window.tabs.count() == 7
    assert window.tabs.tabText(1) == "监控"
    assert window.tabs.tabText(2) == "数据分析"
    assert window.tabs.tabText(5) == "日志"
    # device status is a nested secondary view under 监控, not a top-level tab
    assert window.monitor_tabs.count() == 2
    assert window.monitor_tabs.tabText(1) == "设备状态"
    assert window.multi_device_page.mfc_table.rowCount() == 6
    assert window.recipe_page.recipe_table.columnCount() == 8
    assert window.recipe_page.sections.count() == 3
    assert window.settings_page.sections.count() == 5
    assert window.multi_device_page.sections.count() == 4
    assert window.analysis_page.sections.count() == 2
    assert window.reports_page.sections.count() == 3
    assert window.settings_page.gas_limit_table.item(6, 2).text() == "待映射"
    assert window.alarm_page.btn_ack_alarm.isEnabled() is False
    assert window.alarm_page.btn_reset_interlock.isEnabled() is False
    assert window.btn_pause.isEnabled() is False
    assert window.btn_resume.isEnabled() is False
    assert window.history_page.table.columnCount() == 6
    assert window.history_page.sections.count() == 3
    assert window.alarm_page.sections.count() == 2
    assert window.log_page.sections.count() == 3
    assert window.monitor_page.lbl_control_feedback.text() == "控制反馈: --"
    assert window.monitor_page.sections.count() == 5
    assert window.monitor_page.gas_table.rowCount() == 7
    assert window.monitor_page.gas_table.item(6, 2).text() == "未完成真机映射"
    # redesign: tabs carry icons, header/status bar present
    assert not window.tabs.tabIcon(2).isNull()
    assert "仿真模式" in window.statusBar().currentMessage()
    assert len(window.nav_buttons) == 12
    assert window.current_page == "overview"
    window.navigate("devices")
    assert window.page_stack.currentWidget() is window.tabs
    assert window.monitor_tabs.currentWidget() is window.multi_device_page
    assert not window.multi_device_page.btn_apply_flows.isEnabled()
    window.navigate("preflight")
    assert window.page_stack.currentWidget() is window.preflight_page
    assert window.preflight_page.steps.count() == 3
    assert "现场确认" in window.preflight_page.missing_fields()
    window.navigate("reports")
    assert window.page_stack.currentWidget() is window.reports_page
    window.btn_theme.click()
    assert window.theme_mode == "light"
    window.btn_theme.click()
    assert window.theme_mode == "dark"

    window.close()
    app.quit()


def test_real_mode_without_device_profile_starts_with_diagnostics_unavailable(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = Settings(db_path=str(tmp_path / "unconfigured.db"), simulation_mode=False)
    db = DatabaseManager(settings.db_file)
    db.init_schema()
    client = ModbusRtuClient(serial_port="unused", baudrate=9600, unit_id=1, simulation_mode=False)
    window = MainWindow(settings=settings, db=db, client=client)
    assert window.multi_gateway is None
    assert "DEVICE_PROFILE_PATH" in window.multi_device_page.lbl_status.text()
    assert not window.multi_device_page.btn_set_temp.isEnabled()
    window.close()
    app.quit()


def test_read_only_device_profile_does_not_open_serial_or_change_simulated_main_link(tmp_path):
    app = QApplication.instance() or QApplication([])
    profile = Path(__file__).resolve().parents[1] / "config/device-profile.example.json"
    settings = Settings(
        db_path=str(tmp_path / "diagnostic.db"), simulation_mode=True,
        device_profile_path=str(profile),
    )
    db = DatabaseManager(settings.db_file)
    db.init_schema()
    client = ModbusRtuClient(serial_port="unused", baudrate=9600, unit_id=1, simulation_mode=True)
    window = MainWindow(settings=settings, db=db, client=client)
    assert window.multi_gateway is not None
    assert not window.multi_gateway.is_connected
    assert client.simulation_mode is True
    assert "只读诊断未连接" in window.multi_device_page.lbl_status.text()
    window.close()
    app.quit()


class _FakeWorker:
    def __init__(self) -> None:
        self.stopped = False

    def stop(self) -> None:
        self.stopped = True


def test_preflight_records_sample_and_requires_operator_checks(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = Settings(db_path=str(tmp_path / "preflight.db"), simulation_mode=True)
    db = DatabaseManager(settings.db_file)
    db.init_schema()
    db.create_recipe("试验配方", [{
        "step_no": 1, "target_temp_c": 900, "ramp_rate_cpm": 10,
        "hold_seconds": 600, "n2_lpm": 4.0, "h2_lpm": 1.0,
        "co_lpm": 0.5, "notes": "",
    }])
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)
    window = MainWindow(settings, db, client)
    assert window.recipe_page.list_table.rowCount() == 1
    window.recipe_page.list_table.selectRow(0)
    window.recipe_page.btn_edit_selected.click()
    assert window.recipe_combo.currentData() == 1
    assert window.recipe_page.sections.currentIndex() == 1
    warnings = []
    window.dialogs.warning = lambda _title, message: warnings.append(message)
    window.dialogs.confirm = lambda *_args: True
    window.runtime.start = lambda _experiment_id: setattr(window.runtime, "worker", _FakeWorker())

    window.preflight_page.steps.setCurrentIndex(2)
    window.preflight_page.btn_start.click()
    assert window.experiment_id is None
    assert "现场确认" in warnings[-1]

    preflight = window.preflight_page
    preflight.sample_name.setText("球团矿 A-19")
    preflight.mass.setValue(54.280)
    preflight.tfe.setValue(64.21)
    preflight.feo.setValue(8.42)
    preflight.operator.setText("实验员 A")
    for check in preflight.checks:
        check.setChecked(True)
    preflight.btn_start.click()

    detail = db.get_experiment_detail(window.experiment_id)
    assert detail is not None
    assert detail["name"] == "球团矿 A-19"
    assert detail["initial_mass_g"] == 54.28
    assert detail["tfe_pct"] == 64.21
    assert window.current_page == "current"
    window.close()
    app.quit()


def test_history_subpages_show_selected_record_data(tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = Settings(db_path=str(tmp_path / "history_sections.db"), simulation_mode=True)
    db = DatabaseManager(settings.db_file)
    db.init_schema()
    experiment_id = db.create_experiment("样品 A")
    db.insert_measurement(Measurement(
        experiment_id=experiment_id,
        sampled_at=datetime(2026, 1, 1, 12, 0, 0),
        temperature_c=900, weight_g=54.2, pressure_mpa=0.1,
        n2_lpm=4, h2_lpm=1, co_lpm=0.5,
    ))
    db.create_alarm(experiment_id, "TEST", "WARN", "测试报警")
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)
    window = MainWindow(settings, db, client)
    window.history_page.table.selectRow(0)
    assert window.history_page.measurement_table.rowCount() == 1
    assert window.history_page.measurement_table.item(0, 2).text() == "54.2"
    assert window.history_page.alarm_table.rowCount() == 1
    assert window.alarm_page.history_table.rowCount() == 1
    window.navigate("reports")
    assert window.reports_page.experiment_table.rowCount() == 1
    window.close()
    app.quit()


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
    app, _db, _client, window, exp_id, worker = _build_running_window(tmp_path, "ui_feedback_mismatch.db")
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
