"""Recipe, history, analysis and device services against SQLite with a fake gateway."""

import time
from pathlib import Path

import pytest
from openpyxl import load_workbook

from rka_desktop.application.analysis_service import AnalysisError, AnalysisService
from rka_desktop.application.device_service import DeviceBusy, DeviceService
from rka_desktop.application.history_service import ExperimentBusy, ExperimentNotFound, HistoryService
from rka_desktop.application.recipe_service import RecipeInUse, RecipeNotFound, RecipeService
from rka_desktop.application.tasks import TaskRegistry
from rka_desktop.domain.control import ConfirmationRequired
from rka_desktop.domain.entities import Measurement
from rka_desktop.infrastructure.exports import export_service
from rka_desktop.infrastructure.exports.report_service import ReportService
from tests.conftest import RECIPE_STEPS, FakeGateway


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


def test_recipe_service_crud_import_export_and_guards(stores):
    running = {"id": None}
    service = RecipeService(stores["recipes"], stores["audit"], is_recipe_running=lambda rid: rid == running["id"])
    created = service.create_recipe("A", RECIPE_STEPS)
    assert created["id"] and len(created["steps"]) == 2
    updated = service.update_recipe(created["id"], "B", RECIPE_STEPS[:1])
    assert updated["name"] == "B" and len(updated["steps"]) == 1
    document = service.export_recipe(created["id"])
    imported = service.import_recipe(document, name_override="C")
    assert imported["name"] == "C" and [r["name"] for r in service.list_recipes()] == ["C", "B"]
    running["id"] = created["id"]
    with pytest.raises(RecipeInUse):
        service.update_recipe(created["id"], "X", RECIPE_STEPS)
    with pytest.raises(RecipeInUse):
        service.delete_recipe(created["id"])
    running["id"] = None
    service.delete_recipe(created["id"])
    with pytest.raises(RecipeNotFound):
        service.get_recipe(created["id"])
    actions = [row["action"] for row in stores["audit"].list_audit_logs(limit=20)]
    assert {"RECIPE_CREATE", "RECIPE_UPDATE", "RECIPE_IMPORT", "RECIPE_DELETE"} <= set(actions)


def test_history_service_pages_renames_deletes_and_exports(stores, tmp_path):
    tasks = TaskRegistry()
    active = {"id": None}
    service = HistoryService(stores["experiments"], stores["alarms"], stores["audit"], tasks, tmp_path / "exports",
                             export_service, active_experiment_id=lambda: active["id"])
    exp_id = stores["experiments"].create_experiment("exp", recipe_id=None)
    seed_measurements(stores, exp_id)
    stores["experiments"].finish_experiment(exp_id, status="COMPLETED")
    detail = service.get_experiment(exp_id)
    assert detail["measurement_count"] == 3 and detail["summary"]["sample_count"] == 3
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
    active["id"] = exp_id
    with pytest.raises(ExperimentBusy):
        service.delete_experiment(exp_id)
    active["id"] = None
    service.delete_experiment(exp_id)
    with pytest.raises(ExperimentNotFound):
        service.get_experiment(exp_id)
    tasks.close()


def test_analysis_service_computes_and_reports(stores, tmp_path):
    tasks = TaskRegistry()
    service = AnalysisService(stores["experiments"], stores["audit"], tasks, tmp_path / "exports", ReportService())
    exp_id = stores["experiments"].create_experiment("exp")
    with pytest.raises(AnalysisError, match="试样参数"):
        service.compute(exp_id)
    seed_measurements(stores, exp_id)
    params = {"initial_mass_g": 50.0, "tfe_pct": 60.0, "feo_pct": 0.0}
    result = service.compute(exp_id, params)
    assert result["final_degree_pct"] == pytest.approx(100.0)
    assert result["time_to_40_min"] == pytest.approx(0.8)
    saved = service.save_sample_params(exp_id, params)
    assert saved["tfe_pct"] == 60.0
    assert service.compute(exp_id)["final_degree_pct"] == pytest.approx(100.0)  # stored params
    with pytest.raises(AnalysisError):
        service.compute(exp_id, {"initial_mass_g": 0, "tfe_pct": 60, "feo_pct": 0})
    task = wait_task(tasks, service.start_report(exp_id))
    assert task["status"] == "completed"
    workbook = load_workbook(task["result"]["path"])
    assert set(workbook.sheetnames) == {"报告", "数据"}
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
