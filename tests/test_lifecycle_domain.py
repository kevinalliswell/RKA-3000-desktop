"""Pure rules behind the experiment lifecycle: recipes, limits, safety, review, kinetics models."""

from __future__ import annotations

import math

import pytest

from rka_desktop.domain.gases import ExperimentType, allowed_gases
from rka_desktop.domain.kinetics import SampleParams, compute_reduction, fit_models
from rka_desktop.domain.limits import LimitError, initial_policy, validate_limit_changes, validate_reason
from rka_desktop.domain.preflight import mass_deviation_pct, parse_checklist, parse_sample
from rka_desktop.domain.recipe import Recipe, RecipeValidationError, parse_step
from rka_desktop.domain.recipe_rules import assess_recipe
from rka_desktop.domain.review import assess_review, sampling_stats
from rka_desktop.domain.safety import SafetyMonitor

DEVICE = {"N2": 20.0, "AR": 20.0, "H2": 5.0, "CO": 5.0, "CO2": 20.0, "CH4": 5.0}


def standard_recipe(**overrides) -> Recipe:
    payload = {
        "name": "900℃ 等温还原", "experiment_type": "reduction", "inert_gas": "N2", "purge_lpm": 4.0, "purge_seconds": 600,
        "steps": [
            {"name": "惰性置换", "target_temp_c": 150, "ramp_rate_cpm": 10, "hold_seconds": 600, "n2_lpm": 4},
            {"name": "等温还原", "target_temp_c": 900, "ramp_rate_cpm": 10, "hold_seconds": 3600, "n2_lpm": 3, "h2_lpm": 1, "co_lpm": 0.8},
            {"name": "惰性处置", "target_temp_c": 200, "ramp_rate_cpm": 0, "hold_seconds": 900, "n2_lpm": 4},
        ],
    }
    payload.update(overrides)
    return Recipe.from_document(payload)


def test_flows_accept_flat_and_nested_forms():
    step = parse_step({"target_temp_c": 900, "hold_seconds": 1, "flows": {"CO2": 0.5, "n2": 3}}, 1)
    assert step.flows()["CO2"] == 0.5 and step.n2_lpm == 3.0 and step.active_gases() == ("N2", "CO2")
    with pytest.raises(RecipeValidationError, match="未知气体"):
        parse_step({"target_temp_c": 900, "hold_seconds": 1, "flows": {"XE": 1}}, 1)


def test_recipe_meta_validated_on_save():
    with pytest.raises(RecipeValidationError, match="实验类型"):
        standard_recipe(experiment_type="burn")
    with pytest.raises(RecipeValidationError, match="惰性气"):
        standard_recipe(inert_gas="H2")


def test_standard_recipe_is_runnable():
    recipe = standard_recipe()
    result = assess_recipe(recipe, usage_limits=DEVICE, device_limits=DEVICE, max_program_steps=4)
    assert result.runnable, result.summary()


def test_rules_explain_each_failure():
    recipe = standard_recipe(steps=[
        {"target_temp_c": 150, "hold_seconds": 300, "n2_lpm": 4, "h2_lpm": 0.1},
        {"target_temp_c": 900, "hold_seconds": 60, "n2_lpm": 2, "h2_lpm": 6, "o2_lpm": 0.5},
        {"target_temp_c": 200, "hold_seconds": 900, "n2_lpm": 4},
    ], purge_lpm=0)
    result = assess_recipe(recipe, usage_limits={**DEVICE, "H2": 5.0}, device_limits=DEVICE)
    failed = {check.key for check in result.failures}
    assert failed == {"inert_ends", "gas_type", "channels", "usage_limits", "purge"}
    assert "只能开" in result.step_issues()[1][0]


def test_lower_usage_limit_makes_recipe_non_runnable_but_keeps_it_valid():
    recipe = standard_recipe()
    result = assess_recipe(recipe, usage_limits={**DEVICE, "CO": 0.6}, device_limits=DEVICE)
    assert not result.runnable and [c.key for c in result.failures] == ["usage_limits"]


def test_oxidation_allows_only_co2_o2_plus_inert():
    assert allowed_gases(ExperimentType.OXIDATION, "AR") == ("AR", "CO2", "O2")
    recipe = standard_recipe(experiment_type="oxidation")
    assert "gas_type" in {c.key for c in assess_recipe(recipe, usage_limits=DEVICE, device_limits=DEVICE).failures}


def test_program_size_rule_only_in_program_mode():
    steps = [{"target_temp_c": 150, "hold_seconds": 600, "n2_lpm": 4}] + [
        {"target_temp_c": 900, "hold_seconds": 60, "n2_lpm": 3, "co_lpm": 0.5}] * 3 + [{"target_temp_c": 200, "hold_seconds": 900, "n2_lpm": 4}]
    recipe = standard_recipe(steps=steps)
    assert not assess_recipe(recipe, usage_limits=DEVICE, device_limits=DEVICE, max_program_steps=4).runnable
    assert assess_recipe(recipe, usage_limits=DEVICE, device_limits=DEVICE, max_program_steps=None).runnable


def test_limit_changes_bounded_by_device_and_reason_required():
    policy = initial_policy(DEVICE)
    assert policy.effective(DEVICE)["H2"] == 5.0 and policy.limit_for("O2", DEVICE) is None
    assert validate_limit_changes({"co": 0.6}, DEVICE) == {"CO": 0.6}
    for bad in ({"CO": 0}, {"CO": 6}, {"O2": 1}, {}, {"CO": True}):
        with pytest.raises(LimitError):
            validate_limit_changes(bad, DEVICE)
    with pytest.raises(LimitError):
        validate_reason(" ")


def test_sample_and_checklist_parsing():
    sample, problems = parse_sample({"name": "A-19", "initial_mass_g": 54.28, "tfe_pct": 64.2, "feo_pct": 8.4, "operator": "实验员 A"})
    assert sample is not None and not problems
    _, problems = parse_sample({"name": "", "initial_mass_g": -1, "tfe_pct": 0, "operator": "x"})
    assert len(problems) == 3
    _, problems = parse_sample({"name": "B", "initial_mass_g": 1, "tfe_pct": 60, "feo_pct": 0, "operator": "x"}, ExperimentType.OXIDATION)
    assert "FeO" in problems[0]
    assert parse_checklist({"serial": True, "gas": "yes", "extra": True}) == {
        "serial": True, "calibration": False, "balance": False, "gas": False, "ventilation": False, "interlock": False}
    assert mass_deviation_pct(54.280, 54.276) == pytest.approx(0.00737, abs=1e-4)
    assert mass_deviation_pct(54.28, None) is None


def test_safety_over_temperature_alarm_once_per_episode():
    monitor = SafetyMonitor()
    common = {"gas_pv": {}, "gas_sp": {}, "weight_g": 50.0}
    assert monitor.observe(0, temperature_c=925, target_temp_c=900, **common) == []
    events = monitor.observe(1, temperature_c=931, target_temp_c=900, **common)
    assert [(e.code, e.level) for e in events] == [("SW-OVERTEMP", "alarm")] and events[0].disposes
    assert monitor.observe(2, temperature_c=935, target_temp_c=900, **common) == []
    assert monitor.observe(3, temperature_c=1601, target_temp_c=None, **{**common}) == []  # same episode
    monitor.observe(4, temperature_c=900, target_temp_c=900, **common)
    assert monitor.observe(5, temperature_c=1601, target_temp_c=None, **common)[0].code == "SW-OVERTEMP"


def test_safety_mfc_deviation_warns_then_alarms_and_resets_on_new_setpoint():
    monitor = SafetyMonitor()

    def at(t, pv, sp=1.0):
        return [(e.code, e.level) for e in monitor.observe(t, temperature_c=900, target_temp_c=900, gas_pv={"H2": pv},
                                                           gas_sp={"H2": sp}, weight_g=50.0)]
    assert at(0, 0.85) == []
    assert at(9, 0.85) == []
    assert at(10, 0.85) == [("SW-MFC-DEV-H2", "warning")]
    assert at(30, 0.85) == []
    assert at(60, 0.85) == [("SW-MFC-DEV-H2", "alarm")]
    assert at(61, 0.85, sp=0.9) == []  # new set-point: settling window restarts
    assert at(80, 0.95, sp=0.9) == []  # within 10 %


def test_safety_balance_jump_and_stale_skip():
    monitor = SafetyMonitor(stale_warning_seconds=5)
    base = {"temperature_c": 900, "target_temp_c": 900, "gas_pv": {}, "gas_sp": {}}
    assert monitor.observe(0, weight_g=50.0, **base) == []
    assert monitor.observe(0.5, weight_g=49.9, **base) == []
    assert monitor.observe(1.0, weight_g=48.0, **base)[0].code == "SW-BALANCE-JUMP"
    assert monitor.observe(2.0, weight_g=40.0, stale={"balance"}, **base) == []
    assert monitor.observe(7.0, weight_g=40.0, stale={"balance"}, **base)[0].code == "SW-STALE-BALANCE"
    assert monitor.observe(9.0, weight_g=40.0, stale={"balance"}, **base) == []


def test_sampling_stats_find_gaps_and_reversals():
    stamps = ["2026-01-01T12:00:00", "2026-01-01T12:00:00.500000", "2026-01-01T12:00:05", "2026-01-01T12:00:04"]
    stats = sampling_stats(stamps, 0.5)
    assert (stats.count, stats.gaps, stats.reversals) == (4, 1, 1) and not stats.complete


def _review(**overrides):
    params = dict(review_state="pending", active=False, stats=sampling_stats(["2026-01-01T12:00:00", "2026-01-01T12:00:00.5"], 0.5),
                  alarms_total=0, alarms_unacknowledged=0, recipe_version=3, has_recipe_snapshot=True, audit_count=5,
                  manual_gas_count=1, purge_required_s=600, purge_done_s=612, final_temperature_c=186,
                  safe_temperature_c=200, initial_mass_g=54.276, final_mass_g=43.516, end_reason="completed")
    params.update(overrides)
    return assess_review(**params)


def test_review_severity_controls_archive_and_note():
    clean = _review()
    assert clean.can_archive and not clean.note_required
    assert not _review(alarms_unacknowledged=1).can_archive
    assert not _review(active=True).can_archive
    warned = _review(final_temperature_c=260, end_reason="emergency")
    assert warned.can_archive and warned.note_required


def test_oxidation_degree_from_mass_gain():
    params = SampleParams(initial_mass_g=60.0, tfe_pct=60.0, feo_pct=20.0)
    capacity = 0.111 * 0.20 * 60.0
    result = compute_reduction([(0, 60.0), (60, 60.0 + capacity / 2), (120, 60.0 + capacity)], params, kind="oxidation")
    assert result.final_degree_pct == pytest.approx(100.0)
    assert result.time_to_40_min == pytest.approx(0.8)


def test_model_fit_recovers_known_interface_kinetics():
    k = 0.01
    points = [(t, 1 - (1 - k * t) ** 3) for t in range(1, 60)]
    fits = {fit.model_id: fit for fit in fit_models(points)}
    assert fits["interface"].k_per_min == pytest.approx(k, rel=1e-6)
    assert fits["interface"].r2 == pytest.approx(1.0, abs=1e-9)
    assert fits["interface"].r2 >= max(f.r2 for f in fits.values()) - 1e-12


def test_model_fit_recovers_avrami_exponent():
    k, n = 0.04, 1.3
    points = [(t, 1 - math.exp(-((k * t) ** n))) for t in [x * 0.5 for x in range(1, 120)]]
    avrami = next(fit for fit in fit_models(points) if fit.model_id == "avrami")
    assert avrami.n == pytest.approx(n, rel=1e-6) and avrami.k_per_min == pytest.approx(k, rel=1e-6)
    assert fit_models(points[:3]) == []
