"""失重法 (mass-loss method) reduction-degree kinetics for iron-ore redox tests.

Reduction degree R(t) is computed from sample mass loss. With sample mass m0 (g),
total-iron fraction a_TFe and FeO fraction a_FeO (mass fractions, i.e. percent/100),
reference mass m1 at reduction start, and instantaneous mass m_t:

    R(t) = [ 0.111 * a_FeO * m0 + (m1 - m_t) ] / ( 0.430 * a_TFe * m0 ) * 100 %

- 0.430 = mass fraction of removable oxygen bound to iron as Fe2O3 (O/Fe basis).
- 0.111 = oxygen already absent because iron is partly present as FeO at the start.

This module is pure and hardware-free; it is unit-tested against hand-computed values.
"""

from __future__ import annotations

from dataclasses import dataclass

_O_IN_FE2O3 = 0.430  # removable O per unit TFe
_O_DEFICIT_FEO = 0.111  # O deficit per unit FeO


@dataclass(frozen=True)
class SampleParams:
    initial_mass_g: float  # m0
    tfe_pct: float  # total iron, %
    feo_pct: float  # FeO, %

    def validate(self) -> None:
        if self.initial_mass_g <= 0:
            raise ValueError("initial_mass_g must be > 0")
        if not 0 < self.tfe_pct <= 100:
            raise ValueError("tfe_pct must be in (0, 100]")
        if not 0 <= self.feo_pct <= 100:
            raise ValueError("feo_pct must be in [0, 100]")


@dataclass(frozen=True)
class ReductionPoint:
    t_min: float  # minutes since reduction start
    reduction_degree_pct: float
    rate_pct_per_min: float


@dataclass(frozen=True)
class ReductionResult:
    points: tuple[ReductionPoint, ...]
    final_degree_pct: float
    time_to_40_min: float | None
    time_to_60_min: float | None
    rate_at_40_pct: float | None


def _reduction_degree(m_t: float, m1: float, params: SampleParams) -> float:
    a_tfe = params.tfe_pct / 100.0
    a_feo = params.feo_pct / 100.0
    removable = _O_IN_FE2O3 * a_tfe * params.initial_mass_g
    numerator = _O_DEFICIT_FEO * a_feo * params.initial_mass_g + (m1 - m_t)
    return numerator / removable * 100.0


def _crossing_time(points: tuple[ReductionPoint, ...], threshold: float) -> float | None:
    """Linear-interpolated time at which R first reaches ``threshold`` percent."""
    for prev, cur in zip(points, points[1:]):
        if prev.reduction_degree_pct < threshold <= cur.reduction_degree_pct:
            span = cur.reduction_degree_pct - prev.reduction_degree_pct
            if span == 0:
                return cur.t_min
            frac = (threshold - prev.reduction_degree_pct) / span
            return prev.t_min + frac * (cur.t_min - prev.t_min)
    if points and points[0].reduction_degree_pct >= threshold:
        return points[0].t_min
    return None


def _rate_at_degree(points: tuple[ReductionPoint, ...], threshold: float) -> float | None:
    for prev, cur in zip(points, points[1:]):
        if prev.reduction_degree_pct < threshold <= cur.reduction_degree_pct:
            return cur.rate_pct_per_min
    return None


def compute_reduction(
    series: list[tuple[float, float]],
    params: SampleParams,
    *,
    m1: float | None = None,
) -> ReductionResult:
    """Compute R(t) and rates.

    Args:
        series: ordered (t_seconds, weight_g) samples from reduction start onward.
        params: sample mass and composition.
        m1: reference mass at reduction start; defaults to the first sample weight.
    """
    params.validate()
    if not series:
        raise ValueError("series must contain at least one sample")

    t0 = series[0][0]
    reference = series[0][1] if m1 is None else m1

    degrees: list[tuple[float, float]] = []
    for t_s, m_t in series:
        t_min = (t_s - t0) / 60.0
        degrees.append((t_min, _reduction_degree(m_t, reference, params)))

    points: list[ReductionPoint] = []
    for i, (t_min, r) in enumerate(degrees):
        if i == 0:
            rate = 0.0
        else:
            dt = t_min - degrees[i - 1][0]
            rate = (r - degrees[i - 1][1]) / dt if dt > 0 else 0.0
        points.append(ReductionPoint(t_min=t_min, reduction_degree_pct=r, rate_pct_per_min=rate))

    pts = tuple(points)
    return ReductionResult(
        points=pts,
        final_degree_pct=pts[-1].reduction_degree_pct,
        time_to_40_min=_crossing_time(pts, 40.0),
        time_to_60_min=_crossing_time(pts, 60.0),
        rate_at_40_pct=_rate_at_degree(pts, 40.0),
    )
