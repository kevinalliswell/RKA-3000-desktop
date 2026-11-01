from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any

import pytest

from rka_desktop.application.experiment_runner import ExperimentRunner, RunnerSettings
from rka_desktop.application.limits_service import LimitsService
from rka_desktop.application.ports import GatewayCapabilities, RunControlFeedback
from rka_desktop.application.recipe_service import RecipeService
from rka_desktop.domain.control import GasControlMode, TemperatureControlMode
from rka_desktop.domain.entities import DeviceSnapshot, MultiDeviceSnapshot
from rka_desktop.domain.preflight import CHECKLIST_KEYS
from rka_desktop.domain.recipe import RecipeStep
from rka_desktop.infrastructure.sqlite.database import DatabaseManager
from rka_desktop.infrastructure.sqlite.repositories import (
    SqliteAlarmStore,
    SqliteAuditStore,
    SqliteExperimentStore,
    SqliteLimitStore,
    SqliteRecipeStore,
)

# Inert purge (step 1) -> reaction (step 2) -> inert finish (step 3); short holds keep tests fast.
RECIPE_STEPS = [
    {"step_no": 1, "name": "惰性置换", "target_temp_c": 150.0, "ramp_rate_cpm": 10.0, "hold_seconds": 2, "n2_lpm": 4.0,
     "h2_lpm": 0.0, "co_lpm": 0.0, "notes": ""},
    {"step_no": 2, "name": "等温还原", "target_temp_c": 900.0, "ramp_rate_cpm": 10.0, "hold_seconds": 3, "n2_lpm": 3.0,
     "h2_lpm": 1.0, "co_lpm": 0.8, "notes": ""},
    {"step_no": 3, "name": "惰性处置", "target_temp_c": 200.0, "ramp_rate_cpm": 0.0, "hold_seconds": 2, "n2_lpm": 4.0,
     "h2_lpm": 0.0, "co_lpm": 0.0, "notes": ""},
]
RECIPE_META = {"experiment_type": "reduction", "inert_gas": "N2", "purge_lpm": 4.0, "purge_seconds": 2}
RECIPE_PAYLOAD = {"name": "标准流程", **RECIPE_META, "steps": RECIPE_STEPS}
DEVICE_LIMITS = {"N2": 20.0, "AR": 20.0, "H2": 5.0, "CO": 5.0, "CO2": 20.0, "CH4": 5.0}
SAMPLE = {"name": "球团矿 A-19", "initial_mass_g": 100.0, "tfe_pct": 64.2, "feo_pct": 8.4, "operator": "实验员 A"}


def start_payload(recipe_id: int, **overrides: Any) -> dict[str, Any]:
    payload = {"recipe_id": recipe_id, "sample": dict(SAMPLE), "checklist": {key: True for key in CHECKLIST_KEYS}}
    payload.update(overrides)
    return payload


class FakeClock:
    def __init__(self) -> None:
        self.wall = datetime(2026, 1, 1, 12, 0, 0)
        self.mono = 1000.0

    def now(self) -> datetime:
        return self.wall

    def monotonic(self) -> float:
        return self.mono

    def advance(self, seconds: float) -> None:
        self.wall += timedelta(seconds=seconds)
        self.mono += seconds


class FakeGateway:
    """In-memory device: records writes, serves scripted snapshots, can fail on demand."""

    def __init__(self, *, run_control: bool = True, program: bool = True, readback: bool = True) -> None:
        self.capabilities = GatewayCapabilities(
            temperature_program=program, temperature_setpoint=True, run_control_word=run_control,
            alarm_words=run_control, multi_device_status=True, balance_tare=True, gas_setpoint_readback=readback,
        )
        self.connected = False
        self.connect_result = True
        self.gas_writes: list[dict[str, float]] = []
        self.temp_writes: list[dict[str, float]] = []
        self.programs: list[list[RecipeStep]] = []
        self.commands: list[str] = []
        self.fail_gas = False
        self.fail_command: str | None = None
        self.fail_read = False
        self.degraded: tuple[str, ...] = ()
        self.readback_override: dict[str, float] | None = None
        self.snapshot = DeviceSnapshot(150.0, 100.0, 0.0, 4.0, 0.0, 0.0, 0, flows_lpm={"N2": 4.0})
        self.tare_calls = 0
        self.mfc_writes: list[tuple[int, float]] = []
        self.lock = threading.Lock()
        self.device_limits = dict(DEVICE_LIMITS)

    def connect(self) -> bool:
        self.connected = self.connect_result
        return self.connected

    def close(self) -> None:
        self.connected = False

    def read_snapshot(self) -> DeviceSnapshot:
        if self.fail_read:
            raise RuntimeError("serial timeout")
        return self.snapshot

    def degraded_devices(self) -> tuple[str, ...]:
        return self.degraded

    def gas_device_limits(self) -> dict[str, float]:
        return dict(self.device_limits)

    def max_program_steps(self) -> int | None:
        return 4

    def apply_gas_setpoints(self, flows: dict[str, float]) -> dict[str, float]:
        if self.fail_gas:
            raise RuntimeError("mfc write failed")
        values = {gas: float(value) for gas, value in flows.items() if gas in self.device_limits}
        with self.lock:
            self.gas_writes.append(values)
        return values

    def read_gas_setpoints(self) -> dict[str, float] | None:
        if self.readback_override is not None:
            return dict(self.readback_override)
        return dict(self.gas_writes[-1]) if self.gas_writes else {}

    @property
    def last_gas(self) -> dict[str, float]:
        return {gas: value for gas, value in self.gas_writes[-1].items() if value} if self.gas_writes else {}

    def apply_temperature_setpoint(self, *, temperature_c: float, ramp_rate_cpm: float) -> None:
        self.temp_writes.append({"temperature_c": temperature_c, "ramp_rate_cpm": ramp_rate_cpm})

    def download_temperature_program(self, steps: list[RecipeStep]) -> dict[str, Any]:
        self.programs.append(list(steps))
        return {"group": 0, "segments": len(steps) * 2, "message": "程序已下发（测试）", "remote_start": False}

    def issue_run_control(self, command: str) -> int:
        if command == self.fail_command:
            raise RuntimeError(f"{command} rejected")
        self.commands.append(command)
        return 1

    def evaluate_run_control_feedback(self, feedback_word: int) -> RunControlFeedback:
        return RunControlFeedback(None, 0, feedback_word, feedback_word == 0, "控制反馈: 空闲" if feedback_word == 0 else "不一致")

    def read_multi_snapshot(self) -> MultiDeviceSnapshot | None:
        return MultiDeviceSnapshot((self.snapshot.temperature_c,), {1: 1.0, 2: 3.0, 3: 0.8}, {1: 1.0, 2: 3.0, 3: 0.8},
                                   self.snapshot.weight_g, self.degraded)

    def set_mfc_flow(self, address: int, lpm: float) -> None:
        self.mfc_writes.append((address, lpm))

    def set_temperature_sv(self, celsius: float) -> None:
        self.temp_writes.append({"temperature_c": celsius, "ramp_rate_cpm": 0.0})

    def tare_balance(self) -> bool:
        self.tare_calls += 1
        return True

    def describe(self) -> dict[str, Any]:
        return {"backend": "fake", "simulation": True, "summary": "fake gateway", "devices": [], "mfc_channels": []}


@pytest.fixture
def db(tmp_path) -> DatabaseManager:
    database = DatabaseManager(tmp_path / "test.db")
    database.init_schema()
    return database


@pytest.fixture
def stores(db):
    return {
        "recipes": SqliteRecipeStore(db), "experiments": SqliteExperimentStore(db),
        "alarms": SqliteAlarmStore(db), "audit": SqliteAuditStore(db), "limits": SqliteLimitStore(db),
    }


@pytest.fixture
def recipe_id(stores) -> int:
    return stores["recipes"].create_recipe("标准流程", RECIPE_STEPS, RECIPE_META)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_services(stores, gateway) -> tuple[RecipeService, LimitsService]:
    holder: dict[str, LimitsService] = {}
    recipes = RecipeService(stores["recipes"], stores["audit"], limits=lambda: holder["limits"].effective(),
                            device_limits=gateway.gas_device_limits, max_program_steps=gateway.max_program_steps)
    limits = LimitsService(stores["limits"], stores["audit"], device_limits=gateway.gas_device_limits,
                           lock_reason=lambda: None, assess_all=recipes.assess_all)
    holder["limits"] = limits
    return recipes, limits


def make_runner(stores, gateway, clock, **overrides) -> ExperimentRunner:
    settings = RunnerSettings(
        poll_interval_ms=overrides.pop("poll_interval_ms", 20), acquisition_batch_size=overrides.pop("batch", 2),
        temperature_mode=overrides.pop("temperature_mode", TemperatureControlMode.PROGRAM),
        default_gas_mode=overrides.pop("gas_mode", GasControlMode.AUTO),
        degraded_fault_seconds=overrides.pop("degraded_fault_seconds", 30), **overrides,
    )
    recipes, limits = make_services(stores, gateway)
    return ExperimentRunner(settings=settings, recipe_loader=recipes.load_for_run, limits_provider=limits.effective,
                            experiments=stores["experiments"], alarms=stores["alarms"], audit=stores["audit"], gateway=gateway,
                            clock=clock)


@pytest.fixture
def runner_factory(stores, clock):
    runners: list[ExperimentRunner] = []

    def factory(gateway: FakeGateway | None = None, **overrides) -> tuple[ExperimentRunner, FakeGateway]:
        gateway = gateway or FakeGateway()
        runner = make_runner(stores, gateway, clock, **overrides)
        runners.append(runner)
        return runner, gateway

    yield factory
    for runner in runners:
        runner.close(timeout=5)
