"""Sub-satellite longitude of a geostationary object at its TLE epochs.

Each element set is propagated to its own epoch with SGP4 (TEME position), and
the TEME x-y direction is rotated into an Earth-fixed frame by the Greenwich
mean sidereal time. Longitude is east-positive, wrapped to [-180, 180).

GMST uses the IAU 1982 expression (Vallado, *Fundamentals of Astrodynamics and
Applications*, eq. 3-47; the same polynomial as Meeus, *Astronomical
Algorithms*, eq. 12.4), with UTC standing in for UT1.
"""

# shortcut: UTC is used for UT1 (|UT1-UTC| < 0.9 s, about 0.004 deg of longitude)
# and polar motion and the equation of the equinoxes (< 0.005 deg) are ignored;
# switch to a full TEME->ITRF chain if longitudes are ever needed below 0.01 deg.

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import numpy as np

from orbit_watch.elements import ElementSet
from orbit_watch.propagate import propagate

_J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)  # JD 2451545.0


def gmst_deg(t: datetime) -> float:
    """Greenwich mean sidereal time in degrees, [0, 360), at UTC time ``t``."""
    d = (t - _J2000).total_seconds() / 86400.0
    c = d / 36525.0
    seconds = 67310.54841 + (876600.0 * 3600.0 + 8640184.812866) * c + 0.093104 * c**2 - 6.2e-6 * c**3
    return (seconds % 86400.0) / 240.0


def wrap180(deg: np.ndarray | float) -> np.ndarray | float:
    return (np.asarray(deg) + 180.0) % 360.0 - 180.0


def longitude_deg(record: ElementSet, t: datetime | None = None) -> float:
    """East longitude (deg) of the sub-satellite point of ``record`` at ``t`` (default: its epoch)."""
    t = record.epoch if t is None else t
    (r,), _ = propagate(record, [t])
    return float(wrap180(np.degrees(np.arctan2(r[1], r[0])) - gmst_deg(t)))


def longitudes(records: Sequence[ElementSet]) -> np.ndarray:
    """Longitude at each record's own epoch."""
    return np.array([longitude_deg(r) for r in records])


def drift_rate(days: np.ndarray, lon_deg: np.ndarray) -> float:
    """Least-squares longitude drift (deg/day, east positive) over a short run of epochs.

    The longitudes are unwrapped first, so a run that crosses +-180 deg still fits.
    """
    if len(days) < 2:
        return float("nan")
    return float(np.polyfit(days, np.degrees(np.unwrap(np.radians(lon_deg))), 1)[0])
