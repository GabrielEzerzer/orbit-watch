"""Operating mode of a GEO-region object through time: layer 1 of a routine model for the GEO belt.

The classes are the European Space Agency's, from ESA Space Debris Office, *Classification of
Geosynchronous Objects*, Issue 21.0, 19 July 2019, reference GEN-DB-LOG-00270-OPS-SD (status at
1 January 2019), section 2 and table 1. Issue 21 is the newest issue we could reach (copy at
https://astronomer.ru/data/0128/Classification_of_Geosynchronous_Objects_I21R0.pdf; ESA itself
does not host it publicly). ESA's classes and the mode names used here:

==================  ====  ============================================================================
mode                ESA   rule here
==================  ====  ============================================================================
controlled_lon_inc  C1    longitude held (below), and the median inclination is at most 0.3 deg in
                          some window within a year either side (ESA's 0.3 and its one year)
controlled_lon      C2    longitude held, and no window within a year either side is at 0.3 deg or less
drifting            D     not held, and too fast to be trapped by the stable points (energy, below)
librating_75E       L1    not held, trapped in the well of the eastern stable point (75 deg E)
librating_105W      L2    not held, trapped in the well of the western stable point (105 deg W)
librating_both      L3    not held, above the lower barrier but below the higher one: swings over both
inclined            I     median inclination above 25 deg (ESA's 25)
undetermined        Ind   too few element sets, or a held longitude that does not tell
                          station-keeping from a librator at the turning point of its swing
out_of_region       --    median semi-major axis outside 37,948-46,380 km or eccentricity above 0.25
                          (the union of ESA's GEO, IGO and EGO classes, table 1)
==================  ====  ============================================================================

ESA's C4 (a controlled drift orbit) is not separated: telling it from D needs manoeuvre detection,
which is the next layer. Such windows read as drifting or librating.

ESA classifies each object once, at a reference date, from its orbital history. Here 2021-01-01 to
2026-01-01 is cut into fixed 30-day windows, laid backwards from 2026-01-01 so every object shares
the same grid (the first window is 26 days long). Each window is classified from its own element
sets, and adjacent windows with the same mode are merged into segments. Choices that ESA's
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
  Without this, librators flicker into "controlled" at every turning point. Where a free path
  bends by less than the held spread in 90 days (within about 6 deg of a stable point or 2 deg
  of a barrier), a held 90-day run proves nothing by itself: it counts only if it holds a burn,
  or if the consecutive held windows around it spread less than half of what a free path bends
  over their whole span.
* Wide-box keepers (Meteosat at 0 deg E keeps a box about 1.3 deg wide) let the natural
  acceleration carry them across the box and burn at its edge. A window not held counts as
  controlled if it and some 90-day run of three windows that includes it stay within ``BOX_DEG``
  = 1.5 deg and that run holds a burn (a window off a free path, below). Free librators never
  burn. Among 90-day runs that hold a burn, in a sample of 250 objects, 933 spread less than
  1 deg, 10 spread 1-3 deg and the rest are relocations of 3 deg or more; 1.5 sits in that gap.
  The window's own spread must fit too, so the window that holds the end of a relocation is
  drifting, not control.
* A window holds a burn, and reads as drifting, when its longitude leaves a free path (the
  robust scatter about a quadratic in time is above ``FREE_RESIDUAL_DEG``; free librators sit
  near 0.001 deg, 95th percentile 0.007 deg in a sample of 200 objects) and the windows on
  either side do not lie on one free path either: a cubic through both, its curvature pinned to
  the natural acceleration, leaves more than ``FREE_RESIDUAL_DEG``. A noisy window between two
  windows of one free path is no manoeuvre. In a seeded sample of 400 objects that two-window
  fit leaves 0.42 % of 2,153 free-librator windows above 0.02 deg (99th percentile 0.017),
  99.5 % of keeper windows and every relocation above it. With no data on one side (the ends of
  the record, a gap) the window's own path decides.
* Trapped or drifting: with the longitude acceleration of the Earth's tesseral harmonics
  (``tesseral_potential``, its terms scaled by Kaula's inclination functions),
  ``1/2 * drift**2 + potential(longitude)`` is conserved for a free object. Comparing it with the
  two potential maxima says whether the object is trapped in one well (L1, L2), swings over both
  (L3) or circulates (D). Window estimates of it still scatter by a few per cent with the phase
  of the swing (luni-solar terms and degree 4 and up are left out), so each run of free windows
  takes one energy, the median. A run goes on through still windows (a turning point, a barrier
  top) and ends at a burn, or between two windows that each follow a free path but not the same
  one. A run whose path passes over a barrier is not trapped behind it, whatever the energy reads.
"""

# shortcut: segment boundaries fall on the 30-day grid, so a mode change is dated to within a
# window; refine boundaries with the element sets near each change if a later layer needs days.
# shortcut: the potential keeps the resonant terms of degree 2 and 3 at the geostationary radius and
# the barriers at their equatorial longitudes, so an energy within about 2 % of a barrier can fall on
# the wrong side when the run's path does not cross it; add degree 4 and luni-solar terms if needed.
# shortcut: a whole window of a relocation slower than about 0.45 deg/day, with no burn in it, is
# free and trapped, so it reads as librating (ESA's C4 is not separated); manoeuvre detection
# (layer 2) can tell it apart.
# shortcut: within about 6 deg of a stable point or 2 deg of a barrier, a keeper with no burn big
# enough to see reads undetermined until its hold outlasts a free object's; north-south burns (an
# inclination held near 0) would prove control sooner, from the inclination vector.
# shortcut: a change between C1 and C2 is dated up to a year off (C1 -> C2 a year after the
# inclination was last within 0.3 deg, C2 -> C1 a year before it first is); ESA's one-year rule.
# shortcut: one wild element set (a corrupt mean motion) in a sparse window can break the held test
# and the window's own fit, as for 49055 on 2022-06-11; reject sets far off the window's median
# semi-major axis if it matters.
# shortcut: a wide-box keeper that goes a whole 90-day run without a burn reads as librating or
# undetermined for those windows; manoeuvre detection (layer 2) gives the burns directly.

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from math import cos, factorial, radians, sin, sqrt

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
BOX_DEG = 1.5
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
_MU_KM3_S2 = 398600.4415
_R_EARTH_KM = 6378.1363
_R_GEO_KM = 42164.17


def _inclination_function(n: int, m: int, inc_deg: float) -> float:
    """Kaula's inclination function F_nmp(i) of the term that resonates with a geostationary orbit
    (n - 2p = m; Kaula, *Theory of Satellite Geodesy*, 1966, table 1). At i = 0 it is the
    unnormalised P_nm(0) of the equatorial potential: 3, -1.5 and 15."""
    c, s2 = cos(radians(inc_deg)), sin(radians(inc_deg)) ** 2
    return {(2, 2): 0.75 * (1 + c) ** 2,
            (3, 1): 15 / 16 * s2 * (1 + 3 * c) - 0.75 * (1 + c),
            (3, 3): 1.875 * (1 + c) ** 3}[n, m]


def _tesseral_terms(lon_deg, inc_deg=0.0):
    """(m, coefficient on cos(m lon), coefficient on sin(m lon), lon in rad) of 3 U / r^2 in (rad/day)^2."""
    lam = np.radians(np.asarray(lon_deg, dtype=float))
    for (n, m), (c, s) in _EGM96.items():
        norm = sqrt(2 * (2 * n + 1) * factorial(n - m) / factorial(n + m))
        k = (3.0 / _R_GEO_KM**2 * 86400.0**2 * (_MU_KM3_S2 / _R_GEO_KM) * (_R_EARTH_KM / _R_GEO_KM) ** n
             * norm * _inclination_function(n, m, inc_deg))
        yield m, k * c, k * s, lam


def tesseral_potential(lon_deg: np.ndarray | float, inc_deg: float = 0.0) -> np.ndarray | float:
    """Longitude potential of a near-circular object at the geostationary radius, (rad/day)^2.

    A tangential acceleration ``(1/r) dU/dlon`` changes the semi-major axis, and the drift rate
    follows: ``d2lon/dt2 = -(3 / r^2) dU/dlon``. So with ``V = 3 U / r^2``, ``d2lon/dt2 = -dV/dlon``
    and ``1/2 (dlon/dt)^2 + V(lon)`` is conserved. Minima of ``V`` are the stable points. At
    inclination ``inc_deg`` each term scales by its inclination function (the (2,2) term by
    ``((1 + cos i) / 2)**2``), with ``lon`` the mean longitude.
    """
    return sum(kc * np.cos(m * lam) + ks * np.sin(m * lam) for m, kc, ks, lam in _tesseral_terms(lon_deg, inc_deg))


def longitude_acceleration(lon_deg: np.ndarray | float, inc_deg: float = 0.0) -> np.ndarray | float:
    """Natural longitude acceleration ``-dV/dlon`` of a free near-geostationary object, deg/day^2."""
    return np.degrees(sum(m * (kc * np.sin(m * lam) - ks * np.cos(m * lam))
                          for m, kc, ks, lam in _tesseral_terms(lon_deg, inc_deg)))


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


def energy(lon_deg: float, drift_deg_per_day: float, inc_deg: float = 0.0) -> float:
    """``1/2 drift**2 + potential(lon)``, (rad/day)^2: constant for a free object."""
    return float(0.5 * np.radians(drift_deg_per_day) ** 2 + tesseral_potential(lon_deg, inc_deg))


def libration_mode(energy_: float, lon_deg: float, inc_deg: float = 0.0) -> str:
    """drifting, librating_75E, librating_105W or librating_both, from the conserved energy;
    ``lon_deg`` says which well holds an object trapped in one. The barriers are taken at their
    equatorial longitudes: the potential is flat at a maximum, so the shift with inclination
    hardly changes their height."""
    if energy_ >= tesseral_potential(BARRIER_HIGH_DEG, inc_deg):
        return "drifting"
    if energy_ >= tesseral_potential(BARRIER_LOW_DEG, inc_deg):
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
    """A ``Track`` from one object's element sets (epoch order, as ``series.distinct_epochs`` keeps them)."""
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


def _free_residual(days: np.ndarray, u: np.ndarray, accel: float | None = None) -> float:
    """Robust scatter (1.4826 x median absolute residual, deg) of the unwrapped longitude about a
    free path; a manoeuvre breaks it. Within a window the path is any quadratic in time. With
    ``accel`` (deg/day^2) its curvature is pinned to the natural acceleration, ``accel / 2 * t**2``,
    with a cubic term for the change of acceleration along the path: over 90 days a keeper held
    still away from a stable point then cannot pass for a free object."""
    t = days - days.mean()
    y, basis = (u, [t**2, t, np.ones_like(t)]) if accel is None else (u - 0.5 * accel * t**2, [t**3, t, np.ones_like(t)])
    a = np.column_stack(basis)
    r = y - a @ np.linalg.lstsq(a, y, rcond=None)[0]
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

    def free_residual(sel: np.ndarray, pinned: bool = False) -> float:
        d = tr.days[sel]
        u = _unwrapped(d, tr.lon[sel], float(np.median(tr.rate[sel])))
        accel = float(longitude_acceleration(float(wrap180(np.mean(u))), float(np.median(tr.inclination[sel]))))
        return _free_residual(d, u, accel if pinned else None)

    @lru_cache(maxsize=None)
    def burn(k: int) -> bool:
        """A manoeuvre falls inside the window: its longitude leaves a free path, and the element
        sets of the windows on either side do not lie on one free path either. A stray element
        set or a noisy window between two windows of one free path is not a manoeuvre. Without
        data on both sides (the ends of the record, a gap) the window's own path decides."""
        if free_residual(idx[k]) <= FREE_RESIDUAL_DEG:
            return False
        if not (0 < k < len(idx) - 1 and enough(k - 1) and enough(k + 1)):
            return True
        return free_residual(np.concatenate([idx[k - 1], idx[k + 1]]), pinned=True) > FREE_RESIDUAL_DEG

    @lru_cache(maxsize=None)
    def run_spread(j: int) -> float:
        return spread(np.concatenate([idx[i] for i in range(j, j + HELD_RUN)]))

    def held(k: int) -> bool:
        return enough(k) and spread(idx[k]) <= HELD_SPREAD_DEG

    def still_chain(k: int, accel: float) -> bool:
        """The chain of consecutive held windows around k spreads less than half of what a free
        object with acceleration ``accel`` would sag over the chain's span: the one-window test
        (``spread < 0.5 * free_sag``) applied to the whole hold."""
        a, b = k, k
        while a > 0 and held(a - 1):
            a -= 1
        while b < len(idx) - 1 and held(b + 1):
            b += 1
        chain = np.concatenate(idx[a:b + 1])
        return spread(chain) < 0.5 * 0.45 * accel * ((tr.days[chain[-1]] - tr.days[chain[0]]) / 2) ** 2

    inc_median = {k: float(np.median(tr.inclination[idx[k]])) for k in range(len(idx)) if enough(k)}

    def c1(k: int) -> bool:
        """ESA's C1: inclination at most 0.3 deg, "however control at larger angles within one year
        is accepted as well" (section 2). A keeper whose inclination is back to 0.3 deg or less
        within a year either side is C1, so C1 -> C2 means north-south keeping stopped."""
        return any(v <= C1_MAX_INCLINATION_DEG for j, v in inc_median.items() if abs(j - k) * WINDOW_DAYS <= 365)

    rows, free, slow = [], {}, {}  # free: window -> (energy, mean longitude, inclination); slow: window -> mean longitude
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
        # Runs of HELD_RUN consecutive windows that include this one, all with enough data.
        runs = [j for j in range(k - HELD_RUN + 1, k + 1)
                if j >= 0 and j + HELD_RUN <= len(idx) and all(enough(i) for i in range(j, j + HELD_RUN))]
        # A free object at the turning point of a libration sits still for weeks too, so a held
        # window is control only if a 90-day run is held too, or if it is stiller than the natural
        # acceleration allows (a free path sags by about 0.45 * |accel| * (span / 2)^2 inside the
        # 5-95 % spread). Where a free object sags less than HELD_SPREAD_DEG in 90 days (within
        # about 6 deg of a stable point, 2 deg of a barrier) a held 90-day run proves nothing: it
        # counts only if it holds a burn, or if the hold lasts longer than a free object's could.
        # Wide-box keepers are caught by their burns: a 90-day run inside BOX_DEG with a
        # manoeuvre in it, the window itself inside BOX_DEG too so the window that holds the end
        # of a relocation stays drifting. A free librator never burns.
        mean_lon = float(wrap180(np.mean(u)))
        accel = abs(float(longitude_acceleration(mean_lon, inc_median[k])))
        free_sag = 0.45 * accel * ((d[-1] - d[0]) / 2) ** 2
        run_held = any(run_spread(j) <= HELD_SPREAD_DEG for j in runs)
        if run_held and 0.45 * accel * (HELD_RUN * WINDOW_DAYS / 2) ** 2 < HELD_SPREAD_DEG:
            run_held = (any(run_spread(j) <= HELD_SPREAD_DEG and any(burn(i) for i in range(j, j + HELD_RUN)) for j in runs)
                        or still_chain(k, accel))
        tight = still and (run_held or spread(sel) < 0.5 * free_sag)
        wide = spread(sel) <= BOX_DEG and any(run_spread(j) <= BOX_DEG and any(burn(i) for i in range(j, j + HELD_RUN)) for j in runs)
        if not (REGION_A_KM[0] <= np.median(tr.semi_major_axis_km[sel]) <= REGION_A_KM[1]
                and np.median(tr.eccentricity[sel]) <= REGION_E_MAX):
            mode = "out_of_region"
        elif np.median(inc) > INCLINED_MIN_DEG:
            mode = "inclined"
        elif tight or wide:
            mode = "controlled_lon_inc" if c1(k) else "controlled_lon"
        elif still:
            mode = "undetermined"
            slow[k] = mean_lon
        elif burn(k):
            mode = "drifting"  # not moving freely: manoeuvring, whatever the energy says
        else:
            mode = None
            free[k] = (energy(mean_lon, drift, inc_median[k]), mean_lon, inc_median[k])
        rows.append(dict(start=start, end=end, mode=mode, n_sets=len(sel), **evidence))
    # One energy for each run of free windows: the energy of a free object is constant, and the
    # window estimates scatter with the phase of the swing (luni-solar terms and the terms of
    # degree 4 and up are left out), so near a barrier a per-window label would follow the swing.
    # A run goes on through still (undetermined) windows, where a free object slows at a turning
    # point or over a barrier top, and ends where two neighbouring windows each lie on a free path
    # but not on the same one (a manoeuvre between them). The median of the run decides, and its
    # free windows share one label. A run whose path passes over a barrier is not trapped behind
    # it, whatever the energy reads.
    lon_of = {**slow, **{k: v[1] for k, v in free.items()}}

    def manoeuvre_between(k: int) -> bool:
        """Windows k - 1 and k each lie on a free path, but not on the same one."""
        return (max(free_residual(idx[k - 1]), free_residual(idx[k])) <= FREE_RESIDUAL_DEG
                and free_residual(np.concatenate([idx[k - 1], idx[k]]), pinned=True) > FREE_RESIDUAL_DEG)

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
