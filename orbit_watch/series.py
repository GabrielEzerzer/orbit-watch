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


MIN_EPOCH_GAP_S = 60.0


def distinct_epochs(records: Iterable[ElementSet], *, final: bool = False) -> dict[int, list[ElementSet]]:
    """Per NORAD id, the records ``to_series`` keeps, in epoch order.

    When two records for one object share an epoch, the one that comes later in
    ``records`` wins, so a later source can restate an earlier one. Then any
    record whose epoch is under ``MIN_EPOCH_GAP_S`` before the next one is
    dropped, so near-identical epochs collapse to the latest. A chain of
    epochs each under ``MIN_EPOCH_GAP_S`` after the previous one collapses to
    its last epoch, so kept epochs are always at least ``MIN_EPOCH_GAP_S``
    apart. Space-Track history restates element sets at almost the same epoch
    (hundreds of pairs under 1 s for QZS-3), and two epochs that close give the
    detector's Theil-Sen slope pairs a near-zero time base, which turns into
    fake steps of thousands of km.

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
        epochs = sorted(by_epoch)
        out[norad_id] = [by_epoch[e] for e, nxt in zip(epochs, epochs[1:] + [None])
                         if nxt is None or (nxt - e).total_seconds() >= MIN_EPOCH_GAP_S]
    return out


def to_series(records: Iterable[ElementSet], *, final: bool = False) -> dict[int, ElementSeries]:
    """Group records by NORAD id, sort by epoch and drop duplicate and near-duplicate epochs
    (``distinct_epochs``, which also refuses holdout objects unless ``final``)."""
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
