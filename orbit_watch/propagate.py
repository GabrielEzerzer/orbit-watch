# SGP4 propagation of an element set to TEME position (km) and velocity (km/s).

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

import numpy as np
from sgp4.api import SGP4_ERRORS

from orbit_watch.elements import ElementSet


class PropagationError(RuntimeError):
    pass
def propagate(record: ElementSet, times: Iterable[datetime]) -> tuple[np.ndarray, np.ndarray]:
    sat = record.satrec()
    positions, velocities = [], []
    for t in times:
        if t.tzinfo is None:
            raise ValueError(f"time {t!r} is naive; pass a timezone-aware UTC datetime")
        tsince = (t - record.epoch) / timedelta(minutes=1)
        error, r, v = sat.sgp4_tsince(tsince)
        if error:
            raise PropagationError(
                f"NORAD {record.norad_id} at {t.isoformat()}: SGP4 error {error}, {SGP4_ERRORS[error]}"
            )
        positions.append(r)
        velocities.append(v)
    return np.array(positions, dtype=float).reshape(-1, 3), np.array(velocities, dtype=float).reshape(-1, 3)
