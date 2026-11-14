"""Step (change-point) detection in a TLE semi-major-axis series.

Method. A manoeuvre shows up in mean semi-major axis ``a`` as a step on top of
a slow, smooth drag decay (tens to ~100+ m/day for the ISS, changing with solar
activity). For every gap between consecutive epochs the detector

1. fits a straight line to the ``k`` epochs before the gap and another to the
   ``k`` epochs after it (local, so the decay rate may differ on each side),
2. extrapolates both lines to the middle of the gap; the difference is the step,
3. scores the step against the TLE scatter: ``z = step / se``, where ``se``
   comes from the ordinary least-squares prediction variance of each line at
   the gap and a robust residual scatter ``sigma`` (1.4826 x MAD of the
   residuals of both fits, pooled).

``sigma`` is estimated from the data at every gap, not hard-coded. To stop a
run of nearly identical TLEs from inflating ``z``, it is floored at half the
median ``sigma`` over the whole series. Each side's fit is made once more after
dropping points more than 4 ``sigma`` from the first fit, so a transitional TLE
(one fitted across the burn) or a neighbouring step does not drag the line.

A step appears at several neighbouring gaps as the windows slide past it, so
flagged gaps (``z`` and ``|step|`` over thresholds) are thinned by non-maximum
suppression: within ``nms_days`` only the highest ``|z|`` survives.

A gap is not scored when either side's ``k`` epochs span more than
``max_span_days`` or the gap itself is longer than ``max_gap_days``, so there
is no detection across a data outage such as 2022-06-15..19.

Duplicate epochs are already removed by ``to_series``. Only semi-major axis is
used.
"""

# shortcut: eccentricity and inclination are not used as secondary channels;
# add them if out-of-plane or perigee-only burns need finding.

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from orbit_watch.series import ElementSeries

_DAY_US = 86_400e6
_MAD_TO_SIGMA = 1.4826
_REJECT_SIGMA = 4.0


@dataclass(frozen=True)
class GapScores:
    """Per-gap scores; index ``i`` is the gap between epochs ``i`` and ``i + 1``."""

    start: np.ndarray  # datetime64[us], epoch before the gap
    end: np.ndarray  # datetime64[us], epoch after the gap
    step_m: np.ndarray  # extrapolated after-minus-before, metres (NaN when not scored)
    z: np.ndarray  # step / standard error (NaN when not scored)
    sigma_m: np.ndarray  # residual scatter used, metres

    @property
    def valid(self) -> np.ndarray:
        return np.isfinite(self.z)


@dataclass(frozen=True)
class Detection:
    start: np.datetime64  # epoch before the step
    end: np.datetime64  # epoch after the step
    step_m: float
    z: float

    @property
    def sign(self) -> int:
        return 1 if self.step_m > 0 else -1


def _days(epochs: np.ndarray) -> np.ndarray:
    return (epochs - epochs[0]).astype("int64") / _DAY_US


def _fit(t: np.ndarray, y: np.ndarray):
    """OLS line; returns value at t=0, prediction-variance factor at 0, residuals."""
    tbar = t.mean()
    sxx = ((t - tbar) ** 2).sum()
    if sxx <= 0:
        return None
    slope = ((t - tbar) * (y - y.mean())).sum() / sxx
    at0 = y.mean() - slope * tbar
    resid = y - (at0 + slope * t)
    return at0, 1.0 / len(t) + tbar**2 / sxx, resid


def _mad_sigma(r: np.ndarray) -> float:
    return _MAD_TO_SIGMA * float(np.median(np.abs(r - np.median(r))))


def _score_one(tb, yb, ta, ya, floor):
    fb, fa = _fit(tb, yb), _fit(ta, ya)
    if fb is None or fa is None:
        return np.nan, np.nan, np.nan
    sigma = max(_mad_sigma(np.concatenate([fb[2], fa[2]])), floor)
    if floor > 0:  # second, robust pass
        kb, ka = np.abs(fb[2]) <= _REJECT_SIGMA * sigma, np.abs(fa[2]) <= _REJECT_SIGMA * sigma
        if kb.sum() >= 3 and ka.sum() >= 3:
            fb2, fa2 = _fit(tb[kb], yb[kb]), _fit(ta[ka], ya[ka])
            if fb2 is not None and fa2 is not None:
                fb, fa = fb2, fa2
                sigma = max(_mad_sigma(np.concatenate([fb[2], fa[2]])), floor)
    step = fa[0] - fb[0]
    return step, step / (sigma * np.sqrt(fb[1] + fa[1])), sigma


def score_gaps(
    series: ElementSeries, k: int = 6, max_span_days: float = 3.0, max_gap_days: float = 2.0
) -> GapScores:
    t = _days(series.epochs)
    y = series.semi_major_axis_km * 1000.0
    n = len(t)
    idx = [i for i in range(k - 1, n - k)
           if t[i + 1] - t[i] <= max_gap_days
           and t[i] - t[i - k + 1] <= max_span_days
           and t[i + k] - t[i + 1] <= max_span_days]

    def run(floor):
        out = np.full((3, n - 1), np.nan)
        for i in idx:
            mid = 0.5 * (t[i] + t[i + 1])
            b, a = slice(i - k + 1, i + 1), slice(i + 1, i + k + 1)
            out[:, i] = _score_one(t[b] - mid, y[b] - y[i], t[a] - mid, y[a] - y[i], floor)
        return out

    raw = run(0.0)
    floor = 0.5 * float(np.nanmedian(raw[2])) if idx else 0.0
    step, z, sigma = run(floor)
    return GapScores(series.epochs[:-1], series.epochs[1:], step, z, sigma)


def pick(scores: GapScores, z_min: float, step_min_m: float, nms_days: float = 1.0) -> list[Detection]:
    """Gaps with ``|z| >= z_min`` and ``|step| >= step_min_m``, thinned by non-maximum suppression."""
    with np.errstate(invalid="ignore"):
        flagged = np.flatnonzero(
            scores.valid & (np.abs(scores.z) >= z_min) & (np.abs(scores.step_m) >= step_min_m)
        )
    if not len(flagged):
        return []
    centre = _days(scores.start) + 0.5 * (scores.end - scores.start).astype("int64") / _DAY_US
    kept: list[int] = []
    for i in sorted(flagged, key=lambda j: -abs(scores.z[j])):
        if not kept or np.min(np.abs(centre[kept] - centre[i])) > nms_days:
            kept.append(i)
    return [
        Detection(scores.start[i], scores.end[i], float(scores.step_m[i]), float(scores.z[i]))
        for i in sorted(kept)
    ]


def detect(series: ElementSeries, z_min: float, step_min_m: float, k: int = 6) -> list[Detection]:
    return pick(score_gaps(series, k=k), z_min, step_min_m)
