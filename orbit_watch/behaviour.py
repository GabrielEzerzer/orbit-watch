# Behaviour of a GEO-region object over the days it is tracked, as 12 numbers from the existing pipeline (mode
# segments, burns, state changes, daily longitude, drift and semi-major axis), and a score for how
# far each object sits from every group of similar objects: the distance to its 10th nearest neighbour.

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from orbit_watch.events import HELD, _arcs_overlap
from orbit_watch.geo import wrap180
from orbit_watch.modes import _R_GEO_KM, Segment, day_of
from orbit_watch.routine import YEAR_DAYS, outside

FEATURES = ["held_share", "held_inc_share", "drifting_share", "librating_share", "burns_per_year",
            "burns_outside_holds_per_year", "relocation_starts_per_year", "median_hold_days",
            "lon_travelled_deg_per_year", "median_abs_drift_deg_per_day", "median_sma_offset_km", "sma_iqr_km"]
LOGGED = tuple(range(4, len(FEATURES)))
MIN_SETS = 100
MIN_TRACKED_DAYS = 180.0
CLIP = 5.0
NEIGHBOURS = 10
OUTSIDE_SHARE = 0.05
LIBRATING = ("librating_75E", "librating_105W", "librating_both")


def enough_data(sets: int, first_day: float, last_day: float) -> bool:
    return sets >= MIN_SETS and last_day - first_day >= MIN_TRACKED_DAYS


def _clipped(s: Segment, lo: float, hi: float) -> float:
    return max(0.0, min(day_of(s.end), hi) - max(day_of(s.start), lo))


def hold_lengths(segs: Sequence[Segment], lo: float, hi: float) -> list[float]:
    out: list[float] = []
    prev: Segment | None = None
    for s in segs:
        if s.mode not in HELD:
            prev = None
            continue
        length = _clipped(s, lo, hi)
        if prev is not None and prev.end == s.start and _arcs_overlap(prev, s):
            out[-1] += length
        else:
            out.append(length)
        prev = s
    return [x for x in out if x > 0]


def travelled(days: np.ndarray, lon: np.ndarray, rate: np.ndarray) -> float:
    if len(days) < 2:
        return 0.0
    dt = np.diff(days.astype(float))
    expected = 0.5 * (rate[1:] + rate[:-1]) * dt
    return float(np.abs(expected + wrap180(np.diff(lon.astype(float)) - expected)).sum())


def features(first_day: float, last_day: float, segs: Sequence[Segment], burn_days: np.ndarray,
             relocation_starts: int, days: np.ndarray, lon: np.ndarray, rate: np.ndarray, sma: np.ndarray) -> np.ndarray:
    tracked = last_day - first_day
    years = tracked / YEAR_DAYS

    def share(modes: Sequence[str]) -> float:
        return sum(_clipped(s, first_day, last_day) for s in segs if s.mode in modes) / tracked

    holds = [(day_of(s.start), day_of(s.end)) for s in segs if s.mode in HELD]
    lengths = hold_lengths(segs, first_day, last_day)
    sma = sma.astype(float)
    q1, q3 = np.percentile(sma, [25, 75])
    return np.array([
        share(HELD),
        share(("controlled_lon_inc",)),
        share(("drifting",)),
        share(LIBRATING),
        len(burn_days) / years,
        outside(burn_days, holds) / years,
        relocation_starts / years,
        float(np.median(lengths)) if lengths else 0.0,
        travelled(days, lon, rate) / years,
        float(np.median(np.abs(rate.astype(float)))),
        float(np.median(np.abs(sma - _R_GEO_KM))),
        float(q3 - q1),
    ])


def scaled(table: np.ndarray) -> np.ndarray:
    x = np.array(table, dtype=float)
    x[:, LOGGED] = np.log1p(x[:, LOGGED])
    sd = x.std(axis=0)
    z = np.divide(x - x.mean(axis=0), sd, out=np.zeros_like(x), where=sd > 0)
    return np.clip(z, -CLIP, CLIP)


def kth_neighbour(x: np.ndarray, k: int = NEIGHBOURS) -> tuple[np.ndarray, np.ndarray]:
    dist, idx = np.empty(len(x)), np.empty(len(x), dtype=int)
    for i in range(len(x)):
        d = np.sqrt(((x - x[i]) ** 2).sum(axis=1))
        d[i] = np.inf
        j = int(np.argpartition(d, k - 1)[k - 1])
        dist[i], idx[i] = d[j], j
    return dist, idx


def outside_flags(score: np.ndarray, share: float = OUTSIDE_SHARE) -> tuple[np.ndarray, float]:
    cut = float(np.quantile(score, 1.0 - share))
    return score >= cut, cut
