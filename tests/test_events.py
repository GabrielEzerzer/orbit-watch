from dataclasses import replace
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
    assert abs(first.size + 0.3 / (1.5 * 360.98) * 42164.0) < 2.0


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


def test_holds_less_than_half_a_degree_apart_are_one_slot(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    segs = [held(0, 75, 9.98, 10.02), held(75, 150, 10.28, 10.32)]
    monkeypatch.setattr(E, "segments", lambda tr: segs)
    assert E.events_from_track(M.track(element_sets(days, lon, rate))) == []


def test_a_move_out_and_back_to_the_same_slot_is_a_start_and_an_end(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    out = (days >= 65.0) & (days < 75.0)
    back = (days >= 75.0) & (days < 85.0)
    rate = rate + np.where(out, -0.5, 0.0) + np.where(back, 0.5, 0.0)
    lon = lon + np.cumsum(np.where(out, -0.5, 0.0) + np.where(back, 0.5, 0.0)) * 0.25
    segs = [held(0, 60, 9.98, 10.02), held(60, 90, 5.0, 10.02, "drifting"), held(90, 150, 9.98, 10.03)]
    monkeypatch.setattr(E, "segments", lambda tr: segs)
    found = E.events_from_track(M.track(element_sets(days, lon, rate)))
    assert [e.event_type for e in found] == ["relocation_start", "relocation_end"]


def test_an_arrival_is_never_dated_before_its_departure(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    lon = np.where(days >= 65.0, lon + 1.0, lon)
    segs = [held(0, 60, 9.98, 10.02), held(60, 90, 9.98, 11.02, "drifting"), held(90, 150, 10.98, 11.02)]
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


def test_a_climb_months_after_a_keeping_stop_is_a_graveyard_move_on_the_day_of_the_climb():
    days = np.arange(0.0, EDGES[14], 0.25)
    start = EDGES[3] + 7.0
    climb = start + 150.0
    lon, rate = keeper_track(days, 10.0, 3)
    rate = np.where(days < start, rate, 0.001 * (days - start))
    up = sum(np.where(days >= climb + k, 100.0, 0.0) for k in (0.0, 3.0, 6.0))
    rate = rate - 1.5 * up / 42164.0 * 360.98
    lon = np.where(days < start, lon, lon[days < start][-1] + np.cumsum(np.where(days < start, 0.0, rate)) * 0.25)
    found = E.state_changes(element_sets(days, lon, rate))
    assert [f.event_type for f in found] == ["keeping_stop", "graveyard"]
    assert abs(E._day(found[1].date) - climb) <= 1


def test_a_burn_into_fast_drift_months_before_a_climb_is_a_relocation_start_then_a_graveyard_move():
    days = np.arange(0.0, EDGES[14], 0.25)
    start = EDGES[3] + 7.0
    climb = start + 150.0
    lon, rate = keeper_track(days, 10.0, 3)
    up = np.where(days >= start, -50.0, 0.0) + sum(np.where(days >= climb + k, 120.0, 0.0) for k in (0.0, 3.0, 6.0))
    jitter = np.random.default_rng(3).normal(0, 0.0002, len(days))
    rate = np.where(days < start, rate, jitter) - 1.5 * up / 42164.0 * 360.98
    lon = np.where(days < start, lon, lon[days < start][-1] + np.cumsum(np.where(days < start, 0.0, rate)) * 0.25)
    found = E.state_changes(element_sets(days, lon, rate))
    assert [f.event_type for f in found] == ["relocation_start", "graveyard"]
    assert abs(E._day(found[0].date) - start) <= 1 and abs(E._day(found[1].date) - climb) <= 1
    assert abs(found[0].size + 50.0) < 2.0


def ns_sets(days, inc, seed=7):
    lon, rate = quiet_keeper(days, seed)
    return [s for d, l, r, i in zip(days, lon, rate, inc) for s in element_sets([d], [l], [r], inc=float(i))]


def test_end_of_inclination_keeping_is_dated_from_the_last_correction_plus_half_the_cycle():
    days = np.arange(0.0, EDGES[14], 0.25)
    last = EDGES[5] - 60.0
    fixes = np.arange(10.0, last + 0.1, 14.0)
    since = days - fixes[np.clip(np.searchsorted(fixes, days, side="right") - 1, 0, None)]
    inc = np.where(days < fixes[0], 0.03 + 0.0025 * days, 0.02 + 0.0025 * since)
    found = E.state_changes(ns_sets(days, inc))
    assert [f.event_type for f in found] == ["ns_keeping_stop"] and found[0].size > 0.3
    assert found[0].signal == "ns_gap" and abs(E._day(found[0].date) - (fixes[-1] + 7.0)) <= 1


def test_inclination_that_only_grows_through_the_kept_band_gives_no_ns_keeping_stop():
    days = np.arange(0.0, EDGES[14], 0.25)
    inc = 0.05 + 0.0025 * np.clip(days - EDGES[5], 0.0, None)
    assert E.state_changes(ns_sets(days, inc)) == []


def test_a_quick_move_inside_one_held_segment_is_a_start_and_an_end(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    moving = (days >= 70.0) & (days < 74.0)
    rate = rate + np.where(moving, -0.5, 0.0)
    lon = lon + np.cumsum(np.where(moving, -0.5, 0.0)) * 0.25
    monkeypatch.setattr(E, "segments", lambda tr: [held(0, 150, 7.9, 10.1)])
    found = E.events_from_track(M.track(element_sets(days, lon, rate)))
    assert [e.event_type for e in found] == ["relocation_start", "relocation_end"]
    assert abs(E._day(found[0].date) - 70.0) <= 1 and abs(E._day(found[1].date) - 74.0) <= 1


def test_a_short_blip_while_a_move_inside_a_held_segment_slows_down_is_not_a_second_move(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    push = np.where((days >= 70.0) & (days < 74.0), -0.5, 0.0) + np.where((days >= 76.5) & (days < 77.0), -0.3, 0.0)
    rate = rate + push
    lon = lon + np.cumsum(push) * 0.25
    keep = (days < 74.0) | (days >= 76.5)
    monkeypatch.setattr(E, "segments", lambda tr: [held(0, 150, 7.7, 10.1)])
    found = E.events_from_track(M.track(element_sets(days[keep], lon[keep], rate[keep])))
    assert [e.event_type for e in found] == ["relocation_start", "relocation_end"]


def test_a_burn_that_returns_to_the_same_slot_is_not_a_move_inside_a_held_segment(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    rate = rate + np.where((days >= 70.0) & (days < 72.0), 0.1, 0.0) - np.where((days >= 72.0) & (days < 74.0), 0.1, 0.0)
    monkeypatch.setattr(E, "segments", lambda tr: [held(0, 150, 9.9, 10.1)])
    assert E.events_from_track(M.track(element_sets(days, lon, rate))) == []


def test_a_short_move_between_holds_whose_ranges_touch_is_a_start_and_an_end(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    moving = (days >= 70.0) & (days < 72.0)
    rate = rate + np.where(moving, 0.35, 0.0)
    lon = lon + np.cumsum(np.where(moving, 0.35, 0.0)) * 0.25
    segs = [held(0, 60, 9.98, 10.02), held(60, 90, 9.98, 10.72, "drifting"), held(90, 150, 10.40, 10.72)]
    monkeypatch.setattr(E, "segments", lambda tr: segs)
    found = E.events_from_track(M.track(element_sets(days, lon, rate)))
    assert [e.event_type for e in found] == ["relocation_start", "relocation_end"]
    assert abs(E._day(found[1].date) - 72.0) <= 1


def test_a_departure_is_dated_from_the_hold_edge_when_the_hold_range_already_spans_the_new_slot(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    moving = (days >= 70.0) & (days < 72.0)
    rate = rate + np.where(moving, 0.35, 0.0)
    lon = lon + np.cumsum(np.where(moving, 0.35, 0.0)) * 0.25
    segs = [held(0, 60, 9.98, 10.72), held(60, 90, 9.98, 10.72, "drifting"), held(90, 150, 10.40, 10.72)]
    monkeypatch.setattr(E, "segments", lambda tr: segs)
    start = E.events_from_track(M.track(element_sets(days, lon, rate)))[0]
    assert start.event_type == "relocation_start" and start.signal == "rate_exit"
    assert abs(E._day(start.date) - 70.0) <= 1


def test_a_move_that_starts_inside_a_gap_is_dated_by_running_the_first_set_after_it_back(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    moving = (days >= 68.0) & (days < 88.0)
    rate = rate + np.where(moving, 0.4, 0.0)
    lon = lon + np.cumsum(np.where(moving, 0.4, 0.0)) * 0.25
    keep = (days < 65.0) | (days >= 75.0)
    segs = [held(0, 60, 9.98, 10.02), held(60, 90, 9.98, 18.02, "drifting"), held(90, 150, 17.98, 18.02)]
    monkeypatch.setattr(E, "segments", lambda tr: segs)
    start = E.events_from_track(M.track(element_sets(days[keep], lon[keep], rate[keep])))[0]
    assert start.event_type == "relocation_start" and abs(E._day(start.date) - 68.0) <= 1


def test_a_move_still_under_way_when_the_data_ends_is_a_relocation_start_not_a_keeping_stop(monkeypatch):
    days = np.arange(0.0, 120.0, 0.25)
    lon, rate = quiet_keeper(days)
    moving = days >= 100.0
    rate = rate + np.where(moving, 0.3, 0.0)
    lon = lon + np.cumsum(np.where(moving, 0.3, 0.0)) * 0.25
    monkeypatch.setattr(E, "segments", lambda tr: [held(0, 90, 9.98, 10.02), held(90, 120, 9.98, 16.0, "drifting")])
    found = E.events_from_track(M.track(element_sets(days, lon, rate)))
    assert [f.event_type for f in found] == ["relocation_start"] and abs(E._day(found[0].date) - 100.0) <= 1


def test_a_departure_that_keeps_burning_until_the_end_of_the_data_is_a_relocation_start(monkeypatch):
    days = np.arange(0.0, 120.0, 0.25)
    lon, rate = quiet_keeper(days)
    moving = days >= 100.0
    rate = rate + np.where(moving, -0.04, 0.0)
    lon = lon + np.cumsum(np.where(moving, -0.04, 0.0)) * 0.25
    monkeypatch.setattr(E, "segments", lambda tr: [held(0, 90, 9.98, 10.02), held(90, 120, 9.0, 10.02, "drifting")])
    found = E.events_from_track(M.track(element_sets(days, lon, rate)), np.array([110.0]), np.array([-13000.0]))
    assert [f.event_type for f in found] == ["relocation_start"]


def test_natural_drift_that_speeds_up_after_a_hold_near_the_end_of_the_data_stays_a_keeping_stop(monkeypatch):
    days = np.arange(0.0, 120.0, 0.25)
    lon, rate = quiet_keeper(days)
    free = days >= 100.0
    rate = np.where(free, 0.003 * (days - 100.0), rate)
    lon = np.where(free, lon[free.argmax()] + 0.0015 * (days - 100.0) ** 2, lon)
    monkeypatch.setattr(E, "segments", lambda tr: [held(0, 90, 9.98, 10.02), held(90, 120, 9.98, 10.4, "drifting")])
    found = E.events_from_track(M.track(element_sets(days, lon, rate)))
    assert [f.event_type for f in found] == ["keeping_stop"]


def test_an_arrival_into_a_hold_that_lasts_to_the_last_set_gives_no_departure():
    days = np.arange(0.0, EDGES[14] - 1.0, 0.25)
    lon, rate = keeper_track(days, 10.0, 0)
    start, stop = EDGES[12] + 5.0, EDGES[13] + 5.0
    moving = (days >= start) & (days < stop)
    lon = np.where(days >= stop, 10.0 + 0.3 * (stop - start), lon + np.cumsum(np.where(moving, 0.3, 0.0)) * 0.25)
    rate = np.where(days >= stop, 0.0, rate + np.where(moving, 0.3, 0.0))
    tr = M.track(element_sets(days, lon, rate))
    found = E.events_from_track(tr, np.array([stop + 10.0]), np.array([1500.0]))
    assert [f.event_type for f in found] == ["relocation_start", "relocation_end"]


def test_a_keeping_stop_on_a_slow_burn_cycle_is_dated_between_the_last_burn_and_the_missed_one(monkeypatch):
    days = np.arange(0.0, 200.0, 0.25)
    lon, rate = quiet_keeper(days)
    free = days >= 107.0
    rate = np.where(free, 0.002 * (days - 107.0), rate)
    lon = np.where(free, lon[free.argmax()] + 0.001 * (days - 107.0) ** 2, lon)
    monkeypatch.setattr(E, "segments", lambda tr: [held(0, 120, 9.98, 10.02), held(120, 200, 9.98, 40.0, "drifting")])
    found = E.events_from_track(M.track(element_sets(days, lon, rate)), np.array([20.0, 78.0]), np.array([1500.0, 1500.0]))
    assert [f.event_type for f in found] == ["keeping_stop"]
    assert found[0].signal == "burn_gap" and abs(E._day(found[0].date) - 107.0) <= 1


def test_a_move_whose_burn_follows_a_slow_drift_out_of_the_box_starts_at_the_burn(monkeypatch):
    days = np.arange(0.0, 220.0, 0.25)
    lon, rate = quiet_keeper(days)
    free = days >= 100.0
    rate = np.where(free, -0.002 * (days - 100.0), rate)
    rate = np.where(days >= 115.0, -0.3, rate)
    rate = np.where(days >= 130.0, 0.0, rate)
    lon = np.where(free, lon[free.argmax()] + np.cumsum(np.where(free, rate, 0.0)) * 0.25, lon)
    segs = [held(0, 120, 9.98, 10.02), held(120, 135, 5.0, 9.98, "drifting"), held(135, 220, lon[-1] - 0.02, lon[-1] + 0.02)]
    monkeypatch.setattr(E, "segments", lambda tr: segs)
    found = E.events_from_track(M.track(element_sets(days, lon, rate)), np.array([115.0]), np.array([9000.0]))
    assert [f.event_type for f in found] == ["relocation_start", "relocation_end"]
    assert found[0].signal == "a_step" and abs(E._day(found[0].date) - 115.0) <= 1


def test_free_drift_after_an_arrival_read_as_a_short_hold_gives_no_keeping_stop(monkeypatch):
    days = np.arange(0.0, 200.0, 0.25)
    rate = np.where(days < 60.0, -0.3, -0.001 * (days - 60.0))
    lon = 28.0 + np.cumsum(rate) * 0.25
    segs = [held(0, 60, 10.0, 28.0, "drifting"), replace(held(60, 80, lon[days < 80].min(), 10.0), windows=0),
            held(80, 200, lon[-1], 9.8, "drifting")]
    monkeypatch.setattr(E, "segments", lambda tr: segs)
    found = E.events_from_track(M.track(element_sets(days, lon, rate)), np.array([]), np.array([]))
    assert [f.event_type for f in found] == ["relocation_end"]


def test_a_detected_burn_with_no_step_in_the_sets_or_a_split_detection_is_not_a_free_burn():
    days = np.arange(0.0, EDGES[14], 0.25)
    start, fake, kick = EDGES[5] + 7.0, EDGES[8] + 3.0, EDGES[9] + 3.0
    lon, rate = retired_track(days, start, 4)
    up = np.clip((days - start) / 10.0, 0.0, 1.0) * 300.0 + np.where(days >= kick, 2.0, 0.0)
    drift = -1.5 * up / 42164.0 * 360.98
    tr = M.track(element_sets(days, lon + np.cumsum(drift) * 0.25, rate + drift))
    found = E.events_from_track(tr, np.array([fake, kick - 0.7, kick]), np.array([-4300.0, 1900.0, 2000.0]))
    assert [f.event_type for f in found] == ["graveyard", "free_burn"]
    assert abs(E._day(found[1].date) - kick) <= 1


def test_a_kilometre_burn_in_the_last_days_of_data_is_not_a_free_burn():
    days = np.arange(0.0, EDGES[14], 0.25)
    start, kick = EDGES[5] + 7.0, EDGES[14] - 6.0
    lon, rate = retired_track(days, start, 4)
    up = np.clip((days - start) / 10.0, 0.0, 1.0) * 300.0 + np.where(days >= kick, 2.0, 0.0)
    drift = -1.5 * up / 42164.0 * 360.98
    found = E.state_changes(element_sets(days, lon + np.cumsum(drift) * 0.25, rate + drift))
    assert [f.event_type for f in found] == ["graveyard"]


def test_a_burn_during_a_relocation_still_under_way_at_the_end_of_the_data_is_not_a_free_burn(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    push = np.where(days >= 100.0, 0.3, 0.0) + np.where(days >= 120.0, 0.2, 0.0)
    rate = rate + push
    lon = lon + np.cumsum(push) * 0.25
    monkeypatch.setattr(E, "segments", lambda tr: [held(0, 90, 9.98, 10.02), held(90, 150, 9.98, 25.0, "drifting")])
    found = E.events_from_track(M.track(element_sets(days, lon, rate)), np.array([120.0]), np.array([-15600.0]))
    assert [f.event_type for f in found] == ["relocation_start"]


def test_burns_that_carry_on_a_graveyard_climb_weeks_apart_are_not_free_burns():
    days = np.arange(0.0, EDGES[14], 0.25)
    start = EDGES[5] + 7.0
    lon, rate = retired_track(days, start, 4)
    up = np.clip((days - start) / 10.0, 0.0, 1.0) * 200.0
    up = up + np.where(days >= start + 25.0, 60.0, 0.0) + np.where(days >= start + 50.0, 60.0, 0.0)
    drift = -1.5 * up / 42164.0 * 360.98
    found = E.state_changes(element_sets(days, lon + np.cumsum(drift) * 0.25, rate + drift))
    assert [f.event_type for f in found] == ["graveyard"]


def test_a_held_window_between_stretches_of_an_inclined_orbit_gives_no_events(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    segs = [held(0, 60, 9.9, 10.1, "inclined"), held(60, 90, 9.98, 10.02), held(90, 150, 9.9, 10.1, "inclined")]
    monkeypatch.setattr(E, "segments", lambda tr: segs)
    found = E.events_from_track(M.track(element_sets(days, lon, rate, inc=30.0)), np.array([120.0]), np.array([-4000.0]))
    assert found == []


def test_one_wild_element_set_next_to_a_normal_one_at_the_end_of_the_data_gives_no_event():
    days = np.concatenate([np.arange(0.0, EDGES[9], 0.25), np.arange(EDGES[9], EDGES[10], 3.0)])
    lon, rate = keeper_track(days, 10.0, 8)
    days = np.insert(days, len(days) - 1, days[-1] - 0.02)
    lon, rate = np.insert(lon, len(lon) - 1, lon[-1] + 5.2), np.insert(rate, len(rate) - 1, -7.3)
    assert E.state_changes(element_sets(days, lon, rate)) == []


def test_an_arrival_after_a_gap_in_which_the_drift_reverses_is_dated_at_the_first_set_after_it(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    drift = np.where(days < 60.0, -0.6, 0.0)
    lon = lon + np.where(days < 60.0, 0.6 * (60.0 - days), 0.0) + np.where(days >= 60.0, 1.5, 0.0)
    rate = rate + drift
    keep = (days < 60.0) | (days >= 65.0)
    segs = [held(0, 60, 10.0, 46.0, "drifting"), held(60, 150, 11.48, 11.52)]
    monkeypatch.setattr(E, "segments", lambda tr: segs)
    found = E.events_from_track(M.track(element_sets(days[keep], lon[keep], rate[keep])))
    assert [f.event_type for f in found] == ["relocation_end"] and abs(E._day(found[0].date) - 65.0) <= 0.5


def test_an_arrival_is_dated_when_the_move_stops_even_when_a_trim_inside_the_slot_follows(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    push = np.where((days >= 60.0) & (days < 70.0), -1.0, 0.0) + np.where((days >= 78.0) & (days < 78.5), -0.4, 0.0)
    rate = rate + push
    lon = lon + 10.2 + np.cumsum(push) * 0.25
    segs = [held(0, 60, 20.18, 20.22), held(60, 90, 10.0, 20.22, "drifting"), held(90, 150, 9.98, 10.02)]
    monkeypatch.setattr(E, "segments", lambda tr: segs)
    found = E.events_from_track(M.track(element_sets(days, lon, rate)))
    assert [f.event_type for f in found] == ["relocation_start", "relocation_end"]
    assert abs(E._day(found[1].date) - 70.0) <= 1


def test_a_move_whose_drift_pauses_for_a_few_days_is_one_start_and_one_end(monkeypatch):
    days = np.arange(0.0, 150.0, 0.25)
    lon, rate = quiet_keeper(days)
    push = np.where((days >= 70.0) & (days < 72.0), 0.25, 0.0) + np.where((days >= 76.0) & (days < 84.0), 0.5, 0.0)
    rate = rate + push
    lon = lon + np.cumsum(push) * 0.25
    monkeypatch.setattr(E, "segments", lambda tr: [held(0, 150, 9.9, 14.6)])
    found = E.events_from_track(M.track(element_sets(days, lon, rate)))
    assert [f.event_type for f in found] == ["relocation_start", "relocation_end"]
    assert abs(E._day(found[0].date) - 70.0) <= 1 and abs(E._day(found[1].date) - 84.0) <= 1
    assert abs(found[0].lon_after - 14.5) < 0.2
