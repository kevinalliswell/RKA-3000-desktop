"""Experiment run use case: preflight, start, acquisition, safe disposal, alarms, control modes.

Lifecycle of one experiment (``RunSnapshot.status``)::

    idle ─preflight ok─▶ starting ─▶ running ⇄ paused (set-point mode only)
                                     running ─PLC interlock─▶ interrupted ─▶ running
    running | paused | interrupted ──any exit──▶ purging ──purge time ≥ required and T < safe──▶ stopping
    stopping ──buffered data flushed──▶ completed | stopped | faulted   (experiment then waits for review)

Every exit from a run goes through ``purging`` (惰性处置): process gases are zeroed, the inert gas
flows at the recipe purge rate and heating is stopped. The normal exit is reaching the recipe's
last step, which by rule is a pure-inert step; abnormal exits are an operator stop, an emergency
gas stop, a software alarm, or an execution fault. Only device/IO failures that make monitoring
impossible end a run without completing the purge; they still attempt the purge set-points.

``stopping`` means the outcome is decided but the acquisition thread has not yet flushed buffered
measurements; only after that does the run enter its terminal status.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rka_desktop.application.ports import AlarmStore, AuditStore, ExperimentGateway, ExperimentStore
from rka_desktop.domain.alarm_rules import (
    alarm_text_from_word,
    decode_alarm_word,
    decode_interlock_word,
    has_active_interlock,
    has_interlock_alarm,
    interlock_text_from_word,
    is_interlock_resettable,
)
from rka_desktop.domain.control import (
    ConfirmationRequired,
    GasControlMode,
    TemperatureControlMode,
    check_gas_mode_switch,
    parse_gas_mode,
)
from rka_desktop.domain.entities import DeviceSnapshot, Measurement
from rka_desktop.domain.experiment_engine import EngineUpdate, ExperimentEngine, ExperimentState
from rka_desktop.domain.gases import (
    EXPERIMENT_TYPE_LABELS,
    GAS_BY_KEY,
    GAS_KEYS,
    allowed_gases,
    format_flows,
    label,
    zero_flows,
)
from rka_desktop.domain.kinetics import SampleParams, degree_pct
from rka_desktop.domain.preflight import (
    MASS_TOLERANCE_PCT,
    SITE_CHECKLIST,
    SampleInfo,
    mass_deviation_pct,
    parse_checklist,
    parse_sample,
)
from rka_desktop.domain.recipe import Recipe, RecipeStep, RecipeValidationError
from rka_desktop.domain.recipe_rules import RecipeAssessment, is_reaction_step
from rka_desktop.domain.review import END_REASON_LABELS, GAP_PERIODS
from rka_desktop.domain.safety import DEVICE_LABELS, AlarmEvent, SafetyMonitor

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = frozenset({"starting", "running", "paused", "interrupted", "purging", "stopping"})
RUN_STATUSES = frozenset({"running", "paused", "interrupted"})  # recipe still executing
TERMINAL_STATUSES = frozenset({"stopped", "completed", "faulted"})
RECENT_MEASUREMENTS = 3600  # 30 minutes at 500 ms
OUTCOME_BY_REASON = {
    "completed": "COMPLETED", "operator_stop": "STOPPED", "emergency": "STOPPED", "alarm": "STOPPED",
    "fault": "FAULTED", "shutdown": "STOPPED",
}
READBACK_TOLERANCE_RATIO = 0.02
READBACK_TOLERANCE_LPM = 0.01

RecipeLoader = Callable[[int], tuple[Recipe, RecipeAssessment]]
LimitsProvider = Callable[[], tuple[int, dict[str, float]]]


class RunConflict(ValueError):
    """An experiment is already active, or the service is closing."""


class RunStateError(ValueError):
    """The requested transition is not legal in the current run state."""


class PreflightFailed(ValueError):
    """Start refused because preflight checks did not pass; ``detail`` carries the checks."""

    def __init__(self, message: str, detail: dict[str, Any]) -> None:
        super().__init__(message)
        self.detail = detail


@dataclass(frozen=True)
class RunnerSettings:
    poll_interval_ms: int = 500
    acquisition_batch_size: int = 10
    step_heatup_grace_seconds: int = 120
    step_total_grace_seconds: int = 180
    degraded_fault_seconds: int = 30  # stale readback longer than this records a warning alarm
    mapping_profile: str = "contract_v1"
    temperature_mode: TemperatureControlMode = TemperatureControlMode.PROGRAM
    default_gas_mode: GasControlMode = GasControlMode.AUTO
    purge_exit_temperature_c: float = 200.0


class SystemClock:
    def now(self) -> datetime:
        return datetime.now()

    def monotonic(self) -> float:
        return time.monotonic()


@dataclass
class _Purge:
    required_s: float
    flows: dict[str, float]
    started_mono: float
    started_at: str
    heating: str  # "program_last_step" | "setpoint_written" | "manual_required" | "plc_stop"
    elapsed_s: float = 0.0
    temperature_ok: bool = False
    apply_error: str | None = None


@dataclass
class _RunRecord:
    run_id: str
    experiment_id: int
    code: str
    recipe: Recipe
    sample: SampleInfo
    engine: ExperimentEngine
    gas_mode: GasControlMode
    temperature_mode: TemperatureControlMode
    limits_version: int
    usage_limits: dict[str, float]
    device_limits: dict[str, float]
    started_mono: float
    status: str = "starting"
    pending_terminal: str | None = None
    started_at: str = ""
    finished_at: str | None = None
    error: str | None = None
    status_text: str = "未启动"
    setpoints_text: str = "--"
    temperature_program: dict[str, Any] | None = None
    manual_gas: dict[str, float] | None = None
    commanded_gas: dict[str, float] = field(default_factory=zero_flows)
    step_times: list[dict[str, str | None]] = field(default_factory=list)
    end_reason: str | None = None
    end_detail: str | None = None
    emergency: bool = False
    purge: _Purge | None = None
    reaction_started_at: str | None = None
    reaction_ended_at: str | None = None
    reaction_start_weight: float | None = None
    last_command: dict[str, Any] | None = None
    program_segment: int | None = None
    events: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=300))

    @property
    def steps(self) -> list[RecipeStep]:
        return list(self.recipe.steps)

    @property
    def operator(self) -> str:
        return self.sample.operator or "operator"


class ExperimentRunner:
    def __init__(
        self,
        *,
        settings: RunnerSettings,
        recipe_loader: RecipeLoader,
        limits_provider: LimitsProvider,
        experiments: ExperimentStore,
        alarms: AlarmStore,
        audit: AuditStore,
        gateway: ExperimentGateway,
        clock: SystemClock | None = None,
    ) -> None:
        self.settings = settings
        self._load_recipe = recipe_loader
        self._limits = limits_provider
        self._experiments = experiments
        self._alarms = alarms
        self._audit = audit
        self._gateway = gateway
        self._clock = clock or SystemClock()
        self._lock = threading.RLock()
        self._run: _RunRecord | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._closing = False
        self._connected = False
        self._seq = 0
        self._command_seq = 0
        self._recent: deque[dict[str, Any]] = deque(maxlen=RECENT_MEASUREMENTS)
        self._pending_measurements: list[Measurement] = []
        self._latest_snapshot: DeviceSnapshot | None = None
        self._latest_sampled_mono: float | None = None
        self._degraded_since: dict[str, float] = {}
        self._monitor = SafetyMonitor(stale_warning_seconds=float(settings.degraded_fault_seconds))
        self._reset_runtime_tracking()

    # ------------------------------------------------------------------ queries
    @property
    def is_active(self) -> bool:
        with self._lock:
            return self._run is not None and self._run.status in ACTIVE_STATUSES

    @property
    def active_experiment_id(self) -> int | None:
        with self._lock:
            return self._run.experiment_id if self._run and self._run.status in ACTIVE_STATUSES else None

    def _stale_devices(self) -> set[str]:
        threshold = GAP_PERIODS * self.settings.poll_interval_ms / 1000.0
        now = self._clock.monotonic()
        return {name for name, since in self._degraded_since.items() if now - since >= threshold}

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            run = self._run
            engine_state = run.engine.state.value if run else ExperimentState.IDLE.value
            interrupted = run is not None and run.engine.state == ExperimentState.INTERRUPTED
            paused = run is not None and run.engine.state == ExperimentState.PAUSED
            running = run is not None and run.status == "running"
            in_run = run is not None and run.status in RUN_STATUSES
            pending_alarms = self._alarms.list_unacknowledged_alarms()
            has_interlock = has_active_interlock(self._interlock_active_word, profile_name=self.settings.mapping_profile)
            resettable = is_interlock_resettable(self._interlock_active_word, profile_name=self.settings.mapping_profile)
            resume_block = self._resume_blocking_message() if run else None
            stale = self._stale_devices()
            manual_block = self._manual_gas_block(run, pending_alarms, stale)
            allowed = {
                "start": run is None or run.status in TERMINAL_STATUSES,
                "pause": bool(running and run.temperature_mode == TemperatureControlMode.SETPOINT),
                "resume": bool(in_run and ((interrupted and resume_block is None) or paused)),
                "stop": in_run,
                "emergency": bool(run is not None and (in_run or run.status == "purging") and not run.emergency),
                "ack_alarm": bool(pending_alarms),
                "reset_interlock": bool(
                    in_run and interrupted and self._alarm_active_word == 0 and not pending_alarms
                    and has_interlock and not self._estop_active and resettable
                ),
                "set_gas_mode": in_run,
                "manual_gas": manual_block is None,
            }
            blocked = {"manual_gas": manual_block}
            if run is not None and run.temperature_mode == TemperatureControlMode.PROGRAM:
                blocked["pause"] = "程序模式下温度由仪表执行，软件暂停会与仪表程序脱节"
            interlock_text = interlock_text_from_word(self._interlock_active_word, profile_name=self.settings.mapping_profile)
            if self._estop_active:
                interlock_text = f"{interlock_text} / 急停触发" if interlock_text != "无联锁" else "急停触发"
            step = run.engine.current_step if run else None
            if run is not None and run.status in ("purging", "stopping") or run is not None and run.status in TERMINAL_STATUSES:
                current_index = len(run.recipe.steps) - 1 if run.end_reason == "completed" else self._step_index(run)
            else:
                current_index = self._step_index(run) if run else None
            payload: dict[str, Any] = {
                "seq": self._seq,
                "status": run.status if run else "idle",
                "pending_terminal": run.pending_terminal if run else None,
                "engine_state": engine_state,
                "run_id": run.run_id if run else None,
                "experiment_id": run.experiment_id if run else None,
                "recipe_id": run.recipe.recipe_id if run else None,
                "recipe_name": run.recipe.name if run else None,
                "started_at": run.started_at if run else None,
                "finished_at": run.finished_at if run else None,
                "elapsed_s": (self._clock.monotonic() - run.started_mono) if run and run.status in ACTIVE_STATUSES else None,
                "error": run.error if run else None,
                "current_step_no": (current_index + 1) if current_index is not None else None,
                "total_steps": len(run.recipe.steps) if run else 0,
                "current_step": step.to_dict() if step and run and run.status in RUN_STATUSES else None,
                "status_text": self._execution_text(run, pending_alarms, has_interlock),
                "setpoints_text": run.setpoints_text if run else "--",
                "gas_mode": run.gas_mode.value if run else self.settings.default_gas_mode.value,
                "temperature_mode": run.temperature_mode.value if run else self.settings.temperature_mode.value,
                "temperature_program": run.temperature_program if run else None,
                "program_segment": run.program_segment if run else None,
                "manual_gas": run.manual_gas if run else None,
                "experiment": self._experiment_payload(run),
                "steps": self._steps_payload(run, current_index),
                "step_progress": self._step_progress(run),
                "purge": self._purge_payload(run),
                "end_reason": run.end_reason if run else None,
                "end_reason_text": END_REASON_LABELS.get(run.end_reason or "", None) if run else None,
                "end_detail": run.end_detail if run else None,
                "emergency": bool(run and run.emergency),
                "gases": self._gas_payload(run, stale),
                "live": self._live_payload(run, stale),
                "last_command": run.last_command if run else None,
                "alarm": {
                    "word": self._alarm_active_word,
                    "text": alarm_text_from_word(self._alarm_active_word, profile_name=self.settings.mapping_profile),
                    "active": [
                        {"code": a.code, "level": a.level, "message": a.message, "interlock": a.interlock}
                        for a in decode_alarm_word(self._alarm_active_word, profile_name=self.settings.mapping_profile)
                    ] if self._alarm_active_word else [],
                },
                "interlock": {
                    "word": self._interlock_active_word,
                    "text": interlock_text,
                    "estop": self._estop_active,
                    "active": [
                        {"code": i.code, "message": i.message, "resettable": i.resettable}
                        for i in decode_interlock_word(self._interlock_active_word, profile_name=self.settings.mapping_profile)
                    ] if self._interlock_active_word else [],
                    "resettable": has_interlock and resettable and not self._estop_active,
                },
                "control_feedback": {
                    "word": self._last_run_control_word,
                    "estop_status": self._last_estop_status,
                    "consistent": not self._run_control_feedback_inconsistent,
                    "message": self._last_feedback_text,
                },
                "pending_alarms": pending_alarms,
                "degraded_devices": sorted(self._degraded_since),
                "stale_devices": sorted(stale),
                "latest": self._snapshot_dict(self._latest_snapshot, stale),
                "allowed": allowed,
                "blocked": blocked,
                "connected": self._connected,
                "events": list(run.events) if run else [],
            }
            return payload

    def measurements_since(self, seq: int, limit: int = 600) -> dict[str, Any]:
        with self._lock:
            items = [item for item in self._recent if item["seq"] > seq]
            return {"seq": self._seq, "items": items[-limit:]}

    # ------------------------------------------------------------------ preflight and start
    def preflight(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            return self._preflight_locked(payload or {})

    def _preflight_locked(self, payload: dict[str, Any]) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []

        def check(key: str, label_text: str, ok: bool, detail: str, *, blocking: bool = True) -> None:
            checks.append({"key": key, "label": label_text, "ok": bool(ok), "detail": detail, "blocking": blocking})

        busy = (self._run is not None and self._run.status in ACTIVE_STATUSES) or (
            self._thread is not None and self._thread.is_alive())
        check("idle", "无运行中实验", not busy and not self._closing, "当前没有运行中的实验" if not busy else "已有实验在运行或收尾")

        pending = self._experiments.list_experiments(limit=5, category="pending")
        check("archived", "上一次实验已归档", not pending,
              "无待核查实验" if not pending else "待核查：" + "、".join(p["code"] for p in pending) + "，请先在分析与归档中完成复核")

        recipe: Recipe | None = None
        assessment: RecipeAssessment | None = None
        recipe_id = payload.get("recipe_id")
        if type(recipe_id) is not int:
            check("recipe", "配方可执行", False, "请选择配方")
        else:
            try:
                recipe, assessment = self._load_recipe(recipe_id)
            except LookupError:
                check("recipe", "配方可执行", False, "配方不存在")
            else:
                check("recipe", "配方可执行", assessment.runnable,
                      f"{recipe.name} v{recipe.version} · {assessment.summary()}")

        capabilities = self._gateway.capabilities
        mode = self.settings.temperature_mode
        if mode == TemperatureControlMode.PROGRAM and not capabilities.temperature_program:
            check("temperature_mode", "温度控制方式", False, "当前设备通路不支持下发温度程序，请在设置中改为 setpoint")
        elif mode == TemperatureControlMode.SETPOINT and not capabilities.temperature_setpoint:
            check("temperature_mode", "温度控制方式", False, "当前设备通路不支持逐步下发温度设定")
        else:
            check("temperature_mode", "温度控制方式", True,
                  "温度程序启动时一次性下发到温控器，过程中不调节" if mode == TemperatureControlMode.PROGRAM
                  else "按配方逐段下发温度设定")

        readings: dict[str, Any] = {"connected": False}
        balance_g: float | None = None
        if busy:
            check("devices", "设备回读新鲜", False, "实验运行中，跳过设备检查")
        elif not self._ensure_connected():
            check("devices", "设备回读新鲜", False, "设备连接失败，请检查串口配置")
        else:
            try:
                snapshot = self._gateway.read_snapshot()
                degraded = tuple(self._gateway.degraded_devices())
            except Exception as exc:  # noqa: BLE001
                check("devices", "设备回读新鲜", False, f"读取设备失败：{exc}")
            else:
                readings = {"connected": True, **self._snapshot_dict(snapshot, set(degraded)), "degraded": list(degraded)}
                if "balance" not in degraded:
                    balance_g = snapshot.weight_g
                check("devices", "设备回读新鲜", not degraded,
                      "全部设备有有效回读" if not degraded
                      else "无有效回读：" + "、".join(DEVICE_LABELS.get(d, d) for d in degraded))

        unacked = self._alarms.list_unacknowledged_alarms()
        check("alarms", "无待确认报警", not unacked, "无待确认报警" if not unacked else f"{len(unacked)} 条报警待确认")

        sample, problems = parse_sample(payload.get("sample"), recipe.experiment_type if recipe else None)
        check("sample", "样品信息完整", sample is not None, "已填写" if sample else "；".join(problems))

        deviation = mass_deviation_pct(sample.initial_mass_g, balance_g) if sample else None
        if sample is not None:
            if deviation is None:
                check("mass", "初始质量与天平读数", False, "没有天平读数，无法核对", blocking=False)
            else:
                check("mass", "初始质量与天平读数", deviation <= MASS_TOLERANCE_PCT,
                      f"天平 {balance_g:.3f} g · 输入 {sample.initial_mass_g:.3f} g · 偏差 {deviation:.3f}%"
                      + ("" if deviation <= MASS_TOLERANCE_PCT else f"（> {MASS_TOLERANCE_PCT}%，请复核）"), blocking=False)

        checklist = parse_checklist(payload.get("checklist"))
        missing = [item.label for item in SITE_CHECKLIST if not checklist[item.key]]
        check("checklist", f"现场检查 {len(SITE_CHECKLIST)} 项", not missing,
              "已全部确认" if not missing else f"还差 {len(missing)} 项：" + "、".join(missing))

        ready = all(item["ok"] for item in checks if item["blocking"])
        limits_version, usage_limits = self._limits()
        return {
            "ready": ready,
            "checks": checks,
            "recipe": recipe.to_dict() if recipe else None,
            "assessment": assessment.to_dict() if assessment else None,
            "readings": readings,
            "balance_g": balance_g,
            "mass_deviation_pct": deviation,
            "limits_version": limits_version,
            "usage_limits": usage_limits,
            "checklist_items": [{"key": item.key, "label": item.label, "detail": item.detail} for item in SITE_CHECKLIST],
            "temperature_mode": mode.value,
            "safe_temperature_c": self.settings.purge_exit_temperature_c,
        }

    def start(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            if self._closing:
                raise RunConflict("服务正在关闭，不能启动实验")
            if self._run is not None and self._run.status in ACTIVE_STATUSES:
                raise RunConflict("已有实验正在运行，请先结束当前实验")
            if self._thread is not None and self._thread.is_alive():
                raise RunConflict("上一次实验仍在收尾，请稍候")
            if not isinstance(payload, dict):
                raise RecipeValidationError("启动参数必须是对象")
            if type(payload.get("recipe_id")) is int:
                self._load_recipe(payload["recipe_id"])  # 404 before preflight for an unknown recipe
            result = self._preflight_locked(payload)
            if not result["ready"]:
                failed = [c["label"] for c in result["checks"] if c["blocking"] and not c["ok"]]
                raise PreflightFailed("启动条件未满足：" + "、".join(failed), result)
            recipe, _ = self._load_recipe(payload["recipe_id"])
            sample, _ = parse_sample(payload.get("sample"), recipe.experiment_type)
            assert sample is not None
            mode = parse_gas_mode(payload.get("gas_mode")) if payload.get("gas_mode") is not None else self.settings.default_gas_mode
            limits_version, usage_limits = self._limits()
            device_limits = self._gateway.gas_device_limits()
            checklist = parse_checklist(payload.get("checklist"))

            self._reset_runtime_tracking()
            self._recent.clear()
            self._pending_measurements = []
            self._latest_snapshot = None
            self._stop_event = threading.Event()
            fields = {
                "experiment_type": recipe.experiment_type.value, "inert_gas": recipe.inert_gas,
                "sample_name": sample.name, "operator": sample.operator, "particle_size": sample.particle_size,
                "initial_mass_g": sample.initial_mass_g, "tfe_pct": sample.tfe_pct, "feo_pct": sample.feo_pct,
                "balance_mass_g": result["balance_g"], "recipe_version": recipe.version, "recipe_snapshot": recipe.to_dict(),
                "limits_version": limits_version, "limits_snapshot": usage_limits, "checklist": checklist,
                "gas_mode": mode.value, "temperature_mode": self.settings.temperature_mode.value,
            }
            experiment_id = self._experiments.create_experiment(
                name=f"{sample.name} · {recipe.name}", recipe_id=recipe.recipe_id, fields=fields)
            detail = self._experiments.get_experiment_detail(experiment_id) or {}
            engine = ExperimentEngine(
                list(recipe.steps),
                step_heatup_grace_seconds=self.settings.step_heatup_grace_seconds,
                step_total_grace_seconds=self.settings.step_total_grace_seconds,
            )
            now = self._clock.now()
            run = _RunRecord(
                run_id=f"{experiment_id}-{int(now.timestamp())}", experiment_id=experiment_id,
                code=str(detail.get("code") or experiment_id), recipe=recipe, sample=sample, engine=engine, gas_mode=mode,
                temperature_mode=self.settings.temperature_mode, limits_version=limits_version,
                usage_limits=dict(usage_limits), device_limits=dict(device_limits), started_mono=self._clock.monotonic(),
                started_at=now.isoformat(),
            )
            run.step_times = [{"started_at": None, "ended_at": None} for _ in recipe.steps]
            self._run = run
            self._remember_update(engine.start())
            self._mark_step_started(0, now)
            self._audit_run("EXPERIMENT_START", f"{run.code} · {recipe.name} v{recipe.version} · 样品 {sample.name} "
                            f"{sample.initial_mass_g:.3f} g · 使用上限 v{limits_version} 锁定",
                            category="control", reason="预检全部通过", result="accepted,applied")
            self._event("command", "实验启动请求已验证", f"配方 {recipe.name} v{recipe.version} 快照 · 使用上限 v{limits_version} 锁定",
                        actor=run.operator)

            capabilities = self._gateway.capabilities
            if run.temperature_mode == TemperatureControlMode.PROGRAM:
                try:
                    run.temperature_program = self._gateway.download_temperature_program(list(recipe.steps))
                    self._audit_run("TEMPERATURE_PROGRAM_DOWNLOADED", f"segments={run.temperature_program.get('segments')}",
                                    actor="system", category="control", result="applied")
                    self._event("command", "温度程序已下发", str(run.temperature_program.get("message") or ""))
                except Exception as exc:  # noqa: BLE001
                    self._fail_active(f"温度程序下发失败，实验已故障停止: {exc}", audit_action="TEMPERATURE_PROGRAM_FAILED")
                    return self.snapshot()
            if not self._apply_current_step_setpoints():
                return self.snapshot()
            if capabilities.run_control_word and not self._issue_run_control("start", "启动"):
                return self.snapshot()
            run.status = "running"
            self._thread = threading.Thread(target=self._acquisition_loop, name=f"acq-{experiment_id}", daemon=True)
            self._thread.start()
            return self.snapshot()

    # ------------------------------------------------------------------ operator commands
    def pause(self) -> dict[str, Any]:
        with self._lock:
            run = self._require_in_run()
            if run.temperature_mode == TemperatureControlMode.PROGRAM:
                raise RunStateError("程序模式下温度由仪表执行，软件暂停会与仪表程序脱节，已禁用暂停")
            if run.engine.state != ExperimentState.RUNNING:
                raise RunStateError("只有运行中的实验可以暂停")
            if self._gateway.capabilities.run_control_word and not self._issue_run_control("pause", "暂停"):
                return self.snapshot()
            update = run.engine.pause()
            self._remember_update(update)
            run.status = "paused"
            self._experiments.set_experiment_status(run.experiment_id, ExperimentState.PAUSED.value)
            self._audit_run("EXPERIMENT_PAUSE", "", category="control")
            self._event("command", update.status_text, actor=run.operator)
            return self.snapshot()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            run = self._require_in_run()
            if run.engine.state not in (ExperimentState.PAUSED, ExperimentState.INTERRUPTED):
                raise RunStateError("当前实验不在暂停或中断状态")
            blocking = self._resume_blocking_message()
            if blocking is not None:
                raise RunStateError(blocking)
            if self._gateway.capabilities.run_control_word and not self._issue_run_control("resume", "恢复"):
                return self.snapshot()
            update = run.engine.resume()
            self._remember_update(update)
            run.status = "running"
            self._experiments.set_experiment_status(run.experiment_id, ExperimentState.RUNNING.value)
            self._audit_run("EXPERIMENT_RESUME", "", category="control")
            self._event("command", update.status_text, actor=run.operator)
            self._apply_current_step_setpoints()
            return self.snapshot()

    def stop(self, reason: str | None = None) -> dict[str, Any]:
        """Operator ends the run early: it goes into safe disposal, never straight to terminal."""
        with self._lock:
            run = self._require_active()
            if run.status in ("purging", "stopping"):
                return self.snapshot()
            text = (reason or "").strip()[:200] or "操作者提前结束"
            self._enter_purge("operator_stop", text)
            return self.snapshot()

    def emergency_stop(self) -> dict[str, Any]:
        """Executes immediately, no confirmation: process gas off, inert purge, heating off, latched."""
        with self._lock:
            run = self._require_active()
            if run.status == "stopping":
                return self.snapshot()
            self._enter_purge("emergency", "操作者按下紧急停气", emergency=True)
            return self.snapshot()

    def acknowledge_alarm(self, alarm_id: int | None = None, note: str = "", actor: str | None = None) -> dict[str, Any]:
        with self._lock:
            run = self._run
            text = (note or "").strip()
            if len(text) < 2:
                raise RunStateError("请填写处理说明（至少 2 个字），说明会写入操作审计")
            who = (actor or (run.operator if run else "") or "operator")[:40]
            if alarm_id is None:
                pending = self._alarms.list_unacknowledged_alarms(run.experiment_id if run else None)
                if not pending:
                    raise RunStateError("没有待确认报警")
                alarm_id = int(pending[0]["id"])
            alarm = self._alarms.get_alarm(alarm_id)
            if alarm is None:
                raise LookupError("报警不存在")
            if not self._alarms.acknowledge_alarm(alarm_id, who, text[:300]):
                raise RunStateError("该报警已确认")
            self._audit.log_action(who, "ALARM_ACK", f"{alarm['code']} {alarm['message']}", experiment_id=alarm.get("experiment_id"),
                                   category="safety", reason=text[:300], result="recorded")
            if run is not None and alarm.get("experiment_id") == run.experiment_id:
                self._event("alarm", f"报警已确认：{alarm['message']}", f"说明：{text[:300]}", actor=who)
            return self.snapshot()

    def reset_interlock(self) -> dict[str, Any]:
        with self._lock:
            run = self._require_in_run()
            if self._alarm_active_word != 0:
                raise RunStateError("当前仍有活动报警，请先排除报警")
            if self._alarms.list_unacknowledged_alarms(run.experiment_id):
                raise RunStateError("仍有未确认报警，请先确认")
            if self._interlock_active_word == 0 and not self._estop_active:
                raise RunStateError("当前没有需要复位的联锁")
            if not is_interlock_resettable(self._interlock_active_word, profile_name=self.settings.mapping_profile):
                raise RunStateError("当前联锁状态不允许软件复位，请先解除急停/硬件闭锁")
            if not self._gateway.capabilities.run_control_word:
                raise RunStateError("当前设备通路不支持联锁复位命令")
            if not self._issue_run_control("reset", "联锁复位"):
                return self.snapshot()
            self._audit_run("INTERLOCK_RESET", f"word={self._interlock_active_word:04X}", category="safety")
            self._event("safety", "已请求联锁复位，等待状态解除", actor=run.operator)
            return self.snapshot()

    def set_gas_mode(self, mode: str, *, confirmed: bool) -> dict[str, Any]:
        with self._lock:
            run = self._require_in_run()
            target = parse_gas_mode(mode)
            check_gas_mode_switch(run.gas_mode, target, run_active=True, confirmed=confirmed)
            if target == run.gas_mode:
                return self.snapshot()
            previous = run.gas_mode
            run.gas_mode = target
            run.manual_gas = None
            self._audit_run("GAS_MODE_SWITCH", f"{previous.value} → {target.value}", category="control",
                            reason="运行中切换，已二次确认", result="applied")
            self._event("command", f"配气模式已切换为{'按配方' if target == GasControlMode.AUTO else '手动'}", actor=run.operator)
            if target == GasControlMode.AUTO and run.engine.state in (ExperimentState.RUNNING, ExperimentState.PAUSED):
                # Returning to recipe control re-applies the active step so devices and recipe agree.
                self._apply_current_step_setpoints()
            return self.snapshot()

    def set_manual_gas(self, flows: Any, *, reason: str, confirmed: bool) -> dict[str, Any]:
        with self._lock:
            run = self._require_in_run()
            if run.gas_mode != GasControlMode.MANUAL:
                raise RunStateError("当前为按配方配气，请先切换到手动模式")
            if not confirmed:
                raise ConfirmationRequired("手动下发气体设定需要确认")
            block = self._manual_gas_block(run, self._alarms.list_unacknowledged_alarms(), self._stale_devices())
            if block is not None:
                raise RunStateError(block)
            text = (reason or "").strip()
            if len(text) < 2:
                raise RunStateError("请填写调气原因（至少 2 个字），原因会写入操作审计")
            values = self._validate_manual_flows(run, flows)
            self._command_seq += 1
            command: dict[str, Any] = {"id": self._command_seq, "kind": "manual_gas", "target": values,
                                       "summary": format_flows(values), "state": "accepted", "steps": [], "message": ""}
            run.last_command = command

            def step(code: str, ok: bool, text_: str) -> None:
                command["steps"].append({"code": code, "ok": ok, "label": text_, "at": self._clock.now().isoformat()})

            step("accepted", True, "已受理")
            try:
                self._gateway.apply_gas_setpoints(values)
            except Exception as exc:  # noqa: BLE001
                command.update(state="failed", message=f"下发失败：{exc}")
                step("failed", False, "下发失败")
                self._audit_run("MANUAL_GAS_FAILED", f"{format_flows(values)} · {exc}", category="control", reason=text,
                                result="accepted,failed")
                self._event("command", "手动气体设定下发失败", str(exc), actor=run.operator)
                return self.snapshot()
            verified, mismatch = self._verify_gas(values)
            if verified is False:
                step("mismatch", False, "回读不一致")
                reverted = self._revert_to_recipe(run)
                command.update(state="failed", message=f"回读不一致：{mismatch}；" + ("已回退到配方值" if reverted else "回退失败，请现场核实"))
                if reverted:
                    step("reverted", True, "已回退到配方值")
                self._audit_run("MANUAL_GAS_FAILED", f"{format_flows(values)} · 回读不一致 {mismatch}", category="control",
                                reason=text, result="accepted,mismatch" + (",reverted" if reverted else ""))
                self._event("command", "手动气体设定回读不一致", command["message"], actor=run.operator)
                return self.snapshot()
            step("verified" if verified else "verify_na", True, "回读一致" if verified else "回读不适用")
            step("applied", True, "已生效")
            command["state"] = "applied"
            run.manual_gas = values
            run.commanded_gas = values
            run.setpoints_text = f"手动 · {format_flows(values)}"
            self._audit_run("MANUAL_GAS_SET", format_flows(values), category="control", reason=text,
                            result="accepted," + ("verified" if verified else "verify_na") + ",applied")
            self._event("command", "手动气体设定已生效", f"{format_flows(values)} · 原因：{text}", actor=run.operator)
            return self.snapshot()

    def connect_devices(self) -> bool:
        with self._lock:
            return self._ensure_connected()

    def close(self, timeout: float = 30.0) -> None:
        """End the active run (best-effort purge set-points), wait for the acquisition thread, release devices."""
        with self._lock:
            self._closing = True
            run = self._run
            if run is not None and run.status in ACTIVE_STATUSES and run.status != "stopping":
                try:
                    if run.status != "purging":
                        self._enter_purge("shutdown", "程序关闭时实验仍在进行，已下发惰性处置设定")
                    self._finish(complete_purge=False, note="程序关闭，处置未按条件完成")
                except Exception:  # noqa: BLE001
                    logger.exception("stop during close failed")
            thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout)
            if thread.is_alive():
                logger.error("acquisition thread did not finish within %.0fs", timeout)
        with self._lock:
            self._flush_measurements()
            if self._connected:
                try:
                    self._gateway.close()
                finally:
                    self._connected = False

    # ------------------------------------------------------------------ acquisition loop
    def _acquisition_loop(self) -> None:
        interval = self.settings.poll_interval_ms / 1000.0
        try:
            while not self._stop_event.is_set():
                started = self._clock.monotonic()
                try:
                    snapshot = self._gateway.read_snapshot()
                    degraded = tuple(self._gateway.degraded_devices())
                except Exception as exc:  # noqa: BLE001 - device failure ends the run (legacy behaviour)
                    logger.exception("acquisition failed")
                    with self._lock:
                        if self._run is not None and self._run.status in ACTIVE_STATUSES:
                            self._fail_active(f"采集异常，无法继续监测，实验已故障结束: {exc}", audit_action="ACQUISITION_FAILED",
                                              monitorable=False)
                    break
                self.process_snapshot(snapshot, degraded=degraded)
                elapsed = self._clock.monotonic() - started
                self._stop_event.wait(max(0.0, interval - elapsed))
        finally:
            with self._lock:
                try:
                    self._flush_measurements()
                except Exception as exc:  # noqa: BLE001
                    logger.exception("flush failed")
                    if self._run is not None:
                        self._run.error = f"测量数据落库失败: {exc}"
                self._complete_terminal()

    def process_snapshot(self, snapshot: DeviceSnapshot, *, degraded: tuple[str, ...] = (), sampled_at: datetime | None = None) -> None:
        """Handle one device snapshot. Public so tests can drive the runner without a thread."""
        with self._lock:
            run = self._run
            if run is None or run.status not in RUN_STATUSES | {"purging"}:
                return
            now = sampled_at or self._clock.now()
            mono = self._clock.monotonic()
            self._update_degraded(degraded)
            degraded_now = set(degraded)
            stale = self._stale_devices()
            self._latest_snapshot = snapshot
            self._latest_sampled_mono = mono
            flows = snapshot.flows()
            phase = "purge" if run.status == "purging" else "run"
            self._seq += 1
            self._recent.append({
                "seq": self._seq, "sampled_at": now.isoformat(), "phase": phase,
                "temperature_c": None if "temp" in degraded_now else snapshot.temperature_c,
                "weight_g": None if "balance" in degraded_now else snapshot.weight_g,
                "pressure_mpa": snapshot.pressure_mpa,
                "flows": None if "mfc" in degraded_now else {gas: flows.get(gas, 0.0) for gas in GAS_KEYS},
                "n2_lpm": flows.get("N2", 0.0), "h2_lpm": flows.get("H2", 0.0), "co_lpm": flows.get("CO", 0.0),
            })
            if not degraded_now:
                # Held last-good values are never stored as measurements: a stale period is a gap.
                self._pending_measurements.append(Measurement(
                    experiment_id=run.experiment_id, sampled_at=now, temperature_c=snapshot.temperature_c,
                    weight_g=snapshot.weight_g, pressure_mpa=snapshot.pressure_mpa,
                    **{GAS_BY_KEY[gas].column: float(flows.get(gas, 0.0)) for gas in GAS_KEYS}, phase=phase,
                ))
                if len(self._pending_measurements) >= self.settings.acquisition_batch_size:
                    self._flush_measurements()

            if self._gateway.capabilities.run_control_word:
                self._update_run_control_feedback(snapshot.run_control_word)
            self._last_estop_status = snapshot.estop_status
            self._update_alarm_state(snapshot)
            self._update_interlock_state(snapshot)

            step = run.engine.current_step if run.status in RUN_STATUSES else None
            target = step.target_temp_c if step is not None else None
            instrument_step = self._instrument_step(snapshot.program_segment)
            if step is not None and instrument_step is not None and instrument_step > run.engine.current_step_index:
                # The instrument is already in a later step (its ramp may legitimately exceed the old target).
                target = max(target or 0.0, run.recipe.steps[min(instrument_step, len(run.recipe.steps) - 1)].target_temp_c)
            events = self._monitor.observe(
                mono, temperature_c=snapshot.temperature_c, target_temp_c=target,
                gas_pv={gas: value for gas, value in flows.items() if gas in run.device_limits},
                gas_sp={gas: value for gas, value in run.commanded_gas.items() if gas in run.device_limits},
                weight_g=snapshot.weight_g, stale=degraded_now | stale,
            )
            for event in events:
                self._raise_software_alarm(event)
            if run.status not in RUN_STATUSES | {"purging"}:
                return
            if run.status == "purging":
                self._check_purge(mono, None if "temp" in degraded_now else snapshot.temperature_c, snapshot, degraded_now)
                return

            if run.engine.state == ExperimentState.RUNNING and has_interlock_alarm(
                snapshot.alarm_word, profile_name=self.settings.mapping_profile
            ):
                self._interrupt(f"alarm={snapshot.alarm_word:04X}")
                return
            if run.engine.state == ExperimentState.RUNNING and (snapshot.interlock_word != 0 or snapshot.estop_status):
                self._interrupt(f"interlock={snapshot.interlock_word:04X}")
                return
            if degraded_now:
                return  # never advance recipe timing on held values
            measurement = Measurement(
                experiment_id=run.experiment_id, sampled_at=now, temperature_c=snapshot.temperature_c,
                weight_g=snapshot.weight_g, pressure_mpa=snapshot.pressure_mpa,
                n2_lpm=flows.get("N2", 0.0), h2_lpm=flows.get("H2", 0.0), co_lpm=flows.get("CO", 0.0),
            )
            self._process_measurement(measurement, snapshot.program_segment)

    def _instrument_step(self, segment: int | None) -> int | None:
        """Recipe step the temperature controller is executing (two program segments per step)."""
        run = self._run
        if run is None or run.temperature_mode != TemperatureControlMode.PROGRAM or not segment or segment < 1:
            return None
        return (segment - 1) // 2

    def _process_measurement(self, measurement: Measurement, program_segment: int | None = None) -> None:
        run = self._run
        assert run is not None
        previous_index = run.engine.current_step_index
        program_mode = run.temperature_mode == TemperatureControlMode.PROGRAM
        instrument_step = self._instrument_step(program_segment)
        if instrument_step is not None:
            # The instrument runs the temperature program; gas switching follows its current segment.
            run.program_segment = program_segment
            update = run.engine.sync_to_step(instrument_step, measurement.sampled_at, measurement.temperature_c)
            if not update.step_changed:
                update = run.engine.on_measurement(measurement, advance=False)
        else:
            update = run.engine.on_measurement(measurement, hold_by_time=program_mode)
        self._remember_update(update)
        if update.state == ExperimentState.FAULTED:
            self._enter_purge("fault", update.status_text)
            return
        if update.step_changed:
            new_index = run.engine.current_step_index
            self._mark_step_ended(previous_index, measurement.sampled_at)
            last_index = len(run.recipe.steps) - 1
            if new_index <= last_index:
                self._mark_step_started(new_index, measurement.sampled_at)
            if is_reaction_step(run.recipe.steps[previous_index], run.recipe.inert_gas) and not any(
                is_reaction_step(s, run.recipe.inert_gas) for s in run.recipe.steps[new_index:]
            ) and run.reaction_ended_at is None:
                run.reaction_ended_at = measurement.sampled_at.isoformat()
            if new_index >= last_index:
                # The last step is pure inert by rule: entering it is entering safe disposal.
                self._event("stage", f"第 {min(new_index, last_index) + 1} 段：{run.recipe.steps[last_index].display_name}",
                            "配方最后一段，进入惰性处置")
                self._enter_purge("completed", "配方最后一段正常进入惰性处置")
                return
            new_step = run.recipe.steps[new_index]
            self._event("stage", f"第 {new_index + 1} 段：{new_step.display_name}",
                        f"{new_step.target_temp_c:.0f} ℃ · {format_flows(new_step.flows())}")
            if is_reaction_step(new_step, run.recipe.inert_gas) and run.reaction_started_at is None:
                run.reaction_started_at = measurement.sampled_at.isoformat()
                run.reaction_start_weight = measurement.weight_g
                self._experiments.update_experiment(run.experiment_id, {"reaction_started_at": run.reaction_started_at})
                self._event("stage", "开始测定计时", f"反应段开始，重量基准 {measurement.weight_g:.3f} g")
            self._audit_run("STEP_CHANGE", f"第 {previous_index + 1} 段 → 第 {new_index + 1} 段 {new_step.display_name}",
                            actor="system", category="control")
            self._apply_current_step_setpoints()
        elif update.completed and update.state == ExperimentState.COMPLETED:
            self._enter_purge("completed", "配方步骤全部完成")

    # ------------------------------------------------------------------ safe disposal
    def _enter_purge(self, reason: str, detail: str, *, emergency: bool = False) -> None:
        run = self._run
        if run is None:
            return
        now = self._clock.now()
        if run.status == "purging":
            if emergency and not run.emergency:
                run.emergency = True
                run.end_detail = f"{run.end_detail or ''}；处置中按下紧急停气".lstrip("；")
                assert run.purge is not None
                run.purge.flows = self._purge_flows(run)
                run.purge.required_s = max(run.purge.required_s, float(run.recipe.purge_seconds))
                self._apply_purge(run, emergency=True)
                self._audit_run("EMERGENCY_STOP", "处置中按下紧急停气：重新下发惰性吹扫并停止加热", category="safety",
                                result=self._purge_result(run))
                self._event("safety", "紧急停气与惰性吹扫请求", f"工艺气体归零；{format_flows(run.purge.flows)}", actor=run.operator)
            return
        if run.status not in RUN_STATUSES | {"starting"}:
            return
        run.end_reason = reason
        run.end_detail = detail
        run.emergency = emergency
        if run.reaction_started_at and not run.reaction_ended_at:
            run.reaction_ended_at = now.isoformat()
        completed = reason == "completed"
        last_step = run.recipe.steps[-1]
        flows = last_step.flows() if completed else self._purge_flows(run)
        required = float(max(last_step.hold_seconds, run.recipe.purge_seconds) if completed else run.recipe.purge_seconds)
        run.purge = _Purge(required_s=required, flows=flows, started_mono=self._clock.monotonic(), started_at=now.isoformat(),
                           heating="")
        run.status = "purging"
        run.manual_gas = None
        if run.engine.state not in (ExperimentState.COMPLETED, ExperimentState.FAULTED):
            run.engine.stop()
        self._experiments.update_experiment(run.experiment_id, {
            "status": "PURGING", "end_reason": reason, "end_detail": detail, "purge_required_s": required,
            "reaction_ended_at": run.reaction_ended_at,
        })
        self._apply_purge(run, emergency=emergency, completed=completed)
        action = {"completed": "PURGE_START", "operator_stop": "EXPERIMENT_STOP", "emergency": "EMERGENCY_STOP",
                  "alarm": "ALARM_DISPOSAL", "fault": "FAULT_DISPOSAL", "shutdown": "SHUTDOWN_DISPOSAL"}[reason]
        actor = run.operator if reason in ("operator_stop", "emergency") else "system"
        self._audit_run(action, f"{detail} · {format_flows(flows)} · 至少 {required:.0f} s 且炉温 < "
                        f"{self.settings.purge_exit_temperature_c:.0f} ℃", actor=actor,
                        category="safety" if reason != "completed" else "control", result=self._purge_result(run))
        title = {"completed": "进入惰性处置", "operator_stop": "提前结束，进入惰性处置", "emergency": "紧急停气已执行并锁存",
                 "alarm": "报警自动处置", "fault": "故障，进入惰性处置", "shutdown": "程序关闭，下发惰性处置"}[reason]
        self._event("safety" if reason != "completed" else "stage", title,
                    f"{format_flows(flows)} · 加热：{self._heating_text(run.purge.heating)}", actor=actor)

    def _purge_flows(self, run: _RunRecord) -> dict[str, float]:
        flows = zero_flows()
        flows[run.recipe.inert_gas] = float(run.recipe.purge_lpm)
        return flows

    def _apply_purge(self, run: _RunRecord, *, emergency: bool = False, completed: bool = False) -> None:
        purge = run.purge
        assert purge is not None
        try:
            self._gateway.apply_gas_setpoints(purge.flows)
            run.commanded_gas = dict(purge.flows)
            purge.apply_error = None
        except Exception as exc:  # noqa: BLE001
            purge.apply_error = str(exc)
            logger.exception("purge set-points failed")
            self._raise_software_alarm(AlarmEvent("SW-PURGE-FAILED", "warning", f"惰性吹扫设定下发失败，请现场手动切换惰性气：{exc}"))
        try:
            if run.temperature_mode == TemperatureControlMode.SETPOINT:
                last = run.recipe.steps[-1]
                target = last.target_temp_c if completed and not emergency else 0.0
                self._gateway.apply_temperature_setpoint(temperature_c=target, ramp_rate_cpm=last.ramp_rate_cpm)
                purge.heating = "setpoint_written"
            elif completed and not emergency:
                purge.heating = "program_last_step"
            else:
                purge.heating = "manual_required"
            if self._gateway.capabilities.run_control_word:
                self._sync_run_control("stop", "处置停机")
                purge.heating = "plc_stop"
        except Exception as exc:  # noqa: BLE001
            purge.apply_error = f"{purge.apply_error + '；' if purge.apply_error else ''}停止加热失败：{exc}"
            purge.heating = "manual_required"
            self._raise_software_alarm(AlarmEvent("SW-HEAT-STOP-FAILED", "warning", f"停止加热命令失败，请在温控器上手动停止：{exc}"))

    @staticmethod
    def _heating_text(heating: str) -> str:
        return {
            "program_last_step": "温控程序执行最后一段",
            "setpoint_written": "已下发停止加热设定",
            "manual_required": "请在温控器面板停止程序 / 加热（仪表不支持远程停止）",
            "plc_stop": "已向 PLC 下发停止",
        }.get(heating, heating or "--")

    def _purge_result(self, run: _RunRecord) -> str:
        purge = run.purge
        if purge is None:
            return "recorded"
        return "accepted,failed" if purge.apply_error else "accepted,applied"

    def _check_purge(self, mono: float, temperature_c: float | None, snapshot: DeviceSnapshot, degraded: set[str]) -> None:
        run = self._run
        assert run is not None and run.purge is not None
        purge = run.purge
        purge.elapsed_s = mono - purge.started_mono
        purge.temperature_ok = temperature_c is not None and temperature_c < self.settings.purge_exit_temperature_c
        if purge.elapsed_s >= purge.required_s and purge.temperature_ok:
            self._event("stage", "处置完成", f"吹扫 {purge.elapsed_s:.0f} s · 炉温 {temperature_c:.1f} ℃")
            self._finish(complete_purge=True, final_temperature_c=temperature_c,
                         final_mass_g=None if "balance" in degraded else snapshot.weight_g)

    def _finish(self, *, complete_purge: bool, final_temperature_c: float | None = None, final_mass_g: float | None = None,
                note: str | None = None) -> None:
        run = self._run
        assert run is not None
        reason = run.end_reason or "fault"
        outcome = OUTCOME_BY_REASON.get(reason, "STOPPED")
        latest = self._latest_snapshot
        if final_temperature_c is None and latest is not None and "temp" not in self._stale_devices():
            final_temperature_c = latest.temperature_c
        if final_mass_g is None and latest is not None and "balance" not in self._stale_devices():
            final_mass_g = latest.weight_g
        purge = run.purge
        if purge is not None:
            purge.elapsed_s = self._clock.monotonic() - purge.started_mono
        detail = run.end_detail or ""
        if note:
            detail = f"{detail}；{note}" if detail else note
        self._experiments.update_experiment(run.experiment_id, {
            "status": outcome, "finished_at": self._clock.now().isoformat(), "review_state": "pending",
            "end_reason": reason, "end_detail": detail, "purge_required_s": purge.required_s if purge else None,
            "purge_done_s": purge.elapsed_s if purge else 0.0, "final_temperature_c": final_temperature_c,
            "final_mass_g": final_mass_g, "reaction_started_at": run.reaction_started_at,
            "reaction_ended_at": run.reaction_ended_at,
        })
        self._audit_run("EXPERIMENT_END", f"{END_REASON_LABELS.get(reason, reason)} · 状态 {outcome} · 待核查"
                        + ("" if complete_purge else " · 处置未按条件完成"), actor="system", category="control",
                        result="recorded")
        run.end_detail = detail
        run.pending_terminal = {"COMPLETED": "completed", "STOPPED": "stopped", "FAULTED": "faulted"}[outcome]
        run.status = "stopping"
        self._stop_event.set()
        if self._thread is None or not self._thread.is_alive():
            # No acquisition thread (failure during start, or tests driving process_snapshot): finish now.
            # Otherwise the loop sees the stop event, flushes buffered rows and completes the terminal.
            self._flush_measurements()
            self._complete_terminal()

    def _complete_terminal(self) -> None:
        run = self._run
        if run is None or run.status != "stopping":
            return
        run.status = run.pending_terminal or "stopped"
        run.finished_at = self._clock.now().isoformat()
        self._degraded_since = {}

    def _fail_active(self, reason: str, *, audit_action: str, monitorable: bool = True) -> None:
        """Execution failure: dispose safely; if monitoring is impossible, end right after the purge set-points."""
        run = self._run
        if run is None or run.status in TERMINAL_STATUSES or run.status == "stopping":
            return
        run.error = reason
        self._audit_run(audit_action, reason, actor="system", category="safety", result="failed")
        if run.status != "purging":
            self._enter_purge("fault", reason)
        acquiring = self._thread is not None and self._thread.is_alive()
        if not monitorable or not acquiring:
            # Nobody can watch the purge (no acquisition thread yet, or the devices stopped answering).
            self._finish(complete_purge=False, note="无法继续监测，处置未按条件完成，请现场确认")

    # ------------------------------------------------------------------ helpers
    def _require_active(self) -> _RunRecord:
        run = self._run
        if run is None or run.status not in ACTIVE_STATUSES:
            raise RunStateError("当前无运行中的实验")
        return run

    def _require_in_run(self) -> _RunRecord:
        run = self._require_active()
        if run.status not in RUN_STATUSES:
            raise RunStateError("实验已进入惰性处置，不能再调整" if run.status == "purging" else "实验正在收尾")
        return run

    def _manual_gas_block(self, run: _RunRecord | None, pending_alarms: list[dict[str, Any]], stale: set[str]) -> str | None:
        if run is None or run.status not in RUN_STATUSES:
            return "没有运行中的实验" if run is None or run.status in TERMINAL_STATUSES else "惰性处置中，禁止调气"
        if run.gas_mode != GasControlMode.MANUAL:
            return "当前为按配方配气"
        if pending_alarms:
            return f"{len(pending_alarms)} 条报警待确认，确认前禁止手动调气"
        if stale:
            return "设备回读过期（" + "、".join(DEVICE_LABELS.get(d, d) for d in sorted(stale)) + "），禁止调气"
        return None

    def _validate_manual_flows(self, run: _RunRecord, flows: Any) -> dict[str, float]:
        if not isinstance(flows, dict) or not flows:
            raise RecipeValidationError("请提供各气体的目标流量")
        allowed = set(allowed_gases(run.recipe.experiment_type, run.recipe.inert_gas))
        values = zero_flows()
        for raw_key, raw_value in flows.items():
            gas = str(raw_key).upper()
            if gas not in GAS_BY_KEY:
                raise RecipeValidationError(f"未知气体: {raw_key}")
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)) or not raw_value >= 0:
                raise RecipeValidationError(f"{label(gas)} 流量必须是非负数字")
            value = round(float(raw_value), 2)
            if value > 0 and gas not in allowed:
                raise RecipeValidationError(
                    f"{EXPERIMENT_TYPE_LABELS[run.recipe.experiment_type]}不允许 {label(gas)}；本次只能用 "
                    + "/".join(label(g) for g in sorted(allowed)))
            if value > 0 and gas not in run.device_limits:
                raise RecipeValidationError(f"{label(gas)} 没有配置 MFC 通道")
            limit = run.usage_limits.get(gas)
            if limit is not None and value > limit + 1e-9:
                raise RecipeValidationError(f"{label(gas)} {value:.2f} 超出使用上限 {limit:.2f} L/min（策略 v{run.limits_version}）")
            device = run.device_limits.get(gas)
            if device is not None and value > device + 1e-9:
                raise RecipeValidationError(f"{label(gas)} {value:.2f} 超出设备上限 {device:.2f} L/min")
            values[gas] = value
        return values

    def _verify_gas(self, commanded: dict[str, float]) -> tuple[bool | None, str]:
        """True/False when the MFCs can read back their set-points, None when the backend cannot."""
        if not self._gateway.capabilities.gas_setpoint_readback:
            return None, ""
        try:
            readback = self._gateway.read_gas_setpoints()
        except Exception as exc:  # noqa: BLE001
            return False, f"读取设定回读失败 {exc}"
        if readback is None:
            return False, "MFC 无回读"
        problems = []
        for gas, value in commanded.items():
            if gas not in readback:
                continue
            if abs(readback[gas] - value) > max(READBACK_TOLERANCE_RATIO * value, READBACK_TOLERANCE_LPM):
                problems.append(f"{label(gas)} 设定 {value:.2f} / 回读 {readback[gas]:.2f}")
        return (not problems), "，".join(problems)

    def _revert_to_recipe(self, run: _RunRecord) -> bool:
        step = run.engine.current_step
        if step is None:
            return False
        try:
            self._gateway.apply_gas_setpoints(step.flows())
            run.commanded_gas = step.flows()
            return True
        except Exception:  # noqa: BLE001
            logger.exception("revert to recipe flows failed")
            return False

    def _raise_software_alarm(self, event: AlarmEvent) -> None:
        run = self._run
        experiment_id = run.experiment_id if run else None
        level = "ALARM" if event.level == "alarm" else "WARNING"
        self._alarms.create_alarm(experiment_id, code=event.code, level=level, message=event.message)
        self._audit.log_action("system", "ALARM_RAISED", f"{event.code} {event.message}", experiment_id=experiment_id,
                               category="safety", result="recorded")
        if run is not None:
            self._event("alarm", ("报警：" if event.disposes else "警告：") + event.message,
                        "自动进入惰性处置" if event.disposes and run.status in RUN_STATUSES else "待确认")
            if event.disposes and run.status in RUN_STATUSES:
                self._enter_purge("alarm", event.message)

    def _ensure_connected(self) -> bool:
        if self._connected:
            return True
        try:
            self._connected = bool(self._gateway.connect())
        except Exception as exc:  # noqa: BLE001
            logger.exception("device connect failed")
            self._audit.log_action("system", "DEVICE_CONNECT_FAILED", str(exc), category="system", result="failed")
            self._connected = False
        if self._connected:
            self._audit.log_action("operator", "DEVICE_CONNECT", self._gateway.describe().get("summary", ""), category="system",
                                   result="applied")
        return self._connected

    def _audit_run(self, action: str, detail: str, *, actor: str | None = None, category: str = "control",
                   reason: str | None = None, result: str | None = None) -> None:
        run = self._run
        self._audit.log_action(actor or (run.operator if run else "operator"), action, detail,
                               experiment_id=run.experiment_id if run else None, category=category, reason=reason, result=result)

    def _event(self, kind: str, title: str, detail: str = "", *, actor: str | None = None) -> None:
        if self._run is not None:
            self._run.events.appendleft({"at": self._clock.now().isoformat(), "kind": kind, "title": title, "detail": detail,
                                         "actor": actor or "系统"})
        logger.info("%s %s", title, detail)

    def _mark_step_started(self, index: int, at: datetime) -> None:
        run = self._run
        if run is not None and 0 <= index < len(run.step_times):
            run.step_times[index]["started_at"] = at.isoformat()

    def _mark_step_ended(self, index: int, at: datetime) -> None:
        run = self._run
        if run is not None and 0 <= index < len(run.step_times):
            run.step_times[index]["ended_at"] = at.isoformat()

    def _step_index(self, run: _RunRecord | None) -> int | None:
        if run is None or not run.recipe.steps:
            return None
        return min(run.engine.current_step_index, len(run.recipe.steps) - 1)

    def _experiment_payload(self, run: _RunRecord | None) -> dict[str, Any] | None:
        if run is None:
            return None
        sample = run.sample
        return {
            "id": run.experiment_id, "code": run.code, "sample_name": sample.name, "operator": sample.operator,
            "initial_mass_g": sample.initial_mass_g, "tfe_pct": sample.tfe_pct, "feo_pct": sample.feo_pct,
            "experiment_type": run.recipe.experiment_type.value, "inert_gas": run.recipe.inert_gas,
            "recipe_id": run.recipe.recipe_id, "recipe_name": run.recipe.name, "recipe_version": run.recipe.version,
            "limits_version": run.limits_version, "started_at": run.started_at,
            "purge_lpm": run.recipe.purge_lpm, "purge_seconds": run.recipe.purge_seconds,
        }

    def _steps_payload(self, run: _RunRecord | None, current_index: int | None) -> list[dict[str, Any]]:
        if run is None:
            return []
        items = []
        terminal_like = run.status in ("purging", "stopping") or run.status in TERMINAL_STATUSES
        for index, step in enumerate(run.recipe.steps):
            times = run.step_times[index] if index < len(run.step_times) else {}
            if current_index is None:
                state = "pending"
            elif index < current_index:
                state = "done"
            elif index == current_index:
                if terminal_like and run.end_reason != "completed":
                    state = "interrupted"
                elif run.status in TERMINAL_STATUSES:
                    state = "done"
                else:
                    state = "active"
            else:
                state = "skipped" if terminal_like and run.end_reason != "completed" else "pending"
            items.append({
                **step.to_dict(), "display_name": step.display_name, "flows": step.flows(), "state": state,
                "kind": "reaction" if is_reaction_step(step, run.recipe.inert_gas) else "inert",
                "started_at": times.get("started_at"), "ended_at": times.get("ended_at"),
            })
        return items

    def _step_progress(self, run: _RunRecord | None) -> dict[str, Any] | None:
        if run is None or run.status not in RUN_STATUSES:
            return None
        step = run.engine.current_step
        if step is None:
            return None
        reached = run.engine.target_reached_at
        hold_elapsed = 0.0
        if reached is not None:
            hold_elapsed = max(0.0, (self._clock.now() - reached).total_seconds())
        return {"step_no": step.step_no, "target_reached": reached is not None, "hold_elapsed_s": hold_elapsed,
                "hold_s": step.hold_seconds}

    def _purge_payload(self, run: _RunRecord | None) -> dict[str, Any] | None:
        if run is None or run.purge is None:
            return None
        purge = run.purge
        elapsed = purge.elapsed_s if run.status != "purging" else self._clock.monotonic() - purge.started_mono
        return {
            "required_s": purge.required_s, "elapsed_s": elapsed, "flows": purge.flows, "summary": format_flows(purge.flows),
            "safe_temperature_c": self.settings.purge_exit_temperature_c, "temperature_ok": purge.temperature_ok,
            "heating": purge.heating, "heating_text": self._heating_text(purge.heating), "started_at": purge.started_at,
            "apply_error": purge.apply_error, "inert_gas": run.recipe.inert_gas,
        }

    def _gas_payload(self, run: _RunRecord | None, stale: set[str]) -> list[dict[str, Any]]:
        device_limits = run.device_limits if run else self._safe_device_limits()
        if not device_limits:
            return []
        snapshot = self._latest_snapshot
        flows = snapshot.flows() if snapshot else {}
        readback = snapshot.setpoints_lpm if snapshot else None
        allowed = set(allowed_gases(run.recipe.experiment_type, run.recipe.inert_gas)) if run else set(device_limits)
        step = run.engine.current_step if run and run.status in RUN_STATUSES else None
        recipe_flows = step.flows() if step else {}
        items = []
        for gas in GAS_KEYS:
            if gas not in device_limits:
                continue
            info = GAS_BY_KEY[gas]
            commanded = run.commanded_gas.get(gas, 0.0) if run else 0.0
            purging = run is not None and run.status == "purging"
            if gas not in allowed:
                state = "disabled"
            elif purging:
                state = "purging" if commanded > 0 else "closed"
            else:
                state = "flowing" if commanded > 0 else "closed"
            items.append({
                "gas": gas, "label": info.label, "hazard": info.hazard, "inert": info.inert, "allowed": gas in allowed,
                "device_limit": device_limits.get(gas), "usage_limit": (run.usage_limits.get(gas) if run else None),
                "pv": None if "mfc" in stale or snapshot is None else flows.get(gas, 0.0),
                "readback": None if readback is None or "mfc" in stale else readback.get(gas),
                "commanded": commanded, "recipe": recipe_flows.get(gas), "state": state,
            })
        return items

    def _safe_device_limits(self) -> dict[str, float]:
        try:
            return self._gateway.gas_device_limits()
        except Exception:  # noqa: BLE001
            return {}

    def _live_payload(self, run: _RunRecord | None, stale: set[str]) -> dict[str, Any] | None:
        snapshot = self._latest_snapshot
        if run is None or snapshot is None:
            return None
        weight = None if "balance" in stale else snapshot.weight_g
        temperature = None if "temp" in stale else snapshot.temperature_c
        step = run.engine.current_step if run.status in RUN_STATUSES else None
        flows = snapshot.flows()
        degree = None
        delta = None
        if weight is not None and run.reaction_start_weight is not None:
            delta = weight - run.reaction_start_weight
            try:
                degree = degree_pct(run.recipe.experiment_type.value, weight, run.reaction_start_weight,
                                    SampleParams(run.sample.initial_mass_g, run.sample.tfe_pct, run.sample.feo_pct))
            except ValueError:
                degree = None
        sample_age = (self._clock.monotonic() - self._latest_sampled_mono) if self._latest_sampled_mono is not None else None
        return {
            "temperature_c": temperature, "target_temp_c": step.target_temp_c if step else None,
            "weight_g": weight, "reference_weight_g": run.reaction_start_weight, "delta_m_g": delta,
            "degree_pct": degree, "degree_kind": run.recipe.experiment_type.value,
            "total_flow_lpm": None if "mfc" in stale else sum(flows.values()),
            "flow_summary": "—" if "mfc" in stale else format_flows(flows),
            "reaction_started_at": run.reaction_started_at, "sample_age_s": sample_age,
        }

    def _reset_runtime_tracking(self) -> None:
        self._alarm_active_word = 0
        self._interlock_active_word = 0
        self._estop_active = False
        self._run_control_feedback_inconsistent = False
        self._last_feedback_text = "控制反馈: --" if self._gateway.capabilities.run_control_word else "控制反馈: 不适用"
        self._last_run_control_word = 0
        self._last_estop_status = 0
        self._degraded_since = {}
        self._latest_sampled_mono = None
        self._monitor = SafetyMonitor(stale_warning_seconds=float(self.settings.degraded_fault_seconds))

    def _remember_update(self, update: EngineUpdate | None) -> None:
        if update is None or self._run is None:
            return
        self._run.status_text = update.status_text
        self._run.setpoints_text = update.active_setpoints_text

    def _snapshot_dict(self, snapshot: DeviceSnapshot | None, stale: set[str] | None = None) -> dict[str, Any] | None:
        if snapshot is None:
            return None
        stale = stale or set()
        flows = snapshot.flows()
        return {
            "temperature_c": None if "temp" in stale else snapshot.temperature_c,
            "weight_g": None if "balance" in stale else snapshot.weight_g,
            "pressure_mpa": snapshot.pressure_mpa,
            "flows": None if "mfc" in stale else flows,
            "n2_lpm": flows.get("N2", 0.0), "h2_lpm": flows.get("H2", 0.0), "co_lpm": flows.get("CO", 0.0),
            "alarm_word": snapshot.alarm_word, "interlock_word": snapshot.interlock_word,
            "run_control_word": snapshot.run_control_word, "estop_status": snapshot.estop_status,
        }

    def _execution_text(self, run: _RunRecord | None, pending_alarms: list[dict[str, Any]], has_interlock: bool) -> str:
        if run is None:
            return "待机"
        if run.status == "stopping":
            return "正在收尾，等待数据写入完成"
        if run.status == "purging":
            purge = run.purge
            if purge is None:
                return "惰性处置中"
            return (f"惰性处置中：吹扫 {purge.elapsed_s:.0f} / {purge.required_s:.0f} s，"
                    f"等待炉温 < {self.settings.purge_exit_temperature_c:.0f} ℃")
        if run.status in TERMINAL_STATUSES:
            return f"已结束 · {END_REASON_LABELS.get(run.end_reason or '', '')} · 待核查"
        if run.engine.state == ExperimentState.INTERRUPTED:
            if self._alarm_active_word != 0:
                return "报警处理中，联锁保持中"
            if pending_alarms and has_interlock:
                return "报警已解除，待确认后可执行联锁复位"
            if pending_alarms:
                return "报警已解除，待确认后可恢复实验"
            if self._estop_active:
                return "急停仍处于触发状态，禁止恢复"
            if has_interlock:
                return "联锁保持中，可执行复位"
            return "联锁已解除，可恢复实验"
        return run.status_text

    def _apply_current_step_setpoints(self) -> bool:
        run = self._run
        if run is None:
            return True
        step = run.engine.current_step
        if step is None:
            return True
        try:
            if run.gas_mode == GasControlMode.AUTO:
                flows = step.flows()
                self._gateway.apply_gas_setpoints(flows)
                run.commanded_gas = flows
                verified, mismatch = self._verify_gas(flows)
                if verified is False:
                    self._raise_software_alarm(AlarmEvent("SW-SP-MISMATCH", "warning", f"阶段气体设定回读不一致：{mismatch}"))
                else:
                    self._event("command", "阶段气体设定已" + ("回读生效" if verified else "下发"), format_flows(flows))
            if run.temperature_mode == TemperatureControlMode.SETPOINT:
                self._gateway.apply_temperature_setpoint(temperature_c=step.target_temp_c, ramp_rate_cpm=step.ramp_rate_cpm)
            return True
        except Exception as exc:  # noqa: BLE001
            self._fail_active(f"步骤设定下发失败: {exc}", audit_action="SETPOINT_APPLY_FAILED")
            return False

    def _issue_run_control(self, command: str, label_text: str) -> bool:
        try:
            self._gateway.issue_run_control(command)
            return True
        except Exception as exc:  # noqa: BLE001
            self._fail_active(f"运行控制命令下发失败[{label_text}]: {exc}", audit_action="RUN_CONTROL_FAILED")
            return False

    def _sync_run_control(self, command: str, label_text: str) -> bool:
        try:
            self._gateway.issue_run_control(command)
            return True
        except Exception as exc:  # noqa: BLE001
            self._audit_run("RUN_CONTROL_SYNC_FAILED", f"command={command},label={label_text},error={exc}", actor="system",
                            category="control", result="failed")
            return False

    def _interrupt(self, detail: str, reason: str = "实验已因报警联锁中断") -> None:
        run = self._run
        assert run is not None
        update = run.engine.interrupt(reason)
        self._remember_update(update)
        if self._gateway.capabilities.run_control_word:
            self._sync_run_control("pause", "联锁中断暂停")
        run.status = "interrupted"
        self._experiments.set_experiment_status(run.experiment_id, ExperimentState.INTERRUPTED.value)
        self._audit_run("EXPERIMENT_INTERRUPTED", detail, actor="system", category="safety")
        self._event("safety", update.status_text, detail)

    def _flush_measurements(self) -> int:
        if not self._pending_measurements:
            return 0
        pending, self._pending_measurements = self._pending_measurements, []
        return self._experiments.insert_measurements(pending)

    def _resume_blocking_message(self) -> str | None:
        run = self._run
        if run is None or run.engine.state != ExperimentState.INTERRUPTED:
            return None
        if self._alarm_active_word != 0:
            return "当前仍有活动报警，请先排除报警"
        if self._interlock_active_word != 0 or self._estop_active:
            return "联锁尚未解除，请先执行复位或解除急停"
        if self._alarms.list_unacknowledged_alarms(run.experiment_id):
            return "报警已解除，但仍有未确认报警"
        return None

    def _update_alarm_state(self, snapshot: DeviceSnapshot) -> None:
        run = self._run
        active_alarms = decode_alarm_word(snapshot.alarm_word, profile_name=self.settings.mapping_profile)
        if snapshot.alarm_word != 0 and snapshot.alarm_word != self._alarm_active_word:
            self._alarm_active_word = snapshot.alarm_word
            if run is not None:
                for alarm in active_alarms:
                    self._alarms.create_alarm(run.experiment_id, code=alarm.code, level=alarm.level, message=alarm.message)
                self._audit_run("ALARM_RAISED", f"word={snapshot.alarm_word:04X}", actor="system", category="safety",
                                result="recorded")
            self._event("alarm", f"报警触发：{alarm_text_from_word(snapshot.alarm_word, profile_name=self.settings.mapping_profile)}")
            return
        if snapshot.alarm_word == 0 and self._alarm_active_word != 0:
            self._alarm_active_word = 0
            self._event("alarm", "报警解除")

    def _update_interlock_state(self, snapshot: DeviceSnapshot) -> None:
        previous_estop = self._estop_active
        self._estop_active = bool(snapshot.estop_status)
        word = snapshot.interlock_word
        if (word != 0 or snapshot.estop_status) and (word != self._interlock_active_word or previous_estop != self._estop_active):
            self._interlock_active_word = word
            self._event("safety", f"联锁激活：状态字=0x{word:04X}")
            self._audit_run("INTERLOCK_ACTIVE", f"word={word:04X}", actor="system", category="safety")
            return
        if word == 0 and not snapshot.estop_status and (self._interlock_active_word != 0 or previous_estop):
            self._interlock_active_word = 0
            self._event("safety", "联锁解除")
            self._audit_run("INTERLOCK_CLEARED", "", actor="system", category="safety")

    def _update_run_control_feedback(self, run_control_word: int) -> None:
        feedback = self._gateway.evaluate_run_control_feedback(run_control_word)
        self._last_run_control_word = run_control_word
        self._last_feedback_text = feedback.message
        if feedback.is_consistent:
            if self._run_control_feedback_inconsistent:
                self._event("system", "运行控制反馈已恢复一致")
                self._audit_run("RUN_CONTROL_FEEDBACK_RESTORED", "", actor="system", category="control")
            self._run_control_feedback_inconsistent = False
            return
        if self._run_control_feedback_inconsistent:
            return
        self._run_control_feedback_inconsistent = True
        self._event("system", feedback.message)
        self._audit_run("RUN_CONTROL_FEEDBACK_MISMATCH", feedback.message, actor="system", category="control", result="mismatch")

    def _update_degraded(self, degraded: tuple[str, ...]) -> None:
        now = self._clock.monotonic()
        current = set(degraded)
        for name in list(self._degraded_since):
            if name not in current:
                self._degraded_since.pop(name)
                self._event("system", f"{DEVICE_LABELS.get(name, name)}回读恢复")
        for name in current:
            if name not in self._degraded_since:
                self._degraded_since[name] = now
                self._event("system", f"{DEVICE_LABELS.get(name, name)}无有效回读", "该段数据不入库；持续过期时禁止启动与调气，不自动停机")
