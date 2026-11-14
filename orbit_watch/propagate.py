"""SGP4 propagation of an element set to TEME position and velocity."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

import numpy as np
from sgp4.api import SGP4_ERRORS

from orbit_watch.elements import ElementSet


class PropagationError(RuntimeError):
    """SGP4 returned a non-zero error code (decayed orbit, bad eccentricity, ...)."""


def propagate(record: ElementSet, times: Iterable[datetime]) -> tuple[np.ndarray, np.ndarray]:
    """TEME position (km) and velocity (km/s) of ``record`` at each UTC time.

    Returns two ``(n, 3)`` arrays. Times must be timezone-aware. Raises
    ``PropagationError`` at the first time where SGP4 reports an error.
    """
    sat = record.satrec()
    positions, velocities = [], []
    for t in times:
        if t.tzinfo is None:
            raise ValueError(f"time {t!r} is naive; pass a timezone-aware UTC datetime")
        tsince = (t - record.epoch) / timedelta(minutes=1)
        # Minutes since epoch, computed exactly from datetimes, avoids Julian-date rounding.
        error, r, v = sat.sgp4_tsince(tsince)
        if error:
            raise PropagationError(
                f"NORAD {record.norad_id} at {t.isoformat()}: SGP4 error {error}, {SGP4_ERRORS[error]}"
            )
        positions.append(r)
        velocities.append(v)
    return np.array(positions, dtype=float).reshape(-1, 3), np.array(velocities, dtype=float).reshape(-1, 3)
