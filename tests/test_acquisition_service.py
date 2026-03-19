from datetime import datetime

from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.db.database import DatabaseManager
from rka_desktop.models.entities import DeviceSnapshot, Measurement
from rka_desktop.services.acquisition_service import AcquisitionWorker


def _build_snapshot(temp: float = 900.0) -> DeviceSnapshot:
    return DeviceSnapshot(
        temperature_c=temp,
        weight_g=88.0,
        pressure_mpa=0.02,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
        alarm_word=0,
        interlock_word=0,
        run_control_word=0,
        estop_status=0,
    )


def _build_measurement(experiment_id: int, temp: float = 900.0) -> Measurement:
    return Measurement(
        experiment_id=experiment_id,
        sampled_at=datetime(2026, 1, 1, 12, 0, 0),
        temperature_c=temp,
        weight_g=88.0,
        pressure_mpa=0.02,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
    )


def test_acquisition_worker_flushes_on_batch_size(tmp_path):
    db = DatabaseManager(tmp_path / "acq_batch.db")
    db.init_schema()
    exp_id = db.create_experiment("acq-batch")
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)
    worker = AcquisitionWorker(client=client, db=db, experiment_id=exp_id, poll_interval_ms=100, batch_size=2)

    assert worker._buffer_measurement(_build_measurement(exp_id, 900.0)) == 0
    assert worker._buffer_measurement(_build_measurement(exp_id, 905.0)) == 2

    rows = db.fetch_measurements(exp_id)

    assert len(rows) == 2


def test_acquisition_worker_flushes_remaining_measurements(tmp_path):
    db = DatabaseManager(tmp_path / "acq_flush.db")
    db.init_schema()
    exp_id = db.create_experiment("acq-flush")
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)
    worker = AcquisitionWorker(client=client, db=db, experiment_id=exp_id, poll_interval_ms=100, batch_size=5)

    worker._buffer_measurement(_build_measurement(exp_id, 900.0))
    worker._buffer_measurement(_build_measurement(exp_id, 901.0))

    flushed = worker._flush_pending_measurements()
    rows = db.fetch_measurements(exp_id)

    assert flushed == 2
    assert len(rows) == 2


def test_acquisition_worker_builds_measurement_from_snapshot(tmp_path):
    db = DatabaseManager(tmp_path / "acq_snapshot.db")
    db.init_schema()
    exp_id = db.create_experiment("acq-snapshot")
    client = ModbusRtuClient(serial_port="loop://", baudrate=9600, unit_id=1, simulation_mode=True)
    worker = AcquisitionWorker(client=client, db=db, experiment_id=exp_id, poll_interval_ms=100, batch_size=2)

    measurement = worker._build_measurement(_build_snapshot(915.0))

    assert measurement.experiment_id == exp_id
    assert measurement.temperature_c == 915.0
    assert measurement.n2_lpm == 4.0
