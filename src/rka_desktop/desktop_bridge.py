"""Line-delimited JSON bridge for the Tauri desktop shell.

The bridge deliberately creates a simulation-only client. Device writes are not
part of this public interface, even when the legacy application is configured
for hardware mode.
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from rka_desktop import __version__
from rka_desktop.core.config import Settings
from rka_desktop.core.device_map import get_device_map
from rka_desktop.core.modbus_client import ModbusRtuClient
from rka_desktop.db.database import DatabaseManager
from rka_desktop.repositories import ExperimentRepository, RecipeRepository
from rka_desktop.sim_workflow import SimulationWorkflow, WorkflowError


class DesktopBridge:
    """Simulation-only bridge. No real-device write path is exposed."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings(simulation_mode=True)
        if not self.settings.simulation_mode:
            raise ValueError("Desktop bridge only supports simulation mode")
        self.db = DatabaseManager(Path(self.settings.db_path))
        self.db.init_schema()
        self.sim = SimulationWorkflow(Path(self.settings.db_path))
        self.recipes = RecipeRepository(self.db)
        self.experiments = ExperimentRepository(self.db)
        self.client = ModbusRtuClient(
            serial_port=self.settings.serial_port,
            baudrate=self.settings.baudrate,
            unit_id=self.settings.modbus_unit_id,
            device_map=get_device_map(self.settings.mapping_profile),
            simulation_mode=True,
        )

    def call(self, method: str, _params: dict[str, Any] | None = None) -> dict[str, Any]:
        p = _params or {}
        if method == "sim_bootstrap":
            return {"version": __version__, "settings": self.sim.settings(), "recipes": self.sim.recipes(),
                    "history": self.sim.history(), "snapshot": self.sim.snapshot(), "alarms": self.sim.alarms(),
                    "audit": self.sim.audit()}
        if method == "sim_snapshot":
            return self.sim.snapshot()
        if method == "sim_devices_status":
            return self.sim.devices_status()
        if method == "sim_recipes":
            return {"items": self.sim.recipes()}
        if method == "sim_recipe":
            return self.sim.recipe(self._id_param(p))
        if method == "sim_recipe_save":
            return self.sim.save_recipe(p.get("name", ""), p.get("kind", ""), p.get("stages", []))
        if method == "sim_preflight":
            return self.sim.preflight(int(p.get("recipe_id", 0)), p.get("sample", {}), p.get("checks", {}))
        if method == "sim_run_start":
            return self.sim.start(p.get("name", ""), int(p.get("recipe_id", 0)), p.get("sample", {}), p.get("checks", {}))
        if method == "sim_run":
            return self.sim.run(self._id_param(p))
        if method == "sim_run_events":
            return self.sim.run_events(self._id_param(p))
        if method == "sim_run_action":
            return self.sim.action(self._id_param(p), str(p.get("action", "")), note=str(p.get("note", "")),
                                   actor=str(p.get("actor", "operator")))
        if method == "sim_history":
            return self.sim.history(limit=int(p.get("limit", 50)), offset=int(p.get("offset", 0)),
                                    search=str(p.get("search", "")), status=str(p.get("status", "all")))
        if method == "sim_samples":
            return self.sim.samples(self._id_param(p), limit=int(p.get("limit", 300)),
                                    offset=int(p.get("offset", 0)), stride=int(p.get("stride", 1)),
                                    tail=p.get("tail") is True)
        if method == "sim_alarms":
            return {"items": self.sim.alarms()}
        if method == "sim_alarm_ack":
            return self.sim.acknowledge(self._id_param(p), str(p.get("actor", "")))
        if method == "sim_alarm_clear":
            return self.sim.clear_alarm(self._id_param(p), str(p.get("actor", "")))
        if method == "sim_audit":
            return {"items": self.sim.audit()}
        if method == "sim_analysis":
            return self.sim.analysis(self._id_param(p))
        if method == "sim_report":
            return {"html": self.sim.report_html(self._id_param(p))}
        if method == "sim_settings":
            return self.sim.settings()
        if method == "sim_settings_update":
            return self.sim.set_settings(limits=p.get("limits"), role=p.get("role"), scenario=p.get("scenario"))
        if method == "sim_import_legacy":
            return self.sim.import_legacy(Path(str(p.get("path", ""))))
        if method == "sim_legacy_runs":
            return {"items": self.sim.legacy_runs()}
        if method == "sim_legacy_samples":
            return self.sim.legacy_samples(str(p.get("source_hash", "")), self._id_param(p),
                                           limit=int(p.get("limit", 100)), offset=int(p.get("offset", 0)))
        if method == "sim_legacy_recipes":
            return {"items": self.sim.legacy_recipes()}
        if method == "sim_legacy_audit":
            return {"items": self.sim.legacy_audit()}
        if method == "bootstrap":
            return {
                "version": __version__,
                "mode": "simulation",
                "recipes": self.recipes.list_recipes(),
                "experiments": self.experiments.list_experiments(limit=20),
                "snapshot": self._snapshot(),
            }
        if method == "snapshot":
            return self._snapshot()
        if method == "recipes":
            return {"items": self.recipes.list_recipes()}
        if method == "history":
            return {"items": self.experiments.list_experiments(limit=100)}
        if method == "recipe_detail":
            recipe_id = self._id_param(_params)
            recipe = self.recipes.get_recipe(recipe_id)
            if recipe is None:
                raise ValueError(f"Recipe {recipe_id} not found")
            return {"item": recipe, "steps": self.recipes.get_recipe_steps(recipe_id)}
        if method == "experiment_detail":
            experiment_id = self._id_param(_params)
            experiment = self.experiments.get_experiment_detail(experiment_id)
            if experiment is None:
                raise ValueError(f"Experiment {experiment_id} not found")
            return {
                "item": experiment,
                "summary": self.experiments.get_experiment_summary(experiment_id),
                "alarms": self.db.list_alarm_history(experiment_id=experiment_id, limit=100),
            }
        raise ValueError(f"Unsupported bridge method: {method}")

    @staticmethod
    def _id_param(params: dict[str, Any] | None) -> int:
        value = (params or {}).get("id")
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("id must be a positive integer")
        return value

    def _snapshot(self) -> dict[str, Any]:
        return {
            "sampled_at": datetime.now(timezone.utc).isoformat(),
            "quality": "simulated",
            "values": asdict(self.client.read_snapshot()),
        }


def serve(input_stream: TextIO, output_stream: TextIO, bridge: DesktopBridge) -> None:
    for raw_line in input_stream:
        request_id = None
        try:
            request = json.loads(raw_line)
            if not isinstance(request, dict):
                raise TypeError("Bridge request must be an object")
            request_id = request.get("id")
            if not isinstance(request.get("method"), str):
                raise TypeError("Bridge method must be a string")
            params = request.get("params")
            if params is not None and not isinstance(params, dict):
                raise TypeError("params must be an object")
            response = {"id": request_id, "ok": True, "result": bridge.call(request["method"], params)}
        except WorkflowError as exc:
            response = {"id": request_id, "ok": False, "error": {"code": "WORKFLOW_CONFLICT", "message": str(exc)}}
        except (ValueError, TypeError) as exc:
            response = {"id": request_id, "ok": False, "error": {"code": "INVALID_REQUEST", "message": str(exc)}}
        except Exception as exc:  # noqa: BLE001 - keep the bridge alive and report backend failures
            response = {"id": request_id, "ok": False, "error": {"code": "BACKEND_ERROR", "message": str(exc)}}
        output_stream.write(json.dumps(response, ensure_ascii=False, default=str) + "\n")
        output_stream.flush()


def main() -> int:
    # Init arguments override a hardware-mode .env value. The Tauri shell cannot
    # opt into the legacy real-device write path through this process.
    bridge = DesktopBridge(Settings(simulation_mode=True))
    try:
        serve(sys.stdin, sys.stdout, bridge)
    finally:
        bridge.sim.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
