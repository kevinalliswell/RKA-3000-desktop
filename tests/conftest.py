from __future__ import annotations

import threading
from datetime import datetime, timedelta
from typing import Any

import pytest

from rka_desktop.application.experiment_runner import ExperimentRunner, RunnerSettings
from rka_desktop.application.ports import GatewayCapabilities, RunControlFeedback
from rka_desktop.domain.control import GasControlMode, TemperatureControlMode
from rka_desktop.domain.entities import DeviceSnapshot, MultiDeviceSnapshot
from rka_desktop.domain.recipe import RecipeStep
from rka_desktop.infrastructure.sqlite.database import DatabaseManager
from rka_desktop.infrastructure.sqlite.repositories import (
    SqliteAlarmStore,
    SqliteAuditStore,
    SqliteExperimentStore,
    SqliteRecipeStore,
)

RECIPE_STEPS = [
    {"step_no": 1, "target_temp_c": 900.0, "ramp_rate_cpm": 10.0, "hold_seconds": 1, "n2_lpm": 8.0, "h2_lpm": 1.0, "co_lpm": 0.8, "notes": ""},
    {"step_no": 2, "target_temp_c": 950.0, "ramp_rate_cpm": 10.0, "hold_seconds": 1, "n2_lpm": 6.0, "h2_lpm": 2.0, "co_lpm": 0.5, "notes": ""},
]


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

    def __init__(self, *, run_control: bool = True, program: bool = True) -> None:
        self.capabilities = GatewayCapabilities(
            temperature_program=program, temperature_setpoint=True, run_control_word=run_control,
            alarm_words=run_control, multi_device_status=True, balance_tare=True,
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
        self.snapshot = DeviceSnapshot(900.0, 100.0, 0.0, 8.0, 1.0, 0.8, 0)
        self.tare_calls = 0
        self.mfc_writes: list[tuple[int, float]] = []
        self.lock = threading.Lock()

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

    def apply_gas_setpoints(self, *, n2_lpm: float, h2_lpm: float, co_lpm: float) -> dict[str, float]:
        if self.fail_gas:
            raise RuntimeError("mfc write failed")
        values = {"n2_lpm": n2_lpm, "h2_lpm": h2_lpm, "co_lpm": co_lpm}
        with self.lock:
            self.gas_writes.append(values)
        return values

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
        return MultiDeviceSnapshot((self.snapshot.temperature_c,), {1: 1.0, 2: 8.0, 3: 0.8}, {1: 1.0, 2: 8.0, 3: 0.8},
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
        "alarms": SqliteAlarmStore(db), "audit": SqliteAuditStore(db),
    }


@pytest.fixture
def recipe_id(stores) -> int:
    return stores["recipes"].create_recipe("标准流程", RECIPE_STEPS)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


def make_runner(stores, gateway, clock, **overrides) -> ExperimentRunner:
    settings = RunnerSettings(
        poll_interval_ms=overrides.pop("poll_interval_ms", 20), acquisition_batch_size=overrides.pop("batch", 2),
        temperature_mode=overrides.pop("temperature_mode", TemperatureControlMode.PROGRAM),
        default_gas_mode=overrides.pop("gas_mode", GasControlMode.AUTO),
        degraded_fault_seconds=overrides.pop("degraded_fault_seconds", 30), **overrides,
    )
    return ExperimentRunner(settings=settings, recipes=stores["recipes"], experiments=stores["experiments"],
                            alarms=stores["alarms"], audit=stores["audit"], gateway=gateway, clock=clock)


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
