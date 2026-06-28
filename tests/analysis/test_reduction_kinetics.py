import math

import pytest

from rka_desktop.analysis.reduction_kinetics import (
    SampleParams,
    compute_reduction,
)


def test_reduction_degree_basic_no_feo():
    # m0=50, TFe=60% -> removable O = 0.430*0.6*50 = 12.9 g; FeO=0
    params = SampleParams(initial_mass_g=50.0, tfe_pct=60.0, feo_pct=0.0)
    # weights at 0/60/120 s: lose 6.45 g then 12.9 g total -> R = 0/50/100 %
    series = [(0.0, 50.0), (60.0, 43.55), (120.0, 37.1)]
    result = compute_reduction(series, params)

    assert math.isclose(result.points[0].reduction_degree_pct, 0.0, abs_tol=1e-6)
    assert math.isclose(result.points[1].reduction_degree_pct, 50.0, abs_tol=1e-6)
    assert math.isclose(result.final_degree_pct, 100.0, abs_tol=1e-6)


def test_feo_offset_raises_initial_degree():
    # FeO=10% -> initial offset = 0.111*0.1*50 = 0.555 g over removable 12.9 -> 4.302 %
    params = SampleParams(initial_mass_g=50.0, tfe_pct=60.0, feo_pct=10.0)
    result = compute_reduction([(0.0, 50.0)], params)
    assert math.isclose(result.points[0].reduction_degree_pct, 0.555 / 12.9 * 100.0, rel_tol=1e-6)


def test_rate_and_threshold_times():
    params = SampleParams(initial_mass_g=50.0, tfe_pct=60.0, feo_pct=0.0)
    series = [(0.0, 50.0), (60.0, 43.55), (120.0, 37.1)]  # R = 0/50/100 over 1 min steps
    result = compute_reduction(series, params)

    # rate between points = 50 %/min
    assert math.isclose(result.points[1].rate_pct_per_min, 50.0, abs_tol=1e-6)
    # t40 interpolated on the 0->50 segment: 0.8 min; t60 on 50->100: 1.2 min
    assert math.isclose(result.time_to_40_min, 0.8, abs_tol=1e-6)
    assert math.isclose(result.time_to_60_min, 1.2, abs_tol=1e-6)
    assert math.isclose(result.rate_at_40_pct, 50.0, abs_tol=1e-6)


def test_custom_m1_reference():
    params = SampleParams(initial_mass_g=50.0, tfe_pct=60.0, feo_pct=0.0)
    # If reduction truly started at 49 g, a 49->42.55 loss (6.45) is still 50 %.
    result = compute_reduction([(0.0, 49.0), (60.0, 42.55)], params, m1=49.0)
    assert math.isclose(result.points[1].reduction_degree_pct, 50.0, abs_tol=1e-6)


def test_validation():
    with pytest.raises(ValueError):
        compute_reduction([(0.0, 50.0)], SampleParams(initial_mass_g=0.0, tfe_pct=60.0, feo_pct=0.0))
    with pytest.raises(ValueError):
        compute_reduction([], SampleParams(initial_mass_g=50.0, tfe_pct=60.0, feo_pct=0.0))
