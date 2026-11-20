# Operating mode of a GEO-region object through time in ESA's classes (Classification of Geosynchronous
# Objects, issue 21, 2019), per 30-day window from 2021 to 2026, merged into segments.

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from math import cos, factorial, radians, sin, sqrt

import numpy as np

from orbit_watch.elements import ElementSet
from orbit_watch.geo import drift_rate, gmst_deg, wrap180

WINDOW_DAYS = 30
GRID_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
GRID_END = datetime(2026, 1, 1, tzinfo=timezone.utc)
N_DAYS = (GRID_END - GRID_START).days
MIN_SETS = 5
MIN_SPAN_DAYS = 10.0
HELD_SPREAD_DEG = 0.3
FREE_RESIDUAL_DEG = 0.02
SPLIT_RESIDUAL_DEG = 3 * FREE_RESIDUAL_DEG
NEIGHBOUR_REACH = 3
DROP_WORST = 3
HELD_RUN = 3
BOX_DEG = 1.5
FREE_SHIFT_DEG = 0.5
FREE_SCALE = (0.8, 1.25)
MOVING_SWING = 4.0
YEAR_DAYS = 365
C1_MAX_INCLINATION_DEG = 0.3
SAWTOOTH_MIN = 2
INCLINED_MIN_DEG = 25.0
REGION_A_KM = (37948.0, 46380.0)
REGION_E_MAX = 0.25
SIDEREAL_REV_PER_DAY = 1.00273790935

MODES = (
    "controlled_lon_inc", "controlled_lon", "drifting", "librating_75E", "librating_105W",
    "librating_both", "inclined", "undetermined", "out_of_region",
)

_EGM96 = {
    (2, 2): (2.43914352398e-06, -1.40016683654e-06),
    (3, 1): (2.03046201047e-06, 2.48200415856e-07),
    (3, 3): (7.21321757121e-07, 1.41434926192e-06),
}
_MU_KM3_S2 = 398600.4415
_R_EARTH_KM = 6378.1363
_R_GEO_KM = 42164.17


def day_of(t: datetime | date) -> float:
    if not isinstance(t, datetime):
        t = datetime(t.year, t.month, t.day, tzinfo=GRID_START.tzinfo)
    return (t - GRID_START).total_seconds() / 86400.0


def _inclination_function(n: int, m: int, inc_deg: float) -> float:
    c, s2 = cos(radians(inc_deg)), sin(radians(inc_deg)) ** 2
    return {(2, 2): 0.75 * (1 + c) ** 2,
            (3, 1): 15 / 16 * s2 * (1 + 3 * c) - 0.75 * (1 + c),
            (3, 3): 1.875 * (1 + c) ** 3}[n, m]


def _tesseral_terms(lon_deg, inc_deg=0.0):
    lam = np.radians(np.asarray(lon_deg, dtype=float))
    for (n, m), (c, s) in _EGM96.items():
        norm = sqrt(2 * (2 * n + 1) * factorial(n - m) / factorial(n + m))
        k = (3.0 / _R_GEO_KM**2 * 86400.0**2 * (_MU_KM3_S2 / _R_GEO_KM) * (_R_EARTH_KM / _R_GEO_KM) ** n
             * norm * _inclination_function(n, m, inc_deg))
        yield m, k * c, k * s, lam


def tesseral_potential(lon_deg: np.ndarray | float, inc_deg: float = 0.0) -> np.ndarray | float:
    return sum(kc * np.cos(m * lam) + ks * np.sin(m * lam) for m, kc, ks, lam in _tesseral_terms(lon_deg, inc_deg))


def longitude_acceleration(lon_deg: np.ndarray | float, inc_deg: float = 0.0) -> np.ndarray | float:
    return np.degrees(sum(m * (kc * np.sin(m * lam) - ks * np.cos(m * lam))
                          for m, kc, ks, lam in _tesseral_terms(lon_deg, inc_deg)))


def _extrema() -> tuple[float, float, float, float]:
    lon = np.arange(0.0, 360.0, 0.01)
    v = tesseral_potential(lon)
    is_min = (v < np.roll(v, 1)) & (v < np.roll(v, -1))
    is_max = (v > np.roll(v, 1)) & (v > np.roll(v, -1))
    mins, maxs = lon[is_min], lon[is_max]
    east, west = sorted(mins, key=lambda x: abs(x - 75.0))[0], sorted(mins, key=lambda x: abs(x - 255.0))[0]
    low, high = sorted(maxs, key=lambda x: tesseral_potential(x))
    return float(east), float(west), float(low), float(high)


STABLE_EAST_DEG, STABLE_WEST_DEG, BARRIER_LOW_DEG, BARRIER_HIGH_DEG = _extrema()


def energy(lon_deg: float, drift_deg_per_day: float, inc_deg: float = 0.0) -> float:
    return float(0.5 * np.radians(drift_deg_per_day) ** 2 + tesseral_potential(lon_deg, inc_deg))


def libration_mode(energy_: float, lon_deg: float, inc_deg: float = 0.0) -> str:
    if energy_ >= tesseral_potential(BARRIER_HIGH_DEG, inc_deg):
        return "drifting"
    if energy_ >= tesseral_potential(BARRIER_LOW_DEG, inc_deg):
        return "librating_both"
    east_of_low = (lon_deg - BARRIER_LOW_DEG) % 360.0
    return "librating_75E" if east_of_low < (BARRIER_HIGH_DEG - BARRIER_LOW_DEG) % 360.0 else "librating_105W"


@dataclass(frozen=True)
class Track:
    norad_id: int
    days: np.ndarray
    lon: np.ndarray
    rate: np.ndarray
    inclination: np.ndarray
    semi_major_axis_km: np.ndarray
    eccentricity: np.ndarray
    raan: np.ndarray | None = None


def mean_longitude(record: ElementSet) -> float:
    return float(wrap180(record.raan + record.arg_perigee + record.mean_anomaly - gmst_deg(record.epoch)))


def track(records: Sequence[ElementSet]) -> Track:
    days = np.array([(r.epoch - GRID_START).total_seconds() / 86400.0 for r in records])
    return Track(
        norad_id=records[0].norad_id,
        days=days,
        lon=np.array([mean_longitude(r) for r in records]),
        rate=np.array([360.0 * (r.mean_motion - SIDEREAL_REV_PER_DAY) for r in records]),
        inclination=np.array([r.inclination for r in records]),
        semi_major_axis_km=np.array([r.semi_major_axis_km for r in records]),
        eccentricity=np.array([r.eccentricity for r in records]),
        raan=np.array([r.raan for r in records]),
    )


def window_edges() -> np.ndarray:
    end = (GRID_END - GRID_START).days
    return np.unique(np.concatenate([[0.0], np.arange(end, 0, -WINDOW_DAYS)[::-1].astype(float)]))


def _unwrapped(days: np.ndarray, lon: np.ndarray, rate: float) -> np.ndarray:
    return np.degrees(np.unwrap(np.radians(lon - rate * days))) + rate * days


def _spread(days: np.ndarray, lon: np.ndarray, rate: np.ndarray) -> float:
    u = _unwrapped(days, lon, float(np.median(rate)))
    p5, p95 = np.percentile(u, [5, 95])
    return float(p95 - p5)


def _arc(lon: np.ndarray) -> tuple[float, float]:
    x = np.sort(np.asarray(lon) % 360.0)
    gaps = np.diff(np.concatenate([x, [x[0] + 360.0]]))
    i = int(np.argmax(gaps))
    return float(wrap180(x[(i + 1) % len(x)])), float(wrap180(x[i]))


def _free_residuals(days: np.ndarray, u: np.ndarray, accel: float | None = None) -> np.ndarray:
    t = days - days.mean()
    y, basis = (u, [t**2, t, np.ones_like(t)]) if accel is None else (u - 0.5 * accel * t**2, [t**3, t, np.ones_like(t)])
    a = np.column_stack(basis)
    return y - a @ np.linalg.lstsq(a, y, rcond=None)[0]


def _free_residual(days: np.ndarray, u: np.ndarray, accel: float | None = None) -> float:
    return float(1.4826 * np.median(np.abs(_free_residuals(days, u, accel))))


def _free_path(days: np.ndarray, u: np.ndarray, inc_deg: float) -> tuple[float, float]:
    mean = float(np.mean(u))
    a0 = float(longitude_acceleration(mean, inc_deg))
    a1 = float(longitude_acceleration(mean + 0.01, inc_deg) - longitude_acceleration(mean - 0.01, inc_deg)) / 0.02
    t = days - days.mean()
    half = float(np.abs(t).max())
    p, eq = u - mean, -a0 / a1
    best = (float("inf"), 0.0)
    for s in np.linspace(*FREE_SCALE, 46):
        g = sqrt(abs(s * a1))
        b = (np.column_stack([np.cos(g * t), np.sin(g * t)]) if a1 < 0
             else np.column_stack([np.exp(g * (t - half)), np.exp(-g * (t + half))]))
        a = np.column_stack([np.ones_like(t), b])
        coef = np.linalg.lstsq(a, p, rcond=None)[0]
        if abs(coef[0] - eq) > FREE_SHIFT_DEG:
            centre = eq + np.copysign(FREE_SHIFT_DEG, coef[0] - eq)
            coef = np.concatenate([[centre], np.linalg.lstsq(b, p - centre, rcond=None)[0]])
        path = a @ coef
        misfit = float(1.4826 * np.median(np.abs(p - path)))
        if misfit < best[0]:
            best = (misfit, float(path.max() - path.min()))
    return best


@dataclass(frozen=True)
class Window:
    start: float
    end: float
    mode: str
    n_sets: int
    lon_min: float = float("nan")
    lon_max: float = float("nan")
    drift: float = float("nan")
    inc_min: float = float("nan")
    inc_max: float = float("nan")


def classify(tr: Track) -> list[Window]:
    edges = window_edges()
    first = max(int(np.searchsorted(edges, tr.days[0], side="right")) - 1, 0)
    last = min(int(np.searchsorted(edges, tr.days[-1], side="right")) - 1, len(edges) - 2)
    bounds = np.searchsorted(tr.days, edges)
    idx = [np.arange(bounds[k], bounds[k + 1]) for k in range(len(edges) - 1)]

    def enough(k: int) -> bool:
        sel = idx[k]
        return len(sel) >= MIN_SETS and tr.days[sel[-1]] - tr.days[sel[0]] >= MIN_SPAN_DAYS

    def spread(sel: np.ndarray) -> float:
        return _spread(tr.days[sel], tr.lon[sel], tr.rate[sel])

    def free_residual(sel: np.ndarray, pinned: bool = False, drop: int = 0) -> float:
        d = tr.days[sel]
        u = _unwrapped(d, tr.lon[sel], float(np.median(tr.rate[sel])))
        accel = float(longitude_acceleration(float(wrap180(np.mean(u))), float(np.median(tr.inclination[sel]))))
        accel = accel if pinned else None
        for _ in range(min(drop, len(d) - MIN_SETS)):
            keep = np.arange(len(d)) != np.argmax(np.abs(_free_residuals(d, u, accel)))
            d, u = d[keep], u[keep]
        return _free_residual(d, u, accel)

    def nearest_with_data(k: int, step: int) -> int | None:
        return next((j for j in range(k + step, k + step * (NEIGHBOUR_REACH + 1), step)
                     if 0 <= j < len(idx) and enough(j)), None)

    @lru_cache(maxsize=None)
    def burn(k: int) -> bool:
        if free_residual(idx[k]) <= FREE_RESIDUAL_DEG:
            return False
        before, after = nearest_with_data(k, -1), nearest_with_data(k, 1)
        if before is None or after is None:
            return free_residual(idx[k], drop=DROP_WORST) > FREE_RESIDUAL_DEG
        return free_residual(np.concatenate([idx[before], idx[after]]), pinned=True) > FREE_RESIDUAL_DEG

    @lru_cache(maxsize=None)
    def run_spread(j: int) -> float:
        return spread(np.concatenate([idx[i] for i in range(j, j + HELD_RUN)]))

    def held(k: int) -> bool:
        return enough(k) and spread(idx[k]) <= HELD_SPREAD_DEG

    def chain(k: int) -> tuple[int, int]:
        a, b = k, k
        while a > 0 and held(a - 1):
            a -= 1
        while b < len(idx) - 1 and held(b + 1):
            b += 1
        return a, b

    @lru_cache(maxsize=None)
    def chain_free(a: int, b: int) -> bool:
        sel = np.concatenate(idx[a:b + 1])
        u = _unwrapped(tr.days[sel], tr.lon[sel], float(np.median(tr.rate[sel])))
        misfit, swing = _free_path(tr.days[sel], u, float(np.median(tr.inclination[sel])))
        return misfit <= SPLIT_RESIDUAL_DEG and swing > MOVING_SWING * misfit

    def chain_days(a: int, b: int) -> float:
        return float(tr.days[idx[b][-1]] - tr.days[idx[a][0]])

    def bracketed(k: int) -> bool:
        a, b = chain(k)
        u = _unwrapped(tr.days[idx[k]], tr.lon[idx[k]], float(np.median(tr.rate[idx[k]])))
        return (float(np.ptp(u)) <= HELD_SPREAD_DEG
                and all(0 <= j < len(idx) and enough(j) and burn(j) for j in (a - 1, b + 1)))

    inc_median = {k: float(np.median(tr.inclination[idx[k]])) for k in range(len(idx)) if enough(k)}
    low_inc = sorted(k for k, v in inc_median.items() if v <= C1_MAX_INCLINATION_DEG)
    low_groups = [[low_inc[0]]] if low_inc else []
    for j in low_inc[1:]:
        if (j - low_groups[-1][-1]) * WINDOW_DAYS <= YEAR_DAYS:
            low_groups[-1].append(j)
        else:
            low_groups.append([j])

    def inclination_held(k: int) -> bool:
        return any(g[0] <= k <= g[-1] and (g[-1] - g[0] + 1) * WINDOW_DAYS > YEAR_DAYS for g in low_groups)

    inc_peak = {k: float(tr.inclination[idx[k]].max()) for k in inc_median}
    closed = [(b - a - 1, max(inc_peak[j] for j in range(a, b + 1) if j in inc_median))
              for a, b in zip(low_inc, low_inc[1:])
              if (b - a) * WINDOW_DAYS <= YEAR_DAYS and any(j in inc_median for j in range(a + 1, b))]

    def open_edge_c1(i: int) -> bool:
        if len(closed) < SAWTOOTH_MIN or 0 < i < len(low_inc):
            return False
        edge = [j for j in inc_median if (j >= low_inc[-1] if i else j <= low_inc[0])]
        length = (max(edge) - low_inc[-1]) if i else (low_inc[0] - min(edge))
        return (length <= max(n for n, _ in closed)
                and max(inc_peak[j] for j in edge) <= max(p for _, p in closed))

    def c1(k: int) -> bool:
        if inc_median[k] <= C1_MAX_INCLINATION_DEG:
            return True
        i = bisect_left(low_inc, k)
        if 0 < i < len(low_inc):
            return (low_inc[i] - low_inc[i - 1]) * WINDOW_DAYS <= YEAR_DAYS
        return open_edge_c1(i)

    rows, free, slow = [], {}, {}
    for k in range(first, last + 1):
        sel = idx[k]
        start, end = float(edges[k]), float(edges[k + 1])
        if not enough(k):
            rows.append(dict(start=start, end=end, mode="undetermined", n_sets=len(sel)))
            continue
        d, lon, inc = tr.days[sel], tr.lon[sel], tr.inclination[sel]
        r = float(np.median(tr.rate[sel]))
        drift = drift_rate(d, wrap180(lon - r * d)) + r
        u = _unwrapped(d, lon, r)
        west, east = _arc(lon)
        evidence = dict(lon_min=west, lon_max=east, drift=drift, inc_min=float(inc.min()), inc_max=float(inc.max()))
        still = spread(sel) <= HELD_SPREAD_DEG
        runs = [j for j in range(k - HELD_RUN + 1, k + 1)
                if j >= 0 and j + HELD_RUN <= len(idx) and all(enough(i) for i in range(j, j + HELD_RUN))]
        mean_lon = float(wrap180(np.mean(u)))
        accel = abs(float(longitude_acceleration(mean_lon, inc_median[k])))
        free_sag = 0.45 * accel * ((d[-1] - d[0]) / 2) ** 2
        run_held = any(run_spread(j) <= HELD_SPREAD_DEG for j in runs)
        free_hold = False
        if run_held and 0.45 * accel * (HELD_RUN * WINDOW_DAYS / 2) ** 2 < HELD_SPREAD_DEG:
            burnt = any(run_spread(j) <= HELD_SPREAD_DEG and any(burn(i) for i in range(j, j + HELD_RUN)) for j in runs)
            a, b = chain(k)
            free_chain = not burnt and not inclination_held(k) and chain_free(a, b)
            run_held = not free_chain
            free_hold = free_chain and chain_days(a, b) > YEAR_DAYS
        tight = still and (run_held or spread(sel) < 0.5 * free_sag or (not free_hold and bracketed(k)))
        wide = spread(sel) <= BOX_DEG and any(run_spread(j) <= BOX_DEG and any(burn(i) for i in range(j, j + HELD_RUN)) for j in runs)
        if not (REGION_A_KM[0] <= np.median(tr.semi_major_axis_km[sel]) <= REGION_A_KM[1]
                and np.median(tr.eccentricity[sel]) <= REGION_E_MAX):
            mode = "out_of_region"
        elif np.median(inc) > INCLINED_MIN_DEG:
            mode = "inclined"
        elif tight or wide:
            mode = "controlled_lon_inc" if c1(k) else "controlled_lon"
        elif still and not free_hold:
            mode = "undetermined"
            slow[k] = mean_lon
        elif burn(k):
            mode = "drifting"
        else:
            mode = None
            free[k] = (energy(mean_lon, drift, inc_median[k]), mean_lon, inc_median[k])
        rows.append(dict(start=start, end=end, mode=mode, n_sets=len(sel), **evidence))
    lon_of = {**slow, **{k: v[1] for k, v in free.items()}}

    def manoeuvre_between(k: int) -> bool:
        return (max(free_residual(idx[k - 1]), free_residual(idx[k])) <= FREE_RESIDUAL_DEG
                and free_residual(np.concatenate([idx[k - 1], idx[k]]), pinned=True) > SPLIT_RESIDUAL_DEG)

    def crossed(path: np.ndarray, barrier: float) -> bool:
        return bool(np.floor((path.max() - barrier) / 360.0) > np.floor((path.min() - barrier) / 360.0))

    runs: list[list[int]] = []
    for k in sorted(lon_of):
        if runs and runs[-1][-1] == k - 1 and not manoeuvre_between(k):
            runs[-1].append(k)
        else:
            runs.append([k])
    for run in runs:
        moving = [k for k in run if k in free]
        if not moving:
            continue
        e = float(np.median([free[k][0] for k in moving]))
        i = float(np.median([free[k][2] for k in moving]))
        mode = Counter(libration_mode(e, free[k][1], i) for k in moving).most_common(1)[0][0]
        path = np.degrees(np.unwrap(np.radians([lon_of[k] for k in run])))
        if crossed(path, BARRIER_HIGH_DEG):
            mode = "drifting"
        elif crossed(path, BARRIER_LOW_DEG) and mode in ("librating_75E", "librating_105W"):
            mode = "librating_both"
        for k in moving:
            rows[k - first]["mode"] = mode
    return [Window(**r) for r in rows]


@dataclass(frozen=True)
class Segment:
    norad_id: int
    start: datetime
    end: datetime
    mode: str
    windows: int
    n_sets: int
    lon_min: float
    lon_max: float
    drift_mean: float
    inc_min: float
    inc_max: float


def segments(tr: Track) -> list[Segment]:
    out: list[Segment] = []
    groups: list[list[Window]] = []
    for w in classify(tr):
        if groups and groups[-1][-1].mode == w.mode:
            groups[-1].append(w)
        else:
            groups.append([w])
    for g in groups:
        sel = (tr.days >= g[0].start) & (tr.days < g[-1].end)
        lon, inc = tr.lon[sel], tr.inclination[sel]
        drifts = [w.drift for w in g if not np.isnan(w.drift)]
        out.append(Segment(
            norad_id=tr.norad_id,
            start=GRID_START + timedelta(days=g[0].start),
            end=GRID_START + timedelta(days=g[-1].end),
            mode=g[0].mode,
            windows=len(g),
            n_sets=int(sel.sum()),
            lon_min=_arc(lon)[0] if len(lon) else float("nan"),
            lon_max=_arc(lon)[1] if len(lon) else float("nan"),
            drift_mean=float(np.mean(drifts)) if drifts else float("nan"),
            inc_min=float(inc.min()) if len(inc) else float("nan"),
            inc_max=float(inc.max()) if len(inc) else float("nan"),
        ))
    return out
