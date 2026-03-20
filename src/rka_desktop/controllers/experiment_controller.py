from __future__ import annotations

from dataclasses import dataclass, field

from rka_desktop.core.config import Settings
from rka_desktop.db.database import DatabaseManager
from rka_desktop.hardware.device_gateway import DeviceGateway
from rka_desktop.models.entities import Measurement
from rka_desktop.services.experiment_engine import EngineUpdate, ExperimentEngine, ExperimentState
from rka_desktop.services.recipe_runtime_service import build_recipe_runtime


@dataclass
class ControllerTransition:
    success: bool = True
    update: EngineUpdate | None = None
    logs: list[str] = field(default_factory=list)
    recipe_name: str | None = None
    experiment_id: int | None = None
    final_status: str | None = None


class ExperimentController:
    def __init__(self, settings: Settings, db: DatabaseManager, gateway: DeviceGateway) -> None:
        self.settings = settings
        self.db = db
        self.gateway = gateway
        self.engine: ExperimentEngine | None = None
        self.experiment_id: int | None = None

    @property
    def has_active_experiment(self) -> bool:
        return self.experiment_id is not None and self.engine is not None

    def start_experiment(self, recipe_id: int) -> ControllerTransition:
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

        if not self._apply_current_step_setpoints():
            return ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value)
        if not self._issue_run_control_command("start", "启动"):
            return ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value)

        self.db.log_action("operator", "EXPERIMENT_START", f"id={self.experiment_id},recipe_id={recipe_id}")
        return ControllerTransition(
            success=True,
            update=start_update,
            recipe_name=recipe_name,
            experiment_id=self.experiment_id,
            logs=[f"实验开始，ID={self.experiment_id}，配方={recipe_name}"],
        )

    def pause_experiment(self) -> ControllerTransition | None:
        if not self.has_active_experiment or self.engine is None or self.experiment_id is None:
            return None
        if self.engine.state != ExperimentState.RUNNING:
            return None
        if not self._issue_run_control_command("pause", "暂停"):
            return ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value)

        update = self.engine.pause()
        self.db.set_experiment_status(self.experiment_id, ExperimentState.PAUSED.value)
        self.db.log_action("operator", "EXPERIMENT_PAUSE", f"id={self.experiment_id}")
        return ControllerTransition(update=update, logs=[update.status_text])

    def resume_experiment(self) -> ControllerTransition | None:
        if not self.has_active_experiment or self.engine is None or self.experiment_id is None:
            return None
        if not self._issue_run_control_command("resume", "恢复"):
            return ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value)

        update = self.engine.resume()
        self.db.set_experiment_status(self.experiment_id, ExperimentState.RUNNING.value)
        self.db.log_action("operator", "EXPERIMENT_RESUME", f"id={self.experiment_id}")
        if not self._apply_current_step_setpoints():
            return ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value)
        return ControllerTransition(update=update, logs=[update.status_text])

    def stop_experiment(self) -> ControllerTransition | None:
        if not self.has_active_experiment:
            return None
        if not self._issue_run_control_command("stop", "停止"):
            return ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value)
        return self._finalize_experiment(
            final_status=ExperimentState.STOPPED.value,
            audit_action="EXPERIMENT_STOP",
            log_message=f"实验终止，ID={self.experiment_id}" if self.experiment_id is not None else None,
        )

    def interrupt_experiment(self, detail: str, reason: str = "实验已因报警联锁中断") -> ControllerTransition | None:
        if not self.has_active_experiment or self.engine is None or self.experiment_id is None:
            return None
        update = self.engine.interrupt(reason)
        self._sync_run_control_command("pause", "联锁中断暂停")
        self.db.set_experiment_status(self.experiment_id, ExperimentState.INTERRUPTED.value)
        self.db.log_action("system", "EXPERIMENT_INTERRUPTED", detail)
        return ControllerTransition(update=update, logs=[update.status_text])

    def process_measurement(self, measurement: Measurement) -> ControllerTransition | None:
        if self.engine is None:
            return None

        update = self.engine.on_measurement(measurement)
        logs: list[str] = []

        if update.step_changed:
            if not self._apply_current_step_setpoints():
                return ControllerTransition(success=False, final_status=ExperimentState.FAULTED.value)
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
                return finalize

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

        return ControllerTransition(update=update, logs=logs)

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
        return finalize

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
