from datetime import datetime

from rka_desktop.controllers.experiment_controller import ExperimentController
from rka_desktop.core.config import Settings
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.db.database import DatabaseManager
from rka_desktop.hardware.device_gateway import DeviceGateway
from rka_desktop.models.entities import DeviceSnapshot, Measurement
from rka_desktop.repositories import AlarmRepository, AuditLogRepository, ExperimentRepository, RecipeRepository


def _build_controller(tmp_path, db_name: str = "controller.db"):
    settings = Settings(
        db_path=str(tmp_path / db_name),
        simulation_mode=True,
    )
    db = DatabaseManager(settings.db_file)
    db.init_schema()
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)
    gateway = DeviceGateway(client)
    controller = ExperimentController(
        settings=settings,
        recipe_repository=RecipeRepository(db),
        experiment_repository=ExperimentRepository(db),
        alarm_repository=AlarmRepository(db),
        audit_repository=AuditLogRepository(db),
        gateway=gateway,
    )
    return settings, db, client, controller


def _create_recipe(db: DatabaseManager) -> int:
    return db.create_recipe(
        "标准流程",
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
        ],
    )


def test_controller_starts_experiment(tmp_path):
    _settings, db, client, controller = _build_controller(tmp_path, "controller_start.db")
    recipe_id = _create_recipe(db)

    transition = controller.start_experiment(recipe_id)

    assert transition.success is True
    assert transition.experiment_id is not None
    assert transition.recipe_name == "标准流程"
    assert client.last_run_control_command == "start"
    assert controller.engine is not None


def test_controller_completes_experiment_from_measurements(tmp_path):
    _settings, db, client, controller = _build_controller(tmp_path, "controller_complete.db")
    recipe_id = _create_recipe(db)
    start = controller.start_experiment(recipe_id)
    exp_id = start.experiment_id
    assert exp_id is not None

    first = Measurement(
        experiment_id=exp_id,
        sampled_at=datetime(2026, 1, 1, 12, 0, 0),
        temperature_c=900.0,
        weight_g=100.0,
        pressure_mpa=0.0,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
    )
    second = Measurement(
        experiment_id=exp_id,
        sampled_at=datetime(2026, 1, 1, 12, 0, 1),
        temperature_c=900.0,
        weight_g=99.8,
        pressure_mpa=0.0,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
    )

    controller.process_measurement(first)
    transition = controller.process_measurement(second)
    detail = db.get_experiment_detail(exp_id)

    assert transition is not None
    assert transition.final_status == "COMPLETED"
    assert detail is not None
    assert detail["status"] == "COMPLETED"
    assert client.last_run_control_command == "stop"
    assert controller.engine is None


def test_controller_faults_on_acquisition_error(tmp_path):
    _settings, db, client, controller = _build_controller(tmp_path, "controller_fault.db")
    recipe_id = _create_recipe(db)
    start = controller.start_experiment(recipe_id)
    exp_id = start.experiment_id
    assert exp_id is not None

    transition = controller.fail_active_experiment(
        "采集异常，实验已故障停止: serial timeout",
        audit_action="ACQUISITION_FAILED",
        detail=f"id={exp_id},error=serial timeout",
    )
    detail = db.get_experiment_detail(exp_id)

    assert transition.final_status == "FAULTED"
    assert detail is not None
    assert detail["status"] == "FAULTED"
    assert client.last_run_control_command == "stop"


def test_controller_interrupts_from_alarm_snapshot(tmp_path):
    settings, db, client, controller = _build_controller(tmp_path, "controller_interrupt.db")
    recipe_id = _create_recipe(db)
    start = controller.start_experiment(recipe_id)
    exp_id = start.experiment_id
    assert exp_id is not None

    snapshot = DeviceSnapshot(
        temperature_c=900.0,
        weight_g=100.0,
        pressure_mpa=0.0,
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
        pressure_mpa=0.0,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
    )

    transition = controller.handle_snapshot(snapshot, measurement)
    detail = db.get_experiment_detail(exp_id)

    assert transition.update is not None
    assert transition.update.state.value == "INTERRUPTED"
    assert transition.view_state is not None
    assert transition.view_state.resume_enabled is False
    assert "报警处理中" in (transition.view_state.execution_text or "")
    assert detail is not None
    assert detail["status"] == "INTERRUPTED"
    assert client.last_run_control_command == "pause"


def test_controller_blocks_resume_when_alarm_is_active(tmp_path):
    _settings, db, _client, controller = _build_controller(tmp_path, "controller_resume_block.db")
    recipe_id = _create_recipe(db)
    start = controller.start_experiment(recipe_id)
    exp_id = start.experiment_id
    assert exp_id is not None

    controller.interrupt_experiment(f"id={exp_id},alarm=0001")
    controller.handle_snapshot(
        DeviceSnapshot(
            temperature_c=900.0,
            weight_g=100.0,
            pressure_mpa=0.0,
            n2_lpm=4.0,
            h2_lpm=1.0,
            co_lpm=0.5,
            alarm_word=0x0001,
            interlock_word=0,
            run_control_word=0,
            estop_status=0,
        ),
        Measurement(
            experiment_id=exp_id,
            sampled_at=datetime(2026, 1, 1, 12, 0, 0),
            temperature_c=900.0,
            weight_g=100.0,
            pressure_mpa=0.0,
            n2_lpm=4.0,
            h2_lpm=1.0,
            co_lpm=0.5,
        ),
    )

    transition = controller.resume_experiment()

    assert transition is not None
    assert transition.success is False
    assert transition.user_message == "当前仍有活动报警，请先排除报警"
