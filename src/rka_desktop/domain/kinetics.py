"""失重法 / 增重法 kinetics for iron-ore reduction and oxidation tests.

Reduction degree R(t) is computed from sample mass loss. With sample mass m0 (g),
total-iron fraction a_TFe and FeO fraction a_FeO (mass fractions, i.e. percent/100),
reference mass m1 at reduction start, and instantaneous mass m_t:

    R(t) = [ 0.111 * a_FeO * m0 + (m1 - m_t) ] / ( 0.430 * a_TFe * m0 ) * 100 %

- 0.430 = mass fraction of removable oxygen bound to iron as Fe2O3 (O/Fe basis).
- 0.111 = oxygen already absent because iron is partly present as FeO at the start.

Oxidation degree is computed from mass *gain*, taking the oxygen needed to oxidise the FeO
present in the sample to Fe2O3 as 100 %:

    X(t) = (m_t - m1) / ( 0.111 * a_FeO * m0 ) * 100 %

(2 FeO + 1/2 O2 -> Fe2O3: 8.0 g O per 71.85 g FeO = 0.111.)

Model fitting (``fit_models``) fits g(α) = k·t for common gas–solid models over a window of α
and reports R² of the predicted α against the measured α, so that models are compared on the
same scale.

This module is pure and hardware-free; it is unit-tested against hand-computed values.
"""

from __future__ import annotations

import math
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


def _oxidation_degree(m_t: float, m1: float, params: SampleParams) -> float:
    gain_capacity = _O_DEFICIT_FEO * (params.feo_pct / 100.0) * params.initial_mass_g
    if gain_capacity <= 0:
        raise ValueError("oxidation degree needs feo_pct > 0")
    return (m_t - m1) / gain_capacity * 100.0


def _reduction_degree(m_t: float, m1: float, params: SampleParams) -> float:
    a_tfe = params.tfe_pct / 100.0
    a_feo = params.feo_pct / 100.0
    removable = _O_IN_FE2O3 * a_tfe * params.initial_mass_g
    numerator = _O_DEFICIT_FEO * a_feo * params.initial_mass_g + (m1 - m_t)
    return numerator / removable * 100.0


def degree_pct(kind: str, m_t: float, m1: float, params: SampleParams) -> float:
    """Instantaneous reduction (mass loss) or oxidation (mass gain) degree in percent."""
    return (_reduction_degree if kind == "reduction" else _oxidation_degree)(m_t, m1, params)


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
    kind: str = "reduction",
) -> ReductionResult:
    """Compute R(t) and rates.

    Args:
        series: ordered (t_seconds, weight_g) samples from reduction start onward.
        params: sample mass and composition.
        m1: reference mass at reduction start; defaults to the first sample weight.
        kind: ``"reduction"`` (mass loss) or ``"oxidation"`` (mass gain).
    """
    if kind not in ("reduction", "oxidation"):
        raise ValueError("kind must be reduction or oxidation")
    degree = _reduction_degree if kind == "reduction" else _oxidation_degree
    params.validate()
    if not series:
        raise ValueError("series must contain at least one sample")

    t0 = series[0][0]
    reference = series[0][1] if m1 is None else m1

    degrees: list[tuple[float, float]] = []
    for t_s, m_t in series:
        t_min = (t_s - t0) / 60.0
        degrees.append((t_min, degree(m_t, reference, params)))

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


def measurements_to_series(measurements: list[dict]) -> list[tuple[float, float]]:
    """Convert stored measurement rows into (t_seconds, weight_g) from the first sample.

    Rows without a weight or with an unparseable timestamp are skipped. Timestamps are ISO
    8601 strings as written by the SQLite store.
    """
    from datetime import datetime

    series: list[tuple[float, float]] = []
    t0: datetime | None = None
    for row in measurements:
        weight = row.get("weight_g")
        sampled_at = row.get("sampled_at")
        if weight is None or sampled_at is None:
            continue
        try:
            ts = datetime.fromisoformat(str(sampled_at))
        except ValueError:
            continue
        if t0 is None:
            t0 = ts
        series.append(((ts - t0).total_seconds(), float(weight)))
    return series


def series_window(measurements: list[dict], start: str | None, end: str | None) -> list[dict]:
    """Rows sampled within [start, end] (ISO strings); a missing bound means unbounded."""
    from datetime import datetime

    lo = datetime.fromisoformat(start) if start else None
    hi = datetime.fromisoformat(end) if end else None
    selected = []
    for row in measurements:
        try:
            ts = datetime.fromisoformat(str(row.get("sampled_at")))
        except ValueError:
            continue
        if (lo is None or ts >= lo) and (hi is None or ts <= hi):
            selected.append(row)
    return selected


# ---------------------------------------------------------------- model fitting
FIT_WINDOW = (0.05, 0.70)
MIN_FIT_POINTS = 5


@dataclass(frozen=True)
class ModelFit:
    model_id: str
    name: str
    g_expr: str
    k_per_min: float
    r2: float
    n: float | None
    curve: tuple[tuple[float, float], ...]  # (t_min, predicted alpha)


def _r3(alpha: float) -> float:
    return 1.0 - (1.0 - alpha) ** (1.0 / 3.0)


def _gb(alpha: float) -> float:
    return 1.0 - 2.0 * alpha / 3.0 - (1.0 - alpha) ** (2.0 / 3.0)


def _invert(g, target: float, upper: float) -> float:
    """Bisection for g(α) = target with g increasing on [0, 1); saturates at 1."""
    if target >= upper:
        return 1.0
    lo, hi = 0.0, 1.0 - 1e-12
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if g(mid) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def _r_squared(actual: list[float], predicted: list[float]) -> float:
    mean = sum(actual) / len(actual)
    ss_tot = sum((a - mean) ** 2 for a in actual)
    ss_res = sum((a - p) ** 2 for a, p in zip(actual, predicted))
    return 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0


def _thin(points: list[tuple[float, float]], limit: int = 200) -> tuple[tuple[float, float], ...]:
    if len(points) <= limit:
        return tuple(points)
    step = len(points) / limit
    return tuple(points[int(i * step)] for i in range(limit)) + (points[-1],)


def fit_models(points: list[tuple[float, float]], window: tuple[float, float] = FIT_WINDOW) -> list[ModelFit]:
    """Fit models to (t_min, α) samples with ``window[0] <= α <= window[1]`` and t > 0.

    * ``interface`` — shrinking core, interface reaction control: 1 − (1−α)^(1/3) = k·t
    * ``diffusion`` — shrinking core, product-layer diffusion (Ginstling–Brounshtein):
      1 − 2α/3 − (1−α)^(2/3) = k·t
    * ``avrami`` — Avrami–Erofeev nucleation and growth: [−ln(1−α)]^(1/n) = k·t, n fitted
    """
    data = [(t, a) for t, a in points if t > 0 and window[0] <= a <= window[1]]
    if len(data) < MIN_FIT_POINTS:
        return []
    ts = [t for t, _ in data]
    alphas = [a for _, a in data]
    fits: list[ModelFit] = []

    for model_id, name, expr, g, upper in (
        ("interface", "未反应核 · 界面反应控制", "1 − (1−α)^(1/3)", _r3, 1.0),
        ("diffusion", "未反应核 · 产物层扩散控制", "1 − 2α/3 − (1−α)^(2/3)", _gb, 1.0 / 3.0),
    ):
        gs = [g(a) for a in alphas]
        denom = sum(t * t for t in ts)
        k = sum(gv * t for gv, t in zip(gs, ts)) / denom if denom > 0 else 0.0
        predicted = [_invert(g, k * t, upper) for t in ts]
        fits.append(ModelFit(model_id, name, expr, k, _r_squared(alphas, predicted), None, _thin(list(zip(ts, predicted)))))

    xs = [math.log(t) for t in ts]
    ys = [math.log(-math.log(1.0 - a)) for a in alphas]
    n_pts = len(xs)
    mean_x, mean_y = sum(xs) / n_pts, sum(ys) / n_pts
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx > 0:
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / sxx
        intercept = mean_y - slope * mean_x
        if slope > 0:
            k = math.exp(intercept / slope)
            predicted = [1.0 - math.exp(-((k * t) ** slope)) for t in ts]
            fits.append(ModelFit("avrami", f"Avrami–Erofeev（n = {slope:.2f}）", "[−ln(1−α)]^(1/n)", k,
                                 _r_squared(alphas, predicted), slope, _thin(list(zip(ts, predicted)))))
    return fits
