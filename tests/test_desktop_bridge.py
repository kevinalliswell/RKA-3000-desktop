from __future__ import annotations

import io
import json

import pytest

from rka_desktop.core.config import Settings
from rka_desktop.desktop_bridge import DesktopBridge, serve


def test_bridge_reports_simulation_snapshot_and_existing_lists(tmp_path) -> None:
    bridge = DesktopBridge(Settings(db_path=str(tmp_path / "bridge.db"), simulation_mode=True))
    result = bridge.call("bootstrap")

    assert result["mode"] == "simulation"
    assert result["snapshot"]["quality"] == "simulated"
    assert "temperature_c" in result["snapshot"]["values"]
    assert result["recipes"] == []
    assert result["experiments"] == []


def test_bridge_rejects_hardware_mode_and_unknown_commands(tmp_path) -> None:
    with pytest.raises(ValueError, match="simulation mode"):
        DesktopBridge(Settings(db_path=str(tmp_path / "bridge.db"), simulation_mode=False))

    bridge = DesktopBridge(Settings(db_path=str(tmp_path / "bridge.db"), simulation_mode=True))
    request = io.StringIO('{"id":7,"method":"set_temperature","params":{"value":900}}\n')
    response = io.StringIO()
    serve(request, response, bridge)
    message = json.loads(response.getvalue())
    assert message["id"] == 7
    assert message["ok"] is False
    assert message["error"]["code"] == "INVALID_REQUEST"


def test_bridge_reads_saved_recipe_and_experiment_details(tmp_path) -> None:
    bridge = DesktopBridge(Settings(db_path=str(tmp_path / "bridge.db"), simulation_mode=True))
    recipe_id = bridge.recipes.create_recipe("仿真配方", [])
    experiment_id = bridge.experiments.create_experiment("样品 A", recipe_id=recipe_id)

    recipe = bridge.call("recipe_detail", {"id": recipe_id})
    experiment = bridge.call("experiment_detail", {"id": experiment_id})

    assert recipe["item"]["name"] == "仿真配方"
    assert recipe["steps"] == []
    assert experiment["item"]["name"] == "样品 A"
    assert experiment["summary"] is None
    assert experiment["alarms"] == []
    with pytest.raises(ValueError, match="positive integer"):
        bridge.call("recipe_detail", {"id": True})
