"""Control-mode rules for gas mixing and furnace temperature during a run.

Gas: the software mixes gases per recipe step (``auto``) or leaves the MFC set-points to
the operator (``manual``). Switching while an experiment is active is an operator decision
that must be confirmed explicitly; the rule lives here so API and UI cannot disagree.

Temperature: in ``program`` mode the whole recipe profile is downloaded to the temperature
controller once at start and the controller executes it unattended; the software only
observes PV. In ``setpoint`` mode (the pre-migration behaviour for the PLC register map) the
software writes the target and ramp rate at start and at every step change.
"""

from __future__ import annotations

from enum import Enum


class GasControlMode(str, Enum):
    AUTO = "auto"
    MANUAL = "manual"


class TemperatureControlMode(str, Enum):
    PROGRAM = "program"
    SETPOINT = "setpoint"


class ControlModeError(ValueError):
    pass


class ConfirmationRequired(ControlModeError):
    """The requested change has side effects and needs an explicit operator confirmation."""


def parse_gas_mode(value: object) -> GasControlMode:
    try:
        return GasControlMode(str(value))
    except ValueError as exc:
        raise ControlModeError("配气模式只能是 auto 或 manual") from exc


def parse_temperature_mode(value: object) -> TemperatureControlMode:
    try:
        return TemperatureControlMode(str(value))
    except ValueError as exc:
        raise ControlModeError("温度控制模式只能是 program 或 setpoint") from exc


def check_gas_mode_switch(current: GasControlMode, target: GasControlMode, *, run_active: bool, confirmed: bool) -> None:
    if current == target:
        return
    if run_active and not confirmed:
        raise ConfirmationRequired("实验运行中切换配气模式需要二次确认")
