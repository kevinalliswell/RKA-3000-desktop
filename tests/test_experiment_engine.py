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
