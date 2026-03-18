from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from rka_desktop.models.entities import Measurement
from rka_desktop.services.recipe_runtime_service import RecipeStepRuntime


class ExperimentState(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    INTERRUPTED = "INTERRUPTED"
    STOPPED = "STOPPED"
    COMPLETED = "COMPLETED"
    FAULTED = "FAULTED"


@dataclass
class EngineUpdate:
    state: ExperimentState
    current_step_no: int | None
    total_steps: int
    status_text: str
    active_setpoints_text: str
    step_changed: bool = False
    completed: bool = False


class ExperimentEngine:
    def __init__(
        self,
        steps: list[RecipeStepRuntime],
        target_tolerance_c: float = 5.0,
        step_heatup_grace_seconds: int = 120,
        step_total_grace_seconds: int = 180,
    ) -> None:
        self.steps = steps
        self.target_tolerance_c = target_tolerance_c
        self.step_heatup_grace_seconds = step_heatup_grace_seconds
        self.step_total_grace_seconds = step_total_grace_seconds
        self.state = ExperimentState.IDLE
        self.current_step_index = 0
        self._step_started_at: datetime | None = None
        self._target_reached_at: datetime | None = None
        self._step_start_temp_c: float | None = None

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def current_step(self) -> RecipeStepRuntime | None:
        if not self.steps or self.current_step_index >= len(self.steps):
            return None
        return self.steps[self.current_step_index]

    def start(self) -> EngineUpdate:
        if not self.steps:
            self.state = ExperimentState.STOPPED
            return self._build_update("未找到可执行步骤", completed=True)

        self.state = ExperimentState.RUNNING
        self.current_step_index = 0
        self._step_started_at = None
        self._target_reached_at = None
        self._step_start_temp_c = None
        return self._build_update("实验已启动，等待进入第 1 步", step_changed=True)

    def pause(self) -> EngineUpdate:
        if self.state == ExperimentState.RUNNING:
            self.state = ExperimentState.PAUSED
        return self._build_update("实验已暂停")

    def resume(self) -> EngineUpdate:
        if self.state in (ExperimentState.PAUSED, ExperimentState.INTERRUPTED):
            self.state = ExperimentState.RUNNING
        return self._build_update("实验已恢复")

    def interrupt(self, reason: str = "实验已因报警联锁中断") -> EngineUpdate:
        if self.state == ExperimentState.RUNNING:
            self.state = ExperimentState.INTERRUPTED
        return self._build_update(reason)

    def stop(self) -> EngineUpdate:
        self.state = ExperimentState.STOPPED
        return self._build_update("实验已终止", completed=True)

    def fail(self, reason: str) -> EngineUpdate:
        self.state = ExperimentState.FAULTED
        return self._build_update(reason, completed=True)

    def on_measurement(self, measurement: Measurement) -> EngineUpdate:
        if self.state == ExperimentState.PAUSED:
            return self._build_update("实验暂停中")
        if self.state == ExperimentState.INTERRUPTED:
            return self._build_update("实验联锁中断中，待报警解除并确认")
        if self.state in (ExperimentState.STOPPED, ExperimentState.COMPLETED, ExperimentState.FAULTED):
            return self._build_update("实验已结束", completed=self.state == ExperimentState.COMPLETED)
        if self.state == ExperimentState.IDLE:
            return self._build_update("实验尚未启动")

        step = self.current_step
        if step is None:
            self.state = ExperimentState.COMPLETED
            return self._build_update("实验步骤全部完成", completed=True)

        if self._step_started_at is None:
            self._step_started_at = measurement.sampled_at
            self._step_start_temp_c = measurement.temperature_c

        step_changed = False
        status_text = f"执行第 {step.step_no}/{self.total_steps} 步"
        step_elapsed = int((measurement.sampled_at - self._step_started_at).total_seconds())

        if self._should_fault_step_total_timeout(step, step_elapsed):
            return self.fail(f"第 {step.step_no} 步执行超时，实验已故障停止")

        if measurement.temperature_c >= step.target_temp_c - self.target_tolerance_c:
            if self._target_reached_at is None:
                self._target_reached_at = measurement.sampled_at
                status_text = f"第 {step.step_no} 步达到目标温度，开始保温"
            else:
                elapsed = int((measurement.sampled_at - self._target_reached_at).total_seconds())
                remaining = max(0, step.hold_seconds - elapsed)
                status_text = f"第 {step.step_no} 步保温中，剩余 {remaining}s"

                if elapsed >= step.hold_seconds:
                    self.current_step_index += 1
                    self._step_started_at = measurement.sampled_at
                    self._target_reached_at = None
                    self._step_start_temp_c = measurement.temperature_c
                    step_changed = True

                    if self.current_step_index >= len(self.steps):
                        self.state = ExperimentState.COMPLETED
                        return self._build_update("实验步骤全部完成", completed=True, step_changed=True)

                    next_step = self.current_step
                    assert next_step is not None
                    return self._build_update(
                        f"已切换至第 {next_step.step_no} 步",
                        step_changed=step_changed,
                    )
        else:
            if self._should_fault_heatup_timeout(step, measurement.temperature_c, step_elapsed):
                return self.fail(f"第 {step.step_no} 步升温超时，未达到目标温度，实验已故障停止")
            status_text = f"第 {step.step_no} 步升温中，目标 {step.target_temp_c:.1f}℃"

        return self._build_update(status_text, step_changed=step_changed)

    def _expected_heatup_seconds(self, step: RecipeStepRuntime) -> int:
        start_temp = self._step_start_temp_c if self._step_start_temp_c is not None else step.target_temp_c
        delta_temp = max(0.0, step.target_temp_c - start_temp)
        ramp_rate = max(step.ramp_rate_cpm, 0.1)
        return int((delta_temp / ramp_rate) * 60)

    def _should_fault_heatup_timeout(self, step: RecipeStepRuntime, current_temp_c: float, step_elapsed: int) -> bool:
        if current_temp_c >= step.target_temp_c - self.target_tolerance_c:
            return False
        allowed_heatup = self._expected_heatup_seconds(step) + self.step_heatup_grace_seconds
        return step_elapsed > allowed_heatup

    def _should_fault_step_total_timeout(self, step: RecipeStepRuntime, step_elapsed: int) -> bool:
        allowed_total = self._expected_heatup_seconds(step) + step.hold_seconds + self.step_total_grace_seconds
        return step_elapsed > allowed_total

    def _build_update(self, status_text: str, step_changed: bool = False, completed: bool = False) -> EngineUpdate:
        step = self.current_step
        if step is None and self.steps:
            current_step_no = self.steps[-1].step_no
            setpoints = "执行完成"
        elif step is None:
            current_step_no = None
            setpoints = "无配方步骤"
        else:
            current_step_no = step.step_no
            setpoints = (
                f"目标温度 {step.target_temp_c:.1f}℃ | "
                f"升温速率 {step.ramp_rate_cpm:.1f}℃/min | "
                f"N2/H2/CO {step.n2_lpm:.1f}/{step.h2_lpm:.1f}/{step.co_lpm:.1f}"
            )

        return EngineUpdate(
            state=self.state,
            current_step_no=current_step_no,
            total_steps=self.total_steps,
            status_text=status_text,
            active_setpoints_text=setpoints,
            step_changed=step_changed,
            completed=completed,
        )
