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
from tests.conftest import RECIPE_PAYLOAD, FakeGateway, start_payload

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


def _wait(request, path, predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        payload = request("GET", path)[1]
        if predicate(payload):
            return payload
        time.sleep(0.05)
    pytest.fail(f"condition not reached for {path}: {payload}")


def _wait_task(request, task_id):
    return _wait(request, f"/api/tasks/{task_id}", lambda p: p["task"]["status"] in {"completed", "failed"})["task"]


def test_experiment_lifecycle_over_http(api):
    request, server, container, _ = api
    status, payload, _ = request("POST", "/api/recipes", RECIPE_PAYLOAD)
    assert status == 201 and payload["recipe"]["assessment"]["runnable"]
    recipe_id = payload["recipe"]["id"]
    assert request("GET", "/api/recipes")[1]["recipes"][0]["runnable"] is True
    assert request("POST", "/api/recipes", {**RECIPE_PAYLOAD, "name": ""})[0] == 400
    assert request("GET", "/api/recipes/999")[0] == 404
    document = request("GET", f"/api/recipes/{recipe_id}/export")[1]["document"]
    assert document["format"] == "rka3000-recipe" and document["version"] == 2
    assert request("POST", "/api/recipes/import", {"document": document, "name": "副本"})[0] == 201
    assert request("GET", f"/api/recipes/{recipe_id}/versions")[1]["versions"][0]["version"] == 1
    assert request("GET", "/api/limits")[1]["policy"]["version"] == 1
    rules = request("GET", "/api/rules")[1]
    assert rules["alarm_rules"] and rules["process_gases"]["oxidation"] == ["CO2", "O2"] and rules["inert_gases"] == ["N2", "AR"]

    status, preflight, _ = request("POST", "/api/run/preflight", {"recipe_id": recipe_id})
    assert status == 200 and not preflight["ready"] and preflight["checklist_items"]
    status, payload, _ = request("POST", "/api/run/start", {"recipe_id": recipe_id})
    assert status == 409 and payload["error"]["code"] == "preflight_failed" and payload["error"]["detail"]["checks"]
    assert request("POST", "/api/run/start", {"recipe_id": "1"})[0] == 400
    assert request("POST", "/api/run/start", start_payload(999))[0] == 404
    status, run, _ = request("POST", "/api/run/start", start_payload(recipe_id))
    assert status == 202 and run["status"] == "running" and run["experiment"]["code"].startswith("RKA-")
    status, payload, _ = request("POST", "/api/run/start", start_payload(recipe_id))
    assert status == 409 and payload["error"]["code"] == "conflict"
    status, payload, _ = request("PUT", f"/api/recipes/{recipe_id}", {**RECIPE_PAYLOAD, "reason": "修改测试"})
    assert status == 409  # recipe in use by the active run
    assert request("PUT", "/api/limits", {"limits": {"CO": 1.0}, "reason": "运行中修改"})[0] == 409
    status, payload, _ = request("POST", "/api/run/gas-mode", {"mode": "manual"})
    assert status == 409 and payload["error"]["code"] == "confirmation_required"
    assert request("POST", "/api/run/gas-mode", {"mode": "manual", "confirm": True})[1]["gas_mode"] == "manual"
    status, payload, _ = request("POST", "/api/run/manual-gas", {"flows": {"N2": 3.5}, "reason": "接口测试", "confirm": True})
    assert status == 200 and payload["last_command"]["state"] == "applied" and payload["manual_gas"]["N2"] == 3.5
    assert request("POST", "/api/run/manual-gas", {"flows": {"O2": 1}, "reason": "接口测试", "confirm": True})[0] == 400
    status, payload, _ = request("POST", "/api/devices/tare", {"confirm": True})
    assert status == 409 and payload["error"]["code"] == "conflict"  # devices owned by the run
    status, payload, _ = request("POST", "/api/run/reset-interlock", {"confirm": True})
    assert status == 409 and payload["error"]["code"] == "invalid_state"
    assert request("POST", "/api/run/stop", {})[1]["error"]["code"] == "confirmation_required"
    time.sleep(0.3)
    measurements = request("GET", "/api/run/measurements?since=0")[1]
    assert measurements["items"] and measurements["seq"] >= len(measurements["items"])
    assert request("GET", "/api/overview")[1]["run"]["status"] == "running"
    status, payload, _ = request("POST", "/api/run/emergency")
    assert status == 202 and payload["status"] == "purging" and payload["emergency"]
    run_state = _wait(request, "/api/run", lambda p: p["status"] == "stopped")  # 2 s purge, furnace already cold
    assert run_state["allowed"]["start"] and run_state["end_reason"] == "emergency"
    exp_id = run_state["experiment_id"]

    listed = request("GET", "/api/experiments?category=pending")[1]
    assert [e["id"] for e in listed["experiments"]] == [exp_id] and listed["counts"]["pending"] == 1
    assert request("GET", "/api/experiments?category=nope")[0] == 400
    assert request("GET", "/api/limits")[1]["locked"]  # not archived yet
    assert not request("POST", "/api/run/preflight", start_payload(recipe_id))[1]["ready"]
    assert request("PATCH", f"/api/experiments/{exp_id}", {"name": "重命名"})[1]["experiment"]["name"] == "重命名"
    status, payload, _ = request("POST", f"/api/experiments/{exp_id}/export", {"kind": "measurements_csv"})
    assert status == 202
    task = _wait_task(request, payload["task"]["id"])
    assert task["status"] == "completed" and Path(task["result"]["path"]).is_file()
    assert Path(task["result"]["path"]).parent == container.paths.export_dir
    assert request("GET", "/api/tasks/" + "0" * 32)[0] == 404
    assert request("POST", f"/api/tasks/{task['id']}/cancel")[1]["task"]["status"] == "completed"
    assert request("POST", f"/api/experiments/{exp_id}/kinetics")[0] == 200
    assert request("POST", f"/api/experiments/{exp_id}/report")[1]["error"]["code"] == "conflict"  # not archived

    review = request("GET", f"/api/experiments/{exp_id}/review")[1]
    assert review["can_archive"] and review["note_required"]  # emergency ending must be explained
    assert request("POST", f"/api/experiments/{exp_id}/archive", {"note": "x"})[1]["error"]["code"] == "confirmation_required"
    assert request("POST", f"/api/experiments/{exp_id}/archive", {"confirm": True})[0] == 409
    status, archived, _ = request("POST", f"/api/experiments/{exp_id}/archive",
                                  {"confirm": True, "note": "接口测试中按下紧急停气", "operator": "实验员 A"})
    assert status == 200 and archived["experiment"]["review_state"] == "archived"
    assert request("PUT", f"/api/experiments/{exp_id}/sample-params", {"initial_mass_g": 50, "tfe_pct": 60, "feo_pct": 0})[0] == 409
    assert request("GET", f"/api/experiments/{exp_id}/compare")[1]["items"][0]["current"]
    status, payload, _ = request("POST", f"/api/experiments/{exp_id}/report", {"operator": "实验员 A"})
    assert status == 202 and _wait_task(request, payload["task"]["id"])["result"]["version"] == 1
    assert request("GET", "/api/reports")[1]["items"][0]["latest_report"]["version"] == 1
    assert not request("GET", "/api/limits")[1]["locked"]
    affected = request("POST", "/api/limits/preview", {"limits": {"CO": 0.5}})[1]["affected"]
    assert recipe_id in {item["recipe_id"] for item in affected}
    assert request("PUT", "/api/limits", {"limits": {"CO": 0.5}, "reason": ""})[0] == 400
    assert request("PUT", "/api/limits", {"limits": {"CO": 0.5}, "reason": "接口测试"})[1]["policy"]["version"] == 2

    audit = request("GET", f"/api/audit?limit=50&experiment_id={exp_id}")[1]["logs"]
    assert {"EXPERIMENT_START", "MANUAL_GAS_SET", "EMERGENCY_STOP", "EXPERIMENT_ARCHIVE"} <= {row["action"] for row in audit}
    assert all(row["category"] == "safety" for row in request("GET", "/api/audit?category=safety")[1]["logs"])
    assert request("GET", "/api/audit?category=bogus")[0] == 400
    status, payload, _ = request("POST", "/api/audit/export", {"experiment_id": exp_id})
    assert status == 202 and _wait_task(request, payload["task"]["id"])["status"] == "completed"
    assert request("GET", "/api/alarms?state=pending")[1]["alarms"] == []
    assert request("POST", "/api/alarms/999/ack", {"note": "测试说明"})[0] == 404
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
