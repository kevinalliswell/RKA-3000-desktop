"""Recipe, history, analysis and device services against SQLite with a fake gateway."""

import time
from pathlib import Path

import pytest
from openpyxl import load_workbook

from rka_desktop.application.analysis_service import AnalysisError, AnalysisService, ExperimentArchived
from rka_desktop.application.device_service import DeviceBusy, DeviceService
from rka_desktop.application.history_service import ExperimentBusy, ExperimentNotFound, HistoryService
from rka_desktop.application.limits_service import LimitsLocked, LimitsService
from rka_desktop.application.recipe_service import RecipeInUse, RecipeNotFound, RecipeService
from rka_desktop.application.review_service import ArchiveRefused, ReviewService
from rka_desktop.application.tasks import TaskRegistry
from rka_desktop.domain.control import ConfirmationRequired
from rka_desktop.domain.entities import Measurement
from rka_desktop.domain.limits import LimitError
from rka_desktop.domain.recipe import RecipeValidationError
from rka_desktop.infrastructure.exports import export_service
from rka_desktop.infrastructure.exports.report_service import ReportService
from rka_desktop.infrastructure.sqlite.repositories import SqliteReportStore
from tests.conftest import DEVICE_LIMITS, RECIPE_PAYLOAD, RECIPE_STEPS, FakeGateway, make_services


def wait_task(tasks, task):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        current = tasks.get(task["id"])
        if current["status"] in {"completed", "failed", "cancelled"}:
            return current
        time.sleep(0.005)
    pytest.fail("task did not finish")


def seed_measurements(stores, experiment_id, weights=(50.0, 43.55, 37.1)):
    from datetime import datetime, timedelta

    t0 = datetime(2026, 1, 1, 12, 0, 0)
    stores["experiments"].insert_measurements([
        Measurement(experiment_id, t0 + timedelta(seconds=60 * i), 900.0, w, 0.0, 8.0, 1.0, 0.8) for i, w in enumerate(weights)
    ])


def test_recipe_service_crud_versions_import_export_and_guards(stores):
    running = {"id": None}
    holder = {}
    service = RecipeService(stores["recipes"], stores["audit"], limits=lambda: holder["l"].effective(),
                            device_limits=lambda: dict(DEVICE_LIMITS), is_recipe_running=lambda rid: rid == running["id"])
    holder["l"] = LimitsService(stores["limits"], stores["audit"], device_limits=lambda: dict(DEVICE_LIMITS),
                                lock_reason=lambda: None, assess_all=service.assess_all)
    created = service.create_recipe({**RECIPE_PAYLOAD, "name": "A"})
    assert created["id"] and len(created["steps"]) == 3 and created["version"] == 1 and created["assessment"]["runnable"]
    with pytest.raises(RecipeValidationError, match="修改原因"):
        service.update_recipe(created["id"], {**RECIPE_PAYLOAD, "name": "B"})
    updated = service.update_recipe(created["id"], {**RECIPE_PAYLOAD, "name": "B", "steps": RECIPE_STEPS[1:2],
                                                    "reason": "缩短流程"})
    assert updated["name"] == "B" and updated["version"] == 2 and not updated["assessment"]["runnable"]
    assert [v["version"] for v in updated["versions"]] == [2, 1] and updated["versions"][0]["reason"] == "缩短流程"
    assert service.versions(created["id"])[1]["snapshot"]["name"] == "A"
    listed = {r["name"]: r for r in service.list_recipes()}
    assert listed["B"]["runnable"] is False and "至少 3 段" in listed["B"]["summary"]
    document = service.export_recipe(created["id"])
    imported = service.import_recipe(document, name_override="C")
    assert imported["name"] == "C" and [r["name"] for r in service.list_recipes()] == ["C", "B"]
    running["id"] = created["id"]
    with pytest.raises(RecipeInUse):
        service.update_recipe(created["id"], {**RECIPE_PAYLOAD, "reason": "x 修改"})
    with pytest.raises(RecipeInUse):
        service.delete_recipe(created["id"])
    running["id"] = None
    service.delete_recipe(created["id"])
    with pytest.raises(RecipeNotFound):
        service.get_recipe(created["id"])
    actions = [row["action"] for row in stores["audit"].list_audit_logs(limit=20)]
    assert {"RECIPE_CREATE", "RECIPE_UPDATE", "RECIPE_IMPORT", "RECIPE_DELETE"} <= set(actions)


def test_limits_preview_apply_versions_and_lock(stores):
    gateway = FakeGateway()
    recipes, limits = make_services(stores, gateway)
    recipes.create_recipe(RECIPE_PAYLOAD)
    described = limits.describe()
    assert described["policy"]["version"] == 1 and next(g for g in described["gases"] if g["gas"] == "O2")["available"] is False
    preview = limits.preview({"CO": 0.6})
    assert preview["changes"] == [{"gas": "CO", "label": "CO", "before": 5.0, "after": 0.6}]
    assert [a["name"] for a in preview["affected"]] == ["标准流程"]
    with pytest.raises(LimitError):
        limits.apply({"CO": 0.6}, " ")
    with pytest.raises(LimitError):
        limits.apply({"CO": 9.0}, "超出设备")
    result = limits.apply({"CO": 0.6}, "CO 气路改造期间临时限流", actor="管理员")
    assert result["applied"]["version"] == 2 and limits.effective() == (2, {**DEVICE_LIMITS, "CO": 0.6})
    assert recipes.list_recipes()[0]["runnable"] is False
    with pytest.raises(LimitsLocked):
        limits.apply({"CO": 0.6}, "重复")
    audit = stores["audit"].list_audit_logs(limit=5)[0]
    assert audit["action"] == "LIMITS_UPDATE" and audit["actor"] == "管理员" and audit["category"] == "config"
    locked = LimitsService(stores["limits"], stores["audit"], device_limits=gateway.gas_device_limits,
                           lock_reason=lambda: "实验未归档", assess_all=recipes.assess_all)
    with pytest.raises(LimitsLocked, match="未归档"):
        locked.apply({"CO": 1.0}, "测试锁定")


def test_history_service_pages_renames_deletes_and_exports(stores, tmp_path):
    tasks = TaskRegistry()
    active = {"id": None}
    service = HistoryService(stores["experiments"], stores["alarms"], stores["audit"], tasks, tmp_path / "exports",
                             export_service, active_experiment_id=lambda: active["id"])
    exp_id = stores["experiments"].create_experiment("exp", recipe_id=None, fields={"sample_name": "球团矿 A-19"})
    seed_measurements(stores, exp_id)
    stores["experiments"].update_experiment(exp_id, {"status": "COMPLETED", "review_state": "pending"})
    detail = service.get_experiment(exp_id)
    assert detail["measurement_count"] == 3 and detail["summary"]["sample_count"] == 3 and detail["category"] == "pending"
    listed = service.list_experiments(category="pending")
    assert [e["id"] for e in listed["experiments"]] == [exp_id] and listed["counts"]["pending"] == 1
    assert service.list_experiments(query="A-19")["experiments"][0]["id"] == exp_id
    assert service.list_experiments(query=detail["code"])["experiments"][0]["id"] == exp_id
    assert service.list_experiments(category="archived")["experiments"] == []
    with pytest.raises(ValueError):
        service.list_experiments(category="bogus")
    page = service.measurements(exp_id, limit=2, offset=1)
    assert page["total"] == 3 and [row["weight_g"] for row in page["items"]] == [43.55, 37.1]
    assert service.rename_experiment(exp_id, " 新名 ")["name"] == "新名"
    with pytest.raises(ValueError):
        service.rename_experiment(exp_id, "")
    csv_task = wait_task(tasks, service.start_export("measurements_csv", exp_id))
    xlsx_task = wait_task(tasks, service.start_export("measurements_xlsx", exp_id))
    summary_task = wait_task(tasks, service.start_export("summary_csv", exp_id))
    assert csv_task["status"] == xlsx_task["status"] == summary_task["status"] == "completed"
    csv_text = Path(csv_task["result"]["path"]).read_text(encoding="utf-8-sig")
    assert csv_text.splitlines()[0] == ",".join(export_service.MEASUREMENT_COLUMNS)
    assert len(csv_text.splitlines()) == 4
    sheet = load_workbook(xlsx_task["result"]["path"])["measurements"]
    assert sheet.max_row == 4 and sheet["B1"].value == "temperature_c"
    assert "sample_count" in Path(summary_task["result"]["path"]).read_text(encoding="utf-8-sig")
    with pytest.raises(ValueError):
        service.start_export("pdf", exp_id)
    with pytest.raises(ExperimentNotFound):
        service.start_export("measurements_csv", 999)
    audit_task = wait_task(tasks, service.start_audit_export(experiment_id=exp_id))
    assert audit_task["status"] == "completed" and "RENAME" in Path(audit_task["result"]["path"]).read_text(encoding="utf-8-sig")
    stores["experiments"].update_experiment(exp_id, {"review_state": "archived"})
    with pytest.raises(ExperimentBusy, match="只读"):
        service.rename_experiment(exp_id, "x")
    active["id"] = exp_id
    with pytest.raises(ExperimentBusy):
        service.delete_experiment(exp_id)
    active["id"] = None
    service.delete_experiment(exp_id)
    with pytest.raises(ExperimentNotFound):
        service.get_experiment(exp_id)
    tasks.close()


def _analysis(stores, tmp_path, tasks):
    return AnalysisService(stores["experiments"], stores["audit"], tasks, tmp_path / "exports", ReportService(),
                           SqliteReportStore(stores["recipes"]._db), stores["alarms"])


def test_analysis_service_computes_fits_and_reports_only_when_archived(stores, tmp_path):
    tasks = TaskRegistry()
    service = _analysis(stores, tmp_path, tasks)
    exp_id = stores["experiments"].create_experiment("exp")
    with pytest.raises(AnalysisError, match="试样参数"):
        service.compute(exp_id)
    seed_measurements(stores, exp_id)
    params = {"initial_mass_g": 50.0, "tfe_pct": 60.0, "feo_pct": 0.0}
    result = service.compute(exp_id, params)
    assert result["final_degree_pct"] == pytest.approx(100.0) and result["window"]["source"] == "all"
    assert result["time_to_40_min"] == pytest.approx(0.8) and result["degree_kind"] == "reduction"
    saved = service.save_sample_params(exp_id, params)
    assert saved["tfe_pct"] == 60.0 and not saved["locked"]
    assert service.compute(exp_id)["final_degree_pct"] == pytest.approx(100.0)  # stored params
    with pytest.raises(AnalysisError):
        service.compute(exp_id, {"initial_mass_g": 0, "tfe_pct": 60, "feo_pct": 0})
    with pytest.raises(ExperimentArchived, match="归档"):
        service.start_report(exp_id)
    stores["experiments"].update_experiment(exp_id, {"review_state": "archived"})
    with pytest.raises(ExperimentArchived):
        service.save_sample_params(exp_id, params)
    task = wait_task(tasks, service.start_report(exp_id))
    assert task["status"] == "completed" and task["result"]["version"] == 1
    assert {"报告", "数据", "报警与事件", "操作记录"} <= set(load_workbook(task["result"]["path"]).sheetnames)
    second = wait_task(tasks, service.start_report(exp_id))
    assert second["result"]["version"] == 2 and second["result"]["filename"].endswith("_report_v2.xlsx")
    listed = next(item for item in service.list_reports() if item["id"] == exp_id)
    assert listed["latest_report"]["version"] == 2 and listed["can_generate"]
    tasks.close()


def test_analysis_uses_reaction_window(stores, tmp_path):
    from datetime import datetime, timedelta

    tasks = TaskRegistry()
    service = _analysis(stores, tmp_path, tasks)
    t0 = datetime(2026, 1, 1, 12, 0, 0)
    exp_id = stores["experiments"].create_experiment("exp", fields={
        "reaction_started_at": (t0 + timedelta(minutes=10)).isoformat(),
        "reaction_ended_at": (t0 + timedelta(minutes=12)).isoformat(),
        "initial_mass_g": 50.0, "tfe_pct": 60.0, "feo_pct": 0.0})
    weights = [50.0] * 10 + [50.0, 43.55, 37.1] + [30.0]  # heat-up, reaction (3 samples), cooling
    stores["experiments"].insert_measurements([
        Measurement(exp_id, t0 + timedelta(minutes=i), 900.0, w, 0.0, 3.0, 1.0, 0.8) for i, w in enumerate(weights)])
    result = service.compute(exp_id)
    assert result["window"]["source"] == "reaction" and len(result["points"]) == 3
    assert result["final_degree_pct"] == pytest.approx(100.0) and result["time_to_40_min"] == pytest.approx(0.8)
    tasks.close()


def test_review_blocks_on_unacked_alarm_requires_note_on_warnings_and_freezes_kpi(stores, tmp_path):
    tasks = TaskRegistry()
    analysis = _analysis(stores, tmp_path, tasks)
    active = {"id": None}
    review = ReviewService(stores["experiments"], stores["alarms"], stores["audit"], analysis, poll_interval_s=60.0,
                           safe_temperature_c=200.0, is_active=lambda eid: eid == active["id"])
    exp_id = stores["experiments"].create_experiment("exp", fields={
        "initial_mass_g": 50.0, "tfe_pct": 60.0, "feo_pct": 0.0, "recipe_version": 1, "recipe_snapshot": {"name": "x"},
        "purge_required_s": 600, "purge_done_s": 620, "final_temperature_c": 180.0, "final_mass_g": 37.1,
        "end_reason": "completed", "review_state": "pending"})
    seed_measurements(stores, exp_id)
    stores["experiments"].finish_experiment(exp_id, "COMPLETED")
    alarm = stores["alarms"].create_alarm(exp_id, "SW-X", "WARNING", "测试警告")
    result = review.review(exp_id)
    assert not result["can_archive"] and result["stats"]["count"] == 3
    with pytest.raises(ArchiveRefused, match="未确认"):
        review.archive(exp_id, "")
    stores["alarms"].acknowledge_alarm(alarm, "A", "已处理")
    result = review.review(exp_id)
    assert result["can_archive"] and result["note_required"]  # an acknowledged alarm still needs explaining
    with pytest.raises(ArchiveRefused, match="备注"):
        review.archive(exp_id, "")
    archived = review.archive(exp_id, "警告为气瓶切换波动", actor="实验员 B")
    detail = archived["experiment"]
    assert detail["review_state"] == "archived" and detail["archived_by"] == "实验员 B" and detail["category"] == "archived"
    assert detail["kpi"]["final_degree_pct"] == pytest.approx(100.0) and detail["kpi"]["window"]["source"] == "all"
    assert not archived["can_archive"]
    with pytest.raises(ArchiveRefused, match="已归档"):
        review.archive(exp_id, "再次")
    assert stores["audit"].list_audit_logs(limit=1, experiment_id=exp_id)[0]["action"] == "EXPERIMENT_ARCHIVE"
    tasks.close()


def test_device_service_guards_writes(stores):
    gateway = FakeGateway()
    active = {"run": False}
    service = DeviceService(gateway, stores["audit"], run_active=lambda: active["run"], ensure_connected=gateway.connect)
    status = service.status()
    assert status["supported"] and status["connected"] and status["mfc"][0]["address"] == 1
    with pytest.raises(ConfirmationRequired):
        service.set_mfc_setpoints([{"address": 1, "lpm": 1.0}], confirmed=False)
    with pytest.raises(ValueError):
        service.set_mfc_setpoints([{"address": "1", "lpm": 1.0}], confirmed=True)
    service.set_mfc_setpoints([{"address": 1, "lpm": 1.5}], confirmed=True)
    assert gateway.mfc_writes == [(1, 1.5)]
    service.set_temperature(800, confirmed=True)
    assert gateway.temp_writes[-1]["temperature_c"] == 800.0
    assert service.tare(confirmed=True)["ok"] and gateway.tare_calls == 1
    active["run"] = True
    with pytest.raises(DeviceBusy):
        service.tare(confirmed=True)
    with pytest.raises(DeviceBusy):
        service.set_mfc_setpoints([{"address": 1, "lpm": 1.0}], confirmed=True)


def test_review_counts_every_unacknowledged_alarm_not_just_the_display_page(stores, tmp_path):
    tasks = TaskRegistry()
    review = ReviewService(stores["experiments"], stores["alarms"], stores["audit"], _analysis(stores, tmp_path, tasks),
                           poll_interval_s=0.5, safe_temperature_c=200.0, is_active=lambda eid: False)
    exp_id = stores["experiments"].create_experiment("exp", fields={"review_state": "pending"})
    stores["experiments"].finish_experiment(exp_id, "COMPLETED")
    stores["alarms"].create_alarm(exp_id, "SW-OLD", "WARNING", "最早的一条，未确认")
    for i in range(200):
        stores["alarms"].acknowledge_alarm(stores["alarms"].create_alarm(exp_id, f"SW-{i}", "WARNING", "x"), "A", "已处理")
    result = review.review(exp_id)
    alarms = next(c for c in result["checks"] if c["key"] == "alarms")
    assert alarms["severity"] == "block" and not result["can_archive"]
    tasks.close()
