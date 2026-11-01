"""Run lifecycle: start/pause/resume/stop, alarms, control modes, terminal cleanup (no threads needed)."""

from __future__ import annotations

import time

import pytest

from rka_desktop.application.experiment_runner import RunConflict, RunStateError
from rka_desktop.domain.control import ConfirmationRequired, TemperatureControlMode
from rka_desktop.domain.entities import DeviceSnapshot
from rka_desktop.domain.recipe import RecipeValidationError
from tests.conftest import FakeGateway


def snap(temp=900.0, weight=100.0, alarm=0, interlock=0, run_word=0, estop=0) -> DeviceSnapshot:
    return DeviceSnapshot(temp, weight, 0.0, 8.0, 1.0, 0.8, alarm, interlock, run_word, estop)


def wait_status(runner, status, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runner.snapshot()["status"] == status:
            return runner.snapshot()
        time.sleep(0.01)
    pytest.fail(f"runner did not reach {status}: {runner.snapshot()['status']}")


def test_start_downloads_program_applies_gas_and_runs(runner_factory, recipe_id, stores):
    runner, gateway = runner_factory()
    state = runner.start(recipe_id)
    assert state["status"] == "running"
    assert state["gas_mode"] == "auto"
    assert state["temperature_mode"] == "program"
    assert len(gateway.programs) == 1 and len(gateway.programs[0]) == 2
    assert gateway.gas_writes == [{"n2_lpm": 8.0, "h2_lpm": 1.0, "co_lpm": 0.8}]
    assert gateway.temp_writes == []  # program mode never writes SV during the run
    assert gateway.commands == ["start"]
    assert state["allowed"]["pause"] and not state["allowed"]["start"]
    detail = stores["experiments"].get_experiment_detail(state["experiment_id"])
    assert detail["status"] == "RUNNING" and detail["recipe_id"] == recipe_id
    with pytest.raises(RunConflict):
        runner.start(recipe_id)
    runner.stop()
    final = wait_status(runner, "stopped")
    assert final["allowed"]["start"]
    assert stores["experiments"].get_experiment_detail(state["experiment_id"])["status"] == "STOPPED"
    assert "stop" in gateway.commands


def test_setpoint_mode_writes_temperature_each_step(runner_factory, recipe_id, clock):
    runner, gateway = runner_factory(temperature_mode=TemperatureControlMode.SETPOINT)
    runner.start(recipe_id)
    assert gateway.programs == []
    assert gateway.temp_writes == [{"temperature_c": 900.0, "ramp_rate_cpm": 10.0}]
    runner.stop()
    wait_status(runner, "stopped")


def test_program_mode_requires_capability(runner_factory, recipe_id):
    runner, _ = runner_factory(FakeGateway(program=False))
    with pytest.raises(RunStateError):
        runner.start(recipe_id)


def test_measurements_drive_steps_and_completion(runner_factory, recipe_id, stores, clock):
    runner, gateway = runner_factory(poll_interval_ms=60_000)  # the thread sleeps; we drive snapshots by hand
    state = runner.start(recipe_id)
    exp_id = state["experiment_id"]
    runner.process_snapshot(snap(900.0), sampled_at=clock.now())
    clock.advance(2)
    runner.process_snapshot(snap(901.0), sampled_at=clock.now())  # hold 1 s satisfied -> step 2
    assert runner.snapshot()["current_step_no"] == 2
    assert gateway.gas_writes[-1] == {"n2_lpm": 6.0, "h2_lpm": 2.0, "co_lpm": 0.5}
    clock.advance(2)
    runner.process_snapshot(snap(950.0), sampled_at=clock.now())
    clock.advance(2)
    runner.process_snapshot(snap(951.0), sampled_at=clock.now())
    final = wait_status(runner, "completed")
    assert final["engine_state"] == "COMPLETED"
    assert stores["experiments"].get_experiment_detail(exp_id)["status"] == "COMPLETED"
    # 4 hand-driven snapshots plus whatever the acquisition thread read before its first sleep
    assert stores["experiments"].count_measurements(exp_id) >= 4
    assert gateway.commands[-1] == "stop"
    # a late stop request must not rewrite the terminal state
    with pytest.raises(RunStateError):
        runner.stop()
    assert runner.snapshot()["status"] == "completed"


def test_alarm_interrupts_and_blocks_resume_until_cleared_and_acked(runner_factory, recipe_id, stores, clock):
    runner, gateway = runner_factory(poll_interval_ms=60_000)
    state = runner.start(recipe_id)
    exp_id = state["experiment_id"]
    runner.process_snapshot(snap(alarm=0x0001), sampled_at=clock.now())
    s = runner.snapshot()
    assert s["engine_state"] == "INTERRUPTED" and s["status"] == "interrupted"
    assert "报警处理中" in s["status_text"]
    assert gateway.commands[-1] == "pause"
    assert stores["experiments"].get_experiment_detail(exp_id)["status"] == "INTERRUPTED"
    assert stores["alarms"].list_unacknowledged_alarms(exp_id)
    with pytest.raises(RunStateError):
        runner.resume()
    runner.process_snapshot(snap(alarm=0), sampled_at=clock.now())
    with pytest.raises(RunStateError, match="未确认报警"):
        runner.resume()
    assert runner.snapshot()["allowed"]["ack_alarm"]
    runner.acknowledge_alarm()
    assert runner.snapshot()["allowed"]["resume"]
    runner.resume()
    assert runner.snapshot()["status"] == "running"
    runner.stop()
    wait_status(runner, "stopped")


def test_interlock_reset_requires_confirmation_path_and_resettable_word(runner_factory, recipe_id, clock):
    runner, gateway = runner_factory(poll_interval_ms=60_000)
    runner.start(recipe_id)
    runner.process_snapshot(snap(interlock=0x0002), sampled_at=clock.now())
    s = runner.snapshot()
    assert s["engine_state"] == "INTERRUPTED" and s["interlock"]["resettable"]
    assert s["allowed"]["reset_interlock"]
    runner.reset_interlock()
    assert gateway.commands[-1] == "reset"
    runner.process_snapshot(snap(interlock=0x0010, estop=1), sampled_at=clock.now())
    assert not runner.snapshot()["allowed"]["reset_interlock"]
    with pytest.raises(RunStateError):
        runner.reset_interlock()
    runner.stop()
    wait_status(runner, "stopped")


def test_setpoint_failure_faults_run(runner_factory, recipe_id, stores):
    gateway = FakeGateway()
    gateway.fail_gas = True
    runner, _ = runner_factory(gateway)
    state = runner.start(recipe_id)
    assert state["status"] == "faulted"
    assert "设定下发失败" in state["error"]
    assert stores["experiments"].get_experiment_detail(state["experiment_id"])["status"] == "FAULTED"
    assert runner.snapshot()["allowed"]["start"]


def test_acquisition_error_faults_run_and_flushes(runner_factory, recipe_id, stores):
    gateway = FakeGateway()
    runner, _ = runner_factory(gateway, poll_interval_ms=20)
    state = runner.start(recipe_id)
    time.sleep(0.1)
    gateway.fail_read = True
    final = wait_status(runner, "faulted")
    assert "采集异常" in final["error"]
    assert stores["experiments"].get_experiment_detail(state["experiment_id"])["status"] == "FAULTED"
    assert stores["experiments"].count_measurements(state["experiment_id"]) >= 1


def test_degraded_device_faults_after_deadline(runner_factory, recipe_id, clock):
    gateway = FakeGateway()
    gateway.degraded = ("temp",)  # set before start so the acquisition thread never reports a recovery
    runner, _ = runner_factory(gateway, poll_interval_ms=60_000, degraded_fault_seconds=10)
    runner.start(recipe_id)
    runner.process_snapshot(snap(), degraded=("temp",), sampled_at=clock.now())
    assert runner.snapshot()["degraded_devices"] == ["temp"]
    clock.advance(5)
    runner.process_snapshot(snap(), degraded=("temp",), sampled_at=clock.now())
    assert runner.snapshot()["status"] == "running"
    clock.advance(6)
    runner.process_snapshot(snap(), degraded=("temp",), sampled_at=clock.now())
    final = wait_status(runner, "faulted")
    assert "temp" in final["error"]


def test_gas_mode_switch_needs_confirmation_and_manual_setpoints(runner_factory, recipe_id, stores):
    runner, gateway = runner_factory(poll_interval_ms=60_000)
    runner.start(recipe_id)
    with pytest.raises(ConfirmationRequired):
        runner.set_gas_mode("manual", confirmed=False)
    with pytest.raises(RunStateError):
        runner.set_manual_gas(n2_lpm=1, h2_lpm=1, co_lpm=1, confirmed=True)
    state = runner.set_gas_mode("manual", confirmed=True)
    assert state["gas_mode"] == "manual" and state["allowed"]["manual_gas"]
    with pytest.raises(ConfirmationRequired):
        runner.set_manual_gas(n2_lpm=2.0, h2_lpm=0.5, co_lpm=0.0, confirmed=False)
    with pytest.raises(RecipeValidationError):
        runner.set_manual_gas(n2_lpm=-1, h2_lpm=0.5, co_lpm=0.0, confirmed=True)
    state = runner.set_manual_gas(n2_lpm=2.0, h2_lpm=0.5, co_lpm=0.0, confirmed=True)
    assert state["manual_gas"] == {"n2_lpm": 2.0, "h2_lpm": 0.5, "co_lpm": 0.0}
    assert gateway.gas_writes[-1] == {"n2_lpm": 2.0, "h2_lpm": 0.5, "co_lpm": 0.0}
    # switching back to auto re-applies the recipe step
    runner.set_gas_mode("auto", confirmed=True)
    assert gateway.gas_writes[-1] == {"n2_lpm": 8.0, "h2_lpm": 1.0, "co_lpm": 0.8}
    actions = [row["action"] for row in stores["audit"].list_audit_logs(limit=50)]
    assert "GAS_MODE_SWITCH" in actions and "MANUAL_GAS_SET" in actions
    runner.stop()
    wait_status(runner, "stopped")


def test_pause_resume_and_paused_measurements_do_not_advance(runner_factory, recipe_id, clock):
    runner, gateway = runner_factory(poll_interval_ms=60_000)
    runner.start(recipe_id)
    runner.pause()
    s = runner.snapshot()
    assert s["status"] == "paused" and s["allowed"]["resume"] and not s["allowed"]["pause"]
    clock.advance(10)
    runner.process_snapshot(snap(950.0), sampled_at=clock.now())
    assert runner.snapshot()["current_step_no"] == 1
    runner.resume()
    assert gateway.commands[-1] == "resume"
    runner.stop()
    wait_status(runner, "stopped")


def test_close_stops_active_run_and_releases_gateway(runner_factory, recipe_id, stores):
    runner, gateway = runner_factory(poll_interval_ms=20)
    state = runner.start(recipe_id)
    runner.close(timeout=5)
    assert runner.snapshot()["status"] == "stopped"
    assert stores["experiments"].get_experiment_detail(state["experiment_id"])["status"] == "STOPPED"
    assert gateway.connected is False
    with pytest.raises(RunConflict):
        runner.start(recipe_id)


def test_start_fails_when_device_connect_fails(runner_factory, recipe_id):
    gateway = FakeGateway()
    gateway.connect_result = False
    runner, _ = runner_factory(gateway)
    with pytest.raises(RunStateError, match="设备连接失败"):
        runner.start(recipe_id)
    assert runner.snapshot()["status"] == "idle"
