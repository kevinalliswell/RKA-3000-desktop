"""Experiment run use case: start/pause/resume/stop, acquisition loop, alarms, control modes.

This replaces the Qt-era ``ExperimentController`` + ``AcquisitionWorker`` + ``RuntimeCoordinator``.
Business judgements (step completion, alarm/interlock handling, run-control feedback) are kept
from the previous implementation; what changed is the execution model: a plain thread owns
the acquisition loop and all state is exposed as a JSON-serialisable snapshot.

Run status model (``RunSnapshot.status``):

    idle -> starting -> running <-> paused
                        running -> interrupted -> running
                        running | paused | interrupted -> stopping -> stopped | completed | faulted

``stopping`` means a terminal outcome has been decided but the acquisition thread has not yet
flushed buffered measurements; only after that does the run enter its terminal status.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from rka_desktop.application.ports import AlarmStore, AuditStore, ExperimentGateway, ExperimentStore, RecipeStore
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
from rka_desktop.domain.recipe import MAX_FLOW_LPM, RecipeStep, RecipeValidationError, parse_steps

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = frozenset({"starting", "running", "paused", "interrupted", "stopping"})
TERMINAL_STATUSES = frozenset({"stopped", "completed", "faulted"})
RECENT_MEASUREMENTS = 1800  # 15 minutes at 500 ms


class RunConflict(ValueError):
    """An experiment is already active, or the service is closing."""


class RunStateError(ValueError):
    """The requested transition is not legal in the current run state."""


@dataclass(frozen=True)
class RunnerSettings:
    poll_interval_ms: int = 500
    acquisition_batch_size: int = 10
    step_heatup_grace_seconds: int = 120
    step_total_grace_seconds: int = 180
    degraded_fault_seconds: int = 30
    mapping_profile: str = "contract_v1"
    temperature_mode: TemperatureControlMode = TemperatureControlMode.PROGRAM
    default_gas_mode: GasControlMode = GasControlMode.AUTO


class SystemClock:
    def now(self) -> datetime:
        return datetime.now()

    def monotonic(self) -> float:
        return time.monotonic()


@dataclass
class _RunRecord:
    run_id: str
    experiment_id: int
    recipe_id: int
    recipe_name: str
    steps: list[RecipeStep]
    engine: ExperimentEngine
    gas_mode: GasControlMode
    temperature_mode: TemperatureControlMode
    status: str = "starting"
    pending_terminal: str | None = None
    started_at: str = ""
    finished_at: str | None = None
    error: str | None = None
    status_text: str = "未启动"
    setpoints_text: str = "--"
    temperature_program: dict[str, Any] | None = None
    manual_gas: dict[str, float] | None = None
    messages: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=200))


class ExperimentRunner:
    def __init__(
        self,
        *,
        settings: RunnerSettings,
        recipes: RecipeStore,
        experiments: ExperimentStore,
        alarms: AlarmStore,
        audit: AuditStore,
        gateway: ExperimentGateway,
        clock: SystemClock | None = None,
    ) -> None:
        self.settings = settings
        self._recipes = recipes
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
        self._recent: deque[dict[str, Any]] = deque(maxlen=RECENT_MEASUREMENTS)
        self._pending_measurements: list[Measurement] = []
        self._latest_snapshot: DeviceSnapshot | None = None
        self._degraded_since: dict[str, float] = {}
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

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            run = self._run
            engine_state = run.engine.state.value if run else ExperimentState.IDLE.value
            interrupted = run is not None and run.engine.state == ExperimentState.INTERRUPTED
            paused = run is not None and run.engine.state == ExperimentState.PAUSED
            running = run is not None and run.engine.state == ExperimentState.RUNNING
            active = run is not None and run.status in ACTIVE_STATUSES
            pending_alarms = self._alarms.list_unacknowledged_alarms(run.experiment_id) if run and active else []
            has_interlock = has_active_interlock(self._interlock_active_word, profile_name=self.settings.mapping_profile)
            resettable = is_interlock_resettable(self._interlock_active_word, profile_name=self.settings.mapping_profile)
            resume_block = self._resume_blocking_message() if run else None
            settling = run is not None and run.status == "stopping"
            allowed = {
                "start": run is None or run.status in TERMINAL_STATUSES,
                "pause": active and running and not settling,
                "resume": active and not settling and ((interrupted and resume_block is None) or paused),
                "stop": active and not settling,
                "ack_alarm": bool(pending_alarms),
                "reset_interlock": bool(
                    active and interrupted and self._alarm_active_word == 0 and not pending_alarms
                    and has_interlock and not self._estop_active and resettable
                ),
                "set_gas_mode": active and not settling,
                "manual_gas": active and not settling and run is not None and run.gas_mode == GasControlMode.MANUAL,
            }
            interlock_text = interlock_text_from_word(self._interlock_active_word, profile_name=self.settings.mapping_profile)
            if self._estop_active:
                interlock_text = f"{interlock_text} / 急停触发" if interlock_text != "无联锁" else "急停触发"
            execution_text = self._execution_text(run, pending_alarms, has_interlock)
            step = run.engine.current_step if run else None
            payload: dict[str, Any] = {
                "seq": self._seq,
                "status": run.status if run else "idle",
                "pending_terminal": run.pending_terminal if run else None,
                "engine_state": engine_state,
                "run_id": run.run_id if run else None,
                "experiment_id": run.experiment_id if run else None,
                "recipe_id": run.recipe_id if run else None,
                "recipe_name": run.recipe_name if run else None,
                "started_at": run.started_at if run else None,
                "finished_at": run.finished_at if run else None,
                "error": run.error if run else None,
                "current_step_no": step.step_no if step else (run.steps[-1].step_no if run and run.steps else None),
                "total_steps": len(run.steps) if run else 0,
                "current_step": step.to_dict() if step else None,
                "status_text": execution_text,
                "setpoints_text": run.setpoints_text if run else "--",
                "gas_mode": run.gas_mode.value if run else self.settings.default_gas_mode.value,
                "temperature_mode": run.temperature_mode.value if run else self.settings.temperature_mode.value,
                "temperature_program": run.temperature_program if run else None,
                "manual_gas": run.manual_gas if run else None,
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
                "latest": self._snapshot_dict(self._latest_snapshot),
                "allowed": allowed,
                "connected": self._connected,
                "messages": list(run.messages) if run else [],
            }
            return payload

    def measurements_since(self, seq: int, limit: int = 600) -> dict[str, Any]:
        with self._lock:
            items = [item for item in self._recent if item["seq"] > seq]
            return {"seq": self._seq, "items": items[-limit:]}

    # ------------------------------------------------------------------ commands
    def start(self, recipe_id: int, *, gas_mode: str | None = None) -> dict[str, Any]:
        with self._lock:
            if self._closing:
                raise RunConflict("服务正在关闭，不能启动实验")
            if self._run is not None and self._run.status in ACTIVE_STATUSES:
                raise RunConflict("已有实验正在运行，请先停止当前实验")
            if self._thread is not None and self._thread.is_alive():
                raise RunConflict("上一次实验仍在收尾，请稍候")
            recipe = self._recipes.get_recipe(recipe_id)
            if recipe is None:
                raise LookupError("配方不存在")
            steps = parse_steps(self._recipes.get_recipe_steps(recipe_id))
            mode = parse_gas_mode(gas_mode) if gas_mode is not None else self.settings.default_gas_mode
            temperature_mode = self.settings.temperature_mode
            capabilities = self._gateway.capabilities
            if temperature_mode == TemperatureControlMode.PROGRAM and not capabilities.temperature_program:
                raise RunStateError("当前设备通路不支持下发温度程序，请在设置中将温度控制模式改为 setpoint")
            if temperature_mode == TemperatureControlMode.SETPOINT and not capabilities.temperature_setpoint:
                raise RunStateError("当前设备通路不支持逐步下发温度设定")
            if not self._ensure_connected():
                raise RunStateError("设备连接失败，请检查串口配置")

            self._reset_runtime_tracking()
            self._recent.clear()
            self._pending_measurements = []
            self._latest_snapshot = None
            self._stop_event = threading.Event()
            recipe_name = str(recipe["name"])
            experiment_id = self._experiments.create_experiment(name=f"实验-{recipe_name}", recipe_id=recipe_id)
            engine = ExperimentEngine(
                steps,
                step_heatup_grace_seconds=self.settings.step_heatup_grace_seconds,
                step_total_grace_seconds=self.settings.step_total_grace_seconds,
            )
            run = _RunRecord(
                run_id=f"{experiment_id}-{int(self._clock.now().timestamp())}",
                experiment_id=experiment_id, recipe_id=recipe_id, recipe_name=recipe_name, steps=steps,
                engine=engine, gas_mode=mode, temperature_mode=temperature_mode,
                started_at=self._clock.now().isoformat(),
            )
            self._run = run
            self._remember_update(engine.start())
            self._audit.log_action("operator", "EXPERIMENT_START",
                                   f"id={experiment_id},recipe_id={recipe_id},gas_mode={mode.value},temperature_mode={temperature_mode.value}")
            self._log(f"实验开始，ID={experiment_id}，配方={recipe_name}")

            if temperature_mode == TemperatureControlMode.PROGRAM:
                try:
                    run.temperature_program = self._gateway.download_temperature_program(steps)
                    self._audit.log_action("operator", "TEMPERATURE_PROGRAM_DOWNLOADED",
                                           f"id={experiment_id},segments={run.temperature_program.get('segments')}")
                    self._log(str(run.temperature_program.get("message") or "温度程序已下发"))
                except Exception as exc:  # noqa: BLE001
                    self._fail_active(f"温度程序下发失败，实验已故障停止: {exc}", audit_action="TEMPERATURE_PROGRAM_FAILED",
                                      detail=f"id={experiment_id},error={exc}")
                    return self.snapshot()
            if not self._apply_current_step_setpoints():
                return self.snapshot()
            if capabilities.run_control_word and not self._issue_run_control("start", "启动"):
                return self.snapshot()
            run.status = "running"
            self._thread = threading.Thread(target=self._acquisition_loop, name=f"acq-{experiment_id}", daemon=True)
            self._thread.start()
            return self.snapshot()

    def pause(self) -> dict[str, Any]:
        with self._lock:
            run = self._require_active()
            if run.engine.state != ExperimentState.RUNNING:
                raise RunStateError("只有运行中的实验可以暂停")
            if self._gateway.capabilities.run_control_word and not self._issue_run_control("pause", "暂停"):
                return self.snapshot()
            update = run.engine.pause()
            self._remember_update(update)
            run.status = "paused"
            self._experiments.set_experiment_status(run.experiment_id, ExperimentState.PAUSED.value)
            self._audit.log_action("operator", "EXPERIMENT_PAUSE", f"id={run.experiment_id}")
            self._log(update.status_text)
            return self.snapshot()

    def resume(self) -> dict[str, Any]:
        with self._lock:
            run = self._require_active()
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
            self._audit.log_action("operator", "EXPERIMENT_RESUME", f"id={run.experiment_id}")
            self._log(update.status_text)
            self._apply_current_step_setpoints()
            return self.snapshot()

    def stop(self) -> dict[str, Any]:
        with self._lock:
            run = self._require_active()
            if run.status == "stopping":
                return self.snapshot()
            if self._gateway.capabilities.run_control_word and not self._issue_run_control("stop", "停止"):
                return self.snapshot()
            update = run.engine.stop()
            self._remember_update(update)
            self._request_terminal(ExperimentState.STOPPED.value, audit_action="EXPERIMENT_STOP",
                                   log_message=f"实验终止，ID={run.experiment_id}")
            return self.snapshot()

    def acknowledge_alarm(self) -> dict[str, Any]:
        with self._lock:
            run = self._require_active()
            ok = self._alarms.acknowledge_latest_alarm(run.experiment_id, actor="operator")
            if ok:
                self._audit.log_action("operator", "ALARM_ACK", f"experiment_id={run.experiment_id}")
                self._log("报警已确认")
            else:
                raise RunStateError("没有待确认报警")
            return self.snapshot()

    def reset_interlock(self) -> dict[str, Any]:
        with self._lock:
            run = self._require_active()
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
            self._audit.log_action("operator", "INTERLOCK_RESET", f"id={run.experiment_id},word={self._interlock_active_word:04X}")
            self._log("已请求联锁复位，等待状态解除")
            return self.snapshot()

    def set_gas_mode(self, mode: str, *, confirmed: bool) -> dict[str, Any]:
        with self._lock:
            run = self._require_active()
            target = parse_gas_mode(mode)
            check_gas_mode_switch(run.gas_mode, target, run_active=True, confirmed=confirmed)
            if target == run.gas_mode:
                return self.snapshot()
            previous = run.gas_mode
            run.gas_mode = target
            run.manual_gas = None
            self._audit.log_action("operator", "GAS_MODE_SWITCH",
                                   f"id={run.experiment_id},from={previous.value},to={target.value},confirmed={confirmed}")
            self._log(f"配气模式已切换为 {'自动（按配方）' if target == GasControlMode.AUTO else '手动'}")
            if target == GasControlMode.AUTO and run.engine.state in (ExperimentState.RUNNING, ExperimentState.PAUSED):
                # Returning to recipe control re-applies the active step so devices and recipe agree.
                self._apply_current_step_setpoints()
            return self.snapshot()

    def set_manual_gas(self, *, n2_lpm: float, h2_lpm: float, co_lpm: float, confirmed: bool) -> dict[str, Any]:
        with self._lock:
            run = self._require_active()
            if run.gas_mode != GasControlMode.MANUAL:
                raise RunStateError("当前为自动配气模式，请先切换到手动模式")
            if not confirmed:
                raise ConfirmationRequired("手动下发气体设定需要确认")
            values = {}
            for label, key, value in (("N2", "n2_lpm", n2_lpm), ("H2", "h2_lpm", h2_lpm), ("CO", "co_lpm", co_lpm)):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= MAX_FLOW_LPM:
                    raise RecipeValidationError(f"{label} 流量须在 0 到 {MAX_FLOW_LPM:g} L/min 之间")
                values[key] = float(value)
            try:
                self._gateway.apply_gas_setpoints(**values)
            except Exception as exc:  # noqa: BLE001
                self._audit.log_action("operator", "MANUAL_GAS_FAILED", f"id={run.experiment_id},error={exc}")
                raise RunStateError(f"手动气体设定下发失败: {exc}") from exc
            run.manual_gas = values
            self._audit.log_action("operator", "MANUAL_GAS_SET", f"id={run.experiment_id},values={values}")
            self._log(f"手动配气已下发 N2/H2/CO {values['n2_lpm']:.2f}/{values['h2_lpm']:.2f}/{values['co_lpm']:.2f} L/min")
            return self.snapshot()

    def connect_devices(self) -> bool:
        with self._lock:
            return self._ensure_connected()

    def close(self, timeout: float = 30.0) -> None:
        """Stop the active run, wait for the acquisition thread, release devices."""
        with self._lock:
            self._closing = True
            run = self._run
            if run is not None and run.status in ACTIVE_STATUSES and run.status != "stopping":
                try:
                    if self._gateway.capabilities.run_control_word:
                        self._sync_run_control("stop", "关闭停机")
                    self._remember_update(run.engine.stop())
                    self._request_terminal(ExperimentState.STOPPED.value, audit_action="EXPERIMENT_STOP",
                                           log_message=f"服务关闭，实验终止，ID={run.experiment_id}")
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
                            self._fail_active(f"采集异常，实验已故障停止: {exc}", audit_action="ACQUISITION_FAILED",
                                              detail=f"id={self._run.experiment_id},error={exc}")
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
            if run is None or run.status not in ACTIVE_STATUSES or run.status == "stopping":
                return
            now = sampled_at or self._clock.now()
            measurement = Measurement(
                experiment_id=run.experiment_id, sampled_at=now,
                temperature_c=snapshot.temperature_c, weight_g=snapshot.weight_g, pressure_mpa=snapshot.pressure_mpa,
                n2_lpm=snapshot.n2_lpm, h2_lpm=snapshot.h2_lpm, co_lpm=snapshot.co_lpm,
            )
            self._latest_snapshot = snapshot
            self._seq += 1
            self._recent.append({
                "seq": self._seq, "sampled_at": now.isoformat(), "temperature_c": snapshot.temperature_c,
                "weight_g": snapshot.weight_g, "pressure_mpa": snapshot.pressure_mpa,
                "n2_lpm": snapshot.n2_lpm, "h2_lpm": snapshot.h2_lpm, "co_lpm": snapshot.co_lpm,
            })
            self._pending_measurements.append(measurement)
            if len(self._pending_measurements) >= self.settings.acquisition_batch_size:
                self._flush_measurements()

            if self._gateway.capabilities.run_control_word:
                self._update_run_control_feedback(snapshot.run_control_word)
            self._last_estop_status = snapshot.estop_status
            self._update_alarm_state(snapshot)
            self._update_interlock_state(snapshot)
            self._update_degraded(degraded)
            if run.status not in ACTIVE_STATUSES or run.status == "stopping":
                return

            if run.engine.state == ExperimentState.RUNNING and has_interlock_alarm(
                snapshot.alarm_word, profile_name=self.settings.mapping_profile
            ):
                self._interrupt(f"id={run.experiment_id},alarm={snapshot.alarm_word:04X}")
                return
            if run.engine.state == ExperimentState.RUNNING and (snapshot.interlock_word != 0 or snapshot.estop_status):
                self._interrupt(f"id={run.experiment_id},interlock={snapshot.interlock_word:04X}")
                return
            self._process_measurement(measurement)

    def _process_measurement(self, measurement: Measurement) -> None:
        run = self._run
        assert run is not None
        update = run.engine.on_measurement(measurement)
        self._remember_update(update)
        if update.step_changed and not update.completed:
            self._log(update.status_text)
            if not self._apply_current_step_setpoints():
                return
        if update.completed:
            if update.state == ExperimentState.COMPLETED:
                if self._gateway.capabilities.run_control_word:
                    self._sync_run_control("stop", "完成停机")
                self._log("执行引擎判定实验完成")
                self._request_terminal(ExperimentState.COMPLETED.value, audit_action="EXPERIMENT_COMPLETE",
                                       log_message=f"实验完成，ID={run.experiment_id}")
            elif update.state == ExperimentState.FAULTED:
                self._fail_active(update.status_text, audit_action="STEP_TIMEOUT_FAULT",
                                  detail=f"id={run.experiment_id},step={update.current_step_no}", final_update=update)

    # ------------------------------------------------------------------ internals
    def _require_active(self) -> _RunRecord:
        run = self._run
        if run is None or run.status not in ACTIVE_STATUSES:
            raise RunStateError("当前无运行中的实验")
        return run

    def _ensure_connected(self) -> bool:
        if self._connected:
            return True
        try:
            self._connected = bool(self._gateway.connect())
        except Exception as exc:  # noqa: BLE001
            logger.exception("device connect failed")
            self._audit.log_action("system", "DEVICE_CONNECT_FAILED", str(exc))
            self._connected = False
        if self._connected:
            self._audit.log_action("operator", "DEVICE_CONNECT", self._gateway.describe().get("summary", ""))
        return self._connected

    def _log(self, text: str) -> None:
        if self._run is not None:
            self._run.messages.append({"at": self._clock.now().isoformat(), "text": text})
        logger.info("%s", text)

    def _reset_runtime_tracking(self) -> None:
        self._alarm_active_word = 0
        self._interlock_active_word = 0
        self._estop_active = False
        self._run_control_feedback_inconsistent = False
        self._last_feedback_text = "控制反馈: --" if self._gateway.capabilities.run_control_word else "控制反馈: 不适用"
        self._last_run_control_word = 0
        self._last_estop_status = 0
        self._degraded_since = {}

    def _remember_update(self, update: EngineUpdate | None) -> None:
        if update is None or self._run is None:
            return
        self._run.status_text = update.status_text
        self._run.setpoints_text = update.active_setpoints_text

    def _snapshot_dict(self, snapshot: DeviceSnapshot | None) -> dict[str, Any] | None:
        if snapshot is None:
            return None
        return {
            "temperature_c": snapshot.temperature_c, "weight_g": snapshot.weight_g, "pressure_mpa": snapshot.pressure_mpa,
            "n2_lpm": snapshot.n2_lpm, "h2_lpm": snapshot.h2_lpm, "co_lpm": snapshot.co_lpm,
            "alarm_word": snapshot.alarm_word, "interlock_word": snapshot.interlock_word,
            "run_control_word": snapshot.run_control_word, "estop_status": snapshot.estop_status,
        }

    def _execution_text(self, run: _RunRecord | None, pending_alarms: list[dict[str, Any]], has_interlock: bool) -> str:
        if run is None:
            return "未启动"
        if run.status == "stopping":
            return "正在收尾，等待数据写入完成"
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
                self._gateway.apply_gas_setpoints(n2_lpm=step.n2_lpm, h2_lpm=step.h2_lpm, co_lpm=step.co_lpm)
            if run.temperature_mode == TemperatureControlMode.SETPOINT:
                self._gateway.apply_temperature_setpoint(temperature_c=step.target_temp_c, ramp_rate_cpm=step.ramp_rate_cpm)
            return True
        except Exception as exc:  # noqa: BLE001
            self._fail_active(f"步骤设定下发失败，实验已故障停止: {exc}", audit_action="SETPOINT_APPLY_FAILED",
                              detail=f"id={run.experiment_id},error={exc}")
            return False

    def _issue_run_control(self, command: str, label: str) -> bool:
        try:
            self._gateway.issue_run_control(command)
            return True
        except Exception as exc:  # noqa: BLE001
            run = self._run
            self._fail_active(f"运行控制命令下发失败[{label}]，实验已故障停止: {exc}", audit_action="RUN_CONTROL_FAILED",
                              detail=f"id={run.experiment_id if run else None},command={command},error={exc}")
            return False

    def _sync_run_control(self, command: str, label: str) -> bool:
        try:
            self._gateway.issue_run_control(command)
            return True
        except Exception as exc:  # noqa: BLE001
            if self._run is not None:
                self._audit.log_action("system", "RUN_CONTROL_SYNC_FAILED",
                                       f"id={self._run.experiment_id},command={command},label={label},error={exc}")
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
        self._audit.log_action("system", "EXPERIMENT_INTERRUPTED", detail)
        self._log(update.status_text)

    def _fail_active(self, reason: str, *, audit_action: str, detail: str, final_update: EngineUpdate | None = None) -> None:
        run = self._run
        if run is None or run.status in TERMINAL_STATUSES or run.status == "stopping":
            return
        update = final_update or run.engine.fail(reason)
        self._remember_update(update)
        if self._gateway.capabilities.run_control_word:
            self._sync_run_control("stop", "故障停机")
        self._experiments.set_experiment_status(run.experiment_id, ExperimentState.FAULTED.value)
        self._audit.log_action("system", audit_action, detail)
        run.error = reason
        self._log(reason)
        self._request_terminal(ExperimentState.FAULTED.value, audit_action="EXPERIMENT_FAULT",
                               log_message=f"实验故障退出，ID={run.experiment_id}")

    def _request_terminal(self, final_status: str, *, audit_action: str, log_message: str) -> None:
        run = self._run
        assert run is not None
        self._experiments.finish_experiment(run.experiment_id, status=final_status)
        self._audit.log_action("operator" if audit_action in {"EXPERIMENT_STOP", "EXPERIMENT_COMPLETE"} else "system",
                               audit_action, f"id={run.experiment_id},status={final_status}")
        self._log(log_message)
        run.pending_terminal = {"STOPPED": "stopped", "COMPLETED": "completed", "FAULTED": "faulted"}[final_status]
        run.status = "stopping"
        self._stop_event.set()
        if self._thread is None or not self._thread.is_alive():
            # No acquisition thread yet (failure during start): finish synchronously.
            self._flush_measurements()
            self._complete_terminal()

    def _complete_terminal(self) -> None:
        run = self._run
        if run is None or run.status != "stopping":
            return
        run.status = run.pending_terminal or "stopped"
        run.finished_at = self._clock.now().isoformat()
        self._degraded_since = {}

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
                self._audit.log_action("system", "ALARM_RAISED", f"experiment_id={run.experiment_id},word={snapshot.alarm_word:04X}")
            self._log(f"报警触发：{alarm_text_from_word(snapshot.alarm_word, profile_name=self.settings.mapping_profile)}")
            return
        if snapshot.alarm_word == 0 and self._alarm_active_word != 0:
            self._alarm_active_word = 0
            self._log("报警解除")

    def _update_interlock_state(self, snapshot: DeviceSnapshot) -> None:
        run = self._run
        previous_estop = self._estop_active
        self._estop_active = bool(snapshot.estop_status)
        word = snapshot.interlock_word
        if (word != 0 or snapshot.estop_status) and (word != self._interlock_active_word or previous_estop != self._estop_active):
            self._interlock_active_word = word
            self._log(f"联锁激活：状态字=0x{word:04X}")
            if run is not None:
                self._audit.log_action("system", "INTERLOCK_ACTIVE", f"id={run.experiment_id},word={word:04X}")
            return
        if word == 0 and not snapshot.estop_status and (self._interlock_active_word != 0 or previous_estop):
            self._interlock_active_word = 0
            self._log("联锁解除")
            if run is not None:
                self._audit.log_action("system", "INTERLOCK_CLEARED", f"id={run.experiment_id}")

    def _update_run_control_feedback(self, run_control_word: int) -> None:
        run = self._run
        feedback = self._gateway.evaluate_run_control_feedback(run_control_word)
        self._last_run_control_word = run_control_word
        self._last_feedback_text = feedback.message
        if feedback.is_consistent:
            if self._run_control_feedback_inconsistent:
                self._log("运行控制反馈已恢复一致")
                if run is not None:
                    self._audit.log_action("system", "RUN_CONTROL_FEEDBACK_RESTORED", f"id={run.experiment_id}")
            self._run_control_feedback_inconsistent = False
            return
        if self._run_control_feedback_inconsistent:
            return
        self._run_control_feedback_inconsistent = True
        self._log(feedback.message)
        if run is not None:
            self._audit.log_action("system", "RUN_CONTROL_FEEDBACK_MISMATCH", f"id={run.experiment_id},detail={feedback.message}")

    def _update_degraded(self, degraded: tuple[str, ...]) -> None:
        run = self._run
        now = self._clock.monotonic()
        current = set(degraded)
        for name in list(self._degraded_since):
            if name not in current:
                self._degraded_since.pop(name)
                self._log(f"设备 {name} 通讯恢复")
        for name in current:
            if name not in self._degraded_since:
                self._degraded_since[name] = now
                self._log(f"设备 {name} 通讯异常，保持上次有效值")
        if run is None or run.engine.state != ExperimentState.RUNNING:
            return
        for name, since in self._degraded_since.items():
            if now - since >= self.settings.degraded_fault_seconds:
                self._fail_active(f"设备 {name} 持续 {self.settings.degraded_fault_seconds}s 无有效数据，实验已故障停止",
                                  audit_action="ACQUISITION_FAILED", detail=f"id={run.experiment_id},device={name}")
                return
