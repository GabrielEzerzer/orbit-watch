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
    lon, rate = keeper_track(days, 10.0, 1)
    start = EDGES[5] + 7.0
    up = np.clip((days - start) / 10.0, 0.0, 1.0) * 300.0
    drift = -1.5 * up / 42164.0 * 360.98
    lon = lon + np.cumsum(drift) * 0.25
    found = E.state_changes(element_sets(days, lon, rate + drift))
    assert [f.event_type for f in found] == ["graveyard"]
    assert found[0].size > 250 and abs(E._day(found[0].date) - start) <= 1
