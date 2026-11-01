"""HTTP adapter: loopback/token enforcement, body limits, routing, error mapping, shutdown, stdin EOF."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from http.client import HTTPConnection
from pathlib import Path

import pytest

from rka_desktop.adapters.api.server import ApiServer
from rka_desktop.bootstrap import build_container
from rka_desktop.infrastructure.config import AppConfig
from rka_desktop.infrastructure.paths import AppPaths
from tests.conftest import RECIPE_STEPS, FakeGateway

TOKEN = "test-secret-token-0123456789"


@pytest.fixture
def api(tmp_path):
    paths = AppPaths(tmp_path / "data")
    container = build_container(AppConfig(poll_interval_ms=100), paths, gateway=FakeGateway())
    server = ApiServer(("127.0.0.1", 0), container, TOKEN)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()

    def request(method, path, payload=None, *, authenticated=True, raw: bytes | None = None, content_type="application/json"):
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        headers = {}
        body = raw if raw is not None else (json.dumps(payload).encode("utf-8") if payload is not None else None)
        if body is not None:
            headers["Content-Type"] = content_type
            headers["Content-Length"] = str(len(body))
        if authenticated:
            headers["Authorization"] = f"Bearer {TOKEN}"
        connection.request(method, path, body, headers)
        response = connection.getresponse()
        data = response.read()
        result = response.status, (json.loads(data) if data else None), dict(response.getheaders())
        connection.close()
        return result

    yield request, server, container, thread
    if thread.is_alive():
        server.shutdown()
    server.server_close()
    container.close()
    thread.join(5)


def test_rejects_non_loopback_and_weak_token(tmp_path):
    container = build_container(AppConfig(), AppPaths(tmp_path / "d"), gateway=FakeGateway())
    try:
        with pytest.raises(ValueError):
            ApiServer(("0.0.0.0", 0), container, TOKEN)
        with pytest.raises(ValueError):
            ApiServer(("127.0.0.1", 0), container, "short")
    finally:
        container.close()


def test_auth_health_and_version_header(api):
    request, *_ = api
    assert request("GET", "/api/health", authenticated=False)[0] == 401
    status, payload, headers = request("GET", "/api/health")
    assert status == 200 and payload["ok"] and payload["api_version"] == 1 and payload["simulation_mode"]
    assert headers["X-RKA3000-API-Version"] == "1"
    assert "Access-Control-Allow-Origin" not in headers
    assert request("GET", "/api/nope")[0] == 404
    assert request("DELETE", "/api/health")[0] == 405


def test_body_limits_and_malformed_json(api):
    request, *_ = api
    status, payload, _ = request("POST", "/api/recipes", raw=b"{bad", content_type="application/json")
    assert status == 400 and payload["error"]["code"] == "invalid_request"
    status, payload, _ = request("POST", "/api/recipes", raw=b"[]")
    assert status == 400
    status, payload, _ = request("POST", "/api/recipes", raw=b"x" * (1_048_576 + 1))
    assert status == 413 and payload["error"]["code"] == "payload_too_large"
    status, payload, _ = request("POST", "/api/recipes", raw=b'{"name":"a"}', content_type="text/plain")
    assert status == 400
    assert request("POST", "/api/recipes")[0] == 400  # empty body


def test_recipe_run_and_task_flow_over_http(api):
    request, server, container, _ = api
    status, payload, _ = request("POST", "/api/recipes", {"name": "流程", "steps": RECIPE_STEPS})
    assert status == 201
    recipe_id = payload["recipe"]["id"]
    assert request("GET", "/api/recipes")[1]["recipes"][0]["id"] == recipe_id
    assert request("POST", "/api/recipes", {"name": "", "steps": RECIPE_STEPS})[0] == 400
    assert request("GET", "/api/recipes/999")[0] == 404
    document = request("GET", f"/api/recipes/{recipe_id}/export")[1]["document"]
    assert document["format"] == "rka3000-recipe"
    assert request("POST", "/api/recipes/import", {"document": document, "name": "副本"})[0] == 201

    assert request("POST", "/api/run/start", {"recipe_id": "1"})[0] == 400
    status, run, _ = request("POST", "/api/run/start", {"recipe_id": recipe_id})
    assert status == 202 and run["status"] == "running"
    status, payload, _ = request("POST", "/api/run/start", {"recipe_id": recipe_id})
    assert status == 409 and payload["error"]["code"] == "conflict"
    status, payload, _ = request("PUT", f"/api/recipes/{recipe_id}", {"name": "x", "steps": RECIPE_STEPS})
    assert status == 409  # recipe in use by the active run
    status, payload, _ = request("POST", "/api/run/gas-mode", {"mode": "manual"})
    assert status == 409 and payload["error"]["code"] == "confirmation_required"
    assert request("POST", "/api/run/gas-mode", {"mode": "manual", "confirm": True})[1]["gas_mode"] == "manual"
    status, payload, _ = request("POST", "/api/run/manual-gas", {"n2_lpm": 1, "h2_lpm": 0, "co_lpm": 0, "confirm": True})
    assert status == 200 and payload["manual_gas"]["n2_lpm"] == 1.0
    status, payload, _ = request("POST", "/api/devices/tare", {"confirm": True})
    assert status == 409 and payload["error"]["code"] == "conflict"  # devices owned by the run
    status, payload, _ = request("POST", "/api/run/reset-interlock", {"confirm": True})
    assert status == 409 and payload["error"]["code"] == "invalid_state"
    time.sleep(0.3)
    measurements = request("GET", "/api/run/measurements?since=0")[1]
    assert measurements["items"] and measurements["seq"] >= len(measurements["items"])
    status, payload, _ = request("POST", "/api/run/stop")
    assert status == 202 and payload["status"] in {"stopping", "stopped"}
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and request("GET", "/api/run")[1]["status"] != "stopped":
        time.sleep(0.02)
    run_state = request("GET", "/api/run")[1]
    assert run_state["status"] == "stopped" and run_state["allowed"]["start"]
    exp_id = run_state["experiment_id"]

    assert request("GET", "/api/experiments")[1]["experiments"][0]["id"] == exp_id
    assert request("PATCH", f"/api/experiments/{exp_id}", {"name": "重命名"})[1]["experiment"]["name"] == "重命名"
    status, payload, _ = request("POST", f"/api/experiments/{exp_id}/export", {"kind": "measurements_csv"})
    assert status == 202
    task_id = payload["task"]["id"]
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and request("GET", f"/api/tasks/{task_id}")[1]["task"]["status"] not in {"completed", "failed"}:
        time.sleep(0.02)
    task = request("GET", f"/api/tasks/{task_id}")[1]["task"]
    assert task["status"] == "completed" and Path(task["result"]["path"]).is_file()
    assert Path(task["result"]["path"]).parent == container.paths.export_dir
    assert request("GET", "/api/tasks/" + "0" * 32)[0] == 404
    assert request("POST", f"/api/tasks/{task_id}/cancel")[1]["task"]["status"] == "completed"
    assert request("PUT", f"/api/experiments/{exp_id}/sample-params", {"initial_mass_g": 50, "tfe_pct": 60, "feo_pct": 0})[0] == 200
    assert request("POST", f"/api/experiments/{exp_id}/kinetics")[0] == 200
    assert request("GET", "/api/audit?limit=5")[1]["logs"]
    assert request("GET", "/api/alarms")[1]["alarms"] == []
    assert request("GET", "/api/devices/status")[1]["supported"]
    assert request("POST", "/api/devices/tare", {"confirm": True})[1]["ok"]
    status, payload, _ = request("DELETE", f"/api/experiments/{exp_id}")
    assert status == 409 and payload["error"]["code"] == "confirmation_required"
    assert request("DELETE", f"/api/experiments/{exp_id}", {"confirm": True})[0] == 200
    assert request("GET", f"/api/experiments/{exp_id}")[0] == 404
    assert request("GET", "/api/log")[1]["filename"] == "backend.log"
    assert request("GET", "/api/settings")[1]["config"]["simulation_mode"] is True
    status, payload, _ = request("PUT", "/api/settings", {"poll_interval_ms": 250})
    assert status == 200 and payload["restart_required"] is True and payload["changed"] == ["poll_interval_ms"]
    assert request("PUT", "/api/settings", {"bogus": 1})[0] == 400
    assert request("POST", "/api/shutdown")[0] == 202
    api[3].join(5)
    assert not api[3].is_alive()


def _start_backend(tmp_path: Path, *extra: str, stdin):
    src = Path(__file__).resolve().parents[1] / "src"
    environment = dict(os.environ, RKA3000_API_TOKEN=TOKEN, PYTHONPATH=str(src), RKA3000_DATA_DIR=str(tmp_path / "data"),
                       PYTHONUTF8="1")
    process = subprocess.Popen(
        [sys.executable, "-m", "rka_desktop.adapters.api", "--port", "0", *extra],
        env=environment, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
    )
    line = process.stdout.readline()
    handshake = json.loads(line)
    return process, handshake


def test_backend_handshake_and_stdin_eof_shutdown(tmp_path):
    process, handshake = _start_backend(tmp_path, "--exit-on-stdin-eof", stdin=subprocess.PIPE)
    try:
        assert handshake["port"] > 0 and handshake["api_version"] == 1 and handshake["pid"] == process.pid
        connection = HTTPConnection("127.0.0.1", handshake["port"], timeout=5)
        connection.request("GET", "/api/health", headers={"Authorization": f"Bearer {TOKEN}"})
        assert connection.getresponse().status == 200
        connection.close()
        process.stdin.close()  # what the OS does when the desktop dies
        assert process.wait(timeout=15) == 0
        log = (tmp_path / "data" / "logs" / "backend.log").read_text(encoding="utf-8")
        assert "owner process closed stdin" in log and "backend exited cleanly" in log
        assert TOKEN not in log
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()


def test_backend_without_stdin_watch_shuts_down_via_api(tmp_path):
    process, handshake = _start_backend(tmp_path, stdin=subprocess.DEVNULL)
    try:
        time.sleep(0.3)
        assert process.poll() is None
        connection = HTTPConnection("127.0.0.1", handshake["port"], timeout=5)
        connection.request("POST", "/api/shutdown", headers={"Authorization": f"Bearer {TOKEN}"})
        assert connection.getresponse().status == 202
        connection.close()
        assert process.wait(timeout=15) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
