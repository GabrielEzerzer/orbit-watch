# Sub-satellite longitude of a geostationary object at its TLE epochs, east-positive in [-180, 180).
# TEME is rotated to Earth-fixed by IAU 1982 GMST (Vallado eq. 3-47), with UTC standing in for UT1.

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone

import numpy as np

from orbit_watch.elements import ElementSet
from orbit_watch.propagate import propagate

_J2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)


def gmst_deg(t: datetime) -> float:
    d = (t - _J2000).total_seconds() / 86400.0
    c = d / 36525.0
    seconds = 67310.54841 + (876600.0 * 3600.0 + 8640184.812866) * c + 0.093104 * c**2 - 6.2e-6 * c**3
    return (seconds % 86400.0) / 240.0


def wrap180(deg: np.ndarray | float) -> np.ndarray | float:
    return (np.asarray(deg) + 180.0) % 360.0 - 180.0


def longitude_deg(record: ElementSet, t: datetime | None = None) -> float:
    t = record.epoch if t is None else t
    (r,), _ = propagate(record, [t])
    return float(wrap180(np.degrees(np.arctan2(r[1], r[0])) - gmst_deg(t)))


def longitudes(records: Sequence[ElementSet]) -> np.ndarray:
    return np.array([longitude_deg(r) for r in records])


def drift_rate(days: np.ndarray, lon_deg: np.ndarray) -> float:
    if len(days) < 2:
        return float("nan")
    return float(np.polyfit(days, np.degrees(np.unwrap(np.radians(lon_deg))), 1)[0])
