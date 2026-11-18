# Station-keeping state changes of a GEO-region object, one per change, dated from its element sets:
# relocation start and end, graveyard move, end of keeping, end of north-south keeping, burn while free.

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

import numpy as np

from orbit_watch.clean import drop_snapback_blocks, noise
from orbit_watch.detect import detect
from orbit_watch.elements import ElementSet
from orbit_watch.generalise import FROZEN
from orbit_watch.geo import wrap180
from orbit_watch.modes import GRID_START, Segment, Track, _arc, segments, track
from orbit_watch.series import to_series

HELD = ("controlled_lon_inc", "controlled_lon")
UNREAD = ("undetermined", "inclined")
DEPARTURES = ("relocation_start", "graveyard", "keeping_stop")
EVENT_TYPES = (*DEPARTURES, "relocation_end", "ns_keeping_stop", "free_burn")
GRAVEYARD_RISE_KM = 150.0
REACH_DAYS = 45.0
SUSTAIN_DAYS = 5.0
RATE_TOL_MIN = 0.02
RATE_TOL_MADS = 4.0
BOX_MARGIN_DEG = 0.05
SAME_SLOT_DEG = 0.5
SLOW_RATE = 0.02
FAST_RATE = 0.05
HOLD_BOX_DEG = 0.3
HOLD_MIN_DAYS = 10.0
HOLD_MIN_SETS = 5
STEP_REACH_DAYS = 5.0
BURN_LOOKBACK_DAYS = 60.0
MIN_BURNS = 3
CLIMB_DAYS = 15.0
CLIMB_GAP_DAYS = 30.0
FREE_BURN_MIN_M = 1000.0
EDGE_DAYS = 30.0
NS_ANCHOR_DAYS = 60.0
NS_LOOKBACK_DAYS = 180.0
NS_TOL_SIGMAS = 5.0
NS_SIDE_SETS = 3
NS_SPAN_DAYS = 12.0
NS_TOL_MIN_DEG = 0.006
NS_MERGE_DAYS = 2.0
NS_MIN_CORRECTIONS = 2
GAP_DAYS = 2.0
OPEN_DAYS = 90.0
MOVE_MIN_DEG = 0.5
MOVE_SIDE_DAYS = 10.0
MOVE_MERGE_DAYS = 2.0
MOVE_SIDE_SETS = 3
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
        return (x - s.lon_min + SAME_SLOT_DEG) % 360.0 <= (s.lon_max - s.lon_min) % 360.0 + 2 * SAME_SLOT_DEG
    return inside(a.lon_min, b) or inside(b.lon_min, a)


def _day(dt: datetime) -> float:
    return (dt - GRID_START).total_seconds() / 86400.0


def _lon_near(tr: Track, day: float, before: bool) -> float:
    sel = (tr.days < day) & (tr.days >= day - 10) if before else (tr.days >= day) & (tr.days < day + 10)
    return float(np.median(tr.lon[sel])) if sel.any() else float("nan")


def _a_between(tr: Track, lo: float, hi: float) -> np.ndarray:
    return tr.semi_major_axis_km[(tr.days >= lo) & (tr.days < hi)]


def _band(rate: np.ndarray) -> tuple[float, float]:
    centre = float(np.median(rate))
    return centre, max(RATE_TOL_MIN, RATE_TOL_MADS * 1.4826 * float(np.median(np.abs(rate - centre))))


def _in_hold(tr: Track, held: Segment, edge: str = "") -> np.ndarray:
    lo, hi = _day(held.start), _day(held.end)
    sel = (tr.days >= lo) & (tr.days < hi)
    centre, tol = _band(tr.rate[sel])
    lon_min, lon_max = held.lon_min, held.lon_max
    near = sel & ((tr.days >= hi - EDGE_DAYS) if edge == "end" else (tr.days < lo + EDGE_DAYS))
    if edge and near.sum() >= HOLD_MIN_SETS:
        lon_min, lon_max = _arc(tr.lon[near])
    width = (lon_max - lon_min) % 360.0 + 2 * BOX_MARGIN_DEG
    in_box = (tr.lon - lon_min + BOX_MARGIN_DEG) % 360.0 <= width
    return in_box & (np.abs(tr.rate - centre) <= tol)


def _sustained(tr: Track, flags: np.ndarray, lo: float, hi: float) -> int | None:
    idx = np.flatnonzero((tr.days >= lo) & (tr.days < hi))
    for i in idx:
        ahead = (tr.days >= tr.days[i]) & (tr.days <= tr.days[i] + SUSTAIN_DAYS)
        if flags[ahead].all():
            return int(i)
    return None


def _shift(tr: Track, a: Segment, nxt: Segment) -> float:
    before = (tr.days >= _day(a.end) - MOVE_SIDE_DAYS) & (tr.days < _day(a.end))
    after = (tr.days >= _day(nxt.start)) & (tr.days < _day(nxt.start) + MOVE_SIDE_DAYS)
    if not before.any() or not after.any():
        return 0.0
    return float(wrap180(np.median(tr.lon[after]) - np.median(tr.lon[before])))


def _moved(tr: Track, a: Segment, nxt: Segment) -> bool:
    return (_sustained(tr, np.abs(tr.rate) >= FAST_RATE, _day(a.end), _day(nxt.start)) is not None
            or abs(_shift(tr, a, nxt)) >= MOVE_MIN_DEG)


def _departure_date(tr: Track, held: Segment, b: Segment, limit: float) -> int | None:
    lo = max(_day(held.start), _day(b.start) - REACH_DAYS)
    hi = min(_day(b.start) + REACH_DAYS, limit)
    i = _sustained(tr, ~_in_hold(tr, held), lo, hi)
    return _sustained(tr, ~_in_hold(tr, held, "end"), lo, hi) if i is None else i


def _arrival_date(tr: Track, held: Segment, floor: float) -> int | None:
    lo = max(floor, _day(held.start) - REACH_DAYS)
    hi = min(_day(held.end), _day(held.start) + REACH_DAYS)
    i = _sustained(tr, _in_hold(tr, held), lo, hi)
    return _sustained(tr, _in_hold(tr, held, "start"), lo, hi) if i is None else i


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
            if h and h == len(holds) and not ((tr.days > _day(s0)) & (tr.days < _day(e0))).any():
                break
            out.extend(replace(seg, start=max(seg.start, s0), end=min(seg.end, e0))
                       for seg in stretch if max(seg.start, s0) < min(seg.end, e0))
            if h < len(holds):
                out.append(_hold_segment(tr, *holds[h], stretch[0]))
        k = m
    return out


def inner_moves(tr: Track, held: Segment) -> list[tuple[int, int]]:
    idx = np.flatnonzero((tr.days >= _day(held.start)) & (tr.days < _day(held.end)))
    if len(idx) < 2 * MOVE_SIDE_SETS:
        return []
    centre, tol = _band(tr.rate[idx])
    out_band = idx[np.abs(tr.rate[idx] - centre) > tol]
    runs: list[list[int]] = []
    for i in out_band:
        if runs and tr.days[i] - tr.days[runs[-1][-1]] <= MOVE_MERGE_DAYS:
            runs[-1].append(int(i))
        else:
            runs.append([int(i)])
    calm = np.zeros(len(tr.days), dtype=bool)
    calm[idx] = True
    calm[out_band] = False
    found = []
    for run in runs:
        first, last = run[0], run[-1]
        if found and first < found[-1][1]:
            continue
        before = calm & (tr.days >= tr.days[first] - MOVE_SIDE_DAYS) & (tr.days < tr.days[first])
        after = calm & (tr.days > tr.days[last]) & (tr.days <= tr.days[last] + MOVE_SIDE_DAYS)
        if before.sum() < MOVE_SIDE_SETS or after.sum() < MOVE_SIDE_SETS:
            continue
        shift = float(wrap180(np.median(tr.lon[after]) - np.median(tr.lon[before])))
        drift = float(np.median(tr.rate[run]) - centre)
        if abs(shift) >= MOVE_MIN_DEG and np.sign(shift) == np.sign(drift):
            found.append((first, int(np.flatnonzero(after)[0])))
    return found


def _piece(tr: Track, seg: Segment, start: datetime, end: datetime, mode: str) -> Segment:
    sel = (tr.days >= _day(start)) & (tr.days < _day(end))
    lon_min, lon_max = _arc(tr.lon[sel]) if sel.any() else (seg.lon_min, seg.lon_max)
    return replace(seg, start=start, end=end, mode=mode, n_sets=int(sel.sum()), lon_min=lon_min, lon_max=lon_max)


def with_inner_moves(tr: Track, segs: Sequence[Segment]) -> list[Segment]:
    out: list[Segment] = []
    for seg in segs:
        moves = inner_moves(tr, seg) if seg.mode in HELD else []
        start = seg.start
        for first, arrive in moves:
            out.append(_piece(tr, seg, start, _at(tr, first), seg.mode))
            out.append(_piece(tr, seg, _at(tr, first), _at(tr, arrive), "drifting"))
            start = _at(tr, arrive)
        out.append(_piece(tr, seg, start, seg.end, seg.mode) if moves else seg)
    return out


def _inc_vector(tr: Track) -> np.ndarray:
    node = np.radians(tr.raan)
    return np.column_stack([tr.inclination * np.cos(node), tr.inclination * np.sin(node)])


def ns_corrections(tr: Track, a: Segment, b: Segment) -> list[float]:
    stop = _day(b.start)
    anchor = np.flatnonzero((tr.days >= stop) & (tr.days < min(stop + NS_ANCHOR_DAYS, _day(b.end))))
    if len(anchor) < HOLD_MIN_SETS:
        return []
    v = _inc_vector(tr)
    t = tr.days - stop
    drift = np.linalg.lstsq(np.column_stack([np.ones(len(anchor)), t[anchor]]), v[anchor], rcond=None)[0][1]
    r = v - np.outer(t, drift)
    tol = max(NS_TOL_SIGMAS * max(noise(tr.days[anchor], v[anchor, k], 0.0) for k in range(2)), NS_TOL_MIN_DEG)
    idx = np.flatnonzero((tr.days >= max(_day(a.start), stop - NS_LOOKBACK_DAYS)) & (tr.days < stop))
    steps = []
    for j in range(NS_SIDE_SETS - 1, len(idx) - NS_SIDE_SETS):
        before, after = idx[j - NS_SIDE_SETS + 1:j + 1], idx[j + 1:j + 1 + NS_SIDE_SETS]
        if tr.days[after[-1]] - tr.days[before[0]] > NS_SPAN_DAYS:
            continue
        size = float(np.hypot(*(np.median(r[after], axis=0) - np.median(r[before], axis=0))))
        if size >= tol:
            steps.append((size, 0.5 * float(tr.days[idx[j]] + tr.days[idx[j + 1]])))
    kept: list[float] = []
    for _, day in sorted(steps, reverse=True):
        if all(abs(day - k) > NS_MERGE_DAYS for k in kept):
            kept.append(day)
    return sorted(kept)


def _ns_stop_day(tr: Track, a: Segment, b: Segment) -> float | None:
    found = ns_corrections(tr, a, b) if tr.raan is not None else []
    if len(found) < NS_MIN_CORRECTIONS:
        return None
    return found[-1] + float(np.median(np.diff(found))) / 2.0


def burns(records: Sequence[ElementSet]) -> tuple[np.ndarray, np.ndarray]:
    (series,) = to_series(records).values()
    dets = detect(series, FROZEN)
    start = np.datetime64(GRID_START.replace(tzinfo=None), "us")
    days = [(d.peak_start + (d.peak_end - d.peak_start) / 2 - start) / np.timedelta64(1, "D") for d in dets]
    return np.array(days, dtype=float), np.array([d.step_m for d in dets], dtype=float)


def _missed_burn_day(tr: Track, i: int, burns: np.ndarray) -> float | None:
    if (np.abs(tr.rate[(tr.days >= tr.days[i]) & (tr.days <= tr.days[i] + SUSTAIN_DAYS)]) >= FAST_RATE).any():
        return None
    recent = burns[(burns < tr.days[i]) & (burns >= tr.days[i] - BURN_LOOKBACK_DAYS)]
    if len(recent) < MIN_BURNS:
        return None
    return float(recent[-1] + np.median(np.diff(recent)) / 2.0)


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
           day: float | None = None, signal: str = "") -> Event:
    when = b.start if day is None else GRID_START + timedelta(days=float(day))
    signal = "mode_change" if day is None else signal
    lon_before = _slot(a) if a.mode in HELD else _lon_near(tr, _day(when), True)
    return Event(tr.norad_id, kind, when, signal, round(size, 3), round(lon_before, 3),
                 round(lon_after, 3), a.mode, b.mode, b.start)


def _held_rate(tr: Track, held: Segment) -> float:
    return _band(tr.rate[(tr.days >= _day(held.start)) & (tr.days < _day(held.end))])[0]


def _through_gap(tr: Track, i: int, moving: int, held_rate: float) -> float:
    p = i - 1
    dt = float(tr.days[i] - tr.days[p])
    if p < 0 or dt <= GAP_DAYS:
        return float(tr.days[i])
    shift = float(wrap180(tr.lon[i] - tr.lon[p])) - held_rate * dt
    rel = float(tr.rate[moving]) - held_rate
    if abs(rel) < FAST_RATE:
        return float(tr.days[i])
    lag = shift / rel
    when = tr.days[i] - lag if moving == i else tr.days[p] + lag
    return float(np.clip(when, tr.days[p], tr.days[i]))


def _arrival_day(tr: Track, held: Segment, j: int | None) -> float | None:
    return None if j is None else _through_gap(tr, j, j - 1, _held_rate(tr, held))


def _open_move(tr: Track, held: Segment, left: float | None) -> bool:
    if left is None or tr.days[-1] - left > OPEN_DAYS:
        return False
    rel = np.abs(tr.rate - _held_rate(tr, held))
    i = _sustained(tr, rel >= FAST_RATE, left - 1.0, float(tr.days[-1]) + 1.0)
    calm = np.flatnonzero(rel[:i] < FAST_RATE / 2) if i is not None else []
    return len(calm) > 0 and (calm[-1] == i - 1 or tr.days[i] - tr.days[calm[-1]] <= STEP_REACH_DAYS)


def _departure(tr: Track, a: Segment, b: Segment, limit: float,
               burn_days: np.ndarray) -> tuple[float | None, str, float | None]:
    i = _departure_date(tr, a, b, limit)
    if i is None:
        return None, "", None
    missed = _missed_burn_day(tr, i, burn_days)
    if missed is None:
        return _through_gap(tr, i, i, _held_rate(tr, a)), "rate_exit", None
    fast = np.flatnonzero((tr.days > tr.days[i]) & (tr.days < limit) & (np.abs(tr.rate) >= FAST_RATE))
    return missed, "burn_gap", float(tr.days[fast[0]]) if len(fast) else None


def _climb_burns(found: Sequence[Event], burn_days: np.ndarray, steps: np.ndarray) -> set[float]:
    out: set[float] = set()
    big = np.sort(burn_days[np.abs(steps) >= FREE_BURN_MIN_M])
    for g in (e for e in found if e.event_type == "graveyard"):
        last = _day(g.date)
        for day in big[big > last]:
            if day - last > CLIMB_GAP_DAYS:
                break
            out.add(float(day))
            last = day
    return out


def _free_burns(tr: Track, det: Sequence[Segment], found: Sequence[Event], burn_days: np.ndarray,
                steps: np.ndarray) -> list[Event]:
    taken = np.array([_day(e.date) for e in found])
    moves = sorted((e for e in found if e.event_type in (*DEPARTURES, "relocation_end")), key=lambda e: e.date)
    open_from = _day(moves[-1].date) if moves and moves[-1].event_type == "relocation_start" else np.inf
    climb = _climb_burns(found, burn_days, steps)
    out = []
    for k, seg in enumerate(det):
        if seg.mode in HELD or not any(s.mode in HELD for s in det[:k]) or any(s.mode in HELD for s in det[k:]):
            continue
        for day, step in zip(burn_days, steps):
            if (_day(seg.start) <= day < _day(seg.end) and abs(step) >= FREE_BURN_MIN_M
                    and tr.days[-1] - day >= HOLD_MIN_DAYS
                    and day < open_from and float(day) not in climb
                    and not (np.abs(taken - day) <= CLIMB_DAYS).any()):
                when = GRID_START + timedelta(days=float(day))
                out.append(Event(tr.norad_id, "free_burn", when, "a_step", round(float(step), 1),
                                 round(_lon_near(tr, day, True), 3), round(_lon_near(tr, day, False), 3),
                                 seg.mode, seg.mode, when))
    return out


def events_from_track(tr: Track, burn_days: np.ndarray | None = None, steps: np.ndarray | None = None) -> list[Event]:
    burn_days = np.array([]) if burn_days is None else burn_days
    steps = np.zeros(len(burn_days)) if steps is None else steps
    det = [s for s in with_inner_moves(tr, with_short_holds(tr, segments(tr))) if s.mode not in UNREAD]
    out: list[Event] = []
    departed: float | None = None
    same_slot: Segment | None = None
    for k, (a, b) in enumerate(zip(det, det[1:])):
        rest = det[k + 1:]
        if a.mode in HELD and b.mode in HELD:
            if a.mode == "controlled_lon_inc" and b.mode == "controlled_lon" and _arcs_overlap(a, b):
                ns = _ns_stop_day(tr, a, b)
                if ns is not None:
                    out.append(_event(tr, "ns_keeping_stop", a, b, _slot(b), b.inc_max, ns, "ns_gap"))
            elif not _arcs_overlap(a, b):
                left, signal, _ = _departure(tr, a, b, _day(b.end), burn_days)
                j = _arrival_date(tr, b, left if left is not None else _day(b.start))
                out.append(_event(tr, "relocation_start", a, b, _slot(b), 0.0, left, signal))
                out.append(_event(tr, "relocation_end", a, b, _slot(b), 0.0, _arrival_day(tr, b, j), "rate_entry"))
        elif a.mode in HELD:
            nxt = next((s for s in rest if s.mode in HELD), None)
            if nxt is not None and _arcs_overlap(a, nxt) and not _moved(tr, a, nxt):
                same_slot = nxt
                continue
            kind, rise = _departure_type(tr, a, rest)
            lon_after = _slot(nxt) if nxt else _lon_near(tr, _day(rest[-1].end), True)
            left, signal, burn = _departure(tr, a, b, _day(nxt.start) if nxt else _day(rest[-1].end), burn_days)
            if kind == "keeping_stop" and _open_move(tr, a, left):
                kind = "relocation_start"
            departed = left if left is not None else _day(b.start)
            if signal == "burn_gap" and kind != "keeping_stop" and burn is not None:
                out.append(_event(tr, "keeping_stop", a, b, _lon_near(tr, burn, True), 0.0, left, signal))
                out.append(_event(tr, kind, a, b, lon_after, rise, burn, "rate_exit"))
                departed = burn
            else:
                out.append(_event(tr, kind, a, b, lon_after, rise, left, signal))
        elif b.mode in HELD:
            if b is not same_slot:
                j = _arrival_date(tr, b, departed if departed is not None else _day(a.start))
                out.append(_event(tr, "relocation_end", a, b, _slot(b), 0.0, _arrival_day(tr, b, j), "rate_entry"))
            departed, same_slot = None, None
    return sorted(out + _free_burns(tr, det, out, burn_days, steps), key=lambda e: e.date)


def state_changes(records: Sequence[ElementSet]) -> list[Event]:
    kept, _ = drop_snapback_blocks(records)
    return events_from_track(track(kept), *burns(kept)) if kept else []


def _field(x: float) -> float | str:
    return "" if x != x else x


def as_row(e: Event) -> dict:
    return {"norad_id": e.norad_id, "event_type": e.event_type, "date": e.date.date().isoformat(),
            "signal": e.signal, "size": e.size, "lon_before": _field(e.lon_before), "lon_after": _field(e.lon_after),
            "mode_before": e.mode_before, "mode_after": e.mode_after,
            "mode_change": e.mode_change.date().isoformat()}

