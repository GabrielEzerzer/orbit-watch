# Station-keeping state changes of a GEO-region object, one per change, dated from its element sets:
# relocation start and end, graveyard move, end of keeping, end of north-south keeping, burn while free.

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from orbit_watch.clean import drop_snapback_blocks
from orbit_watch.elements import ElementSet
from orbit_watch.modes import GRID_START, Segment, Track, segments, track

HELD = ("controlled_lon_inc", "controlled_lon")
DEPARTURES = ("relocation_start", "graveyard", "keeping_stop")
EVENT_TYPES = (*DEPARTURES, "relocation_end", "ns_keeping_stop", "free_burn")
GRAVEYARD_RISE_KM = 150.0
ROW_FIELDS = ["norad_id", "event_type", "date", "signal", "size", "lon_before", "lon_after", "mode_before",
              "mode_after", "mode_change"]


@dataclass(frozen=True)
class Event:
    norad_id: int
    event_type: str
    date: datetime
    signal: str
    size: float
    lon_before: float
    lon_after: float
    mode_before: str
    mode_after: str
    mode_change: datetime


def _centre(lon_min: float, lon_max: float) -> float:
    return float(((lon_min + ((lon_max - lon_min) % 360.0) / 2.0) + 180.0) % 360.0 - 180.0)


def _slot(s: Segment) -> float:
    return _centre(s.lon_min, s.lon_max)


def _arcs_overlap(a: Segment, b: Segment) -> bool:
    def inside(x: float, s: Segment) -> bool:
        return (x - s.lon_min) % 360.0 <= (s.lon_max - s.lon_min) % 360.0
    return inside(a.lon_min, b) or inside(b.lon_min, a)


def _day(dt: datetime) -> float:
    return (dt - GRID_START).total_seconds() / 86400.0


def _lon_near(tr: Track, day: float, before: bool) -> float:
    sel = (tr.days < day) & (tr.days >= day - 10) if before else (tr.days >= day) & (tr.days < day + 10)
    return float(np.median(tr.lon[sel])) if sel.any() else float("nan")


def _a_between(tr: Track, lo: float, hi: float) -> np.ndarray:
    return tr.semi_major_axis_km[(tr.days >= lo) & (tr.days < hi)]


def _departure_type(tr: Track, held: Segment, rest: Sequence[Segment]) -> tuple[str, float]:
    held_a = _a_between(tr, _day(held.start), _day(held.end))
    end = next((s for s in rest if s.mode in HELD), None)
    after_a = _a_between(tr, _day(rest[0].start), _day(end.start) if end else _day(rest[-1].end))
    rise = float(np.max(after_a) - np.median(held_a)) if len(after_a) and len(held_a) else 0.0
    if end is not None:
        return "relocation_start", rise
    if rise >= GRAVEYARD_RISE_KM:
        return "graveyard", rise
    return "keeping_stop", rise


def _event(tr: Track, kind: str, a: Segment, b: Segment, lon_after: float, size: float) -> Event:
    when = b.start
    lon_before = _slot(a) if a.mode in HELD else _lon_near(tr, _day(when), True)
    return Event(tr.norad_id, kind, when, "mode_change", round(size, 3), round(lon_before, 3),
                 round(lon_after, 3), a.mode, b.mode, b.start)


def events_from_track(tr: Track) -> list[Event]:
    det = [s for s in segments(tr) if s.mode != "undetermined"]
    out: list[Event] = []
    for k, (a, b) in enumerate(zip(det, det[1:])):
        rest = det[k + 1:]
        if a.mode in HELD and b.mode in HELD:
            if a.mode == "controlled_lon_inc" and b.mode == "controlled_lon" and _arcs_overlap(a, b):
                out.append(_event(tr, "ns_keeping_stop", a, b, _slot(b), b.inc_max))
            elif not _arcs_overlap(a, b):
                out.append(_event(tr, "relocation_start", a, b, _slot(b), 0.0))
                out.append(_event(tr, "relocation_end", a, b, _slot(b), 0.0))
        elif a.mode in HELD:
            kind, rise = _departure_type(tr, a, rest)
            nxt = next((s for s in rest if s.mode in HELD), None)
            lon_after = _slot(nxt) if nxt else _lon_near(tr, _day(rest[-1].end), True)
            out.append(_event(tr, kind, a, b, lon_after, rise))
        elif b.mode in HELD:
            out.append(_event(tr, "relocation_end", a, b, _slot(b), 0.0))
    return out


def state_changes(records: Sequence[ElementSet]) -> list[Event]:
    kept, _ = drop_snapback_blocks(records)
    return events_from_track(track(kept)) if kept else []


def as_row(e: Event) -> dict:
    return {"norad_id": e.norad_id, "event_type": e.event_type, "date": e.date.date().isoformat(),
            "signal": e.signal, "size": e.size, "lon_before": e.lon_before, "lon_after": e.lon_after,
            "mode_before": e.mode_before, "mode_after": e.mode_after,
            "mode_change": e.mode_change.date().isoformat()}

