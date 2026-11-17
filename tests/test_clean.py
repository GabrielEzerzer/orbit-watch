from datetime import timedelta

import numpy as np

from orbit_watch import modes as M
from orbit_watch import clean as C
from orbit_watch.clean import drop_snapback_blocks
from orbit_watch.elements import _build
from orbit_watch.geo import gmst_deg

DAYS = np.arange(0.0, 40.0, 0.25)


def sets(days, lon, rate, inc, raan, norad=90002):
    out = []
    for d, l, r, i, o in zip(days, lon, rate, inc, raan):
        epoch = M.GRID_START + timedelta(days=float(d))
        out.append(_build(norad, None, epoch, M.SIDEREAL_REV_PER_DAY + r / 360.0, 0.0002, float(i), float(o) % 360.0,
                          0.0, (l - o + gmst_deg(epoch)) % 360.0, 0.0, 0.0, 0.0))
    return out


def keeper(seed=0):
    rng = np.random.default_rng(seed)
    n = len(DAYS)
    rate = 0.004 - 0.0004 * DAYS
    lon = 100.0 + 0.004 * DAYS - 0.0002 * DAYS**2 + rng.normal(0, 0.002, n)
    rate = rate + rng.normal(0, 0.0002, n)
    return lon, rate, 0.06 + rng.normal(0, 0.001, n), 300.0 + rng.normal(0, 1.0, n)


def test_block_that_jumps_away_and_snaps_back_is_removed():
    lon, rate, inc, raan = keeper()
    block = (DAYS >= 20.0) & (DAYS < 24.0)
    inc, raan, rate = inc.copy(), raan.copy(), rate.copy()
    inc[block], raan[block] = 0.02, 330.0
    rate[block] -= 0.009
    records = sets(DAYS, lon, rate, inc, raan)
    kept, blocks = drop_snapback_blocks(records)
    assert len(blocks) == 1 and blocks[0].n_sets == int(block.sum())
    assert len(kept) == len(records) - int(block.sum())
    assert blocks[0].start == records[int(np.argmax(block))].epoch


def test_single_wild_set_is_removed():
    lon, rate, inc, raan = keeper(1)
    rate = rate.copy()
    rate[80] -= 0.02
    kept, blocks = drop_snapback_blocks(sets(DAYS, lon, rate, inc, raan))
    assert [b.n_sets for b in blocks] == [1]


def test_short_real_move_that_does_not_return_is_kept():
    lon, rate, inc, raan = keeper(2)
    moving = (DAYS >= 20.0) & (DAYS < 24.0)
    drift = np.where(moving, 0.25, 0.0)
    lon = lon + np.cumsum(drift * 0.25)
    rate = rate + drift
    records = sets(DAYS, lon, rate, inc, raan)
    kept, blocks = drop_snapback_blocks(records)
    assert blocks == [] and len(kept) == len(records)


def test_east_west_burn_that_stays_is_kept():
    lon, rate, inc, raan = keeper(3)
    rate = rate + np.where(DAYS >= 20.0, -0.01, 0.0)
    lon = lon + np.cumsum(np.where(DAYS >= 20.0, -0.01, 0.0) * 0.25)
    kept, blocks = drop_snapback_blocks(sets(DAYS, lon, rate, inc, raan))
    assert blocks == []


def test_north_south_burn_followed_by_an_east_west_burn_is_kept():
    lon, rate, inc, raan = keeper(4)
    inc = np.where(DAYS >= 20.0, 0.02, inc)
    rate = rate + np.where(DAYS >= 21.0, -0.01, 0.0)
    lon = lon + np.cumsum(np.where(DAYS >= 21.0, -0.01, 0.0) * 0.25)
    kept, blocks = drop_snapback_blocks(sets(DAYS, lon, rate, inc, raan))
    assert blocks == []


def test_a_thin_side_is_judged_on_the_inclination_vector_only():
    sigma = {"a": 0.005, "i": 0.0007}
    a_only = ({"a": 1.0, "i": 0.001}, {"a": 0.1, "i": 0.0005}, 0.01)
    inc = ({"a": 0.05, "i": 0.03}, {"a": 0.01, "i": 0.003}, 0.01)
    assert C.is_snapback(*a_only, True, sigma) and not C.is_snapback(*a_only, False, sigma)
    assert C.is_snapback(*inc, False, sigma)
    days = np.array([0.0, 1.0, 1.2, 1.4, 1.6, 2.6, 2.8, 3.0, 3.2])
    jumps = np.array([True, False, False, False, True, False, False, False])
    _, _, solid = C._sides(days, jumps, 1, 4)
    assert solid is False
    _, _, solid = C._sides(np.arange(12) * 0.5, np.zeros(11, bool), 5, 6)
    assert solid is True
