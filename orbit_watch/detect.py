"""Step (change-point) detection in a TLE semi-major-axis series.

Method. A manoeuvre shows up in mean semi-major axis ``a`` as a step on top of
a slow, smooth drag decay (tens to ~100+ m/day for the ISS, changing with solar
activity). For every gap between consecutive epochs the detector takes the
``k`` epochs before the gap and the ``k`` after it and

1. estimates the local decay rate as the median slope over every pair of
   epochs on the same side of the gap (Theil-Sen, pooled over both sides; no
   pair straddles the gap, so the step does not enter the slope),
2. removes that slope, measured from the middle of the gap,
3. takes the step as the median of the detrended values after the gap minus the
   median before it,
4. scores it against the TLE scatter: ``z = step / se`` with
   ``se = sigma * sqrt(pi / 2) * sqrt(2 / k)`` (the standard error of a
   difference of two medians), where ``sigma`` is 1.4826 x the median absolute
   deviation of the detrended values about their side's median, pooled.

Medians, not least-squares lines, because a burn is usually followed by one or
two transitional TLEs (fitted across the burn) that sit off both trends; a
least-squares line through them leans, and its extrapolation produces ghost
steps of either sign near the real one. A median ignores up to ``k/2 - 1`` such
points.

``sigma`` is estimated from the data at every gap, not hard-coded. It is
floored at half the median ``sigma`` over the series so that a run of nearly
identical TLEs does not inflate ``z``. Consecutive ISS TLEs come from
overlapping orbit-determination arcs, so their scatter is small and correlated:
``z`` ranks steps but is not a calibrated probability, and the minimum ``|step|``
does most of the work.

A step appears at several neighbouring gaps as the windows slide past it, so
flagged gaps (``|z|`` and ``|step|`` over thresholds) are thinned by non-maximum
suppression, highest ``|z|`` first (the gap whose two sides are both clean
scatters least, so it scores highest). Each surviving gap is a peak: it absorbs
the flagged gaps fewer than ``k`` gaps from it that no stronger peak has
absorbed, and its detection spans the union of those gaps, with the peak's step
and ``z``. A flagged gap that is not absorbed is dropped when its centre lies
within ``nms_days`` of a stronger peak's centre. Absorption is by distance from
the peak, not chained from gap to gap: a weak gap between two burns, whose
window mixes both, joins one of them without merging the two (the 2025-09-25
and 09-26 ISS burns).

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


@dataclass(frozen=True)
class GapScores:
    """Per-gap scores; index ``i`` is the gap between epochs ``i`` and ``i + 1``."""

    start: np.ndarray  # datetime64[us], epoch before the gap
    end: np.ndarray  # datetime64[us], epoch after the gap
    step_m: np.ndarray  # extrapolated after-minus-before, metres (NaN when not scored)
    z: np.ndarray  # step / standard error (NaN when not scored)
    sigma_m: np.ndarray  # residual scatter used, metres
    k: int = 0  # epochs per side; pick absorbs flagged gaps fewer than k gaps from a peak

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


def _mad(r: np.ndarray) -> np.ndarray:
    return np.median(np.abs(r - np.median(r, axis=-1, keepdims=True)), axis=-1)


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

    step = np.full(n - 1, np.nan)
    sigma = np.full(n - 1, np.nan)
    if idx:
        ii = np.array(idx)
        off = np.arange(-k + 1, k + 1)  # k epochs before the gap, k after
        tw, yw = t[ii[:, None] + off], y[ii[:, None] + off]
        mid = 0.5 * (t[ii] + t[ii + 1])[:, None]
        p, q = np.triu_indices(k, 1)  # every pair of epochs on one side of the gap
        p, q = np.concatenate([p, p + k]), np.concatenate([q, q + k])
        slopes = (yw[:, q] - yw[:, p]) / (tw[:, q] - tw[:, p])
        r = yw - np.median(slopes, axis=1)[:, None] * (tw - mid)
        before, after = r[:, :k], r[:, k:]
        step[ii] = np.median(after, axis=1) - np.median(before, axis=1)
        sigma[ii] = _MAD_TO_SIGMA * _mad(np.concatenate(
            [before - np.median(before, axis=1, keepdims=True),
             after - np.median(after, axis=1, keepdims=True)], axis=1))
    floor = 0.5 * float(np.nanmedian(sigma)) if idx else 0.0
    sigma = np.maximum(sigma, floor)
    z = step / (sigma * np.sqrt(np.pi / 2) * np.sqrt(2.0 / k))
    return GapScores(series.epochs[:-1], series.epochs[1:], step, z, sigma, k)


def pick(scores: GapScores, z_min: float, step_min_m: float, nms_days: float = 1.0) -> list[Detection]:
    """Gaps with ``|z| >= z_min`` and ``|step| >= step_min_m``, thinned by non-maximum suppression.

    In decreasing ``|z|``: a flagged gap already absorbed is skipped; one whose centre is within
    ``nms_days`` of a kept peak's centre is dropped; otherwise it is a peak and absorbs the
    unabsorbed flagged gaps fewer than ``scores.k`` gaps from it. A detection spans its peak's
    absorbed gaps and carries the peak's step and ``z``.
    """
    with np.errstate(invalid="ignore"):
        flagged = np.flatnonzero(
            scores.valid & (np.abs(scores.z) >= z_min) & (np.abs(scores.step_m) >= step_min_m)
        )
    if not len(flagged):
        return []
    centre = _days(scores.start) + 0.5 * (scores.end - scores.start).astype("int64") / _DAY_US
    owner: dict[int, int] = {}  # flagged gap -> the peak that absorbed it
    peaks: list[int] = []
    for i in sorted(flagged, key=lambda j: -abs(scores.z[j])):
        if i in owner or (peaks and np.min(np.abs(centre[peaks] - centre[i])) <= nms_days):
            continue
        peaks.append(i)
        for j in flagged[np.abs(flagged - i) < max(scores.k, 1)]:
            owner.setdefault(int(j), i)
    out = []
    for p in sorted(peaks):
        members = [j for j, o in owner.items() if o == p]
        out.append(Detection(scores.start[min(members)], scores.end[max(members)],
                             float(scores.step_m[p]), float(scores.z[p])))
    return out


def detect(series: ElementSeries, z_min: float, step_min_m: float, k: int = 6) -> list[Detection]:
    return pick(score_gaps(series, k=k), z_min, step_min_m)
