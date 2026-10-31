"""Simulation-only experiment workflow for the new desktop UI.

This module never imports a hardware client. All transitions are validated here,
and every persisted run owns a copy of the recipe used at start.
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

GASES = ("n2", "ar", "co", "co2", "h2", "ch4", "o2")
MFC = {"n2": 1, "ar": 1, "co": 2, "co2": 3, "h2": 4, "ch4": 5, "o2": 6}
DEFAULT_LIMITS = {"n2": 20.0, "ar": 20.0, "co": 5.0, "co2": 20.0, "h2": 5.0, "ch4": 5.0, "o2": 10.0}
DEVICE_MAX = {"n2": 20.0, "ar": 20.0, "co": 10.0, "co2": 20.0, "h2": 10.0, "ch4": 10.0, "o2": 20.0}
ACTIVE = ("PURGE", "REACTION", "COOLING", "PAUSED")


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowError(ValueError):
    """A rejected simulation command with a user-facing reason."""


class SimulationWorkflow:
    def __init__(self, path: Path, *, start_worker: bool = True, tick_seconds: float = 1.0) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.tick_seconds = tick_seconds
        self._closed = threading.Event()
        self.worker_error = ""
        with self._db() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sim_recipes (
                  id INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL,
                  version INTEGER NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
                  UNIQUE(name, version));
                CREATE TABLE IF NOT EXISTS sim_runs (
                  id INTEGER PRIMARY KEY, name TEXT NOT NULL, sample TEXT NOT NULL,
                  recipe_id INTEGER NOT NULL, recipe_snapshot TEXT NOT NULL,
                  state TEXT NOT NULL, stage_index INTEGER NOT NULL DEFAULT 0,
                  stage_elapsed REAL NOT NULL DEFAULT 0, resumed_state TEXT,
                  started_at TEXT NOT NULL, updated_at TEXT NOT NULL, finished_at TEXT,
                  review_note TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT 'simulation');
                CREATE TABLE IF NOT EXISTS sim_samples (
                  id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL, sampled_at TEXT NOT NULL,
                  elapsed_s REAL NOT NULL, temperature_c REAL, weight_g REAL,
                  flows TEXT NOT NULL, quality TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '');
                CREATE INDEX IF NOT EXISTS sim_samples_run ON sim_samples(run_id,id);
                CREATE TABLE IF NOT EXISTS sim_alarms (
                  id INTEGER PRIMARY KEY, run_id INTEGER, code TEXT NOT NULL,
                  severity TEXT NOT NULL, message TEXT NOT NULL, appeared_at TEXT NOT NULL,
                  acknowledged_at TEXT, acknowledged_by TEXT, cleared_at TEXT);
                CREATE TABLE IF NOT EXISTS sim_audit (
                  id INTEGER PRIMARY KEY, run_id INTEGER, actor TEXT NOT NULL,
                  action TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sim_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sim_imports (
                  fingerprint TEXT PRIMARY KEY, source_path TEXT NOT NULL,
                  backup_path TEXT NOT NULL, imported_at TEXT NOT NULL,
                  recipe_count INTEGER NOT NULL, run_count INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS sim_legacy_runs (
                  source_hash TEXT NOT NULL, source_id INTEGER NOT NULL,
                  body TEXT NOT NULL, imported_at TEXT NOT NULL,
                  PRIMARY KEY(source_hash, source_id));
                CREATE TABLE IF NOT EXISTS sim_legacy_recipes (
                  source_hash TEXT NOT NULL, source_id INTEGER NOT NULL,
                  body TEXT NOT NULL, imported_at TEXT NOT NULL,
                  PRIMARY KEY(source_hash, source_id));
                CREATE TABLE IF NOT EXISTS sim_legacy_audit (
                  source_hash TEXT NOT NULL, source_id INTEGER NOT NULL,
                  body TEXT NOT NULL, imported_at TEXT NOT NULL,
                  PRIMARY KEY(source_hash, source_id));
                CREATE TABLE IF NOT EXISTS sim_legacy_samples (
                  source_hash TEXT NOT NULL, source_run_id INTEGER NOT NULL,
                  source_sample_id INTEGER NOT NULL, body TEXT NOT NULL,
                  PRIMARY KEY(source_hash, source_sample_id));
                CREATE INDEX IF NOT EXISTS sim_legacy_samples_run
                  ON sim_legacy_samples(source_hash, source_run_id, source_sample_id);
            """)
            db.execute("INSERT OR IGNORE INTO sim_settings VALUES ('limits', ?)", (json.dumps(DEFAULT_LIMITS),))
            db.execute("INSERT OR IGNORE INTO sim_settings VALUES ('role', 'operator')")
            db.execute("INSERT OR IGNORE INTO sim_settings VALUES ('scenario', 'normal')")
            db.execute("UPDATE sim_runs SET state='RECOVERY_REQUIRED', review_note='应用重启后需人工复核，仿真不会自动续行', updated_at=? WHERE state IN ('PURGE','REACTION','COOLING','PAUSED')", (utcnow(),))
            if not db.execute("SELECT 1 FROM sim_recipes LIMIT 1").fetchone():
                self._insert_recipe(db, "还原基准配方", "reduction", [
                    {"name": "反应测定", "duration_s": 60, "temperature_c": 750, "flows": {"n2": 5, "h2": 1, "co": 1}}
                ])
                self._insert_recipe(db, "氧化基准配方", "oxidation", [
                    {"name": "反应测定", "duration_s": 60, "temperature_c": 700, "flows": {"n2": 5, "o2": 1}}
                ])
        if start_worker:
            self.worker = threading.Thread(target=self._run_worker, name="rka-simulation", daemon=True)
            self.worker.start()

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=3)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout=3000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def close(self) -> None:
        self._closed.set()
        if hasattr(self, "worker"):
            self.worker.join(timeout=2)

    def _setting(self, db: sqlite3.Connection, key: str) -> str:
        return str(db.execute("SELECT value FROM sim_settings WHERE key=?", (key,)).fetchone()[0])

    def settings(self) -> dict[str, Any]:
        with self.lock, self._db() as db:
            return {"limits": json.loads(self._setting(db, "limits")), "role": self._setting(db, "role"),
                    "scenario": self._setting(db, "scenario"), "mode": "simulation", "hardware_writes": False}

    def set_settings(self, *, limits: dict[str, Any] | None = None, role: str | None = None,
                     scenario: str | None = None) -> dict[str, Any]:
        with self.lock, self._db() as db:
            if role is not None:
                if role not in ("operator", "reviewer", "administrator"):
                    raise WorkflowError("角色无效")
                db.execute("UPDATE sim_settings SET value=? WHERE key='role'", (role,))
            if limits is not None:
                if set(limits) != set(GASES):
                    raise WorkflowError("须为七种气体分别设置上限")
                for gas, value in limits.items():
                    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0 or value > DEVICE_MAX[gas]:
                        raise WorkflowError(f"{gas} 上限无效")
                if any(float(limits[g]) != json.loads(self._setting(db, "limits"))[g] for g in GASES):
                    if self._setting(db, "role") != "administrator":
                        raise WorkflowError("仅仿真管理员可修改气体使用上限")
                    if db.execute("SELECT 1 FROM sim_runs WHERE state != 'ARCHIVED' LIMIT 1").fetchone():
                        raise WorkflowError("有实验未归档，不能修改气体使用上限")
                    db.execute("UPDATE sim_settings SET value=? WHERE key='limits'", (json.dumps(limits),))
            if scenario is not None:
                if scenario not in ("normal", "offline", "stale", "alarm", "unstable"):
                    raise WorkflowError("仿真场景无效")
                db.execute("UPDATE sim_settings SET value=? WHERE key='scenario'", (scenario,))
            self._audit(db, None, "settings.update", json.dumps({"limits": limits, "role": role, "scenario": scenario}, ensure_ascii=False))
        return self.settings()

    def _audit(self, db: sqlite3.Connection, run_id: int | None, action: str, detail: str,
               actor: str = "operator") -> None:
        db.execute("INSERT INTO sim_audit(run_id,actor,action,detail,created_at) VALUES(?,?,?,?,?)",
                   (run_id, actor, action, detail, utcnow()))

    def _validate_recipe(self, kind: str, stages: list[dict[str, Any]], limits: dict[str, float]) -> list[dict[str, Any]]:
        if kind not in ("reduction", "oxidation") or not isinstance(stages, list) or not 1 <= len(stages) <= 24:
            raise WorkflowError("实验类型或阶段数无效")
        normalized = []
        for i, stage in enumerate(stages):
            if not isinstance(stage, dict) or not str(stage.get("name", "")).strip():
                raise WorkflowError(f"阶段 {i+1} 缺少名称")
            duration = stage.get("duration_s")
            temp = stage.get("temperature_c")
            if isinstance(duration, bool) or not isinstance(duration, (int, float)) or not 1 <= duration <= 86400:
                raise WorkflowError(f"阶段 {i+1} 时长须为 1–86400 秒")
            if isinstance(temp, bool) or not isinstance(temp, (int, float)) or not math.isfinite(temp) or not 20 <= temp <= 1200:
                raise WorkflowError(f"阶段 {i+1} 温度须为 20–1200 ℃")
            raw_flows = stage.get("flows", {})
            if not isinstance(raw_flows, dict) or any(g not in GASES for g in raw_flows):
                raise WorkflowError(f"阶段 {i+1} 气体无效")
            flows = {}
            for gas in GASES:
                value = raw_flows.get(gas, 0)
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or value > limits[gas]:
                    raise WorkflowError(f"阶段 {i+1} 的 {gas.upper()} 超出上限")
                flows[gas] = float(value)
            if flows["n2"] and flows["ar"]:
                raise WorkflowError("N₂ 与 Ar 共用 MFC-01，不能同时使用")
            if kind == "reduction" and flows["o2"]:
                raise WorkflowError("还原实验禁用 O₂")
            if kind == "oxidation" and any(flows[g] for g in ("co", "h2", "ch4")):
                raise WorkflowError("氧化实验禁用 CO、H₂、CH₄")
            normalized.append({"name": str(stage["name"]).strip()[:80], "duration_s": int(duration),
                               "temperature_c": float(temp), "flows": flows})
        inert = {g for stage in normalized for g in ("n2", "ar") if stage["flows"][g] > 0}
        if len(inert) > 1:
            raise WorkflowError("一次实验只能选 N₂ 或 Ar 作为惰性气体")
        if not inert:
            raise WorkflowError("至少一个阶段需要 N₂ 或 Ar 惰性气体")
        return normalized

    def _insert_recipe(self, db: sqlite3.Connection, name: str, kind: str,
                       stages: list[dict[str, Any]]) -> dict[str, Any]:
        limits = json.loads(self._setting(db, "limits"))
        stages = self._validate_recipe(kind, stages, limits)
        version = int(db.execute("SELECT COALESCE(MAX(version),0)+1 FROM sim_recipes WHERE name=?", (name,)).fetchone()[0])
        body = {"name": name, "kind": kind, "version": version, "stages": stages}
        cur = db.execute("INSERT INTO sim_recipes(name,kind,version,body,created_at) VALUES(?,?,?,?,?)",
                         (name, kind, version, json.dumps(body, ensure_ascii=False), utcnow()))
        self._audit(db, None, "recipe.save", f"{name} v{version}")
        return {"id": cur.lastrowid, **body}

    def save_recipe(self, name: str, kind: str, stages: list[dict[str, Any]]) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 100:
            raise WorkflowError("配方名称须为 1–100 个字符")
        with self.lock, self._db() as db:
            return self._insert_recipe(db, name.strip(), kind, stages)

    def recipes(self) -> list[dict[str, Any]]:
        with self.lock, self._db() as db:
            rows = db.execute("SELECT id,name,kind,version,created_at FROM sim_recipes ORDER BY id DESC").fetchall()
            return [dict(row) for row in rows]

    def recipe(self, recipe_id: int) -> dict[str, Any]:
        with self.lock, self._db() as db:
            row = db.execute("SELECT id,body,created_at FROM sim_recipes WHERE id=?", (recipe_id,)).fetchone()
            if row is None:
                raise WorkflowError("配方不存在")
            return {"id": row["id"], "created_at": row["created_at"], **json.loads(row["body"])}

    def preflight(self, recipe_id: int, sample: dict[str, Any], checks: dict[str, bool]) -> dict[str, Any]:
        recipe = self.recipe(recipe_id)
        reasons = []
        if not isinstance(sample, dict) or not str(sample.get("name", "")).strip():
            reasons.append("请填写样品名称")
        mass = sample.get("initial_mass_g") if isinstance(sample, dict) else None
        if isinstance(mass, bool) or not isinstance(mass, (int, float)) or not math.isfinite(mass) or mass <= 0:
            reasons.append("请填写有效的初始质量")
        if not isinstance(checks, dict) or not all(checks.get(key) is True for key in ("gas", "exhaust", "balance", "operator")):
            reasons.append("请完成气源、排风、天平和人员确认")
        settings = self.settings()
        try:
            self._validate_recipe(recipe["kind"], recipe["stages"], settings["limits"])
        except WorkflowError as exc:
            reasons.append(f"配方与当前上限不符：{exc}")
        if settings["scenario"] != "normal":
            reasons.append("仿真设备场景异常，不能启动")
        with self.lock, self._db() as db:
            if db.execute("SELECT 1 FROM sim_runs WHERE state IN ('PURGE','REACTION','COOLING','PAUSED','RECOVERY_REQUIRED','EMERGENCY','REVIEW','REVIEWED') LIMIT 1").fetchone():
                reasons.append("存在未复核或未归档的实验")
        return {"ok": not reasons, "reasons": reasons, "recipe": recipe,
                "mode": "simulation", "checked_at": utcnow()}

    def start(self, name: str, recipe_id: int, sample: dict[str, Any], checks: dict[str, bool]) -> dict[str, Any]:
        checked = self.preflight(recipe_id, sample, checks)
        if not checked["ok"]:
            raise WorkflowError("；".join(checked["reasons"]))
        if not name.strip():
            raise WorkflowError("实验名称不能为空")
        now = utcnow()
        with self.lock, self._db() as db:
            cur = db.execute("INSERT INTO sim_runs(name,sample,recipe_id,recipe_snapshot,state,started_at,updated_at) VALUES(?,?,?,?,?,?,?)",
                             (name.strip(), json.dumps(sample, ensure_ascii=False), recipe_id,
                              json.dumps(checked["recipe"], ensure_ascii=False), "PURGE", now, now))
            self._audit(db, cur.lastrowid, "run.start", "仿真惰性置换启动")
            return self._run(db, cur.lastrowid)

    def _run(self, db: sqlite3.Connection, run_id: int) -> dict[str, Any]:
        row = db.execute("SELECT * FROM sim_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise WorkflowError("实验不存在")
        item = dict(row)
        item["sample"] = json.loads(item["sample"])
        item["recipe_snapshot"] = json.loads(item["recipe_snapshot"])
        return item

    def current(self) -> dict[str, Any] | None:
        with self.lock, self._db() as db:
            row = db.execute("SELECT id FROM sim_runs WHERE state IN ('PURGE','REACTION','COOLING','PAUSED','RECOVERY_REQUIRED','EMERGENCY','REVIEW','REVIEWED') ORDER BY id DESC LIMIT 1").fetchone()
            return self._run(db, row["id"]) if row else None

    def run(self, run_id: int) -> dict[str, Any]:
        with self.lock, self._db() as db:
            return self._run(db, run_id)

    def action(self, run_id: int, action: str, *, note: str = "", actor: str = "operator") -> dict[str, Any]:
        with self.lock, self._db() as db:
            run = self._run(db, run_id)
            state = run["state"]
            actor = self._setting(db, "role")
            next_state: str
            if action == "pause" and state in ("PURGE", "REACTION", "COOLING"):
                next_state = "PAUSED"
                db.execute("UPDATE sim_runs SET resumed_state=? WHERE id=?", (state, run_id))
            elif action == "resume" and state == "PAUSED":
                if self._setting(db, "scenario") != "normal":
                    raise WorkflowError("请先解除仿真故障场景")
                next_state = run["resumed_state"] or "PURGE"
            elif action == "stop" and state in ACTIVE:
                next_state = "REVIEW"
            elif action == "emergency" and state in ACTIVE:
                next_state = "EMERGENCY"
            elif action == "review" and state in ("REVIEW", "RECOVERY_REQUIRED", "EMERGENCY"):
                if actor not in ("reviewer", "administrator"):
                    raise WorkflowError("请切换至复核员或管理员角色完成复核")
                if not note.strip():
                    raise WorkflowError("数据复核须填写结论")
                next_state = "REVIEWED"
            elif action == "archive" and state == "REVIEWED":
                if actor not in ("reviewer", "administrator"):
                    raise WorkflowError("请切换至复核员或管理员角色归档")
                next_state = "ARCHIVED"
            else:
                raise WorkflowError(f"不能在 {state} 状态执行 {action}")
            now = utcnow()
            db.execute("UPDATE sim_runs SET state=?,review_note=CASE WHEN ?='review' THEN ? ELSE review_note END,updated_at=?,finished_at=CASE WHEN ? IN ('stop','emergency') THEN ? ELSE finished_at END WHERE id=?",
                       (next_state, action, note.strip(), now, action, now, run_id))
            detail = note.strip() or (f"{state} → {next_state}; 恢复先前阶段" if action == "resume" else
                                      f"{state} → {next_state}; 关闭反应气" if action in ("pause", "stop", "emergency") else
                                      f"{state} → {next_state}")
            self._audit(db, run_id, f"run.{action}", detail, actor)
            if action == "emergency":
                db.execute("INSERT INTO sim_alarms(run_id,code,severity,message,appeared_at) VALUES(?,?,?,?,?)",
                           (run_id, "EMERGENCY", "critical", "仿真紧急处置：反应气关闭，需人工复核", now))
            return self._run(db, run_id)

    def _run_worker(self) -> None:
        while not self._closed.wait(self.tick_seconds):
            try:
                self.tick()
            except Exception as exc:  # worker remains alive; snapshot exposes failure
                self.worker_error = str(exc)

    def tick(self) -> None:
        with self.lock, self._db() as db:
            row = db.execute("SELECT id FROM sim_runs WHERE state IN ('PURGE','REACTION','COOLING') ORDER BY id DESC LIMIT 1").fetchone()
            if row is None:
                return
            run = self._run(db, row["id"])
            scenario = self._setting(db, "scenario")
            if scenario == "offline":
                self._alarm_once(db, run["id"], "DEVICE_OFFLINE", "error", "仿真设备离线，实验已暂停")
                db.execute("UPDATE sim_runs SET state='PAUSED',resumed_state=?,updated_at=? WHERE id=?", (run["state"], utcnow(), run["id"]))
                self._audit(db, run["id"], "run.auto_pause", "仿真设备离线，关闭反应气")
                return
            if scenario == "alarm":
                self._alarm_once(db, run["id"], "SIM_ALARM", "warning", "仿真报警，实验已暂停")
                db.execute("UPDATE sim_runs SET state='PAUSED',resumed_state=?,updated_at=? WHERE id=?", (run["state"], utcnow(), run["id"]))
                self._audit(db, run["id"], "run.auto_pause", "仿真报警，关闭反应气")
                return
            if scenario in ("stale", "unstable"):
                code = "SAMPLE_STALE" if scenario == "stale" else "BALANCE_UNSTABLE"
                reason = "仿真采样过期" if scenario == "stale" else "仿真天平不稳定"
                self._alarm_once(db, run["id"], code, "warning", f"{reason}，实验已暂停")
                db.execute("INSERT INTO sim_samples(run_id,sampled_at,elapsed_s,temperature_c,weight_g,flows,quality,reason) VALUES(?,?,?,?,?,?,?,?)",
                           (run["id"], utcnow(), run["stage_elapsed"], None, None,
                            json.dumps({g: 0.0 for g in GASES}), scenario, reason))
                db.execute("UPDATE sim_runs SET state='PAUSED',resumed_state=?,updated_at=? WHERE id=?", (run["state"], utcnow(), run["id"]))
                self._audit(db, run["id"], "run.auto_pause", f"{reason}，关闭反应气")
                return
            elapsed = run["stage_elapsed"] + self.tick_seconds
            transitioned = False
            stages = run["recipe_snapshot"]["stages"]
            idx = run["stage_index"]
            inert = "ar" if any(s["flows"]["ar"] > 0 for s in stages) else "n2"
            inert_purge_flow = min(5.0, json.loads(self._setting(db, "limits"))[inert])
            flows = {g: 0.0 for g in GASES}
            if run["state"] == "PURGE":
                flows[inert] = inert_purge_flow
                temp = 25.0
                if elapsed >= 5:
                    transitioned = True
                    db.execute("UPDATE sim_runs SET state='REACTION',stage_elapsed=0,updated_at=? WHERE id=?", (utcnow(), run["id"]))
                    self._audit(db, run["id"], "stage.reaction", "惰性置换完成")
            elif run["state"] == "REACTION":
                stage = stages[idx]
                flows = stage["flows"]
                temp = stage["temperature_c"]
                if elapsed >= stage["duration_s"]:
                    transitioned = True
                    if idx + 1 < len(stages):
                        db.execute("UPDATE sim_runs SET stage_index=?,stage_elapsed=0,updated_at=? WHERE id=?", (idx + 1, utcnow(), run["id"]))
                        self._audit(db, run["id"], "stage.next", f"进入阶段 {idx+2}")
                    else:
                        db.execute("UPDATE sim_runs SET state='COOLING',stage_elapsed=0,updated_at=? WHERE id=?", (utcnow(), run["id"]))
                        self._audit(db, run["id"], "stage.cooling", "反应完成，吹扫冷却")
            else:
                flows[inert] = inert_purge_flow
                temp = max(25.0, stages[-1]["temperature_c"] - elapsed * 35)
                if elapsed >= 10:
                    transitioned = True
                    completed_at = utcnow()
                    db.execute("UPDATE sim_runs SET state='REVIEW',stage_elapsed=0,updated_at=?,finished_at=? WHERE id=?", (completed_at, completed_at, run["id"]))
                    self._audit(db, run["id"], "run.complete", "吹扫冷却完成，等待数据复核")
            total = db.execute("SELECT COUNT(*) FROM sim_samples WHERE run_id=?", (run["id"],)).fetchone()[0]
            mass = run["sample"]["initial_mass_g"] * (1 - min(total / 6000, 0.18))
            quality = "simulated"
            db.execute("INSERT INTO sim_samples(run_id,sampled_at,elapsed_s,temperature_c,weight_g,flows,quality,reason) VALUES(?,?,?,?,?,?,?,?)",
                       (run["id"], utcnow(), total * self.tick_seconds, temp, mass, json.dumps(flows), quality, ""))
            if not transitioned:
                db.execute("UPDATE sim_runs SET stage_elapsed=?,updated_at=? WHERE id=? AND state IN ('PURGE','REACTION','COOLING')",
                           (elapsed, utcnow(), run["id"]))
            self.worker_error = ""

    def _alarm_once(self, db: sqlite3.Connection, run_id: int, code: str, severity: str, message: str) -> None:
        if not db.execute("SELECT 1 FROM sim_alarms WHERE run_id=? AND code=? AND cleared_at IS NULL", (run_id, code)).fetchone():
            db.execute("INSERT INTO sim_alarms(run_id,code,severity,message,appeared_at) VALUES(?,?,?,?,?)",
                       (run_id, code, severity, message, utcnow()))

    def snapshot(self) -> dict[str, Any]:
        with self.lock, self._db() as db:
            run = self.current()
            scenario = self._setting(db, "scenario")
            sample = db.execute("SELECT * FROM sim_samples WHERE run_id=? ORDER BY id DESC LIMIT 1", (run["id"],)).fetchone() if run else None
            age = (datetime.now(timezone.utc) - datetime.fromisoformat(sample["sampled_at"])).total_seconds() if sample else None
            state = "offline" if scenario == "offline" else "stale" if scenario in ("stale", "unstable") or (age is not None and age > 8) or (run is not None and run["state"] not in ("PURGE", "REACTION", "COOLING")) else "unknown" if sample is None else "simulated"
            reason = "仿真工作线程故障：" + self.worker_error if self.worker_error else "仿真设备离线场景" if state == "offline" else "采样超过 8 秒或仿真过期场景" if state == "stale" else "尚无采样" if state == "unknown" else ""
            if self.worker_error:
                state = "offline"
            return {"mode": "simulation", "state": state, "reason": reason,
                    "sampled_at": sample["sampled_at"] if sample else None,
                    "values": {"temperature_c": sample["temperature_c"], "weight_g": sample["weight_g"],
                               "flows": json.loads(sample["flows"])} if sample and state == "simulated" and run and run["state"] in ("PURGE", "REACTION", "COOLING") else None,
                    "run": run}

    def history(self, *, limit: int = 50, offset: int = 0, search: str = "", status: str = "all") -> dict[str, Any]:
        limit = max(1, min(int(limit), 100))
        offset = max(0, int(offset))
        search = str(search).strip()[:100].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        status = str(status)
        with self.lock, self._db() as db:
            clause = "WHERE (name LIKE ? ESCAPE '\\' OR CAST(id AS TEXT) LIKE ? ESCAPE '\\') AND (?='all' OR state=?)"
            pattern = f"%{search}%"
            args = (pattern, pattern, status, status)
            count = db.execute(f"SELECT COUNT(*) FROM sim_runs {clause}", args).fetchone()[0]
            rows = db.execute(f"SELECT id,name,state,started_at,finished_at,review_note,source FROM sim_runs {clause} ORDER BY id DESC LIMIT ? OFFSET ?", (*args, limit, offset)).fetchall()
            return {"items": [dict(row) for row in rows], "total": count}

    def samples(self, run_id: int, *, limit: int = 300, offset: int = 0, stride: int = 1,
                tail: bool = False) -> dict[str, Any]:
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))
        stride = max(1, min(int(stride), 1000))
        with self.lock, self._db() as db:
            self._run(db, run_id)
            count = db.execute("SELECT COUNT(*) FROM sim_samples WHERE run_id=?", (run_id,)).fetchone()[0]
            if tail:
                rows = db.execute("SELECT * FROM sim_samples WHERE run_id=? ORDER BY id DESC LIMIT ?", (run_id, limit)).fetchall()[::-1]
            else:
                rows = db.execute("SELECT * FROM sim_samples WHERE run_id=? AND ((id - (SELECT MIN(id) FROM sim_samples WHERE run_id=?)) % ?)=0 ORDER BY id LIMIT ? OFFSET ?",
                                  (run_id, run_id, stride, limit, offset)).fetchall()
            return {"items": [{**dict(row), "flows": json.loads(row["flows"])} for row in rows], "total": count}

    def devices_status(self) -> dict[str, Any]:
        """Read-only status contract for future real polling (30 s cadence)."""
        checked_at = utcnow()
        return {"checked_at": checked_at, "recheck_seconds": 30,
                "devices": [{"id": key, "protocol": protocol, "mode": "simulation",
                             "real_state": "unknown", "last_valid_at": None,
                             "reason": "未提供现场设备配置；未发起真实连接"}
                            for key, protocol in (("temperature", "TAIE Modbus RTU"),
                                                   ("mfc", "Azbil CPL"), ("balance", "serial ASCII"))]}

    def alarms(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.lock, self._db() as db:
            return [dict(row) for row in db.execute("SELECT * FROM sim_alarms ORDER BY id DESC LIMIT ?", (min(limit, 200),))]

    def acknowledge(self, alarm_id: int, actor: str) -> dict[str, Any]:
        if not actor.strip():
            raise WorkflowError("请填写确认人")
        with self.lock, self._db() as db:
            row = db.execute("SELECT * FROM sim_alarms WHERE id=?", (alarm_id,)).fetchone()
            if row is None:
                raise WorkflowError("报警不存在")
            db.execute("UPDATE sim_alarms SET acknowledged_at=COALESCE(acknowledged_at,?),acknowledged_by=COALESCE(acknowledged_by,?) WHERE id=?",
                       (utcnow(), actor.strip(), alarm_id))
            self._audit(db, row["run_id"], "alarm.acknowledge", row["code"], actor.strip())
            return dict(db.execute("SELECT * FROM sim_alarms WHERE id=?", (alarm_id,)).fetchone())

    def clear_alarm(self, alarm_id: int, actor: str) -> dict[str, Any]:
        if not actor.strip():
            raise WorkflowError("请填写解除人")
        with self.lock, self._db() as db:
            row = db.execute("SELECT * FROM sim_alarms WHERE id=?", (alarm_id,)).fetchone()
            if row is None:
                raise WorkflowError("报警不存在")
            if not row["acknowledged_at"]:
                raise WorkflowError("请先确认报警")
            if self._setting(db, "scenario") != "normal":
                raise WorkflowError("仿真故障场景仍存在，不能解除报警")
            db.execute("UPDATE sim_alarms SET cleared_at=COALESCE(cleared_at,?) WHERE id=?", (utcnow(), alarm_id))
            self._audit(db, row["run_id"], "alarm.clear", row["code"], actor.strip())
            return dict(db.execute("SELECT * FROM sim_alarms WHERE id=?", (alarm_id,)).fetchone())

    def audit(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.lock, self._db() as db:
            return [dict(row) for row in db.execute("SELECT * FROM sim_audit ORDER BY id DESC LIMIT ?", (min(limit, 200),))]

    def run_events(self, run_id: int) -> dict[str, Any]:
        with self.lock, self._db() as db:
            self._run(db, run_id)
            alarms = [dict(row) for row in db.execute("SELECT * FROM sim_alarms WHERE run_id=? ORDER BY id DESC LIMIT 1000", (run_id,))]
            audit = [dict(row) for row in db.execute("SELECT * FROM sim_audit WHERE run_id=? ORDER BY id DESC LIMIT 1000", (run_id,))]
            return {"alarms": alarms, "audit": audit}

    def analysis(self, run_id: int) -> dict[str, Any]:
        run = self.run(run_id)
        with self.lock, self._db() as db:
            counts = db.execute("SELECT COUNT(*) total, COUNT(CASE WHEN quality='simulated' AND weight_g IS NOT NULL THEN 1 END) valid, MAX(CASE WHEN quality='simulated' AND weight_g IS NOT NULL THEN temperature_c END) max_temp FROM sim_samples WHERE run_id=?", (run_id,)).fetchone()
            first = db.execute("SELECT weight_g FROM sim_samples WHERE run_id=? AND quality='simulated' AND weight_g IS NOT NULL ORDER BY id LIMIT 1", (run_id,)).fetchone()
            last = db.execute("SELECT weight_g FROM sim_samples WHERE run_id=? AND quality='simulated' AND weight_g IS NOT NULL ORDER BY id DESC LIMIT 1", (run_id,)).fetchone()
        if counts["valid"] < 2:
            return {"valid": False, "reason": "有效采样不足 2 条", "sample_count": counts["valid"], "total_count": counts["total"]}
        first_weight, last_weight = first[0], last[0]
        return {"valid": True, "sample_count": counts["valid"], "total_count": counts["total"],
                "initial_weight_g": first_weight, "final_weight_g": last_weight,
                "weight_change_g": round(last_weight - first_weight, 6),
                "weight_change_pct": round((last_weight - first_weight) / first_weight * 100, 3),
                "max_temperature_c": counts["max_temp"],
                "method": "仿真有效采样的首末质量差；仅作趋势参考，不代替化学计量还原度或氧化率",
                "review_required": run["state"] != "ARCHIVED"}

    def report_html(self, run_id: int) -> str:
        run = self.run(run_id)
        analysis = self.analysis(run_id)
        esc = lambda value: html.escape(str(value))
        stride = max(1, math.ceil(analysis["total_count"] / 200))
        sampled = self.samples(run_id, limit=200, stride=stride)
        with self.lock, self._db() as db:
            alarm_rows = [dict(row) for row in db.execute("SELECT code,severity,message,appeared_at,acknowledged_at,cleared_at FROM sim_alarms WHERE run_id=? ORDER BY id", (run_id,))]
            audit_rows = [dict(row) for row in db.execute("SELECT actor,action,detail,created_at FROM sim_audit WHERE run_id=? ORDER BY id", (run_id,))]
        rows = [("实验编号", run["id"]), ("名称", run["name"]), ("状态", run["state"]),
                ("报告状态", "已归档" if run["state"] == "ARCHIVED" else "待复核 / 未归档"),
                ("样品", run["sample"].get("name", "")), ("初始称重 / g", run["sample"].get("initial_mass_g", "")),
                ("配方", f"{run['recipe_snapshot']['name']} v{run['recipe_snapshot']['version']}"),
                ("开始时间", run["started_at"]), ("结束时间", run["finished_at"] or "—"),
                ("有效采样 / 总采样", f"{analysis['sample_count']} / {analysis['total_count']}"),
                ("质量变化 / %", analysis.get("weight_change_pct", "无法计算")),
                ("复核结论", run["review_note"] or "待复核")]
        table = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in rows)
        stages = "".join(f"<tr><td>{i+1}</td><td>{esc(stage['name'])}</td><td>{esc(stage['duration_s'])}</td><td>{esc(stage['temperature_c'])}</td><td>{esc(', '.join(f'{gas.upper()} {flow:g}' for gas,flow in stage['flows'].items() if flow))}</td></tr>"
                         for i, stage in enumerate(run["recipe_snapshot"]["stages"]))
        def measure(value: float | None, digits: int) -> str:
            return f"{value:.{digits}f}" if value is not None else "—"

        sample_rows = "".join(f"<tr><td>{esc(item['sampled_at'])}</td><td>{esc(measure(item['temperature_c'], 1))}</td><td>{esc(measure(item['weight_g'], 4))}</td><td>{esc(item['quality'])}</td></tr>"
                              for item in sampled["items"])
        alarms = "".join(f"<tr><td>{esc(row['appeared_at'])}</td><td>{esc(row['code'])}</td><td>{esc(row['message'])}</td><td>{esc(row['acknowledged_at'] or '未确认')}</td><td>{esc(row['cleared_at'] or '未解除')}</td></tr>"
                         for row in alarm_rows) or "<tr><td colspan='5'>无报警</td></tr>"
        audit = "".join(f"<tr><td>{esc(row['created_at'])}</td><td>{esc(row['actor'])}</td><td>{esc(row['action'])}</td><td>{esc(row['detail'])}</td></tr>"
                        for row in audit_rows)
        warning = "仿真技术记录；结果仅供流程验证。设备真实参数与联锁未核验。"
        return ("<!doctype html><html lang='zh-CN'><meta charset='utf-8'><title>RKA-3000 技术记录</title>"
                "<style>body{font:15px system-ui;max-width:800px;margin:48px auto;color:#172033}h1{font-size:25px}"
                "h2{font-size:18px;margin-top:32px}table{border-collapse:collapse;width:100%}th,td{padding:8px;text-align:left;border:1px solid #ccd5e0;font-size:12px}"
                "th{background:#f2f6fa}.note{margin-top:25px;padding:14px;background:#fff2d8}"
                "@media print{body{margin:16mm}}</style><h1>RKA-3000 实验技术记录</h1>"
                f"<p>生成时间：{esc(utcnow())} · 来源：{esc(run['source'])}</p><table>{table}</table>"
                "<h2>配方阶段快照</h2><table><tr><th>序号</th><th>阶段</th><th>时长 / s</th><th>目标温度 / ℃</th><th>流量 / L/min</th></tr>"
                f"{stages}</table><h2>采样摘录</h2><p>按每 {stride} 点抽取 1 点展示，共 {analysis['total_count']} 条原始采样；完整数据在应用历史页分页查看。</p>"
                "<table><tr><th>采样时间</th><th>温度 / ℃</th><th>质量 / g</th><th>质量标记</th></tr>"
                f"{sample_rows}</table><h2>报警与处理</h2><table><tr><th>发生</th><th>代码</th><th>内容</th><th>确认</th><th>解除</th></tr>{alarms}</table>"
                f"<h2>操作审计</h2><table><tr><th>时间</th><th>角色</th><th>动作</th><th>详情</th></tr>{audit}</table>"
                f"<p class='note'>{esc(warning)} {esc(analysis.get('method', analysis.get('reason', '')))}</p></html>")

    def import_legacy(self, source: Path) -> dict[str, Any]:
        """Copy a legacy DB's records transactionally; do not write to source."""
        source = Path(source).resolve()
        if not source.is_file() or source == self.path.resolve():
            raise WorkflowError("请选择不同于当前工作库的旧 SQLite 文件")
        digest = hashlib.sha256()
        with source.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        fingerprint = digest.hexdigest()
        with self.lock, self._db() as db:
            existing = db.execute("SELECT * FROM sim_imports WHERE fingerprint=?", (fingerprint,)).fetchone()
            if existing:
                return {"already_imported": True, **dict(existing)}
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as old:
                old.row_factory = sqlite3.Row
                tables = {r[0] for r in old.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                if not {"recipes", "recipe_steps", "experiments", "measurements"} <= tables:
                    raise WorkflowError("文件不是受支持的旧版 RKA 数据库")
                recipes = []
                for recipe in old.execute("SELECT * FROM recipes"):
                    body = dict(recipe)
                    body["steps"] = [dict(r) for r in old.execute("SELECT * FROM recipe_steps WHERE recipe_id=? ORDER BY step_no", (recipe["id"],))]
                    recipes.append(body)
                runs = [dict(r) for r in old.execute("SELECT * FROM experiments")]
                details = []
                for run in runs:
                    sample_count = old.execute("SELECT COUNT(*) FROM measurements WHERE experiment_id=?", (run["id"],)).fetchone()[0]
                    alarms = [dict(r) for r in old.execute("SELECT * FROM alarms WHERE experiment_id=?", (run["id"],))] if "alarms" in tables else []
                    details.append({**run, "sample_count": sample_count, "alarms": alarms})
                audit = [dict(r) for r in old.execute("SELECT * FROM audit_logs")] if "audit_logs" in tables else []
            backup = self.path.with_name(f"{self.path.stem}.before-import-{fingerprint[:12]}.db")
            if self.path.exists() and not backup.exists():
                with sqlite3.connect(backup) as target:
                    db.backup(target)
            imported = utcnow()
            for recipe in recipes:
                db.execute("INSERT INTO sim_legacy_recipes(source_hash,source_id,body,imported_at) VALUES(?,?,?,?)",
                           (fingerprint, recipe["id"], json.dumps(recipe, ensure_ascii=False), imported))
            for run in details:
                db.execute("INSERT INTO sim_legacy_runs(source_hash,source_id,body,imported_at) VALUES(?,?,?,?)",
                           (fingerprint, run["id"], json.dumps(run, ensure_ascii=False), imported))
            with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as old:
                old.row_factory = sqlite3.Row
                cursor = old.execute("SELECT * FROM measurements ORDER BY id")
                for row in cursor:
                    db.execute("INSERT INTO sim_legacy_samples(source_hash,source_run_id,source_sample_id,body) VALUES(?,?,?,?)",
                               (fingerprint, row["experiment_id"], row["id"], json.dumps(dict(row), ensure_ascii=False)))
            for event in audit:
                db.execute("INSERT INTO sim_legacy_audit(source_hash,source_id,body,imported_at) VALUES(?,?,?,?)",
                           (fingerprint, event["id"], json.dumps(event, ensure_ascii=False), imported))
            db.execute("INSERT INTO sim_imports VALUES(?,?,?,?,?,?)",
                       (fingerprint, str(source), str(backup), imported, len(recipes), len(runs)))
            self._audit(db, None, "legacy.import", f"{source.name}: {len(recipes)} 配方、{len(runs)} 实验")
            return {"already_imported": False, "fingerprint": fingerprint, "source_path": str(source),
                    "backup_path": str(backup), "recipe_count": len(recipes), "run_count": len(runs)}

    def legacy_runs(self) -> list[dict[str, Any]]:
        with self.lock, self._db() as db:
            rows = db.execute("SELECT source_hash,source_id,body,imported_at FROM sim_legacy_runs ORDER BY imported_at DESC,source_id DESC").fetchall()
            return [{"source_hash": r["source_hash"], "source_id": r["source_id"],
                     "imported_at": r["imported_at"], **json.loads(r["body"])} for r in rows]

    def legacy_samples(self, source_hash: str, run_id: int, *, limit: int = 100, offset: int = 0) -> dict[str, Any]:
        if len(source_hash) != 64 or any(ch not in "0123456789abcdef" for ch in source_hash):
            raise WorkflowError("旧库来源指纹无效")
        limit = max(1, min(int(limit), 1000))
        offset = max(0, int(offset))
        with self.lock, self._db() as db:
            count = db.execute("SELECT COUNT(*) FROM sim_legacy_samples WHERE source_hash=? AND source_run_id=?", (source_hash, run_id)).fetchone()[0]
            rows = db.execute("SELECT body FROM sim_legacy_samples WHERE source_hash=? AND source_run_id=? ORDER BY source_sample_id LIMIT ? OFFSET ?",
                              (source_hash, run_id, limit, offset)).fetchall()
            return {"items": [json.loads(row["body"]) for row in rows], "total": count}

    def legacy_recipes(self) -> list[dict[str, Any]]:
        with self.lock, self._db() as db:
            rows = db.execute("SELECT source_hash,source_id,body,imported_at FROM sim_legacy_recipes ORDER BY imported_at DESC,source_id DESC").fetchall()
            return [{"source_hash": r["source_hash"], "source_id": r["source_id"],
                     "imported_at": r["imported_at"], **json.loads(r["body"])} for r in rows]

    def legacy_audit(self) -> list[dict[str, Any]]:
        with self.lock, self._db() as db:
            rows = db.execute("SELECT source_hash,source_id,body,imported_at FROM sim_legacy_audit ORDER BY imported_at DESC,source_id DESC").fetchall()
            return [{"source_hash": r["source_hash"], "source_id": r["source_id"],
                     "imported_at": r["imported_at"], **json.loads(r["body"])} for r in rows]
