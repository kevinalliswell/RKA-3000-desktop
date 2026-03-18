from datetime import datetime, timedelta

from rka_desktop.models.entities import Measurement
from rka_desktop.services.experiment_engine import ExperimentEngine, ExperimentState
from rka_desktop.services.recipe_runtime_service import build_recipe_runtime


def _measurement(sampled_at: datetime, temperature_c: float) -> Measurement:
    return Measurement(
        experiment_id=1,
        sampled_at=sampled_at,
        temperature_c=temperature_c,
        weight_g=80.0,
        pressure_mpa=0.02,
        n2_lpm=4.0,
        h2_lpm=1.0,
        co_lpm=0.5,
    )


def test_engine_completes_single_step_recipe():
    steps = build_recipe_runtime(
        [
            {
                "step_no": 1,
                "target_temp_c": 900,
                "ramp_rate_cpm": 10,
                "hold_seconds": 5,
                "n2_lpm": 4.0,
                "h2_lpm": 1.0,
                "co_lpm": 0.5,
                "notes": "",
            }
        ]
    )
    engine = ExperimentEngine(steps)
    start_update = engine.start()
    assert start_update.state == ExperimentState.RUNNING

    t0 = datetime.now()
    update1 = engine.on_measurement(_measurement(t0, 880))
    update2 = engine.on_measurement(_measurement(t0 + timedelta(seconds=6), 901))

    assert update1.state == ExperimentState.RUNNING
    assert update2.state == ExperimentState.RUNNING

    update3 = engine.on_measurement(_measurement(t0 + timedelta(seconds=12), 902))
    assert update3.completed is True
    assert update3.state == ExperimentState.COMPLETED


def test_engine_pause_and_resume():
    steps = build_recipe_runtime(
        [
            {
                "step_no": 1,
                "target_temp_c": 900,
                "ramp_rate_cpm": 10,
                "hold_seconds": 30,
                "n2_lpm": 4.0,
                "h2_lpm": 1.0,
                "co_lpm": 0.5,
                "notes": "",
            }
        ]
    )
    engine = ExperimentEngine(steps)
    engine.start()

    pause_update = engine.pause()
    assert pause_update.state == ExperimentState.PAUSED

    paused_measurement_update = engine.on_measurement(_measurement(datetime.now(), 910))
    assert paused_measurement_update.state == ExperimentState.PAUSED

    resume_update = engine.resume()
    assert resume_update.state == ExperimentState.RUNNING


def test_engine_interrupt_requires_manual_resume():
    steps = build_recipe_runtime(
        [
            {
                "step_no": 1,
                "target_temp_c": 900,
                "ramp_rate_cpm": 10,
                "hold_seconds": 30,
                "n2_lpm": 4.0,
                "h2_lpm": 1.0,
                "co_lpm": 0.5,
                "notes": "",
            }
        ]
    )
    engine = ExperimentEngine(steps)
    engine.start()

    interrupt_update = engine.interrupt()
    assert interrupt_update.state == ExperimentState.INTERRUPTED

    interrupted_measurement_update = engine.on_measurement(_measurement(datetime.now(), 910))
    assert interrupted_measurement_update.state == ExperimentState.INTERRUPTED

    resume_update = engine.resume()
    assert resume_update.state == ExperimentState.RUNNING


def test_engine_fail_marks_terminal_fault():
    steps = build_recipe_runtime(
        [
            {
                "step_no": 1,
                "target_temp_c": 900,
                "ramp_rate_cpm": 10,
                "hold_seconds": 30,
                "n2_lpm": 4.0,
                "h2_lpm": 1.0,
                "co_lpm": 0.5,
                "notes": "",
            }
        ]
    )
    engine = ExperimentEngine(steps)
    engine.start()

    fail_update = engine.fail("setpoint write failed")
    assert fail_update.state == ExperimentState.FAULTED
    assert fail_update.completed is True


def test_engine_faults_when_heatup_exceeds_expected_time():
    steps = build_recipe_runtime(
        [
            {
                "step_no": 1,
                "target_temp_c": 100,
                "ramp_rate_cpm": 60,
                "hold_seconds": 30,
                "n2_lpm": 4.0,
                "h2_lpm": 1.0,
                "co_lpm": 0.5,
                "notes": "",
            }
        ]
    )
    engine = ExperimentEngine(steps, step_heatup_grace_seconds=0, step_total_grace_seconds=300)
    engine.start()

    t0 = datetime.now()
    engine.on_measurement(_measurement(t0, 20))
    timeout_update = engine.on_measurement(_measurement(t0 + timedelta(seconds=81), 40))

    assert timeout_update.state == ExperimentState.FAULTED
    assert "升温超时" in timeout_update.status_text


def test_engine_faults_when_step_total_duration_exceeds_limit():
    steps = build_recipe_runtime(
        [
            {
                "step_no": 1,
                "target_temp_c": 50,
                "ramp_rate_cpm": 60,
                "hold_seconds": 10,
                "n2_lpm": 4.0,
                "h2_lpm": 1.0,
                "co_lpm": 0.5,
                "notes": "",
            }
        ]
    )
    engine = ExperimentEngine(steps, step_heatup_grace_seconds=0, step_total_grace_seconds=0)
    engine.start()

    t0 = datetime.now()
    engine.on_measurement(_measurement(t0, 49))
    engine.on_measurement(_measurement(t0 + timedelta(seconds=5), 50))
    timeout_update = engine.on_measurement(_measurement(t0 + timedelta(seconds=12), 50))

    assert timeout_update.state == ExperimentState.FAULTED
    assert "执行超时" in timeout_update.status_text
