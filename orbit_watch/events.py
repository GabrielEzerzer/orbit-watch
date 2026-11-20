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
from orbit_watch.modes import _R_GEO_KM, GRID_START, REGION_A_KM, REGION_E_MAX, Segment, Track, _arc, segments, track
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
SLOW_CYCLE_DAYS = 180.0
MIN_BURNS = 3
USUAL_SHARE = 0.8
SET_STEP_KM = 0.3
CLIMB_DAYS = 15.0
CLIMB_GAP_DAYS = 30.0
CLIMB_STALL_DAYS = 90.0
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
SET_CALM_M = 250.0
MOVE_SIDE_SETS = 3
REFERENCE_DAYS = 90.0
CLIMB_START_SHARE = 0.1
DRIFT_START_DAYS = 10.0
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


def _edge_slot(tr: Track, s: Segment, edge: str, until: float | None = None) -> float:
    if (s.lon_max - s.lon_min) % 360.0 <= SAME_SLOT_DEG:
        return _slot(s)
    lo, hi = _day(s.start), _day(s.end) if until is None else min(_day(s.end), until)
    near = (tr.days >= lo) & (tr.days < hi) & ((tr.days >= hi - EDGE_DAYS) if edge == "end" else (tr.days < lo + EDGE_DAYS))
    return _centre(*_arc(tr.lon[near])) if near.sum() >= HOLD_MIN_SETS else _slot(s)


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


def _in_hold(tr: Track, held: Segment, edge: str = "", margin: float = BOX_MARGIN_DEG) -> np.ndarray:
    return _in_box(tr, held, edge, margin) & _in_band(tr, held)


def _in_band(tr: Track, held: Segment) -> np.ndarray:
    centre, tol = _band(tr.rate[(tr.days >= _day(held.start)) & (tr.days < _day(held.end))])
    return np.abs(tr.rate - centre) <= tol


def _in_box(tr: Track, held: Segment, edge: str = "", margin: float = BOX_MARGIN_DEG) -> np.ndarray:
    lo, hi = _day(held.start), _day(held.end)
    sel = (tr.days >= lo) & (tr.days < hi)
    lon_min, lon_max = held.lon_min, held.lon_max
    near = sel & ((tr.days >= hi - EDGE_DAYS) if edge == "end" else (tr.days < lo + EDGE_DAYS))
    if edge and near.sum() >= HOLD_MIN_SETS:
        lon_min, lon_max = _arc(tr.lon[near])
    return (tr.lon - lon_min + margin) % 360.0 <= (lon_max - lon_min) % 360.0 + 2 * margin


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
    i = _sustained(tr, _in_hold(tr, held, "start"), lo, hi) if i is None else i
    if i is None:
        return None
    k = _sustained(tr, _in_hold(tr, held, margin=SAME_SLOT_DEG), lo, float(tr.days[i]))
    if k is None or not k or not _in_box(tr, held, margin=SAME_SLOT_DEG)[k:i].all():
        return i
    return k if abs(tr.rate[k - 1] - _held_rate(tr, held)) >= FAST_RATE else i


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
    flagged = np.abs(tr.rate[idx] - centre) > tol
    out_band = idx[flagged]
    pos = np.flatnonzero(flagged)
    runs: list[list[int]] = []
    for k, i in enumerate(out_band):
        if runs and (pos[k] == pos[k - 1] + 1 or tr.days[i] - tr.days[runs[-1][-1]] <= MOVE_MERGE_DAYS):
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


def _missed_burn_day(tr: Track, i: int, burns: np.ndarray, floor: float, fast: bool) -> tuple[float, float] | None:
    before = np.sort(burns[burns < tr.days[i]])
    if fast:
        return _late_burn_gap(before[before >= floor], float(tr.days[i]))
    recent = before[before >= tr.days[i] - BURN_LOOKBACK_DAYS]
    if len(recent) >= MIN_BURNS:
        return float(recent[-1] + np.median(np.diff(recent)) / 2.0), 0.0
    slow = before[before >= max(floor, tr.days[i] - SLOW_CYCLE_DAYS)]
    slow = slow[np.r_[True, np.diff(slow) > MOVE_MERGE_DAYS]] if len(slow) else slow
    if len(slow) < 2:
        return None
    cycle = slow[-1] - slow[-2]
    return (float(slow[-1] + cycle / 2.0), float(cycle)) if cycle / 2.0 < tr.days[i] - slow[-1] <= 1.5 * cycle else None


def _late_burn_gap(held_burns: np.ndarray, exit_day: float) -> tuple[float, float] | None:
    if not len(held_burns):
        return None
    starts = held_burns[np.r_[True, np.diff(held_burns) > MOVE_MERGE_DAYS]]
    recent = starts[starts >= held_burns[-1] - BURN_LOOKBACK_DAYS]
    if len(recent) < MIN_BURNS:
        return None
    cycle = float(np.median(np.diff(recent)))
    return (float(held_burns[-1] + cycle / 2.0), 0.0) if exit_day - held_burns[-1] > cycle else None


def _stop_before_odd_burns(tr: Track, i: int, burns: np.ndarray, steps: np.ndarray, floor: float,
                           slot: float) -> tuple[float, float] | None:
    if (np.abs(tr.rate[(tr.days >= tr.days[i]) & (tr.days <= tr.days[i] + SUSTAIN_DAYS)]) >= FAST_RATE).any():
        return None
    sel = (burns >= max(floor, tr.days[i] - SLOW_CYCLE_DAYS)) & (burns < tr.days[i])
    order = np.argsort(burns[sel])
    days, size = burns[sel][order], steps[sel][order]
    sign = np.sign(size)
    usual = np.sign(np.median(sign)) if len(sign) else 0.0
    odd = 0
    while odd < len(sign) and sign[len(sign) - 1 - odd] != usual:
        odd += 1
    if usual == 0 or odd == 0 or odd == len(sign):
        return None
    if (sign[:len(sign) - odd] == usual).mean() < USUAL_SHARE:
        return None
    if np.abs(size[len(sign) - odd:]).max() > np.abs(size[sign == usual]).max():
        return None
    side = np.sign(wrap180(np.interp(days[len(sign) - odd:], tr.days, tr.lon) - slot))
    if not (side == usual).all():
        return None
    last = days[len(sign) - 1 - odd]
    recent = days[(days >= last - BURN_LOOKBACK_DAYS) & (days <= last) & (sign == usual)]
    if len(recent) < MIN_BURNS:
        return None
    stop = float(last + np.median(np.diff(recent)) / 2.0)
    return (stop, 0.0) if stop < days[len(sign) - odd] else None


def _set_step(tr: Track, lo: float, hi: float) -> float | None:
    a, t, n = tr.semi_major_axis_km, tr.days, MOVE_SIDE_SETS
    for k in np.flatnonzero((t > lo) & (t <= hi))[:-1]:
        if k + 1 < n or k + 1 + n > len(t):
            continue
        if abs(np.median(a[k + 1:k + 1 + n]) - np.median(a[k + 1 - n:k + 1])) >= SET_STEP_KM:
            j = k + int(np.argmax(np.abs(np.diff(a[k:k + n + 1])) >= SET_STEP_KM))
            return float(t[j] + t[j + 1]) / 2.0
    return None


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


def _move_sma(tr: Track, held: Segment, lo: float, hi: float) -> float:
    held_a = _a_between(tr, _day(held.start), _day(held.end))
    sel = (tr.days >= lo) & (tr.days < hi)
    rel = tr.rate - _held_rate(tr, held)
    moving = sel & (np.abs(rel) >= FAST_RATE)
    idx = np.flatnonzero(sel)
    way = np.where(moving, np.sign(rel), 0.0)
    runs = np.split(idx, np.flatnonzero(np.diff(way[idx])) + 1) if len(idx) else []
    fast = [r for r in runs if moving[r[0]] and len(r) >= MOVE_SIDE_SETS]
    net = float(np.sum(wrap180(np.diff(tr.lon[idx])))) if len(idx) else 0.0
    ahead = [r for r in fast if abs(net) >= MOVE_MIN_DEG and way[r[0]] == np.sign(net)]
    first = (ahead or fast or [None])[0]
    if first is not None:
        moving = np.zeros_like(moving)
        moving[first] = True
    pick = moving if moving.any() else sel
    return float(np.median(tr.semi_major_axis_km[pick]) - np.median(held_a)) if pick.any() and len(held_a) else 0.0


def _fast_until(tr: Track, held: Segment, left: float, climb: float) -> bool:
    sel = (tr.days >= left) & (tr.days < climb)
    return _jumps(tr, held, left, climb) and float(np.median(np.abs(tr.rate[sel] - _held_rate(tr, held)))) >= FAST_RATE


def _climb_start(tr: Track, held: Segment, left: float, burn_days: np.ndarray, steps: np.ndarray) -> float | None:
    idx = np.flatnonzero(tr.days >= left)
    base = np.median(_a_between(tr, _day(held.start), _day(held.end)))
    raw = tr.semi_major_axis_km[idx]
    a = np.array([np.median(raw[max(0, k - 1):k + 2]) for k in range(len(raw))])
    top, gained, start = a[0], left, None
    for k in range(1, len(idx)):
        if a[k] - top >= FREE_BURN_MIN_M / 1000.0:
            if tr.days[idx[k]] - gained > CLIMB_STALL_DAYS:
                lo, hi = float(tr.days[idx[k - 1]]), float(tr.days[idx[k]])
                big = burn_days[(burn_days >= lo - STEP_REACH_DAYS) & (burn_days <= hi) & (np.abs(steps) >= FREE_BURN_MIN_M)]
                start = float(big[-1]) if len(big) else lo
            top, gained = a[k], float(tr.days[idx[k]])
        if a[k] - base >= GRAVEYARD_RISE_KM:
            return start
    return None


def _event(tr: Track, kind: str, a: Segment, b: Segment, lon_after: float, size: float,
           day: float | None = None, signal: str = "") -> Event:
    when = b.start if day is None else GRID_START + timedelta(days=float(day))
    signal = "mode_change" if day is None else signal
    lon_before = _edge_slot(tr, a, "end", _day(when)) if a.mode in HELD else _lon_near(tr, _day(when), True)
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
    if lag < 0 and abs(shift) >= MOVE_MIN_DEG:
        return float(tr.days[i])
    when = tr.days[i] - lag if moving == i else tr.days[p] + lag
    return float(np.clip(when, tr.days[p], tr.days[i]))


def _arrival_day(tr: Track, held: Segment, j: int | None) -> float | None:
    return None if j is None else _through_gap(tr, j, j - 1, _held_rate(tr, held))


def _open_move(tr: Track, held: Segment, left: float | None, burn_days: np.ndarray, steps: np.ndarray) -> bool:
    if left is None or tr.days[-1] - left > OPEN_DAYS:
        return False
    if ((burn_days > left) & (burn_days <= left + CLIMB_DAYS) & (np.abs(steps) >= FREE_BURN_MIN_M)).any():
        return True
    return _jumps(tr, held, left, float(tr.days[-1]) + 1.0)


def _crossing_burn(tr: Track, held: Segment, left: float | None, burn_days: np.ndarray) -> float | None:
    if left is None:
        return None
    before = burn_days[(burn_days >= _day(held.start)) & (burn_days < left)]
    pre = np.flatnonzero(tr.days < before.max()) if len(before) else []
    post = np.flatnonzero(tr.days >= left)
    if not len(pre) or not len(post):
        return None
    burn, slot = float(before.max()), _slot(held)
    side = np.sign(wrap180(tr.lon[post[0]] - slot))
    rel = tr.rate[(tr.days > burn) & (tr.days <= left)] - _held_rate(tr, held)
    if side == 0 or np.sign(wrap180(tr.lon[pre[-1]] - slot)) != -side or not len(rel) or (np.sign(rel) != side).any():
        return None
    return burn


def _burns_on(tr: Track, held: Segment, left: float | None, limit: float, burn_days: np.ndarray,
              steps: np.ndarray) -> bool:
    if left is None or not _jumps(tr, held, left, left + STEP_REACH_DAYS):
        return False
    return bool(((burn_days > left + CLIMB_DAYS) & (burn_days < limit) & (np.abs(steps) >= FREE_BURN_MIN_M)).any())


def _held_again(tr: Track, held: Segment, left: float, move: float, burn_days: np.ndarray, steps: np.ndarray) -> bool:
    box = min(HOLD_BOX_DEG, (held.lon_max - held.lon_min) % 360.0 + 2 * BOX_MARGIN_DEG)
    for burn in burn_days[(burn_days > left) & (burn_days < move) & (np.abs(steps) >= FREE_BURN_MIN_M)]:
        idx = np.flatnonzero((tr.days > burn) & (tr.days < move))
        if (len(idx) >= HOLD_MIN_SETS and tr.days[idx[0]] - burn <= STEP_REACH_DAYS
                and tr.days[idx[-1]] - tr.days[idx[0]] >= HOLD_MIN_DAYS and (np.abs(tr.rate[idx]) <= SLOW_RATE).all()
                and np.degrees(np.ptp(np.unwrap(np.radians(tr.lon[idx])))) <= box):
            return True
    return False


def _drifting_from(tr: Track, held: Segment, left: float, move: float) -> bool:
    sel = (tr.days >= left) & (tr.days < min(move, left + DRIFT_START_DAYS))
    nxt = np.flatnonzero(tr.days >= move)
    if sel.sum() < MOVE_SIDE_SETS or not len(nxt):
        return False
    rel = tr.rate - _held_rate(tr, held)
    return bool(np.sign(rel[nxt[0]]) * np.median(rel[sel]) >= SLOW_RATE)


def _jumps(tr: Track, held: Segment, left: float, hi: float) -> bool:
    rel = np.abs(tr.rate - _held_rate(tr, held))
    i = _sustained(tr, rel >= FAST_RATE, left - 1.0, hi)
    calm = np.flatnonzero(rel[:i] < FAST_RATE / 2) if i is not None else []
    return len(calm) > 0 and (calm[-1] == i - 1 or tr.days[i] - tr.days[calm[-1]] <= STEP_REACH_DAYS)


def _departure(tr: Track, a: Segment, b: Segment, limit: float, burn_days: np.ndarray,
               steps: np.ndarray) -> tuple[float | None, str, float | None, float, float | None, bool]:
    i = _departure_date(tr, a, b, limit)
    if i is None:
        return None, "", None, 0.0, None, False
    fast = bool((np.abs(tr.rate[(tr.days >= tr.days[i]) & (tr.days <= tr.days[i] + SUSTAIN_DAYS)]) >= FAST_RATE).any())
    missed = _stop_before_odd_burns(tr, i, burn_days, steps, _day(a.start), _slot(a))
    exit_day = float(tr.days[i])
    soon = (tr.days >= exit_day) & (tr.days <= exit_day + SUSTAIN_DAYS)
    natural = (fast and not ((burn_days > exit_day) & (burn_days <= exit_day + SUSTAIN_DAYS)).any()
               and np.abs(tr.rate[soon] - _held_rate(tr, a)).max() <= 2 * FAST_RATE
               and not _jumps(tr, a, exit_day, exit_day + SUSTAIN_DAYS)
               and _drifting_from(tr, a, exit_day - DRIFT_START_DAYS, exit_day))
    if missed is None and (natural or not fast):
        missed = _missed_burn_day(tr, i, burn_days, _day(a.start), fast)
    if missed is None:
        return _through_gap(tr, i, i, _held_rate(tr, a)), "rate_exit", None, 0.0, float(tr.days[i]), False
    late = fast and natural
    fast = np.flatnonzero((tr.days > tr.days[i]) & (tr.days < limit) & (np.abs(tr.rate) >= FAST_RATE))
    if not len(fast):
        return missed[0], "burn_gap", None, missed[1], float(tr.days[i]), late
    return missed[0], "burn_gap", float(tr.days[fast[0]]), missed[1], float(tr.days[i]), late


def _burn_after_drift(tr: Track, left: float, limit: float, burn_days: np.ndarray, steps: np.ndarray) -> float | None:
    if (np.abs(tr.rate[(tr.days >= left) & (tr.days <= left + SUSTAIN_DAYS)]) >= FAST_RATE).any():
        return None
    fast = np.flatnonzero((tr.days > left) & (tr.days < min(limit, left + REACH_DAYS)) & (np.abs(tr.rate) >= FAST_RATE))
    if not len(fast):
        return None
    lo, hi = float(tr.days[fast[0]]) - STEP_REACH_DAYS, float(tr.days[fast[0]])
    big = burn_days[(burn_days > max(left, lo)) & (burn_days <= hi) & (np.abs(steps) >= FREE_BURN_MIN_M)]
    return float(big.min()) if len(big) else None


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


def _seen_in_sets(tr: Track, day: float, burn_days: np.ndarray, picked: dict[float, float]) -> bool:
    b = np.sort(burn_days)
    k = int(np.flatnonzero(b == day)[0])
    first, last = k, k
    while first and b[first] - b[first - 1] <= MOVE_MERGE_DAYS:
        first -= 1
    while last + 1 < len(b) and b[last + 1] - b[last] <= MOVE_MERGE_DAYS:
        last += 1
    rivals = [abs(picked[float(d)]) for d in b[first:last + 1] if float(d) in picked]
    if abs(picked[day]) < max(rivals):
        return False
    lo = max(b[first] - STEP_REACH_DAYS, b[first - 1] if first else -np.inf)
    hi = min(b[last] + STEP_REACH_DAYS, b[last + 1] if last + 1 < len(b) else np.inf)
    before = tr.semi_major_axis_km[(tr.days >= lo) & (tr.days < b[first])][-3:]
    after = tr.semi_major_axis_km[(tr.days > b[last]) & (tr.days <= hi)][:3]
    if not len(before) or not len(after):
        return True
    return abs(float(np.median(after) - np.median(before))) * 1000.0 >= FREE_BURN_MIN_M


def _set_steps(tr: Track, lo: float, hi: float, burn_days: np.ndarray) -> list[tuple[float, float]]:
    idx = np.flatnonzero((tr.days >= lo) & (tr.days < hi))
    a, t = tr.semi_major_axis_km, tr.days
    def line(x: np.ndarray) -> np.ndarray | None:
        if np.ptp(t[x]) <= 0:
            return None
        fit = np.polyfit(t[x], a[x], 1)
        return fit if np.abs(a[x] - np.polyval(fit, t[x])).max() * 1000.0 <= SET_CALM_M else None

    cand = []
    for k in range(3, len(idx) - 2):
        b = idx[k - 3:k]
        fit = line(b) if t[b[-1]] - t[b[0]] <= STEP_REACH_DAYS else None
        if fit is None or abs(a[idx[k]] - np.polyval(fit, t[idx[k]])) * 1000.0 <= SET_CALM_M:
            continue
        for j in range(k, len(idx) - 2):
            f = idx[j:j + 3]
            if t[f[-1]] - t[b[-1]] > STEP_REACH_DAYS:
                break
            after = line(f)
            if after is not None and abs(after[0] - fit[0]) * 1000.0 <= SET_CALM_M:
                jump = float(np.median(a[f] - np.polyval(fit, t[f]))) * 1000.0
                mid = float(t[b[-1]] + t[idx[k]]) / 2.0
                step = np.diff(a[idx[np.abs(t[idx] - mid) <= MOVE_SIDE_DAYS]]) * 1000.0
                scale = 1.4826 * float(np.median(np.abs(step - np.median(step))))
                if (abs(jump) >= max(FREE_BURN_MIN_M, FROZEN.z_min * scale)
                        and not (np.abs(burn_days - mid) <= MOVE_MERGE_DAYS).any()):
                    cand.append((mid, jump))
                break
    out: list[tuple[float, float]] = []
    for mid, jump in cand:
        if out and mid - out[-1][0] <= MOVE_MERGE_DAYS:
            out[-1] = (mid, jump) if abs(jump) > abs(out[-1][1]) else out[-1]
        else:
            out.append((mid, jump))
    return out


def _free_burns(tr: Track, det: Sequence[Segment], found: Sequence[Event], burn_days: np.ndarray,
                steps: np.ndarray) -> list[Event]:
    taken = np.array([_day(e.date) for e in found])
    moves = sorted((e for e in found if e.event_type in (*DEPARTURES, "relocation_end")), key=lambda e: e.date)
    open_from = (_day(moves[-1].date) if moves and moves[-1].event_type == "relocation_start"
                 and tr.days[-1] - _day(moves[-1].date) <= OPEN_DAYS else np.inf)
    free = [seg for k, seg in enumerate(det) if seg.mode not in HELD
            and any(s.mode in HELD for s in det[:k]) and not any(s.mode in HELD for s in det[k:])]
    for seg in free:
        extra = _set_steps(tr, _day(seg.start), _day(seg.end), burn_days)
        burn_days, steps = np.r_[burn_days, [d for d, _ in extra]], np.r_[steps, [s for _, s in extra]]
    climb = _climb_burns(found, burn_days, steps)
    picked: dict[float, float] = {}
    modes: dict[float, str] = {}
    for seg in free:
        for day, step in zip(burn_days, steps):
            if (_day(seg.start) <= day < _day(seg.end) and abs(step) >= FREE_BURN_MIN_M
                    and tr.days[-1] - day >= HOLD_MIN_DAYS
                    and day < open_from and float(day) not in climb
                    and not (np.abs(taken - day) <= CLIMB_DAYS).any()):
                picked[float(day)], modes[float(day)] = float(step), seg.mode
    out = []
    for day, step in picked.items():
        if _seen_in_sets(tr, day, burn_days, picked):
            when = GRID_START + timedelta(days=day)
            out.append(Event(tr.norad_id, "free_burn", when, "a_step", round(step, 1),
                             round(_lon_near(tr, day, True), 3), round(_lon_near(tr, day, False), 3),
                             modes[day], modes[day], when))
    return out


def _first_climb(tr: Track, det: Sequence[Segment], burn_days: np.ndarray, steps: np.ndarray) -> list[Event]:
    if not len(tr.days) or not det or any(s.mode in HELD for s in det):
        return []
    a = tr.semi_major_axis_km
    first = tr.days < tr.days[0] + REFERENCE_DAYS
    ref = float(np.median(a[first]))
    if not REGION_A_KM[0] <= ref <= REGION_A_KM[1] or np.median(tr.eccentricity[first]) > REGION_E_MAX:
        return []
    med = np.array([np.median(a[max(k - 1, 0):k + 2]) for k in range(len(a))])
    stays = np.flip(np.logical_and.accumulate(np.flip(med - ref >= GRAVEYARD_RISE_KM)))
    if not stays.any():
        return []
    i = int(np.argmax(stays))
    if np.median(a[i:]) < _R_GEO_KM + GRAVEYARD_RISE_KM:
        return []
    rise = float(np.max(a[i:]) - ref)
    low = np.flatnonzero(a[:i] - ref < CLIMB_START_SHARE * rise)
    if not len(low) or tr.days[low[-1]] < tr.days[0] + REFERENCE_DAYS:
        return []
    pre = int(low[-1])
    seg = {k: next((s for s in det if _day(s.start) <= tr.days[k] < _day(s.end)), None) for k in (pre, i)}
    if seg[pre] is None or seg[i] is None:
        return []
    climb = burn_days[(burn_days > tr.days[pre]) & (burn_days <= tr.days[i]) & (np.abs(steps) >= FREE_BURN_MIN_M)]
    day = float(climb.min()) if len(climb) else _through_gap(tr, pre + 1, pre + 1, float(tr.rate[pre]))
    when = GRID_START + timedelta(days=day)
    return [Event(tr.norad_id, "graveyard", when, "a_step", round(rise, 3), round(_lon_near(tr, day, True), 3),
                  round(_lon_near(tr, _day(det[-1].end), True), 3), seg[pre].mode, seg[i].mode, when)]


def readable_segments(tr: Track) -> list[Segment]:
    return [s for s in with_inner_moves(tr, with_short_holds(tr, segments(tr))) if s.mode not in UNREAD]


def holds_of(tr: Track) -> list[tuple[float, float]]:
    return [(_day(s.start), _day(s.end)) for s in readable_segments(tr) if s.mode in HELD]


def events_from_track(tr: Track, burn_days: np.ndarray | None = None, steps: np.ndarray | None = None) -> list[Event]:
    burn_days = np.array([]) if burn_days is None else burn_days
    steps = np.zeros(len(burn_days)) if steps is None else steps
    det = readable_segments(tr)
    out: list[Event] = []
    departed: float | None = None
    same_slot: Segment | None = None
    for k, (a, b) in enumerate(zip(det, det[1:])):
        rest = det[k + 1:]
        if a.mode in HELD and b.mode in HELD:
            if a.mode == "controlled_lon_inc" and b.mode == "controlled_lon" and _arcs_overlap(a, b):
                ns = _ns_stop_day(tr, a, b)
                if ns is not None:
                    out.append(_event(tr, "ns_keeping_stop", a, b, _edge_slot(tr, b, "start"), b.inc_max, ns, "ns_gap"))
            elif not _arcs_overlap(a, b):
                left, signal, _, _, _, _ = _departure(tr, a, b, _day(b.end), burn_days, steps)
                j = _arrival_date(tr, b, left if left is not None else _day(b.start))
                out.append(_event(tr, "relocation_start", a, b, _edge_slot(tr, b, "start"), 0.0, left, signal))
                out.append(_event(tr, "relocation_end", a, b, _edge_slot(tr, b, "start"), 0.0, _arrival_day(tr, b, j), "rate_entry"))
        elif a.mode in HELD:
            nxt = next((s for s in rest if s.mode in HELD), None)
            if nxt is not None and _arcs_overlap(a, nxt) and not _moved(tr, a, nxt):
                same_slot = nxt
                continue
            kind, rise = _departure_type(tr, a, rest)
            lon_after = _edge_slot(tr, nxt, "start") if nxt else _lon_near(tr, _day(rest[-1].end), True)
            limit = _day(nxt.start) if nxt else _day(rest[-1].end)
            left, signal, burn, cycle, exit_day, late = _departure(tr, a, b, limit, burn_days, steps)
            if kind == "keeping_stop" and (_open_move(tr, a, left, burn_days, steps)
                                           or _burns_on(tr, a, left, limit, burn_days, steps)):
                kind = "relocation_start"
            pushed = _burn_after_drift(tr, left, limit, burn_days, steps) if signal == "rate_exit" and kind != "keeping_stop" else None
            if pushed is not None:
                left, signal = pushed, "a_step"
            climb = _climb_start(tr, a, left, burn_days, steps) if kind == "graveyard" and left is not None else None
            if climb is not None:
                out.append(_event(tr, "graveyard", b, b, lon_after, rise, climb, "a_step"))
                if _fast_until(tr, a, left, climb):
                    kind, limit = "relocation_start", climb
                else:
                    before = _a_between(tr, left, climb)
                    kind, rise = "keeping_stop", float(np.max(before) - np.median(_a_between(tr, _day(a.start), _day(a.end))))
            crossing = _crossing_burn(tr, a, left, burn_days) if kind == "keeping_stop" and signal == "rate_exit" else None
            if crossing is not None:
                left, signal = crossing, "a_step"
            step = _set_step(tr, left, min(limit, exit_day)) if signal == "burn_gap" and kind != "keeping_stop" and cycle else None
            if step is not None:
                left, signal = step, "a_step"
            departed = left if left is not None else _day(b.start)
            if kind == "relocation_start":
                moved = burn if signal == "burn_gap" and burn is not None else departed
                rise = _move_sma(tr, a, moved, limit)
            if signal == "burn_gap" and kind != "keeping_stop" and burn is not None and burn - left < cycle:
                first = int(np.flatnonzero(tr.days == burn)[0])
                out.append(_event(tr, kind, a, b, lon_after, rise, _through_gap(tr, first, first, _held_rate(tr, a)),
                                  "rate_exit"))
                departed = burn
            elif signal == "burn_gap" and kind != "keeping_stop" and burn is not None and (
                    _drifting_from(tr, a, left, burn) or (late and kind == "relocation_start")):
                out.append(_event(tr, kind, a, b, lon_after, rise, left, signal))
            elif signal == "burn_gap" and kind != "keeping_stop" and burn is not None:
                if not _held_again(tr, a, left, burn, burn_days, steps):
                    out.append(_event(tr, "keeping_stop", a, b, _lon_near(tr, burn, True), 0.0, left, signal))
                out.append(_event(tr, kind, a, b, lon_after, rise, burn, "rate_exit"))
                departed = burn
            elif kind != "keeping_stop" or a.windows or ((burn_days >= _day(a.start)) & (burn_days <= departed)).any():
                out.append(_event(tr, kind, a, b, lon_after, rise, left, signal))
        elif b.mode in HELD:
            if b is not same_slot:
                j = _arrival_date(tr, b, departed if departed is not None else _day(a.start))
                out.append(_event(tr, "relocation_end", a, b, _edge_slot(tr, b, "start"), 0.0, _arrival_day(tr, b, j), "rate_entry"))
            departed, same_slot = None, None
    out = _merge_pauses(sorted(out, key=lambda e: e.date))
    return sorted(out + _free_burns(tr, det, out, burn_days, steps) + _first_climb(tr, det, burn_days, steps),
                  key=lambda e: e.date)


def _merge_pauses(found: list[Event]) -> list[Event]:
    out: list[Event] = []
    carry: tuple[float, float] | None = None
    for e in found:
        moves = [k for k, x in enumerate(out) if x.event_type in ("relocation_start", "relocation_end")]
        if (e.event_type == "relocation_start" and len(moves) >= 2 and out[moves[-1]].event_type == "relocation_end"
                and out[moves[-2]].event_type == "relocation_start"
                and (e.date - out[moves[-1]].date).total_seconds() < MOVE_SIDE_DAYS * 86400.0):
            first, pause = out[moves[-2]], out[moves[-1]]
            if np.sign(wrap180(pause.lon_after - first.lon_before)) == np.sign(wrap180(e.lon_after - e.lon_before)):
                out[moves[-2]] = replace(first, lon_after=e.lon_after)
                del out[moves[-1]]
                carry = (e.lon_before, first.lon_before)
                continue
        if e.event_type == "relocation_end" and carry is not None:
            e = replace(e, lon_before=carry[1]) if e.lon_before == carry[0] else e
            carry = None
        out.append(e)
    return out


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

