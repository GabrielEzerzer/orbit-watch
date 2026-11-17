from datetime import timedelta

import numpy as np

from orbit_watch import events as E
from orbit_watch import modes as M
from orbit_watch.elements import _build
from orbit_watch.geo import gmst_deg

EDGES = M.window_edges()


def element_sets(days, lon, rate, inc=0.05, norad=90003):
    out = []
    for d, l, r in zip(days, lon, rate):
        epoch = M.GRID_START + timedelta(days=float(d))
        out.append(_build(norad, None, epoch, M.SIDEREAL_REV_PER_DAY + r / 360.0, 0.0002, inc, 0.0, 0.0,
                          (l + gmst_deg(epoch)) % 360.0, 0.0, 0.0, 0.0))
    return out


def keeper_track(days, lon0, seed):
    rng = np.random.default_rng(seed)
    lon = lon0 + 0.04 * np.sin(2 * np.pi * days / 14.0) + rng.normal(0, 0.003, len(days))
    return lon, np.gradient(lon, days)


def retired_track(days, start, seed):
    lon, rate = keeper_track(days, 10.0, seed)
    jitter = np.random.default_rng(seed).normal(0, 0.0002, len(days))
    return np.where(days < start, lon, 10.0), np.where(days < start, rate, jitter)


def relocating(move_start, move_days, rate, end=EDGES[14]):
    days = np.arange(0.0, end, 0.25)
    lon, r = keeper_track(days, 10.0, 0)
    moving = (days >= move_start) & (days < move_start + move_days)
    shift = np.cumsum(np.where(moving, rate, 0.0)) * 0.25
    return days, lon + shift, r + np.where(moving, rate, 0.0)


def test_relocation_gives_a_start_and_an_end_near_the_move():
    start = EDGES[5] + 7.0
    days, lon, rate = relocating(start, 20.0, 0.3)
    found = E.state_changes(element_sets(days, lon, rate))
    kinds = [f.event_type for f in found]
    assert kinds == ["relocation_start", "relocation_end"]
    first, second = found
    assert abs(E._day(first.date) - start) <= 1 and abs(E._day(second.date) - (start + 20.0)) <= 1
    assert (first.signal, second.signal) == ("rate_exit", "rate_entry")
    assert abs(first.lon_before - 10.0) < 0.2 and abs(first.lon_after - 16.0) < 0.3


def test_climb_of_a_kept_object_is_a_graveyard_move():
    days = np.arange(0.0, EDGES[10], 0.25)
    start = EDGES[5] + 7.0
    lon, rate = retired_track(days, start, 1)
    up = np.clip((days - start) / 10.0, 0.0, 1.0) * 300.0
    drift = -1.5 * up / 42164.0 * 360.98
    lon = lon + np.cumsum(drift) * 0.25
    found = E.state_changes(element_sets(days, lon, rate + drift))
    assert [f.event_type for f in found] == ["graveyard"]
    assert found[0].size > 250 and abs(E._day(found[0].date) - start) <= 1


def test_stop_between_two_moves_is_an_arrival_and_a_departure():
    days = np.arange(0.0, EDGES[14], 0.25)
    lon, rate = keeper_track(days, 10.0, 2)
    lon, rate = 10.0 + 0.1 * (lon - 10.0), 0.1 * rate
    legs = ((EDGES[5] + 7.0, 10.0), (EDGES[5] + 37.0, 15.0))
    for start, length in legs:
        moving = (days >= start) & (days < start + length)
        lon = lon + np.cumsum(np.where(moving, 0.3, 0.0)) * 0.25
        rate = rate + np.where(moving, 0.3, 0.0)
    found = E.state_changes(element_sets(days, lon, rate))
    assert [f.event_type for f in found] == ["relocation_start", "relocation_end"] * 2
    expected = [legs[0][0], legs[0][0] + 10.0, legs[1][0], legs[1][0] + 15.0]
    assert all(abs(E._day(f.date) - d) <= 1 for f, d in zip(found, expected))


def test_slow_drift_with_no_burn_into_it_is_not_a_hold():
    days = np.arange(0.0, 40.0, 0.25)
    rate = np.where(days < 30.0, 0.012, -2.0)
    lon = 10.0 + np.cumsum(rate) * 0.25
    tr = M.track(element_sets(days, lon, rate))
    assert E.short_holds(tr, 0.0, 40.0) == []


def test_keeping_stop_is_dated_between_the_last_burn_and_the_missed_one():
    days = np.arange(0.0, EDGES[10], 0.25)
    last = EDGES[5] + 10.0
    burns = np.arange(3.0, last + 0.1, 7.0)
    since = days - burns[np.clip(np.searchsorted(burns, days, side="right") - 1, 0, None)]
    rate = -0.00525 + 0.0015 * since + np.random.default_rng(3).normal(0, 0.0002, len(days))
    lon = 10.0 + np.cumsum(rate) * 0.25
    found = E.state_changes(element_sets(days, lon, rate))
    assert [f.event_type for f in found] == ["keeping_stop"]
    assert found[0].signal == "burn_gap" and abs(E._day(found[0].date) - (burns[-1] + 3.5)) <= 1


def test_kilometre_burn_after_a_graveyard_move_is_a_free_burn():
    days = np.arange(0.0, EDGES[14], 0.25)
    start, kick = EDGES[5] + 7.0, EDGES[9] + 3.0
    lon, rate = retired_track(days, start, 4)
    up = np.clip((days - start) / 10.0, 0.0, 1.0) * 300.0 + np.where(days >= kick, 2.0, 0.0)
    up = up + np.where(days >= EDGES[11] + 3.0, 0.3, 0.0)
    drift = -1.5 * up / 42164.0 * 360.98
    found = E.state_changes(element_sets(days, lon + np.cumsum(drift) * 0.25, rate + drift))
    assert [f.event_type for f in found] == ["graveyard", "free_burn"]
    assert abs(E._day(found[1].date) - kick) <= 1 and found[1].size > 1000


def quiet_keeper(days, seed=5):
    lon, rate = keeper_track(days, 10.0, seed)
    return 10.0 + 0.1 * (lon - 10.0), 0.1 * rate


def held(start, end, lon_min, lon_max, mode="controlled_lon"):
    return M.Segment(90009, M.GRID_START + timedelta(days=start), M.GRID_START + timedelta(days=end), mode, 2, 100,
                     lon_min, lon_max, 0.0, 0.05, 0.05)


def test_a_window_misread_between_two_holds_of_the_same_box_is_not_a_relocation(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    segs = [held(0, 60, 9.98, 10.02), held(60, 90, 9.98, 10.02, "librating_75E"), held(90, 150, 9.98, 10.03)]
    monkeypatch.setattr(E, "segments", lambda tr: segs)
    assert E.events_from_track(M.track(element_sets(days, lon, rate))) == []


def test_an_arrival_is_never_dated_before_its_departure(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    lon = np.where(days >= 65.0, lon + 0.4, lon)
    segs = [held(0, 60, 9.98, 10.02), held(60, 90, 9.98, 10.42, "drifting"), held(90, 150, 10.38, 10.42)]
    monkeypatch.setattr(E, "segments", lambda tr: segs)
    monkeypatch.setattr(E, "_departure", lambda *a: (80.0, "rate_exit", None))
    start, end = E.events_from_track(M.track(element_sets(days, lon, rate)))
    assert (start.event_type, end.event_type) == ("relocation_start", "relocation_end")
    assert E._day(end.date) >= E._day(start.date) == 80.0


def test_keeping_stop_then_a_later_climb_are_two_events():
    days = np.arange(0.0, EDGES[10], 0.25)
    last = EDGES[5] + 10.0
    burns = np.arange(3.0, last + 0.1, 7.0)
    since = days - burns[np.clip(np.searchsorted(burns, days, side="right") - 1, 0, None)]
    rate = -0.00525 + 0.0015 * since + np.random.default_rng(6).normal(0, 0.0002, len(days))
    climb = last + 30.0
    up = np.clip((days - climb) / 5.0, 0.0, 1.0) * 300.0
    rate = rate - 1.5 * up / 42164.0 * 360.98
    found = E.state_changes(element_sets(days, 10.0 + np.cumsum(rate) * 0.25, rate))
    assert [f.event_type for f in found[:2]] == ["keeping_stop", "graveyard"]
    assert abs(E._day(found[0].date) - (burns[-1] + 3.5)) <= 1 and abs(E._day(found[1].date) - climb) <= 1


def test_end_of_inclination_keeping_at_the_same_slot_is_an_ns_keeping_stop():
    days = np.arange(0.0, EDGES[14], 0.25)
    lon, rate = quiet_keeper(days, 7)
    stop = EDGES[5]
    inc = 0.05 + 0.0025 * np.clip(days - stop, 0.0, None)
    sets = [s for d, l, r, i in zip(days, lon, rate, inc) for s in element_sets([d], [l], [r], inc=float(i))]
    found = E.state_changes(sets)
    assert [f.event_type for f in found] == ["ns_keeping_stop"] and found[0].size > 0.3
