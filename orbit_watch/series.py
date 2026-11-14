"""Per-object element time series, the input to change-point detection."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from orbit_watch.elements import ElementSet
from orbit_watch.truth import require_not_holdout


@dataclass(frozen=True)
class ElementSeries:
    """Epoch-sorted elements for one object, one entry per distinct epoch.

    ``epochs`` is ``datetime64[us]`` in UTC; the other arrays align with it.
    """

    norad_id: int
    epochs: np.ndarray
    semi_major_axis_km: np.ndarray
    inclination: np.ndarray  # deg
    eccentricity: np.ndarray
    raan: np.ndarray  # deg
    mean_motion: np.ndarray  # rev/day
    bstar: np.ndarray

    def __len__(self) -> int:
        return len(self.epochs)


def to_series(records: Iterable[ElementSet], *, final: bool = False) -> dict[int, ElementSeries]:
    """Group records by NORAD id, sort by epoch and drop duplicate epochs.

    When two records for one object share an epoch, the one that comes later in
    ``records`` wins, so a later source can restate an earlier one.

    Raises ``truth.HoldoutError`` if any object is in the holdout of
    ``groundtruth/splits.json``, unless ``final``; objects the file does not list pass.
    """
    by_object: dict[int, dict] = {}
    for rec in records:
        by_object.setdefault(rec.norad_id, {})[rec.epoch] = rec
    for norad_id in by_object:
        require_not_holdout(norad_id, final=final)
    out = {}
    for norad_id, by_epoch in by_object.items():
        recs = [by_epoch[e] for e in sorted(by_epoch)]
        out[norad_id] = ElementSeries(
            norad_id=norad_id,
            epochs=np.array([r.epoch.replace(tzinfo=None) for r in recs], dtype="datetime64[us]"),
            semi_major_axis_km=np.array([r.semi_major_axis_km for r in recs]),
            inclination=np.array([r.inclination for r in recs]),
            eccentricity=np.array([r.eccentricity for r in recs]),
            raan=np.array([r.raan for r in recs]),
            mean_motion=np.array([r.mean_motion for r in recs]),
            bstar=np.array([r.bstar for r in recs]),
        )
    return out
