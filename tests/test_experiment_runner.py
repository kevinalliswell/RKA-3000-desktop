"""Run lifecycle: preflight, start, disposal on every exit, alarms, control modes, terminal cleanup."""

from __future__ import annotations

import time

import pytest

from rka_desktop.application.experiment_runner import PreflightFailed, RunConflict, RunStateError
from rka_desktop.domain.control import ConfirmationRequired, TemperatureControlMode
from rka_desktop.domain.entities import DeviceSnapshot
from rka_desktop.domain.recipe import RecipeValidationError
from tests.conftest import RECIPE_META, RECIPE_STEPS, FakeGateway, start_payload


def snap(temp=900.0, weight=100.0, alarm=0, interlock=0, run_word=0, estop=0, flows=None) -> DeviceSnapshot:
    flows = flows or {"N2": 3.0, "H2": 1.0, "CO": 0.8}
    return DeviceSnapshot(temp, weight, 0.0, flows.get("N2", 0.0), flows.get("H2", 0.0), flows.get("CO", 0.0), alarm,
                          interlock, run_word, estop, flows_lpm=dict(flows))


def wait_status(runner, status, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if runner.snapshot()["status"] == status:
            return runner.snapshot()
        time.sleep(0.01)
    pytest.fail(f"runner did not reach {status}: {runner.snapshot()['status']}")


def finish_purge(runner, gateway, clock, seconds=3.0):
    """Cool the furnace below the safe temperature and let the purge time pass."""
    gateway.snapshot = snap(150.0, flows={"N2": 4.0})
    clock.advance(seconds)
    runner.process_snapshot(gateway.snapshot, sampled_at=clock.now())


def test_preflight_lists_every_blocking_condition(runner_factory, recipe_id, stores):
    runner, _ = runner_factory()
    result = runner.preflight({"recipe_id": recipe_id})
    assert not result["ready"]
    failing = {c["key"] for c in result["checks"] if c["blocking"] and not c["ok"]}
    assert failing == {"sample", "checklist"}
    assert result["assessment"]["runnable"] and result["readings"]["connected"]
    ready = runner.preflight(start_payload(recipe_id))
    assert ready["ready"] and ready["mass_deviation_pct"] == 0.0
    with pytest.raises(PreflightFailed) as excinfo:
        runner.start(start_payload(recipe_id, checklist={"serial": True}))
    assert "现场检查" in str(excinfo.value) and excinfo.value.detail["checks"]
    assert runner.snapshot()["status"] == "idle"
    with pytest.raises(LookupError):
        runner.start(start_payload(999))


def test_non_runnable_recipe_and_pending_review_block_start(runner_factory, stores, clock):
    bad = stores["recipes"].create_recipe("只有一段", [{"target_temp_c": 900, "ramp_rate_cpm": 10, "hold_seconds": 5,
                                                    "n2_lpm": 3, "h2_lpm": 1, "co_lpm": 0}], RECIPE_META)
    runner, gateway = runner_factory(poll_interval_ms=60_000)
    result = runner.preflight(start_payload(bad))
    assert not result["ready"] and next(c for c in result["checks"] if c["key"] == "recipe")["ok"] is False
    # An experiment that ended but is not archived blocks the next one.
    good = stores["recipes"].create_recipe("标准流程", RECIPE_STEPS,
                                           RECIPE_META)
    runner.start(start_payload(good))
    runner.stop("测试结束")
    finish_purge(runner, gateway, clock)
    wait_status(runner, "stopped")
    blocked = runner.preflight(start_payload(good))
    archived = next(c for c in blocked["checks"] if c["key"] == "archived")
    assert not blocked["ready"] and not archived["ok"] and "RKA-" in archived["detail"]


def test_start_freezes_snapshots_downloads_program_and_applies_first_step(runner_factory, recipe_id, stores):
    runner, gateway = runner_factory(poll_interval_ms=60_000)
    state = runner.start(start_payload(recipe_id))
    assert state["status"] == "running" and state["gas_mode"] == "auto" and state["temperature_mode"] == "program"
    assert len(gateway.programs) == 1 and len(gateway.programs[0]) == 3
    assert gateway.gas_writes[0]["N2"] == 4.0 and gateway.gas_writes[0]["H2"] == 0.0
    assert gateway.temp_writes == []  # program mode never writes SV during the run
    assert gateway.commands == ["start"]
    assert not state["allowed"]["pause"] and state["blocked"]["pause"]  # pause would desync the instrument program
    assert state["experiment"]["code"].startswith("RKA-") and state["experiment"]["operator"] == "实验员 A"
    assert [s["state"] for s in state["steps"]] == ["active", "pending", "pending"]
    detail = stores["experiments"].get_experiment_detail(state["experiment_id"])
    assert detail["status"] == "RUNNING" and detail["recipe_version"] == 1 and detail["limits_version"] == 1
    assert detail["recipe_snapshot"]["steps"][1]["co_lpm"] == 0.8 and detail["checklist"]["interlock"] is True
    assert detail["sample_name"] == "球团矿 A-19" and detail["balance_mass_g"] == 100.0
    with pytest.raises(RunConflict):
        runner.start(start_payload(recipe_id))


def test_normal_path_enters_purge_at_last_step_and_waits_for_cooling(runner_factory, recipe_id, stores, clock):
    runner, gateway = runner_factory(FakeGateway(run_control=False), poll_interval_ms=60_000)
    state = runner.start(start_payload(recipe_id))
    exp_id = state["experiment_id"]
    runner.process_snapshot(snap(150.0, flows={"N2": 4.0}), sampled_at=clock.now())
    clock.advance(2.5)
    runner.process_snapshot(snap(150.0, flows={"N2": 4.0}), sampled_at=clock.now())  # step 1 hold done -> reaction step
    s = runner.snapshot()
    assert s["current_step_no"] == 2 and gateway.last_gas == {"N2": 3.0, "H2": 1.0, "CO": 0.8}
    assert stores["experiments"].get_experiment_detail(exp_id)["reaction_started_at"]
    runner.process_snapshot(snap(900.0, weight=99.0), sampled_at=clock.now())
    clock.advance(3.5)
    runner.process_snapshot(snap(900.0, weight=98.0), sampled_at=clock.now())  # reaction done -> last (inert) step
    s = runner.snapshot()
    assert s["status"] == "purging" and s["end_reason"] == "completed"
    assert s["purge"]["heating"] == "program_last_step" and s["purge"]["required_s"] == 2.0
    assert gateway.last_gas == {"N2": 4.0}
    assert s["steps"][2]["state"] == "active" and s["live"]["delta_m_g"] == pytest.approx(-2.0)
    assert not s["allowed"]["manual_gas"] and not s["allowed"]["stop"] and s["allowed"]["emergency"]
    # Purge time passed but still hot: keep purging.
    clock.advance(5)
    runner.process_snapshot(snap(450.0, flows={"N2": 4.0}), sampled_at=clock.now())
    assert runner.snapshot()["status"] == "purging"
    finish_purge(runner, gateway, clock, seconds=1)
    final = wait_status(runner, "completed")
    assert final["allowed"]["start"] and [s["state"] for s in final["steps"]] == ["done", "done", "done"]
    detail = stores["experiments"].get_experiment_detail(exp_id)
    assert detail["status"] == "COMPLETED" and detail["review_state"] == "pending" and detail["end_reason"] == "completed"
    assert detail["final_temperature_c"] == 150.0 and detail["purge_done_s"] >= 2 and detail["reaction_ended_at"]
    phases = {row["phase"] for row in stores["experiments"].fetch_measurements(exp_id)}
    assert phases == {"run", "purge"}
    with pytest.raises(RunStateError):
        runner.stop()  # a late stop must not rewrite the terminal state
    assert runner.snapshot()["status"] == "completed"


def test_operator_stop_purges_with_recipe_purge_flow(runner_factory, recipe_id, stores, clock):
    runner, gateway = runner_factory(poll_interval_ms=60_000)
    state = runner.start(start_payload(recipe_id))
    s = runner.stop("样品破裂")
    assert s["status"] == "purging" and s["end_reason"] == "operator_stop"
    assert gateway.last_gas == {"N2": 4.0} and gateway.commands[-1] == "stop"
    assert s["purge"]["heating"] == "plc_stop"
    assert [x["state"] for x in s["steps"]] == ["interrupted", "skipped", "skipped"]
    assert runner.stop()["status"] == "purging"  # idempotent
    finish_purge(runner, gateway, clock)
    wait_status(runner, "stopped")
    detail = stores["experiments"].get_experiment_detail(state["experiment_id"])
    assert detail["status"] == "STOPPED" and detail["end_detail"] == "样品破裂"


def test_emergency_stop_needs_no_confirmation_and_latches(runner_factory, recipe_id, stores, clock):
    runner, gateway = runner_factory(FakeGateway(run_control=False), poll_interval_ms=60_000,
                                     temperature_mode=TemperatureControlMode.SETPOINT)
    runner.start(start_payload(recipe_id))
    s = runner.emergency_stop()
    assert s["status"] == "purging" and s["emergency"] and not s["allowed"]["emergency"]
    assert gateway.last_gas == {"N2": 4.0}
    assert gateway.temp_writes[-1]["temperature_c"] == 0.0 and s["purge"]["heating"] == "setpoint_written"
    with pytest.raises(RunStateError):
        runner.set_gas_mode("manual", confirmed=True)
    actions = [row["action"] for row in stores["audit"].list_audit_logs(limit=20)]
    assert "EMERGENCY_STOP" in actions
    finish_purge(runner, gateway, clock)
    wait_status(runner, "stopped")


def test_program_mode_abnormal_exit_asks_for_manual_heating_stop(runner_factory, recipe_id, clock):
    runner, gateway = runner_factory(FakeGateway(run_control=False), poll_interval_ms=60_000)
    runner.start(start_payload(recipe_id))
    s = runner.stop()
    assert s["purge"]["heating"] == "manual_required" and "温控器面板" in s["purge"]["heating_text"]
    assert gateway.temp_writes == []
    finish_purge(runner, gateway, clock)


def test_software_alarm_disposes_and_blocks_until_acknowledged(runner_factory, recipe_id, stores, clock):
    runner, gateway = runner_factory(poll_interval_ms=60_000)
    state = runner.start(start_payload(recipe_id))
    runner.process_snapshot(snap(200.0, flows={"N2": 4.0}), sampled_at=clock.now())  # target 150 + 30 exceeded
    s = runner.snapshot()
    assert s["status"] == "purging" and s["end_reason"] == "alarm" and "炉温超限" in s["end_detail"]
    assert s["pending_alarms"][0]["code"] == "SW-OVERTEMP" and s["allowed"]["ack_alarm"]
    with pytest.raises(RunStateError, match="处理说明"):
        runner.acknowledge_alarm(s["pending_alarms"][0]["id"], note="")
    runner.acknowledge_alarm(s["pending_alarms"][0]["id"], note="热电偶松动，已紧固")
    alarm = stores["alarms"].list_alarm_history(state["experiment_id"])[0]
    assert alarm["ack_note"] == "热电偶松动，已紧固" and alarm["acknowledged_by"] == "实验员 A"
    finish_purge(runner, gateway, clock)
    wait_status(runner, "stopped")


def test_plc_alarm_word_interrupts_and_blocks_resume_until_cleared_and_acked(runner_factory, recipe_id, stores, clock):
    runner, gateway = runner_factory(poll_interval_ms=60_000)
    state = runner.start(start_payload(recipe_id))
    exp_id = state["experiment_id"]
    runner.process_snapshot(snap(150.0, alarm=0x0001, flows={"N2": 4.0}), sampled_at=clock.now())
    s = runner.snapshot()
    assert s["engine_state"] == "INTERRUPTED" and s["status"] == "interrupted"
    assert gateway.commands[-1] == "pause"
    assert stores["experiments"].get_experiment_detail(exp_id)["status"] == "INTERRUPTED"
    with pytest.raises(RunStateError):
        runner.resume()
    runner.process_snapshot(snap(150.0, alarm=0, flows={"N2": 4.0}), sampled_at=clock.now())
    with pytest.raises(RunStateError, match="未确认报警"):
        runner.resume()
    runner.acknowledge_alarm(note="已排除超温")
    assert runner.snapshot()["allowed"]["resume"]
    assert runner.resume()["status"] == "running"
    runner.stop()


def test_interlock_reset_requires_resettable_word(runner_factory, recipe_id, clock):
    runner, gateway = runner_factory(poll_interval_ms=60_000)
    runner.start(start_payload(recipe_id))
    runner.process_snapshot(snap(150.0, interlock=0x0002, flows={"N2": 4.0}), sampled_at=clock.now())
    s = runner.snapshot()
    assert s["engine_state"] == "INTERRUPTED" and s["allowed"]["reset_interlock"]
    runner.reset_interlock()
    assert gateway.commands[-1] == "reset"
    runner.process_snapshot(snap(150.0, interlock=0x0010, estop=1, flows={"N2": 4.0}), sampled_at=clock.now())
    assert not runner.snapshot()["allowed"]["reset_interlock"]
    with pytest.raises(RunStateError):
        runner.reset_interlock()
    runner.stop()


def test_setpoint_failure_at_start_ends_run_for_review(runner_factory, recipe_id, stores):
    gateway = FakeGateway()
    gateway.fail_gas = True
    runner, _ = runner_factory(gateway)
    state = runner.start(start_payload(recipe_id))
    assert state["status"] == "faulted" and "设定下发失败" in state["error"]
    detail = stores["experiments"].get_experiment_detail(state["experiment_id"])
    assert detail["status"] == "FAULTED" and detail["review_state"] == "pending"
    assert runner.snapshot()["allowed"]["start"]
    alarms = {a["code"] for a in stores["alarms"].list_unacknowledged_alarms()}
    assert "SW-PURGE-FAILED" in alarms  # the purge set-point attempt failed too, and that is recorded


def test_acquisition_error_ends_run_and_flushes(runner_factory, recipe_id, stores):
    gateway = FakeGateway()
    runner, _ = runner_factory(gateway, poll_interval_ms=20)
    state = runner.start(start_payload(recipe_id))
    time.sleep(0.1)
    gateway.fail_read = True
    final = wait_status(runner, "faulted")
    assert "采集异常" in final["error"]
    detail = stores["experiments"].get_experiment_detail(state["experiment_id"])
    assert detail["status"] == "FAULTED" and detail["end_reason"] == "fault"
    assert stores["experiments"].count_measurements(state["experiment_id"]) >= 1


def test_stale_device_never_ends_the_run_but_blocks_manual_gas_and_skips_storage(runner_factory, recipe_id, stores, clock):
    gateway = FakeGateway()
    runner, _ = runner_factory(gateway, poll_interval_ms=60_000, degraded_fault_seconds=10)
    state = runner.start(start_payload(recipe_id))
    deadline = time.monotonic() + 5
    while runner.snapshot()["latest"] is None and time.monotonic() < deadline:
        time.sleep(0.005)  # let the acquisition thread finish its first (healthy) read
    gateway.degraded = ("balance",)
    runner.set_gas_mode("manual", confirmed=True)
    runner._flush_measurements()
    before = stores["experiments"].count_measurements(state["experiment_id"])
    for _ in range(4):
        clock.advance(60)  # stale means > 3 sampling periods (3 x 60 s here)
        runner.process_snapshot(snap(150.0, flows={"N2": 4.0}), degraded=("balance",), sampled_at=clock.now())
    s = runner.snapshot()
    assert s["status"] == "running" and s["stale_devices"] == ["balance"]
    assert s["live"]["weight_g"] is None and not s["allowed"]["manual_gas"]
    assert [a["code"] for a in s["pending_alarms"]] == ["SW-STALE-BALANCE"]
    runner._flush_measurements()
    assert stores["experiments"].count_measurements(state["experiment_id"]) == before
    runner.stop()


def test_manual_gas_three_state_command_with_readback(runner_factory, recipe_id, stores):
    runner, gateway = runner_factory(poll_interval_ms=60_000)
    runner.start(start_payload(recipe_id))
    with pytest.raises(ConfirmationRequired):
        runner.set_gas_mode("manual", confirmed=False)
    with pytest.raises(RunStateError):
        runner.set_manual_gas({"N2": 1}, reason="测试", confirmed=True)
    assert runner.set_gas_mode("manual", confirmed=True)["allowed"]["manual_gas"]
    with pytest.raises(ConfirmationRequired):
        runner.set_manual_gas({"N2": 2.0}, reason="测试", confirmed=False)
    with pytest.raises(RunStateError, match="原因"):
        runner.set_manual_gas({"N2": 2.0}, reason="", confirmed=True)
    with pytest.raises(RecipeValidationError, match="不允许"):
        runner.set_manual_gas({"N2": 2.0, "O2": 0.5}, reason="测试", confirmed=True)
    with pytest.raises(RecipeValidationError, match="使用上限"):
        runner.set_manual_gas({"N2": 2.0, "H2": 5.5}, reason="测试", confirmed=True)
    with pytest.raises(RecipeValidationError):
        runner.set_manual_gas({"N2": -1}, reason="测试", confirmed=True)
    state = runner.set_manual_gas({"N2": 3.0, "H2": 1.2, "CO": 0.6}, reason="微调还原势", confirmed=True)
    command = state["last_command"]
    assert command["state"] == "applied" and [s["code"] for s in command["steps"]] == ["accepted", "verified", "applied"]
    assert gateway.last_gas == {"N2": 3.0, "H2": 1.2, "CO": 0.6} and state["manual_gas"]["H2"] == 1.2
    # Readback disagrees: the command fails and the recipe values are restored.
    gateway.readback_override = {"N2": 3.0, "H2": 0.0, "CO": 0.6}
    state = runner.set_manual_gas({"N2": 3.0, "H2": 1.5, "CO": 0.6}, reason="再次微调", confirmed=True)
    command = state["last_command"]
    assert command["state"] == "failed" and [s["code"] for s in command["steps"]] == ["accepted", "mismatch", "reverted"]
    assert gateway.last_gas == {"N2": 4.0}  # current step (inert purge) flows
    gateway.readback_override = None
    runner.set_gas_mode("auto", confirmed=True)
    assert gateway.last_gas == {"N2": 4.0}
    audit = stores["audit"].list_audit_logs(limit=50)
    manual = next(row for row in audit if row["action"] == "MANUAL_GAS_SET")
    assert manual["reason"] == "微调还原势" and manual["result"] == "accepted,verified,applied"
    assert "GAS_MODE_SWITCH" in {row["action"] for row in audit}
    runner.stop()


def test_manual_gas_blocked_while_alarm_unacknowledged(runner_factory, recipe_id, stores):
    runner, _ = runner_factory(poll_interval_ms=60_000)
    state = runner.start(start_payload(recipe_id))
    runner.set_gas_mode("manual", confirmed=True)
    stores["alarms"].create_alarm(state["experiment_id"], "SW-MFC-DEV-H2", "WARNING", "H₂ 偏差")
    s = runner.snapshot()
    assert not s["allowed"]["manual_gas"] and "报警待确认" in s["blocked"]["manual_gas"]
    with pytest.raises(RunStateError, match="报警"):
        runner.set_manual_gas({"N2": 3.0}, reason="测试", confirmed=True)
    runner.stop()


def test_pause_only_in_setpoint_mode(runner_factory, recipe_id, clock):
    runner, gateway = runner_factory(poll_interval_ms=60_000)
    runner.start(start_payload(recipe_id))
    with pytest.raises(RunStateError, match="程序模式"):
        runner.pause()
    runner.stop()
    finish_purge(runner, gateway, clock)
    wait_status(runner, "stopped")


def test_setpoint_mode_pause_resume_and_paused_measurements_do_not_advance(runner_factory, stores, clock):
    recipe = stores["recipes"].create_recipe("标准流程", RECIPE_STEPS, RECIPE_META)
    runner, gateway = runner_factory(poll_interval_ms=60_000, temperature_mode=TemperatureControlMode.SETPOINT)
    runner.start(start_payload(recipe))
    assert gateway.programs == [] and gateway.temp_writes[0] == {"temperature_c": 150.0, "ramp_rate_cpm": 10.0}
    s = runner.pause()
    assert s["status"] == "paused" and s["allowed"]["resume"] and not s["allowed"]["pause"]
    clock.advance(10)
    runner.process_snapshot(snap(150.0, flows={"N2": 4.0}), sampled_at=clock.now())
    assert runner.snapshot()["current_step_no"] == 1
    runner.resume()
    assert gateway.commands[-1] == "resume"
    runner.stop()


def test_close_disposes_active_run_and_releases_gateway(runner_factory, recipe_id, stores):
    runner, gateway = runner_factory(poll_interval_ms=20)
    state = runner.start(start_payload(recipe_id))
    runner.close(timeout=5)
    assert runner.snapshot()["status"] == "stopped"
    detail = stores["experiments"].get_experiment_detail(state["experiment_id"])
    assert detail["status"] == "STOPPED" and detail["end_reason"] == "shutdown" and detail["review_state"] == "pending"
    assert gateway.last_gas == {"N2": 4.0}
    assert gateway.connected is False
    with pytest.raises(RunConflict):
        runner.start(start_payload(recipe_id))


def test_start_fails_when_device_connect_fails(runner_factory, recipe_id):
    gateway = FakeGateway()
    gateway.connect_result = False
    runner, _ = runner_factory(gateway)
    with pytest.raises(PreflightFailed, match="设备回读新鲜"):
        runner.start(start_payload(recipe_id))
    assert runner.snapshot()["status"] == "idle"


def test_program_mode_requires_capability(runner_factory, recipe_id):
    runner, _ = runner_factory(FakeGateway(program=False))
    with pytest.raises(PreflightFailed, match="温度控制方式"):
        runner.start(start_payload(recipe_id))


def test_program_mode_follows_instrument_segment(runner_factory, recipe_id, stores, clock):
    runner, gateway = runner_factory(FakeGateway(run_control=False), poll_interval_ms=60_000)
    runner.start(start_payload(recipe_id))

    def at_segment(segment, temp=150.0, flows=None):
        snapshot = snap(temp, flows=flows or {"N2": 4.0})
        snapshot.program_segment = segment
        clock.advance(1)
        runner.process_snapshot(snapshot, sampled_at=clock.now())

    clock.advance(30)  # far beyond the step-1 hold: without the instrument the engine would have moved on
    at_segment(2)
    assert runner.snapshot()["current_step_no"] == 1 and "跟随仪表程序" in runner.snapshot()["status_text"]
    at_segment(3, temp=300.0)  # instrument starts step 2's ramp segment -> reaction gas now
    state = runner.snapshot()
    assert state["current_step_no"] == 2 and state["program_segment"] == 3
    assert gateway.last_gas == {"N2": 3.0, "H2": 1.0, "CO": 0.8}
    at_segment(1)  # a lower segment (program restarted / idle) never moves the run backwards
    assert runner.snapshot()["current_step_no"] == 2
    at_segment(5, temp=300.0)  # instrument reached the last step -> safe disposal
    assert runner.snapshot()["status"] == "purging" and runner.snapshot()["end_reason"] == "completed"
    finish_purge(runner, gateway, clock)
    wait_status(runner, "completed")


def test_program_mode_without_segment_does_not_stall_when_furnace_cools_early(runner_factory, recipe_id, clock):
    runner, gateway = runner_factory(FakeGateway(run_control=False), poll_interval_ms=60_000)
    runner.start(start_payload(recipe_id))
    runner.process_snapshot(snap(150.0, flows={"N2": 4.0}), sampled_at=clock.now())
    clock.advance(2.5)
    runner.process_snapshot(snap(150.0, flows={"N2": 4.0}), sampled_at=clock.now())
    assert runner.snapshot()["current_step_no"] == 2
    runner.process_snapshot(snap(900.0), sampled_at=clock.now())  # step 2 reaches its target
    clock.advance(2)
    runner.process_snapshot(snap(600.0), sampled_at=clock.now())  # the instrument already cools toward step 3
    clock.advance(2)
    runner.process_snapshot(snap(400.0), sampled_at=clock.now())
    assert runner.snapshot()["status"] == "purging"  # hold counted by time, not stuck in "heating"
    finish_purge(runner, gateway, clock)


def test_failed_purge_set_points_do_not_count_as_purge_time(runner_factory, recipe_id, stores, clock):
    runner, gateway = runner_factory(FakeGateway(run_control=False), poll_interval_ms=60_000)
    state = runner.start(start_payload(recipe_id))
    gateway.fail_gas = True
    s = runner.stop("测试吹扫失败")
    assert s["purge"]["apply_error"] and s["purge"]["elapsed_s"] == 0
    finish_purge(runner, gateway, clock, seconds=3)  # cool, but nothing was purged
    assert runner.snapshot()["status"] == "purging" and runner.snapshot()["purge"]["elapsed_s"] == 0
    clock.advance(5)
    runner.process_snapshot(gateway.snapshot, sampled_at=clock.now())  # retry still fails
    assert runner.snapshot()["status"] == "purging"
    gateway.fail_gas = False
    clock.advance(5)
    runner.process_snapshot(gateway.snapshot, sampled_at=clock.now())  # retry succeeds: purge starts now
    assert gateway.last_gas == {"N2": 4.0} and runner.snapshot()["purge"]["apply_error"] is None
    finish_purge(runner, gateway, clock, seconds=2.5)
    wait_status(runner, "stopped")
    detail = stores["experiments"].get_experiment_detail(state["experiment_id"])
    assert 2 <= detail["purge_done_s"] < 4


def test_cooling_between_reaction_steps_is_not_over_temperature(runner_factory, stores, clock):
    steps = [
        {"name": "惰性置换", "target_temp_c": 150, "ramp_rate_cpm": 10, "hold_seconds": 2, "n2_lpm": 4},
        {"name": "高温还原", "target_temp_c": 900, "ramp_rate_cpm": 10, "hold_seconds": 3, "n2_lpm": 3, "co_lpm": 0.8},
        {"name": "低温还原", "target_temp_c": 500, "ramp_rate_cpm": 10, "hold_seconds": 3, "n2_lpm": 3, "co_lpm": 0.8},
        {"name": "惰性处置", "target_temp_c": 200, "ramp_rate_cpm": 0, "hold_seconds": 2, "n2_lpm": 4},
    ]
    recipe = stores["recipes"].create_recipe("降温段", steps, RECIPE_META)
    runner, gateway = runner_factory(FakeGateway(run_control=False), poll_interval_ms=60_000)
    runner.start(start_payload(recipe))
    for segment, temp in ((3, 900.0), (5, 890.0), (5, 880.0), (6, 600.0), (6, 520.0)):
        snapshot = snap(temp, flows={"N2": 3.0, "CO": 0.8})
        snapshot.program_segment = segment
        clock.advance(1)
        runner.process_snapshot(snapshot, sampled_at=clock.now())
        assert runner.snapshot()["status"] == "running", (segment, temp)
    assert runner.snapshot()["pending_alarms"] == []
    # Once the step has cooled into its band, its own target applies again.
    snapshot = snap(560.0, flows={"N2": 3.0, "CO": 0.8})
    snapshot.program_segment = 6
    clock.advance(1)
    runner.process_snapshot(snapshot, sampled_at=clock.now())
    assert runner.snapshot()["end_reason"] == "alarm"
    finish_purge(runner, gateway, clock)
