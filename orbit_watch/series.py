# Per-object element time series, the input to change-point detection.

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from orbit_watch.elements import ElementSet
from orbit_watch.truth import require_not_holdout


@dataclass(frozen=True)
class ElementSeries:
    norad_id: int
    epochs: np.ndarray
    semi_major_axis_km: np.ndarray
    inclination: np.ndarray
    eccentricity: np.ndarray
    raan: np.ndarray
    mean_motion: np.ndarray
    bstar: np.ndarray

    def __len__(self) -> int:
        return len(self.epochs)


MIN_EPOCH_GAP_S = 60.0


def distinct_epochs(records: Iterable[ElementSet], *, final: bool = False) -> dict[int, list[ElementSet]]:
    by_object: dict[int, dict] = {}
    for rec in records:
        by_object.setdefault(rec.norad_id, {})[rec.epoch] = rec
    for norad_id in by_object:
        require_not_holdout(norad_id, final=final)
    out = {}
    for norad_id, by_epoch in by_object.items():
        epochs = sorted(by_epoch)
        out[norad_id] = [by_epoch[e] for e, nxt in zip(epochs, epochs[1:] + [None])
                         if nxt is None or (nxt - e).total_seconds() >= MIN_EPOCH_GAP_S]
    return out


def to_series(records: Iterable[ElementSet], *, final: bool = False) -> dict[int, ElementSeries]:
    out = {}
    for norad_id, recs in distinct_epochs(records, final=final).items():
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
