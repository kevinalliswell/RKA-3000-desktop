from datetime import datetime

from rka_desktop.db.database import DatabaseManager
from rka_desktop.models.entities import Measurement


def test_history_queries_return_expected_records(tmp_path):
    db_file = tmp_path / "history.db"
    db = DatabaseManager(db_file)
    db.init_schema()

    recipe_id = db.create_recipe(
        "历史查询流程",
        [
            {
                "step_no": 1,
                "target_temp_c": 950,
                "ramp_rate_cpm": 12,
                "hold_seconds": 240,
                "n2_lpm": 7.5,
                "h2_lpm": 1.2,
                "co_lpm": 0.7,
                "notes": "history",
            }
        ],
    )
    exp_id = db.create_experiment("history-exp", recipe_id=recipe_id)
    db.log_action("tester", "EXP_START", f"id={exp_id}")
    db.create_alarm(exp_id, code="ALM-1001", level="HIGH", message="history alarm")
    db.insert_measurement(
        Measurement(
            experiment_id=exp_id,
            sampled_at=datetime.now(),
            temperature_c=950.0,
            weight_g=81.234,
            pressure_mpa=0.018,
            n2_lpm=7.5,
            h2_lpm=1.2,
            co_lpm=0.7,
        )
    )
    db.finish_experiment(exp_id)

    experiments = db.list_experiments()
    detail = db.get_experiment_detail(exp_id)
    summary = db.get_experiment_summary(exp_id)
    alarms = db.list_alarm_history(exp_id)
    logs = db.list_audit_logs()

    assert experiments[0]["id"] == exp_id
    assert detail is not None
    assert detail["recipe_id"] == recipe_id
    assert summary is not None
    assert summary["sample_count"] == 1
    assert alarms[0]["code"] == "ALM-1001"
    assert logs[0]["action"] == "EXP_START"


def test_report_can_load_all_alarms_beyond_history_page_limit(tmp_path):
    db = DatabaseManager(tmp_path / "alarms.db")
    db.init_schema()
    exp_id = db.create_experiment("many alarms")
    for index in range(105):
        db.create_alarm(exp_id, code=f"A-{index}", level="WARN", message="check")

    assert len(db.list_alarm_history(exp_id)) == 100
    assert len(db.list_alarm_history(exp_id, limit=None)) == 105


def test_report_can_select_experiments_beyond_history_page_limit(tmp_path):
    db = DatabaseManager(tmp_path / "experiments.db")
    db.init_schema()
    for index in range(105):
        db.create_experiment(f"experiment-{index}")

    assert len(db.list_experiments()) == 100
    assert len(db.list_experiments(limit=None)) == 105
