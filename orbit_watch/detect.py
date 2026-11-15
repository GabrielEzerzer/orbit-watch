# Step detection in a TLE semi-major-axis or inclination series: Theil-Sen detrending on k epochs
# each side of a gap, a median step scored against the TLE scatter, then non-maximum suppression.

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from orbit_watch.series import ElementSeries

_DAY_US = 86_400e6
_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class Setting:
    k: int
    z_min: float
    step_min_m: float
    nms_days: float = 1.0
    inc_z_min: float | None = None
    inc_step_min_deg: float | None = None

    def __post_init__(self):
        if (self.inc_z_min is None) != (self.inc_step_min_deg is None):
            raise ValueError(
                "the inclination channel needs both inc_z_min and inc_step_min_deg, or neither; got "
                f"inc_z_min={self.inc_z_min}, inc_step_min_deg={self.inc_step_min_deg}")

    @property
    def inc_channel(self) -> bool:
        return self.inc_step_min_deg is not None


@dataclass(frozen=True)
class GapScores:
    start: np.ndarray
    end: np.ndarray
    step_m: np.ndarray
    z: np.ndarray
    sigma_m: np.ndarray
    channel: str = "a"

    @property
    def valid(self) -> np.ndarray:
        return np.isfinite(self.z)


@dataclass(frozen=True)
class Detection:
    start: np.datetime64
    end: np.datetime64
    step_m: float
    z: float
    channel: str = "a"
    peak_start: np.datetime64 | None = None
    peak_end: np.datetime64 | None = None

    def __post_init__(self):
        if self.peak_start is None:
            object.__setattr__(self, "peak_start", self.start)
        if self.peak_end is None:
            object.__setattr__(self, "peak_end", self.end)

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
        off = np.arange(-k + 1, k + 1)
        tw, yw = t[ii[:, None] + off], y[ii[:, None] + off]
        mid = 0.5 * (t[ii] + t[ii + 1])[:, None]
        p, q = np.triu_indices(k, 1)
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
        Detection(scores.start[i], scores.end[i], float(scores.step_m[i]), float(scores.z[i]), scores.channel,
                  scores.start[i], scores.end[i])
        for i in sorted(kept)
    ]


def _centre(d: Detection) -> np.datetime64:
    return d.start + (d.end - d.start) / 2


def merge_channels(a_dets: list[Detection], i_dets: list[Detection], nms_days: float = 1.0) -> list[Detection]:
    tol = np.timedelta64(int(nms_days * _DAY_US), "us")
    ca = np.array([_centre(d) for d in a_dets], dtype="datetime64[us]")
    extra = [d for d in i_dets if not len(ca) or np.min(np.abs(ca - _centre(d))) > tol]
    return sorted(a_dets + extra, key=lambda d: d.start)


def pick_setting(a_scores: GapScores, i_scores: GapScores | None, s: Setting) -> list[Detection]:
    if a_scores.channel != "a" or (s.inc_channel and (i_scores is None or i_scores.channel != "i")):
        raise ValueError("pick_setting needs semi-major-axis scores, and inclination scores when the "
                         "setting turns the inclination channel on")
    dets = pick(a_scores, s.z_min, s.step_min_m, s.nms_days)
    if not s.inc_channel:
        return dets
    return merge_channels(dets, pick(i_scores, s.inc_z_min, s.inc_step_min_deg, s.nms_days), s.nms_days)


def detect(series: ElementSeries, s: Setting) -> list[Detection]:
    i_scores = score_gaps(series, k=s.k, channel="i") if s.inc_channel else None
    return pick_setting(score_gaps(series, k=s.k), i_scores, s)
