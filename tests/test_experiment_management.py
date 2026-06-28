from datetime import datetime

from rka_desktop.db.database import DatabaseManager
from rka_desktop.models.entities import Measurement
from rka_desktop.repositories import ExperimentRepository


def _db(tmp_path):
    db = DatabaseManager(tmp_path / "mgmt.db")
    db.init_schema()
    return db


def _measurement(exp_id):
    return Measurement(
        experiment_id=exp_id,
        sampled_at=datetime(2026, 6, 28, 10, 0, 0),
        temperature_c=900.0,
        weight_g=50.0,
        pressure_mpa=0.0,
        n2_lpm=1.0,
        h2_lpm=1.0,
        co_lpm=0.0,
    )


def test_rename_experiment(tmp_path):
    repo = ExperimentRepository(_db(tmp_path))
    exp_id = repo.create_experiment("old-name")
    repo.rename_experiment(exp_id, "new-name")
    assert repo.get_experiment_detail(exp_id)["name"] == "new-name"


def test_delete_experiment_removes_experiment_and_measurements(tmp_path):
    db = _db(tmp_path)
    repo = ExperimentRepository(db)
    exp_id = repo.create_experiment("to-delete")
    db.insert_measurement(_measurement(exp_id))
    assert db.fetch_measurements(exp_id)

    repo.delete_experiment(exp_id)

    assert repo.get_experiment_detail(exp_id) is None
    assert db.fetch_measurements(exp_id) == []


def test_audit_log_records_actions(tmp_path):
    from rka_desktop.repositories import AuditLogRepository

    db = _db(tmp_path)
    audit = AuditLogRepository(db)
    audit.log_action("operator", "EXPERIMENT_DELETE", "#1")
    logs = audit.list_audit_logs(limit=10)
    assert logs and logs[0]["action"] == "EXPERIMENT_DELETE"
