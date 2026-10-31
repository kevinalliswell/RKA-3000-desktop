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


class DesktopBridge:
    """Small, read-only bridge used while the web UI is being migrated."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings(simulation_mode=True)
        if not self.settings.simulation_mode:
            raise ValueError("Desktop bridge only supports simulation mode")
        self.db = DatabaseManager(Path(self.settings.db_path))
        self.db.init_schema()
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
    serve(sys.stdin, sys.stdout, bridge)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
