"""Start the frozen (or source) backend in an isolated data directory and exercise the API.

No serial port is opened: the default configuration is simulation mode, and the checks stop
before any run is started. Verifies: stdout handshake, 401 without token, health, recipe CRUD,
export task, graceful shutdown with exit code 0 and no leftover process.
"""

from __future__ import annotations

import argparse
import json
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from http.client import HTTPConnection
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("executable", nargs="?", help="frozen backend; defaults to `python -m rka_desktop.adapters.api`")
    args = parser.parse_args()
    token = secrets.token_hex(32)
    with tempfile.TemporaryDirectory(prefix="rka3000-smoke-") as temp:
        environment = dict(os.environ, RKA3000_API_TOKEN=token, PYTHONUTF8="1", RKA3000_DATA_DIR=str(Path(temp) / "data"))
        if args.executable:
            command = [str(Path(args.executable).resolve()), "--port", "0"]
        else:
            environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
            command = [sys.executable, "-m", "rka_desktop.adapters.api", "--port", "0"]
        with (Path(temp) / "backend-stderr.txt").open("w+", encoding="utf-8") as errors:
            process = subprocess.Popen(command, env=environment, cwd=temp, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=errors, text=True, encoding="utf-8")
            try:
                ready: queue.Queue[str] = queue.Queue()
                threading.Thread(target=lambda: ready.put(process.stdout.readline()), daemon=True).start()
                handshake = json.loads(ready.get(timeout=60))
                port = handshake["port"]
                assert handshake["api_version"] == 1, handshake

                def request(method, path, payload=None, authenticated=True):
                    connection = HTTPConnection("127.0.0.1", port, timeout=10)
                    headers = {"Content-Type": "application/json"}
                    if authenticated:
                        headers["Authorization"] = f"Bearer {token}"
                    connection.request(method, path, json.dumps(payload) if payload is not None else None, headers)
                    response = connection.getresponse()
                    result = response.status, json.loads(response.read() or b"null")
                    connection.close()
                    return result

                assert request("GET", "/api/health", authenticated=False)[0] == 401
                status, health = request("GET", "/api/health")
                assert status == 200 and health["ok"] and health["simulation_mode"], health
                assert request("GET", "/api/run")[1]["status"] == "idle"
                assert request("GET", "/api/devices/status")[1]["supported"]
                status, created = request("POST", "/api/recipes", {"name": "smoke", "steps": [
                    {"target_temp_c": 900, "ramp_rate_cpm": 10, "hold_seconds": 60, "n2_lpm": 8, "h2_lpm": 1, "co_lpm": 0.8}]})
                assert status == 201, created
                assert request("POST", "/api/recipes", {"name": "", "steps": []})[0] == 400
                assert request("DELETE", f"/api/recipes/{created['recipe']['id']}")[0] == 200
                assert request("POST", "/api/run/start", {"recipe_id": 999})[0] == 404
                assert request("GET", "/api/limits")[1]["policy"]["version"] == 1
                assert request("GET", "/api/overview")[1]["run"]["status"] == "idle"
                assert request("POST", "/api/run/preflight", {})[1]["ready"] is False
                assert request("POST", "/api/shutdown")[0] == 202
                exit_code = process.wait(timeout=30)
                assert exit_code == 0, f"backend exit code {exit_code}"
                log = (Path(temp) / "data" / "logs" / "backend.log").read_text(encoding="utf-8")
                assert "backend exited cleanly" in log
                assert token not in log, "token leaked into the log"
                print("Backend smoke: handshake, auth, health, recipes, limits, preflight, validation and shutdown passed.")
            except BaseException:
                errors.flush()
                errors.seek(0)
                print(errors.read())
                raise
            finally:
                if process.poll() is None:
                    if sys.platform == "win32":
                        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], check=False, capture_output=True)
                    else:
                        process.kill()
                    process.wait(timeout=10)
                time.sleep(0.2)


if __name__ == "__main__":
    main()
