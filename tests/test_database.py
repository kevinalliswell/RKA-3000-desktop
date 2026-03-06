from datetime import datetime

from rka_desktop.db.database import DatabaseManager
from rka_desktop.models.entities import Measurement


def test_database_init_and_insert(tmp_path):
    db_file = tmp_path / "test.db"
    db = DatabaseManager(db_file)
    db.init_schema()

    exp_id = db.create_experiment("test")
    m = Measurement(
        experiment_id=exp_id,
        sampled_at=datetime.now(),
        temperature_c=900.0,
        weight_g=88.123,
        pressure_mpa=0.021,
        n2_lpm=4.5,
        h2_lpm=1.2,
        co_lpm=0.8,
    )
    db.insert_measurement(m)
    db.finish_experiment(exp_id)

    rows = db.fetch_measurements(exp_id)
    assert exp_id > 0
    assert db_file.exists()
    assert len(rows) == 1
    assert float(rows[0]["temperature_c"]) == 900.0


def test_recipe_and_alarm_flow(tmp_path):
    db_file = tmp_path / "test_recipe_alarm.db"
    db = DatabaseManager(db_file)
    db.init_schema()

    recipe_id = db.create_recipe(
        "标准流程",
        [
            {
                "step_no": 1,
                "target_temp_c": 900,
                "ramp_rate_cpm": 10,
                "hold_seconds": 300,
                "n2_lpm": 8.0,
                "h2_lpm": 1.0,
                "co_lpm": 0.8,
                "notes": "phase-1",
            }
        ],
    )

    recipes = db.list_recipes()
    steps = db.get_recipe_steps(recipe_id)
    exp_id = db.create_experiment("exp-1", recipe_id=recipe_id)
    db.create_alarm(exp_id, code="ALM-0002", level="HIGH", message="测试报警")

    assert len(recipes) >= 1
    assert recipes[0]["id"] == recipe_id
    assert len(steps) == 1
    assert int(steps[0]["hold_seconds"]) == 300

    assert db.acknowledge_latest_alarm(exp_id, actor="tester") is True
    assert db.acknowledge_latest_alarm(exp_id, actor="tester") is False
