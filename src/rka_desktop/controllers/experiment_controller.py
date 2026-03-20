from __future__ import annotations

from dataclasses import dataclass, field

from rka_desktop.core.alarm_rules import (
    alarm_text_from_word,
    decode_alarm_word,
    has_active_interlock,
    has_interlock_alarm,
    interlock_text_from_word,
    is_interlock_resettable,
)
from rka_desktop.core.config import Settings
from rka_desktop.db.database import DatabaseManager
from rka_desktop.hardware.device_gateway import DeviceGateway
from rka_desktop.models.entities import DeviceSnapshot, Measurement
from rka_desktop.services.experiment_engine import EngineUpdate, ExperimentEngine, ExperimentState
from rka_desktop.services.recipe_runtime_service import build_recipe_runtime


@dataclass
class RuntimeViewState:
    execution_text: str | None = None
    setpoints_text: str | None = None
    current_alarm_text: str | None = None
    current_interlock_text: str | None = None
    monitor_alarm_text: str | None = None
    monitor_alarm_style: str | None = None
    monitor_interlock_text: str | None = None
    monitor_interlock_style: str | None = None
    run_control_word: int | None = None
    estop_status: int | None = None
    control_feedback_text: str | None = None
    control_feedback_style: str | None = None
    pending_alarms: list[dict[str, object]] = field(default_factory=list)
    ack_alarm_enabled: bool | None = None
    reset_interlock_enabled: bool | None = None
    start_enabled: bool | None = None
    pause_enabled: bool | None = None
    resume_enabled: bool | None = None
    stop_enabled: bool | None = None


@dataclass
class ControllerTransition:
    success: bool = True
    update: EngineUpdate | None = None
    logs: list[str] = field(default_factory=list)
    recipe_name: str | None = None
    experiment_id: int | None = None
    final_status: str | None = None
    view_state: RuntimeViewState | None = None
    user_message: str | None = None
    user_message_level: str | None = None


class ExperimentController:
    def __init__(self, settings: Settings, db: DatabaseManager, gateway: DeviceGateway) -> None:
        self.settings = settings
        self.db = db
        self.gateway = gateway
        self.engine: ExperimentEngine | None = None
        self.experiment_id: int | None = None
        self._reset_runtime_tracking()

    @property
    def has_active_experiment(self) -> bool:
        return self.experiment_id is not None and self.engine is not None

    def start_experiment(self, recipe_id: int) -> ControllerTransition:
        self._reset_runtime_tracking()
        recipe = self.db.get_recipe(recipe_id)
        recipe_steps = self.db.get_recipe_steps(recipe_id)
        if not recipe_steps:
            raise ValueError("当前配方没有可执行步骤")

        recipe_name = recipe["name"] if recipe else f"配方{recipe_id}"
        self.experiment_id = self.db.create_experiment(name=f"实验-{recipe_name}", recipe_id=recipe_id)
        self.engine = ExperimentEngine(
            build_recipe_runtime(recipe_steps),
            step_heatup_grace_seconds=self.settings.step_heatup_grace_seconds,
            step_total_grace_seconds=self.settings.step_total_grace_seconds,
        )
        start_update = self.engine.start()
        self._remember_update(start_update)

        if not self._apply_current_step_setpoints():
            return self._with_view_state(ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value))
        if not self._issue_run_control_command("start", "启动"):
            return self._with_view_state(ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value))

        self.db.log_action("operator", "EXPERIMENT_START", f"id={self.experiment_id},recipe_id={recipe_id}")
        return self._with_view_state(
            ControllerTransition(
            success=True,
            update=start_update,
            recipe_name=recipe_name,
            experiment_id=self.experiment_id,
            logs=[f"实验开始，ID={self.experiment_id}，配方={recipe_name}"],
            )
        )

    def pause_experiment(self) -> ControllerTransition | None:
        if not self.has_active_experiment or self.engine is None or self.experiment_id is None:
            return None
        if self.engine.state != ExperimentState.RUNNING:
            return None
        if not self._issue_run_control_command("pause", "暂停"):
            return self._with_view_state(ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value))

        update = self.engine.pause()
        self._remember_update(update)
        self.db.set_experiment_status(self.experiment_id, ExperimentState.PAUSED.value)
        self.db.log_action("operator", "EXPERIMENT_PAUSE", f"id={self.experiment_id}")
        return self._with_view_state(ControllerTransition(update=update, logs=[update.status_text]))

    def resume_experiment(self) -> ControllerTransition | None:
        if not self.has_active_experiment or self.engine is None or self.experiment_id is None:
            return None
        blocking_message = self._resume_blocking_message()
        if blocking_message is not None:
            return self._with_view_state(
                ControllerTransition(success=False, user_message=blocking_message, user_message_level="warning")
            )
        if not self._issue_run_control_command("resume", "恢复"):
            return self._with_view_state(ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value))

        update = self.engine.resume()
        self._remember_update(update)
        self.db.set_experiment_status(self.experiment_id, ExperimentState.RUNNING.value)
        self.db.log_action("operator", "EXPERIMENT_RESUME", f"id={self.experiment_id}")
        if not self._apply_current_step_setpoints():
            return self._with_view_state(ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value))
        return self._with_view_state(ControllerTransition(update=update, logs=[update.status_text]))

    def stop_experiment(self) -> ControllerTransition | None:
        if not self.has_active_experiment:
            return None
        if not self._issue_run_control_command("stop", "停止"):
            return self._with_view_state(ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value))
        return self._finalize_experiment(
            final_status=ExperimentState.STOPPED.value,
            audit_action="EXPERIMENT_STOP",
            log_message=f"实验终止，ID={self.experiment_id}" if self.experiment_id is not None else None,
        )

    def interrupt_experiment(self, detail: str, reason: str = "实验已因报警联锁中断") -> ControllerTransition | None:
        if not self.has_active_experiment or self.engine is None or self.experiment_id is None:
            return None
        update = self.engine.interrupt(reason)
        self._remember_update(update)
        self._sync_run_control_command("pause", "联锁中断暂停")
        self.db.set_experiment_status(self.experiment_id, ExperimentState.INTERRUPTED.value)
        self.db.log_action("system", "EXPERIMENT_INTERRUPTED", detail)
        return self._with_view_state(ControllerTransition(update=update, logs=[update.status_text]))

    def acknowledge_alarm(self) -> ControllerTransition:
        if self.experiment_id is None:
            return self._with_view_state(
                ControllerTransition(success=False, user_message="当前无运行中的实验", user_message_level="info")
            )

        ok = self.db.acknowledge_latest_alarm(self.experiment_id, actor="operator")
        logs = ["报警已确认"] if ok else ["没有待确认报警"]
        if ok:
            self.db.log_action("operator", "ALARM_ACK", f"experiment_id={self.experiment_id}")
        return self._with_view_state(ControllerTransition(success=ok, logs=logs))

    def reset_interlock(self) -> ControllerTransition:
        if self.experiment_id is None:
            return self._with_view_state(
                ControllerTransition(success=False, user_message="当前无运行中的实验", user_message_level="info")
            )
        if self._alarm_active_word != 0:
            return self._with_view_state(
                ControllerTransition(success=False, user_message="当前仍有活动报警，请先排除报警", user_message_level="warning")
            )
        if self._has_unacknowledged_alarms():
            return self._with_view_state(
                ControllerTransition(success=False, user_message="仍有未确认报警，请先确认", user_message_level="warning")
            )
        if self._interlock_active_word == 0 and not self._estop_active:
            return self._with_view_state(
                ControllerTransition(success=False, user_message="当前没有需要复位的联锁", user_message_level="info")
            )
        if not is_interlock_resettable(self._interlock_active_word, profile_name=self.settings.mapping_profile):
            return self._with_view_state(
                ControllerTransition(
                    success=False,
                    user_message="当前联锁状态不允许软件复位，请先解除急停/硬件闭锁",
                    user_message_level="warning",
                )
            )
        if not self._issue_run_control_command("reset", "联锁复位"):
            return self._with_view_state(ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value))
        self.db.log_action("operator", "INTERLOCK_RESET", f"id={self.experiment_id},word={self._interlock_active_word:04X}")
        return self._with_view_state(ControllerTransition(logs=["已请求联锁复位，等待状态解除"]))

    def handle_snapshot(self, snapshot: DeviceSnapshot, measurement: Measurement) -> ControllerTransition:
        transition = ControllerTransition()
        transition.logs.extend(self._update_run_control_feedback(snapshot.run_control_word))
        transition.logs.extend(self._update_alarm_state(snapshot))
        transition.logs.extend(self._update_interlock_state(snapshot))

        interrupted = False
        if (
            self.engine is not None
            and self.experiment_id is not None
            and self.engine.state == ExperimentState.RUNNING
            and has_interlock_alarm(snapshot.alarm_word, profile_name=self.settings.mapping_profile)
        ):
            interrupt_transition = self.interrupt_experiment(f"id={self.experiment_id},alarm={snapshot.alarm_word:04X}")
            transition = self._merge_transitions(transition, interrupt_transition)
            interrupted = interrupt_transition is not None

        if (
            not interrupted
            and self.engine is not None
            and self.experiment_id is not None
            and self.engine.state == ExperimentState.RUNNING
            and (snapshot.interlock_word != 0 or snapshot.estop_status)
        ):
            interrupt_transition = self.interrupt_experiment(
                f"id={self.experiment_id},interlock={snapshot.interlock_word:04X}"
            )
            transition = self._merge_transitions(transition, interrupt_transition)
            interrupted = interrupt_transition is not None

        if not interrupted:
            process_transition = self.process_measurement(measurement)
            transition = self._merge_transitions(transition, process_transition)

        return self._with_view_state(transition, run_control_word=snapshot.run_control_word, estop_status=snapshot.estop_status)

    def handle_acquisition_error(self, message: str) -> ControllerTransition:
        return self.fail_active_experiment(
            f"采集异常，实验已故障停止: {message}",
            audit_action="ACQUISITION_FAILED",
            detail=f"id={self.experiment_id},error={message}" if self.experiment_id is not None else f"error={message}",
        )

    def process_measurement(self, measurement: Measurement) -> ControllerTransition | None:
        if self.engine is None:
            return None

        update = self.engine.on_measurement(measurement)
        self._remember_update(update)
        logs: list[str] = []

        if update.step_changed:
            if not self._apply_current_step_setpoints():
                return self._with_view_state(ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value))
            logs.append(update.status_text)

        if update.completed:
            if update.state == ExperimentState.COMPLETED:
                self._sync_run_control_command("stop", "完成停机")
                finalize = self._finalize_experiment(
                    final_status=ExperimentState.COMPLETED.value,
                    final_update=update,
                    terminate_engine=False,
                    audit_action="EXPERIMENT_COMPLETE",
                    log_message=f"实验完成，ID={self.experiment_id}" if self.experiment_id is not None else None,
                )
                finalize.logs.insert(0, "执行引擎判定实验完成")
                return self._with_view_state(finalize)

            if update.state == ExperimentState.FAULTED:
                return self.fail_active_experiment(
                    update.status_text,
                    audit_action="STEP_TIMEOUT_FAULT",
                    detail=(
                        f"id={self.experiment_id},step={update.current_step_no}"
                        if self.experiment_id is not None
                        else "step_timeout"
                    ),
                    final_update=update,
                )

        return self._with_view_state(ControllerTransition(update=update, logs=logs))

    def fail_active_experiment(
        self,
        reason: str,
        *,
        audit_action: str,
        detail: str,
        final_update: EngineUpdate | None = None,
    ) -> ControllerTransition:
        update = final_update
        if self.engine is not None and update is None:
            update = self.engine.fail(reason)
        if update is not None:
            self._remember_update(update)
        self._sync_run_control_command("stop", "故障停机")
        if self.experiment_id is not None:
            self.db.set_experiment_status(self.experiment_id, ExperimentState.FAULTED.value)
            self.db.log_action("system", audit_action, detail)
        finalize = self._finalize_experiment(
            final_status=ExperimentState.FAULTED.value,
            final_update=update,
            terminate_engine=False,
            audit_action="EXPERIMENT_FAULT",
            log_message=f"实验故障退出，ID={self.experiment_id}" if self.experiment_id is not None else None,
        )
        finalize.logs.insert(0, reason)
        return self._with_view_state(finalize)

    def _apply_current_step_setpoints(self) -> bool:
        if self.engine is None or self.engine.current_step is None:
            return True

        step = self.engine.current_step
        try:
            self.gateway.apply_setpoints(
                temperature_c=step.target_temp_c,
                ramp_rate_cpm=step.ramp_rate_cpm,
                n2_lpm=step.n2_lpm,
                h2_lpm=step.h2_lpm,
                co_lpm=step.co_lpm,
            )
            return True
        except Exception as exc:
            self.fail_active_experiment(
                f"步骤设定下发失败，实验已故障停止: {exc}",
                audit_action="SETPOINT_APPLY_FAILED",
                detail=f"id={self.experiment_id},error={exc}" if self.experiment_id is not None else f"error={exc}",
            )
            return False

    def _issue_run_control_command(self, command: str, action_label: str) -> bool:
        try:
            self.gateway.issue_run_control(command)
            return True
        except Exception as exc:
            self.fail_active_experiment(
                f"运行控制命令下发失败[{action_label}]，实验已故障停止: {exc}",
                audit_action="RUN_CONTROL_FAILED",
                detail=(
                    f"id={self.experiment_id},command={command},error={exc}"
                    if self.experiment_id is not None
                    else f"command={command},error={exc}"
                ),
            )
            return False

    def _sync_run_control_command(self, command: str, action_label: str) -> bool:
        try:
            self.gateway.issue_run_control(command)
            return True
        except Exception as exc:
            if self.experiment_id is not None:
                self.db.log_action(
                    "system",
                    "RUN_CONTROL_SYNC_FAILED",
                    f"id={self.experiment_id},command={command},error={exc}",
                )
            return False

    def _finalize_experiment(
        self,
        *,
        final_status: str,
        final_update: EngineUpdate | None = None,
        terminate_engine: bool = True,
        audit_action: str,
        log_message: str | None = None,
    ) -> ControllerTransition:
        update = final_update
        if self.engine is not None and update is None and terminate_engine:
            update = self.engine.stop()

        exp_id = self.experiment_id
        self.engine = None
        self.experiment_id = None
        self._reset_runtime_tracking(keep_feedback=False)

        logs: list[str] = []
        if exp_id is not None:
            self.db.finish_experiment(exp_id, status=final_status)
            self.db.log_action("operator", audit_action, f"id={exp_id},status={final_status}")
            logs.append(log_message or f"实验结束，ID={exp_id}，状态={final_status}")

        return ControllerTransition(
            update=update,
            logs=logs,
            experiment_id=exp_id,
            final_status=final_status,
        )

    def _reset_runtime_tracking(self, keep_feedback: bool = False) -> None:
        self._alarm_active_word = 0
        self._interlock_active_word = 0
        self._estop_active = False
        if not keep_feedback:
            self._run_control_feedback_inconsistent = False
            self._last_feedback_text = "控制反馈: --"
            self._last_feedback_style = ""
            self._last_run_control_word = 0
            self._last_estop_status = 0
        self._last_status_text = "未启动"
        self._last_setpoints_text = "--"

    def _remember_update(self, update: EngineUpdate | None) -> None:
        if update is None:
            return
        self._last_status_text = update.status_text
        self._last_setpoints_text = update.active_setpoints_text

    def _has_unacknowledged_alarms(self) -> bool:
        return bool(self.experiment_id is not None and self.db.list_unacknowledged_alarms(self.experiment_id))

    def _resume_blocking_message(self) -> str | None:
        if self.engine is None or self.engine.state != ExperimentState.INTERRUPTED:
            return None
        if self._alarm_active_word != 0:
            return "当前仍有活动报警，请先排除报警"
        if self._interlock_active_word != 0 or self._estop_active:
            return "联锁尚未解除，请先执行复位或解除急停"
        if self._has_unacknowledged_alarms():
            return "报警已解除，但仍有未确认报警"
        return None

    def _update_alarm_state(self, snapshot: DeviceSnapshot) -> list[str]:
        logs: list[str] = []
        active_alarms = decode_alarm_word(snapshot.alarm_word, profile_name=self.settings.mapping_profile)

        if snapshot.alarm_word != 0 and snapshot.alarm_word != self._alarm_active_word:
            self._alarm_active_word = snapshot.alarm_word
            if self.experiment_id is not None:
                for alarm in active_alarms:
                    self.db.create_alarm(
                        self.experiment_id,
                        code=alarm.code,
                        level=alarm.level,
                        message=alarm.message,
                    )
                self.db.log_action("system", "ALARM_RAISED", f"experiment_id={self.experiment_id},word={snapshot.alarm_word:04X}")
            logs.append(f"报警触发：报警字={snapshot.alarm_word}")
            return logs

        if snapshot.alarm_word == 0 and self._alarm_active_word != 0:
            self._alarm_active_word = 0
            logs.append("报警解除")

        return logs

    def _update_interlock_state(self, snapshot: DeviceSnapshot) -> list[str]:
        logs: list[str] = []
        previous_estop = self._estop_active
        self._estop_active = bool(snapshot.estop_status)
        current_word = snapshot.interlock_word
        if (current_word != 0 or snapshot.estop_status) and (
            current_word != self._interlock_active_word or previous_estop != self._estop_active
        ):
            self._interlock_active_word = current_word
            logs.append(f"联锁激活：状态字=0x{current_word:04X}")
            if self.experiment_id is not None:
                self.db.log_action("system", "INTERLOCK_ACTIVE", f"id={self.experiment_id},word={current_word:04X}")
            return logs

        if current_word == 0 and not snapshot.estop_status and (self._interlock_active_word != 0 or previous_estop):
            self._interlock_active_word = 0
            logs.append("联锁解除")
            if self.experiment_id is not None:
                self.db.log_action("system", "INTERLOCK_CLEARED", f"id={self.experiment_id}")

        return logs

    def _update_run_control_feedback(self, run_control_word: int) -> list[str]:
        logs: list[str] = []
        feedback = self.gateway.evaluate_run_control_feedback(run_control_word)
        self._last_run_control_word = run_control_word
        self._last_feedback_text = feedback.message
        self._last_feedback_style = "color: #1b5e20;" if feedback.is_consistent else "color: #b71c1c; font-weight: bold;"

        if feedback.is_consistent:
            if self._run_control_feedback_inconsistent:
                logs.append("运行控制反馈已恢复一致")
                if self.experiment_id is not None:
                    self.db.log_action("system", "RUN_CONTROL_FEEDBACK_RESTORED", f"id={self.experiment_id}")
            self._run_control_feedback_inconsistent = False
            return logs

        if self._run_control_feedback_inconsistent:
            return logs

        self._run_control_feedback_inconsistent = True
        logs.append(feedback.message)
        if self.experiment_id is not None:
            self.db.log_action(
                "system",
                "RUN_CONTROL_FEEDBACK_MISMATCH",
                f"id={self.experiment_id},detail={feedback.message}",
            )
        return logs

    def _build_view_state(
        self,
        *,
        run_control_word: int | None = None,
        estop_status: int | None = None,
    ) -> RuntimeViewState:
        current_alarm_text = f"当前报警: {alarm_text_from_word(self._alarm_active_word, profile_name=self.settings.mapping_profile)}"
        interlock_text = interlock_text_from_word(self._interlock_active_word, profile_name=self.settings.mapping_profile)
        if self._estop_active:
            interlock_text = f"{interlock_text} / 急停触发" if interlock_text != "无联锁" else "急停触发"
        current_interlock_text = f"当前联锁: {interlock_text}"

        if self._alarm_active_word != 0:
            monitor_alarm_text = f"状态: {alarm_text_from_word(self._alarm_active_word, profile_name=self.settings.mapping_profile)}"
            monitor_alarm_style = "color: #b71c1c; font-weight: bold;"
        else:
            monitor_alarm_text = "状态: 正常"
            monitor_alarm_style = "color: #1b5e20;"

        if self._interlock_active_word != 0 or self._estop_active:
            monitor_interlock_text = f"联锁: {interlock_text}"
            monitor_interlock_style = "color: #b71c1c; font-weight: bold;"
        else:
            monitor_interlock_text = "联锁: 无联锁"
            monitor_interlock_style = "color: #1b5e20;"

        has_active = self.has_active_experiment
        pending_alarms = self.db.list_unacknowledged_alarms(self.experiment_id) if self.experiment_id is not None else []
        has_interlock = has_active_interlock(self._interlock_active_word, profile_name=self.settings.mapping_profile)
        reset_enabled = (
            has_active
            and self.engine is not None
            and self.engine.state == ExperimentState.INTERRUPTED
            and self._alarm_active_word == 0
            and not pending_alarms
            and has_interlock
            and not self._estop_active
            and is_interlock_resettable(self._interlock_active_word, profile_name=self.settings.mapping_profile)
        )
        resume_enabled = (
            has_active
            and self.engine is not None
            and self.engine.state == ExperimentState.INTERRUPTED
            and self._resume_blocking_message() is None
        ) or (
            has_active
            and self.engine is not None
            and self.engine.state == ExperimentState.PAUSED
        )

        if self.engine is not None and self.engine.state == ExperimentState.INTERRUPTED:
            if self._alarm_active_word != 0:
                execution_text = "报警处理中，联锁保持中"
            elif pending_alarms and has_interlock:
                execution_text = "报警已解除，待确认后可执行联锁复位"
            elif pending_alarms:
                execution_text = "报警已解除，待确认后可恢复实验"
            elif self._estop_active:
                execution_text = "急停仍处于触发状态，禁止恢复"
            elif has_interlock:
                execution_text = "联锁保持中，可执行复位"
            else:
                execution_text = "联锁已解除，可恢复实验"
        else:
            execution_text = self._last_status_text

        return RuntimeViewState(
            execution_text=execution_text,
            setpoints_text=self._last_setpoints_text,
            current_alarm_text=current_alarm_text,
            current_interlock_text=current_interlock_text,
            monitor_alarm_text=monitor_alarm_text,
            monitor_alarm_style=monitor_alarm_style,
            monitor_interlock_text=monitor_interlock_text,
            monitor_interlock_style=monitor_interlock_style,
            run_control_word=self._last_run_control_word if run_control_word is None else run_control_word,
            estop_status=self._last_estop_status if estop_status is None else estop_status,
            control_feedback_text=self._last_feedback_text,
            control_feedback_style=self._last_feedback_style,
            pending_alarms=pending_alarms,
            ack_alarm_enabled=bool(pending_alarms),
            reset_interlock_enabled=reset_enabled,
            start_enabled=not has_active,
            pause_enabled=bool(has_active and self.engine is not None and self.engine.state == ExperimentState.RUNNING),
            resume_enabled=bool(resume_enabled),
            stop_enabled=bool(has_active),
        )

    def _with_view_state(
        self,
        transition: ControllerTransition,
        *,
        run_control_word: int | None = None,
        estop_status: int | None = None,
    ) -> ControllerTransition:
        if estop_status is not None:
            self._last_estop_status = estop_status
        transition.view_state = self._build_view_state(run_control_word=run_control_word, estop_status=estop_status)
        return transition

    def _merge_transitions(
        self,
        base: ControllerTransition,
        extra: ControllerTransition | None,
    ) -> ControllerTransition:
        if extra is None:
            return base
        base.success = base.success and extra.success
        base.logs.extend(extra.logs)
        if extra.update is not None:
            base.update = extra.update
        if extra.recipe_name is not None:
            base.recipe_name = extra.recipe_name
        if extra.experiment_id is not None:
            base.experiment_id = extra.experiment_id
        if extra.final_status is not None:
            base.final_status = extra.final_status
        if extra.user_message is not None:
            base.user_message = extra.user_message
            base.user_message_level = extra.user_message_level
        return base
