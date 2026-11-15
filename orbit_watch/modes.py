"""Operating mode of a GEO-region object through time: layer 1 of a routine model for the GEO belt.

The classes are the European Space Agency's, from ESA Space Debris Office, *Classification of
Geosynchronous Objects*, Issue 21.0, 19 July 2019, reference GEN-DB-LOG-00270-OPS-SD (status at
1 January 2019), section 2 and table 1. Issue 21 is the newest issue we could reach (copy at
https://astronomer.ru/data/0128/Classification_of_Geosynchronous_Objects_I21R0.pdf; ESA itself
does not host it publicly). ESA's classes and the mode names used here:

==================  ====  ============================================================================
mode                ESA   rule here
==================  ====  ============================================================================
controlled_lon_inc  C1    longitude held (below) and median inclination at most 0.3 deg (ESA's 0.3)
controlled_lon      C2    longitude held and median inclination above 0.3 deg
drifting            D     not held, and too fast to be trapped by the stable points (energy, below)
librating_75E       L1    not held, trapped in the well of the eastern stable point (75 deg E)
librating_105W      L2    not held, trapped in the well of the western stable point (105 deg W)
librating_both      L3    not held, above the lower barrier but below the higher one: swings over both
inclined            I     median inclination above 25 deg (ESA's 25)
undetermined        Ind   too few element sets, or a held longitude with no neighbouring data to
                          tell station-keeping from a librator at the turning point of its swing
out_of_region       --    median semi-major axis outside 37,948-46,380 km or eccentricity above 0.25
                          (the union of ESA's GEO, IGO and EGO classes, table 1)
==================  ====  ============================================================================

ESA's C4 (a controlled drift orbit) is not separated: telling it from D needs manoeuvre detection,
which is the next layer. Such windows read as drifting or librating.

ESA classifies one snapshot a year from a year of history. Here the time from 2021-01-01 to
2026-01-01 is cut into fixed 30-day windows, laid backwards from 2026-01-01 so every object shares
the same grid (the first window is 26 days long). Each window is classified from its own element
sets, and adjacent windows with the same mode are merged into segments. Choices that ESA's yearly
rule does not make for us, one line each:

* 30 days: long enough to hold a full east-west station-keeping cycle (about two weeks for most
  operators) and 30 or more element sets, short enough to date a relocation to within a month.
* At least ``MIN_SETS`` element sets spanning ``MIN_SPAN_DAYS``: fewer cannot give a drift rate,
  so the window is undetermined rather than guessed.
* Longitude is the *mean* longitude (right ascension of the node + argument of perigee + mean
  anomaly - Greenwich mean sidereal time), the quantity ESA tabulates. The sub-satellite longitude
  (``geo.longitudes``) also carries the daily figure-eight of an inclined orbit, about +-1 deg at
  15 deg inclination, which would make inclined kept satellites look loose.
* "Longitude held": the 5th-95th percentile spread of the mean longitude in the window is at most
  ``HELD_SPREAD_DEG`` = 0.3 deg. The percentile drops a stray element set or two. ITU's
  east-west tolerance for geostationary stations is +-0.1 deg (Radio Regulations No. 22.6), a
  0.2 deg spread; 0.3 leaves room for TLE noise and wider boxes, and sits in the gap of the
  spread distribution (on a sample of 150 objects, 2,627 windows below 0.15 deg, 147 between
  0.15 and 0.5 deg, and the rest above).
* A free object at the turning point of a libration also sits still for a month or more, so a
  held window counts as controlled only if three consecutive windows that include it (90 days)
  are held together, or if it is stiller than a free object could be at that longitude (the
  natural acceleration bends a free path by a known amount). Otherwise it is undetermined.
  Without this, librators flicker into "controlled" at every turning point. Over 90 days a free
  object turning more than about 6 deg from a stable point bends by more than the held spread;
  smaller swings still pass as controlled (ESA corrects those by hand, section 4).
* A window the energy calls trapped counts as librating only if its longitude follows a free
  path: the robust scatter about a quadratic in time is at most ``FREE_RESIDUAL_DEG``. Free
  librators sit near 0.001 deg (95th percentile 0.007 deg in a sample of 200 objects); a
  window with a burn in it (the start or end of a relocation) does not, and reads as drifting.
* Trapped or drifting: with the longitude acceleration of the Earth's tesseral harmonics
  (``tesseral_potential``), ``1/2 * drift**2 + potential(longitude)`` is conserved for a free object.
  Comparing it with the two potential maxima says whether the object is trapped in one well
  (L1, L2), swings over both (L3) or circulates (D), from one window, wherever in its swing it is.
"""

# shortcut: segment boundaries fall on the 30-day grid, so a mode change is dated to within a
# window; refine boundaries with the element sets near each change if a later layer needs days.
# shortcut: the tesseral potential is evaluated on the equator at the geostationary radius; it is
# only used below 25 deg inclination, where cos(i) > 0.9. Use the full potential for inclined objects.
# shortcut: a whole window of a relocation slower than about 0.45 deg/day, with no burn in it, is
# free and trapped, so it reads as librating (ESA's C4 is not separated); manoeuvre detection
# (layer 2) can tell it apart.
# shortcut: librators swinging less than about 6 deg from a stable point read as controlled at the
# turning points of their swing; a longer held run would catch them at the cost of short parks.

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from math import factorial, sqrt

import numpy as np

from orbit_watch.elements import ElementSet
from orbit_watch.geo import drift_rate, gmst_deg, wrap180

WINDOW_DAYS = 30
GRID_START = datetime(2021, 1, 1, tzinfo=timezone.utc)
GRID_END = datetime(2026, 1, 1, tzinfo=timezone.utc)
MIN_SETS = 5
MIN_SPAN_DAYS = 10.0
HELD_SPREAD_DEG = 0.3
FREE_RESIDUAL_DEG = 0.02
HELD_RUN = 3  # windows
C1_MAX_INCLINATION_DEG = 0.3  # ESA, section 2, C1
INCLINED_MIN_DEG = 25.0  # ESA, section 2, I
REGION_A_KM = (37948.0, 46380.0)  # ESA, table 1, IGO and EGO
REGION_E_MAX = 0.25  # ESA, table 1
SIDEREAL_REV_PER_DAY = 1.00273790935

MODES = (
    "controlled_lon_inc", "controlled_lon", "drifting", "librating_75E", "librating_105W",
    "librating_both", "inclined", "undetermined", "out_of_region",
)

# EGM96 fully normalised tesseral coefficients (Lemoine et al., NASA/TP-1998-206861) for the
# terms that do not vanish on the equator up to degree 3: (n, m): (C, S).
_EGM96 = {
    (2, 2): (2.43914352398e-06, -1.40016683654e-06),
    (3, 1): (2.03046201047e-06, 2.48200415856e-07),
    (3, 3): (7.21321757121e-07, 1.41434926192e-06),
}
_P_EQUATOR = {(2, 2): 3.0, (3, 1): -1.5, (3, 3): 15.0}  # unnormalised P_nm(0)
_MU_KM3_S2 = 398600.4415
_R_EARTH_KM = 6378.1363
_R_GEO_KM = 42164.17


def _tesseral_terms(lon_deg):
    """(n, m, coefficient on cos(m lon), coefficient on sin(m lon), lon in rad) of 3 U / r^2 in (rad/day)^2."""
    lam = np.radians(np.asarray(lon_deg, dtype=float))
    for (n, m), (c, s) in _EGM96.items():
        norm = sqrt(2 * (2 * n + 1) * factorial(n - m) / factorial(n + m))
        k = (3.0 / _R_GEO_KM**2 * 86400.0**2 * (_MU_KM3_S2 / _R_GEO_KM) * (_R_EARTH_KM / _R_GEO_KM) ** n
             * norm * _P_EQUATOR[n, m])
        yield m, k * c, k * s, lam


def tesseral_potential(lon_deg: np.ndarray | float) -> np.ndarray | float:
    """Longitude potential of a geostationary object, (rad/day)^2.

    A tangential acceleration ``(1/r) dU/dlon`` changes the semi-major axis, and the drift rate
    follows: ``d2lon/dt2 = -(3 / r^2) dU/dlon``. So with ``V = 3 U / r^2``, ``d2lon/dt2 = -dV/dlon``
    and ``1/2 (dlon/dt)^2 + V(lon)`` is conserved. Minima of ``V`` are the stable points.
    """
    return sum(kc * np.cos(m * lam) + ks * np.sin(m * lam) for m, kc, ks, lam in _tesseral_terms(lon_deg))


def longitude_acceleration(lon_deg: np.ndarray | float) -> np.ndarray | float:
    """Natural longitude acceleration ``-dV/dlon`` of a free geostationary object, deg/day^2."""
    return np.degrees(sum(m * (kc * np.sin(m * lam) - ks * np.cos(m * lam))
                          for m, kc, ks, lam in _tesseral_terms(lon_deg)))


def _extrema() -> tuple[float, float, float, float]:
    """Longitudes (deg, [0, 360)) of the eastern and western stable points and the lower and
    higher potential maxima, found on a 0.01 deg grid."""
    lon = np.arange(0.0, 360.0, 0.01)
    v = tesseral_potential(lon)
    is_min = (v < np.roll(v, 1)) & (v < np.roll(v, -1))
    is_max = (v > np.roll(v, 1)) & (v > np.roll(v, -1))
    mins, maxs = lon[is_min], lon[is_max]
    east, west = sorted(mins, key=lambda x: abs(x - 75.0))[0], sorted(mins, key=lambda x: abs(x - 255.0))[0]
    low, high = sorted(maxs, key=lambda x: tesseral_potential(x))
    return float(east), float(west), float(low), float(high)


STABLE_EAST_DEG, STABLE_WEST_DEG, BARRIER_LOW_DEG, BARRIER_HIGH_DEG = _extrema()
_V_LOW, _V_HIGH = float(tesseral_potential(BARRIER_LOW_DEG)), float(tesseral_potential(BARRIER_HIGH_DEG))


def libration_mode(lon_deg: float, drift_deg_per_day: float) -> str:
    """drifting, librating_75E, librating_105W or librating_both, from the conserved energy."""
    energy = 0.5 * np.radians(drift_deg_per_day) ** 2 + tesseral_potential(lon_deg)
    if energy >= _V_HIGH:
        return "drifting"
    if energy >= _V_LOW:
        return "librating_both"
    # Trapped in one well: the eastern well lies between the two barriers going east from the low one.
    east_of_low = (lon_deg - BARRIER_LOW_DEG) % 360.0
    return "librating_75E" if east_of_low < (BARRIER_HIGH_DEG - BARRIER_LOW_DEG) % 360.0 else "librating_105W"


@dataclass(frozen=True)
class Track:
    """What the classifier needs from one object's element sets, in epoch order."""

    norad_id: int
    days: np.ndarray  # days since GRID_START
    lon: np.ndarray  # mean longitude, deg east, [-180, 180)
    rate: np.ndarray  # drift implied by the mean motion, deg/day (a guide for unwrapping only)
    inclination: np.ndarray
    semi_major_axis_km: np.ndarray
    eccentricity: np.ndarray


def mean_longitude(record: ElementSet) -> float:
    """Mean longitude (deg east, [-180, 180)) of ``record`` at its epoch."""
    return float(wrap180(record.raan + record.arg_perigee + record.mean_anomaly - gmst_deg(record.epoch)))


def track(records: Sequence[ElementSet]) -> Track:
    """A ``Track`` from one object's element sets (epoch order, one per epoch, as ``to_series`` keeps)."""
    days = np.array([(r.epoch - GRID_START).total_seconds() / 86400.0 for r in records])
    return Track(
        norad_id=records[0].norad_id,
        days=days,
        lon=np.array([mean_longitude(r) for r in records]),
        rate=np.array([360.0 * (r.mean_motion - SIDEREAL_REV_PER_DAY) for r in records]),
        inclination=np.array([r.inclination for r in records]),
        semi_major_axis_km=np.array([r.semi_major_axis_km for r in records]),
        eccentricity=np.array([r.eccentricity for r in records]),
    )


def window_edges() -> np.ndarray:
    """Window boundaries in days since GRID_START: 30-day windows laid back from GRID_END."""
    end = (GRID_END - GRID_START).days
    return np.unique(np.concatenate([[0.0], np.arange(end, 0, -WINDOW_DAYS)[::-1].astype(float)]))


def _unwrapped(days: np.ndarray, lon: np.ndarray, rate: float) -> np.ndarray:
    """Longitudes made continuous. The mean-motion drift is taken out first, so a fast drifter
    with sparse element sets does not alias, then put back."""
    return np.degrees(np.unwrap(np.radians(lon - rate * days))) + rate * days


def _spread(days: np.ndarray, lon: np.ndarray, rate: np.ndarray) -> float:
    u = _unwrapped(days, lon, float(np.median(rate)))
    p5, p95 = np.percentile(u, [5, 95])
    return float(p95 - p5)


def _arc(lon: np.ndarray) -> tuple[float, float]:
    """(west end, east end) of the shortest arc holding every longitude, deg in [-180, 180);
    west > east when the arc crosses 180 deg."""
    x = np.sort(np.asarray(lon) % 360.0)
    gaps = np.diff(np.concatenate([x, [x[0] + 360.0]]))
    i = int(np.argmax(gaps))
    return float(wrap180(x[(i + 1) % len(x)])), float(wrap180(x[i]))


def _free_residual(days: np.ndarray, u: np.ndarray) -> float:
    """Robust scatter (1.4826 x median absolute residual, deg) of the unwrapped longitude about a
    quadratic in time: a free object's 30-day path is that quadratic, a manoeuvre breaks it."""
    t = days - days.mean()
    r = u - np.polyval(np.polyfit(t, u, 2), t)
    return float(1.4826 * np.median(np.abs(r)))


@dataclass(frozen=True)
class Window:
    start: float  # days since GRID_START
    end: float
    mode: str
    n_sets: int
    lon_min: float = float("nan")  # west end of the shortest arc of longitudes, deg east
    lon_max: float = float("nan")  # east end
    drift: float = float("nan")  # least-squares deg/day
    inc_min: float = float("nan")
    inc_max: float = float("nan")


def classify(tr: Track) -> list[Window]:
    """One ``Window`` per grid window from the object's first to its last element set."""
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

    out = []
    for k in range(first, last + 1):
        sel = idx[k]
        start, end = float(edges[k]), float(edges[k + 1])
        if not enough(k):
            out.append(Window(start, end, "undetermined", len(sel)))
            continue
        d, lon, inc = tr.days[sel], tr.lon[sel], tr.inclination[sel]
        r = float(np.median(tr.rate[sel]))
        drift = drift_rate(d, wrap180(lon - r * d)) + r
        u = _unwrapped(d, lon, r)
        west, east = _arc(lon)
        evidence = dict(lon_min=west, lon_max=east, drift=drift, inc_min=float(inc.min()), inc_max=float(inc.max()))
        held_spread = spread(sel)
        if not (REGION_A_KM[0] <= np.median(tr.semi_major_axis_km[sel]) <= REGION_A_KM[1]
                and np.median(tr.eccentricity[sel]) <= REGION_E_MAX):
            mode = "out_of_region"
        elif np.median(inc) > INCLINED_MIN_DEG:
            mode = "inclined"
        elif held_spread <= HELD_SPREAD_DEG:
            # A free object at the turning point of a libration sits still for weeks too. It is
            # control if the longitude is held over HELD_RUN consecutive windows that include this
            # one, or if the window is stiller than the natural acceleration allows: a free
            # object's longitude sags by at least about 0.45 * |accel| * (span / 2)^2 inside the
            # 5-95 % spread.
            runs = (range(j, j + HELD_RUN) for j in range(k - HELD_RUN + 1, k + 1))
            run_held = any(
                all(0 <= i < len(idx) and enough(i) for i in run)
                and spread(np.concatenate([idx[i] for i in run])) <= HELD_SPREAD_DEG
                for run in runs)
            free_sag = 0.45 * abs(float(longitude_acceleration(float(wrap180(np.mean(u)))))) * ((d[-1] - d[0]) / 2) ** 2
            if run_held or held_spread < 0.5 * free_sag:
                mode = "controlled_lon_inc" if np.median(inc) <= C1_MAX_INCLINATION_DEG else "controlled_lon"
            else:
                mode = "undetermined"
        else:
            mode = libration_mode(float(wrap180(np.mean(u))), drift)
            if mode != "drifting" and _free_residual(d, u) > FREE_RESIDUAL_DEG:
                mode = "drifting"  # trapped by energy but not moving freely: manoeuvring
        out.append(Window(start, end, mode, len(sel), **evidence))
    return out


@dataclass(frozen=True)
class Segment:
    norad_id: int
    start: datetime
    end: datetime
    mode: str
    windows: int
    n_sets: int
    lon_min: float  # west end of the shortest arc of the segment's longitudes, deg east
    lon_max: float  # east end (lon_min > lon_max when the arc crosses 180 deg)
    drift_mean: float  # mean of the windows' least-squares drift rates, deg/day
    inc_min: float
    inc_max: float


def segments(tr: Track) -> list[Segment]:
    """Adjacent windows with the same mode merged into segments."""
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
