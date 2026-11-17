# Station-keeping state changes of a GEO-region object, one per change, dated from its element sets:
# relocation start and end, graveyard move, end of keeping, end of north-south keeping, burn while free.

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import numpy as np

from orbit_watch.clean import drop_snapback_blocks
from orbit_watch.elements import ElementSet
from orbit_watch.modes import GRID_START, Segment, Track, segments, track

HELD = ("controlled_lon_inc", "controlled_lon")
DEPARTURES = ("relocation_start", "graveyard", "keeping_stop")
EVENT_TYPES = (*DEPARTURES, "relocation_end", "ns_keeping_stop", "free_burn")
GRAVEYARD_RISE_KM = 150.0
REACH_DAYS = 45.0
SUSTAIN_DAYS = 5.0
RATE_TOL_MIN = 0.02
RATE_TOL_MADS = 4.0
BOX_MARGIN_DEG = 0.05
SLOW_RATE = 0.02
FAST_RATE = 0.05
HOLD_BOX_DEG = 0.3
HOLD_MIN_DAYS = 10.0
HOLD_MIN_SETS = 5
STEP_REACH_DAYS = 5.0
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


def _in_hold(tr: Track, held: Segment) -> np.ndarray:
    sel = (tr.days >= _day(held.start)) & (tr.days < _day(held.end))
    centre = float(np.median(tr.rate[sel]))
    tol = max(RATE_TOL_MIN, RATE_TOL_MADS * 1.4826 * float(np.median(np.abs(tr.rate[sel] - centre))))
    width = (held.lon_max - held.lon_min) % 360.0 + 2 * BOX_MARGIN_DEG
    in_box = (tr.lon - held.lon_min + BOX_MARGIN_DEG) % 360.0 <= width
    return in_box & (np.abs(tr.rate - centre) <= tol)


def _sustained(tr: Track, flags: np.ndarray, lo: float, hi: float) -> int | None:
    idx = np.flatnonzero((tr.days >= lo) & (tr.days < hi))
    for i in idx:
        ahead = (tr.days >= tr.days[i]) & (tr.days <= tr.days[i] + SUSTAIN_DAYS)
        if flags[ahead].all():
            return int(i)
    return None


def _departure_date(tr: Track, held: Segment, b: Segment, limit: float) -> int | None:
    lo = max(_day(held.start), _day(b.start) - REACH_DAYS)
    return _sustained(tr, ~_in_hold(tr, held), lo, min(_day(b.start) + REACH_DAYS, limit))


def _arrival_date(tr: Track, held: Segment, floor: float) -> int | None:
    lo = max(floor, _day(held.start) - REACH_DAYS)
    return _sustained(tr, _in_hold(tr, held), lo, min(_day(held.end), _day(held.start) + REACH_DAYS))


def _at(tr: Track, i: int) -> datetime:
    return GRID_START + timedelta(days=float(tr.days[i]))


def _entered_by_step(tr: Track, first: int) -> bool:
    before = (tr.days >= tr.days[first] - STEP_REACH_DAYS) & (tr.days < tr.days[first])
    return bool((np.abs(tr.rate[before]) >= FAST_RATE).any())


def short_holds(tr: Track, lo: float, hi: float) -> list[tuple[int, int]]:
    idx = np.flatnonzero((tr.days >= lo) & (tr.days < hi))
    runs, cur = [], []
    for i in idx:
        lon = np.unwrap(np.radians(tr.lon[cur + [i]])) if cur else None
        fits = cur and np.degrees(np.ptp(lon)) <= HOLD_BOX_DEG
        if abs(tr.rate[i]) <= SLOW_RATE and (not cur or fits):
            cur.append(int(i))
            continue
        runs.append(cur)
        cur = [int(i)] if abs(tr.rate[i]) <= SLOW_RATE else []
    runs.append(cur)
    return [(r[0], r[-1]) for r in runs if len(r) >= HOLD_MIN_SETS
            and tr.days[r[-1]] - tr.days[r[0]] >= HOLD_MIN_DAYS and _entered_by_step(tr, r[0])]


def _hold_segment(tr: Track, first: int, last: int, template: Segment) -> Segment:
    lon = tr.lon[first:last + 1]
    u = np.degrees(np.unwrap(np.radians(lon)))
    lo = float(((u.min() + 180.0) % 360.0) - 180.0)
    return replace(template, start=_at(tr, first), end=_at(tr, last), mode="controlled_lon", windows=0,
                   n_sets=last - first + 1, lon_min=lo, lon_max=float(((lo + np.ptp(u) + 180.0) % 360.0) - 180.0),
                   drift_mean=float(np.mean(tr.rate[first:last + 1])),
                   inc_min=float(tr.inclination[first:last + 1].min()),
                   inc_max=float(tr.inclination[first:last + 1].max()))


def with_short_holds(tr: Track, segs: Sequence[Segment]) -> list[Segment]:
    out: list[Segment] = []
    k = 0
    while k < len(segs):
        m = k
        while m < len(segs) and segs[m].mode not in HELD:
            m += 1
        if m == k:
            out.append(segs[k])
            k += 1
            continue
        stretch = segs[k:m]
        near = [segs[j] for j in (k - 1, m) if 0 <= j < len(segs)]
        holds: list[tuple[int, int]] = []
        for h in short_holds(tr, _day(stretch[0].start), _day(stretch[-1].end)):
            if holds and _arcs_overlap(_hold_segment(tr, *holds[-1], stretch[0]), _hold_segment(tr, *h, stretch[0])):
                holds[-1] = (holds[-1][0], h[1])
            else:
                holds.append(h)
        holds = [h for h in holds if not any(_arcs_overlap(_hold_segment(tr, *h, stretch[0]), n) for n in near)]
        starts = [stretch[0].start] + [_at(tr, last) for _, last in holds]
        ends = [_at(tr, first) for first, _ in holds] + [stretch[-1].end]
        for h, (s0, e0) in enumerate(zip(starts, ends)):
            out.extend(replace(seg, start=max(seg.start, s0), end=min(seg.end, e0))
                       for seg in stretch if max(seg.start, s0) < min(seg.end, e0))
            if h < len(holds):
                out.append(_hold_segment(tr, *holds[h], stretch[0]))
        k = m
    return out


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


def _event(tr: Track, kind: str, a: Segment, b: Segment, lon_after: float, size: float,
           at: int | None = None, signal: str = "") -> Event:
    when = b.start if at is None else GRID_START + timedelta(days=float(tr.days[at]))
    signal = "mode_change" if at is None else signal
    lon_before = _slot(a) if a.mode in HELD else _lon_near(tr, _day(when), True)
    return Event(tr.norad_id, kind, when, signal, round(size, 3), round(lon_before, 3),
                 round(lon_after, 3), a.mode, b.mode, b.start)


def events_from_track(tr: Track) -> list[Event]:
    det = [s for s in with_short_holds(tr, segments(tr)) if s.mode != "undetermined"]
    out: list[Event] = []
    for k, (a, b) in enumerate(zip(det, det[1:])):
        rest = det[k + 1:]
        if a.mode in HELD and b.mode in HELD:
            if a.mode == "controlled_lon_inc" and b.mode == "controlled_lon" and _arcs_overlap(a, b):
                out.append(_event(tr, "ns_keeping_stop", a, b, _slot(b), b.inc_max))
            elif not _arcs_overlap(a, b):
                i = _departure_date(tr, a, b, _day(b.end))
                j = _arrival_date(tr, b, tr.days[i] if i is not None else _day(a.start))
                out.append(_event(tr, "relocation_start", a, b, _slot(b), 0.0, i, "rate_exit"))
                out.append(_event(tr, "relocation_end", a, b, _slot(b), 0.0, j, "rate_entry"))
        elif a.mode in HELD:
            kind, rise = _departure_type(tr, a, rest)
            nxt = next((s for s in rest if s.mode in HELD), None)
            lon_after = _slot(nxt) if nxt else _lon_near(tr, _day(rest[-1].end), True)
            i = _departure_date(tr, a, b, _day(nxt.start) if nxt else _day(rest[-1].end))
            out.append(_event(tr, kind, a, b, lon_after, rise, i, "rate_exit"))
        elif b.mode in HELD:
            j = _arrival_date(tr, b, _day(a.start))
            out.append(_event(tr, "relocation_end", a, b, _slot(b), 0.0, j, "rate_entry"))
    return out


def state_changes(records: Sequence[ElementSet]) -> list[Event]:
    kept, _ = drop_snapback_blocks(records)
    return events_from_track(track(kept)) if kept else []


def as_row(e: Event) -> dict:
    return {"norad_id": e.norad_id, "event_type": e.event_type, "date": e.date.date().isoformat(),
            "signal": e.signal, "size": e.size, "lon_before": e.lon_before, "lon_after": e.lon_after,
            "mode_before": e.mode_before, "mode_after": e.mode_after,
            "mode_change": e.mode_change.date().isoformat()}

