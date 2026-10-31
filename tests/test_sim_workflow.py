from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from rka_desktop.sim_workflow import SimulationWorkflow, WorkflowError


@pytest.fixture
def workflow(tmp_path: Path):
    service = SimulationWorkflow(tmp_path / "desktop.db", start_worker=False)
    yield service
    service.close()


def ready():
    return {"gas": True, "exhaust": True, "balance": True, "operator": True}


def start(workflow: SimulationWorkflow):
    recipe_id = workflow.recipes()[0]["id"]
    return workflow.start("仿真试验", recipe_id, {"name": "样品 A", "initial_mass_g": 1.2}, ready())


def test_gas_interlocks_and_version_snapshot(workflow: SimulationWorkflow):
    with pytest.raises(WorkflowError, match="禁用 O₂"):
        workflow.save_recipe("非法还原", "reduction", [{"name": "反应", "duration_s": 2, "temperature_c": 700, "flows": {"n2": 2, "o2": 1}}])
    with pytest.raises(WorkflowError, match="共用 MFC-01"):
        workflow.save_recipe("双惰性", "oxidation", [{"name": "反应", "duration_s": 2, "temperature_c": 700, "flows": {"n2": 2, "ar": 2}}])
    with pytest.raises(WorkflowError, match="禁用 CO"):
        workflow.save_recipe("非法氧化", "oxidation", [{"name": "反应", "duration_s": 2, "temperature_c": 700, "flows": {"ar": 2, "co": 1}}])
    run = start(workflow)
    workflow.save_recipe(run["recipe_snapshot"]["name"], "oxidation", [{"name": "新版", "duration_s": 2, "temperature_c": 500, "flows": {"n2": 2}}])
    assert workflow.run(run["id"])["recipe_snapshot"]["version"] == run["recipe_snapshot"]["version"]


def test_normal_cycle_review_and_report(workflow: SimulationWorkflow):
    run = start(workflow)
    for _ in range(76):
        workflow.tick()
    assert workflow.run(run["id"])["state"] == "REVIEW"
    assert workflow.samples(run["id"], limit=10)["total"] == 75
    analysis = workflow.analysis(run["id"])
    assert analysis["valid"] and analysis["sample_count"] == 75
    with pytest.raises(WorkflowError, match="复核员"):
        workflow.action(run["id"], "review", note="数据完整")
    workflow.set_settings(role="reviewer")
    workflow.action(run["id"], "review", note="数据完整")
    assert "待复核 / 未归档" in workflow.report_html(run["id"])
    workflow.action(run["id"], "archive")
    assert workflow.current() is None
    report = workflow.report_html(run["id"])
    assert "数据完整" in report and "仿真技术记录" in report and "v1" in report and "已归档" in report


def test_fault_pause_emergency_and_restart(tmp_path: Path):
    path = tmp_path / "desktop.db"
    service = SimulationWorkflow(path, start_worker=False)
    run = start(service)
    service.tick()
    service.set_settings(scenario="offline")
    service.tick()
    assert service.run(run["id"])["state"] == "PAUSED"
    assert service.snapshot()["values"] is None
    with pytest.raises(WorkflowError, match="故障"):
        service.action(run["id"], "resume")
    alarm = service.alarms()[0]
    service.acknowledge(alarm["id"], "张三")
    with pytest.raises(WorkflowError, match="仍存在"):
        service.clear_alarm(alarm["id"], "张三")
    service.set_settings(scenario="normal")
    service.clear_alarm(alarm["id"], "张三")
    service.action(run["id"], "resume")
    service.action(run["id"], "emergency")
    assert service.current()["state"] == "EMERGENCY"
    with pytest.raises(WorkflowError):
        service.action(run["id"], "resume")
    service.close()
    reopened = SimulationWorkflow(path, start_worker=False)
    assert reopened.current()["state"] == "EMERGENCY"
    reopened.set_settings(role="reviewer")
    reopened.action(run["id"], "review", note="紧急处置记录完成")
    reopened.action(run["id"], "archive")
    second = start(reopened)
    reopened.close()
    again = SimulationWorkflow(path, start_worker=False)
    assert again.run(second["id"])["state"] == "RECOVERY_REQUIRED"
    again.close()


def test_invalid_sample_is_recorded_but_not_analyzed(workflow: SimulationWorkflow):
    run = start(workflow)
    workflow.tick()
    workflow.set_settings(scenario="unstable")
    workflow.tick()
    assert workflow.run(run["id"])["state"] == "PAUSED"
    assert workflow.snapshot()["state"] == "stale"
    samples = workflow.samples(run["id"])["items"]
    assert samples[-1]["quality"] == "unstable"
    assert samples[-1]["weight_g"] is None
    assert workflow.analysis(run["id"])["sample_count"] == 1


def test_limits_require_admin_and_do_not_change_during_run(workflow: SimulationWorkflow):
    new_limits = dict(workflow.settings()["limits"])
    new_limits["co"] = 6.0
    with pytest.raises(WorkflowError, match="管理员"):
        workflow.set_settings(limits=new_limits)
    workflow.set_settings(role="administrator", limits=new_limits)
    assert workflow.settings()["limits"]["co"] == 6.0
    start(workflow)
    new_limits["co"] = 7.0
    with pytest.raises(WorkflowError, match="未归档"):
        workflow.set_settings(limits=new_limits)


def test_history_filters_and_pagination(workflow: SimulationWorkflow):
    run = start(workflow)
    assert workflow.history(search="仿真", status="PURGE")["total"] == 1
    assert workflow.history(search="不存在")["total"] == 0
    assert workflow.history(search="%", status="all")["total"] == 0
    assert workflow.samples(run["id"], tail=True)["items"] == []


def test_legacy_import_is_copy_and_idempotent(workflow: SimulationWorkflow, tmp_path: Path):
    source = tmp_path / "old.db"
    with sqlite3.connect(source) as db:
        db.executescript("""
            CREATE TABLE recipes(id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE recipe_steps(id INTEGER PRIMARY KEY, recipe_id INTEGER, step_no INTEGER);
            CREATE TABLE experiments(id INTEGER PRIMARY KEY, name TEXT, status TEXT);
            CREATE TABLE measurements(id INTEGER PRIMARY KEY, experiment_id INTEGER, weight_g REAL);
            INSERT INTO recipes VALUES(1,'旧配方');
            INSERT INTO recipe_steps VALUES(1,1,1);
            INSERT INTO experiments VALUES(1,'旧实验','COMPLETED');
            INSERT INTO measurements VALUES(1,1,0.9);
        """)
    original = source.read_bytes()
    first = workflow.import_legacy(source)
    second = workflow.import_legacy(source)
    assert not first["already_imported"] and second["already_imported"]
    assert first["recipe_count"] == first["run_count"] == 1
    assert len(workflow.legacy_runs()) == len(workflow.legacy_recipes()) == 1
    assert workflow.legacy_runs()[0]["sample_count"] == 1
    assert workflow.legacy_samples(first["fingerprint"], 1)["items"][0]["weight_g"] == 0.9
    assert Path(first["backup_path"]).exists()
    assert source.read_bytes() == original
