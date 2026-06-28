from rka_desktop.db.database import DatabaseManager
from rka_desktop.db.migrations import SCHEMA_VERSION
from rka_desktop.repositories import ExperimentRepository


def _db(tmp_path):
    db = DatabaseManager(tmp_path / "params.db")
    db.init_schema()
    return db


def test_schema_has_sample_param_columns(tmp_path):
    db = _db(tmp_path)
    assert db.get_schema_version() == SCHEMA_VERSION
    exp_id = db.create_experiment("exp")
    detail = db.get_experiment_detail(exp_id)
    # columns exist and default to NULL before being set
    assert "initial_mass_g" in detail
    assert detail["initial_mass_g"] is None
    assert detail["tfe_pct"] is None
    assert detail["feo_pct"] is None


def test_sample_params_round_trip(tmp_path):
    db = _db(tmp_path)
    repo = ExperimentRepository(db)
    exp_id = repo.create_experiment("exp")
    repo.set_sample_params(exp_id, initial_mass_g=50.0, tfe_pct=60.0, feo_pct=10.0)
    detail = repo.get_experiment_detail(exp_id)
    assert detail["initial_mass_g"] == 50.0
    assert detail["tfe_pct"] == 60.0
    assert detail["feo_pct"] == 10.0


def test_existing_db_upgrades_columns(tmp_path):
    # init twice to simulate re-opening an older DB; columns must persist idempotently
    db = _db(tmp_path)
    exp_id = db.create_experiment("exp")
    db.init_schema()  # idempotent migration
    db.set_experiment_sample_params(exp_id, 40.0, 65.0, 5.0)
    detail = db.get_experiment_detail(exp_id)
    assert detail["initial_mass_g"] == 40.0
