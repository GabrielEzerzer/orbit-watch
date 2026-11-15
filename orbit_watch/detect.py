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
suppression: within ``nms_days`` only the highest ``|z|`` survives (the gap
whose two sides are both clean scatters least, so it scores highest).

A gap is not scored when either side's ``k`` epochs span more than
``max_span_days`` or the gap itself is longer than ``max_gap_days``, so there
is no detection across a data outage such as 2022-06-15..19.

The same scoring runs on inclination (``channel="i"``, steps in degrees): a
north-south burn turns the orbit plane and changes the semi-major axis little.
``merge_channels`` adds inclination detections to the semi-major-axis ones,
dropping an inclination detection whose centre lies within ``nms_days`` of a
semi-major-axis detection's centre (the same non-maximum suppression, with the
semi-major-axis channel first, since ``z`` is not comparable across channels).

Duplicate epochs are already removed by ``to_series``.
"""

# shortcut: eccentricity is not used as a channel; add it if perigee-only burns need finding.

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
    step_m: np.ndarray  # extrapolated after-minus-before: metres, or degrees for channel "i" (NaN when not scored)
    z: np.ndarray  # step / standard error (NaN when not scored)
    sigma_m: np.ndarray  # residual scatter used, in step_m's unit
    channel: str = "a"  # "a" semi-major axis, "i" inclination

    @property
    def valid(self) -> np.ndarray:
        return np.isfinite(self.z)


@dataclass(frozen=True)
class Detection:
    start: np.datetime64  # epoch before the step
    end: np.datetime64  # epoch after the step
    step_m: float  # metres, or degrees when channel is "i"
    z: float
    channel: str = "a"

    @property
    def sign(self) -> int:
        return 1 if self.step_m > 0 else -1


def _days(epochs: np.ndarray) -> np.ndarray:
    return (epochs - epochs[0]).astype("int64") / _DAY_US


def _mad(r: np.ndarray) -> np.ndarray:
    return np.median(np.abs(r - np.median(r, axis=-1, keepdims=True)), axis=-1)


def score_gaps(
    series: ElementSeries, k: int = 6, max_span_days: float = 3.0, max_gap_days: float = 2.0,
    channel: str = "a",
) -> GapScores:
    """Score every gap on semi-major axis in metres (``channel="a"``) or inclination in degrees ("i")."""
    t = _days(series.epochs)
    y = {"a": lambda: series.semi_major_axis_km * 1000.0, "i": lambda: series.inclination}[channel]()
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
    return GapScores(series.epochs[:-1], series.epochs[1:], step, z, sigma, channel)


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
        Detection(scores.start[i], scores.end[i], float(scores.step_m[i]), float(scores.z[i]), scores.channel)
        for i in sorted(kept)
    ]


def _centre(d: Detection) -> np.datetime64:
    return d.start + (d.end - d.start) / 2


def merge_channels(a_dets: list[Detection], i_dets: list[Detection], nms_days: float = 1.0) -> list[Detection]:
    """``a_dets`` plus each of ``i_dets`` whose centre is more than ``nms_days`` from every ``a_dets`` centre."""
    tol = np.timedelta64(int(nms_days * _DAY_US), "us")
    ca = np.array([_centre(d) for d in a_dets], dtype="datetime64[us]")
    extra = [d for d in i_dets if not len(ca) or np.min(np.abs(ca - _centre(d))) > tol]
    return sorted(a_dets + extra, key=lambda d: d.start)


def detect(series: ElementSeries, z_min: float, step_min_m: float, k: int = 6) -> list[Detection]:
    return pick(score_gaps(series, k=k), z_min, step_min_m)
