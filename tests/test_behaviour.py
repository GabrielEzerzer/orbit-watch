from datetime import timedelta

import numpy as np
import pytest

from orbit_watch import behaviour as bh
from orbit_watch.modes import _R_GEO_KM, GRID_START, Segment


def seg(start, end, mode, lon=(10.0, 10.1)):
    return Segment(1, GRID_START + timedelta(days=start), GRID_START + timedelta(days=end), mode, 1, 10, lon[0], lon[1],
                   0.0, 0.0, 0.1)


def test_features_of_a_small_object_with_a_known_answer():
    year = 365.25
    segs = [seg(-10, 100, "controlled_lon_inc"), seg(100, 150, "controlled_lon"), seg(150, 200, "drifting"),
            seg(200, 300, "controlled_lon", (20.0, 20.1)), seg(300, 400, "librating_75E")]
    burns = np.array([50.0, 120.0, 175.0, 250.0])
    days = np.array([0, 1, 2, 4], dtype=np.int16)
    lon = np.array([10.0, 10.5, 10.0, 9.0], dtype=np.float32)
    rate = np.array([0.01, -0.03, 0.02, -0.05], dtype=np.float32)
    sma = _R_GEO_KM + np.array([1.0, 3.0, -2.0, 10.0])
    f = dict(zip(bh.FEATURES, bh.features(0.0, year, segs, burns, 1, days, lon, rate, sma, 2)))
    assert f["held_share"] == pytest.approx(250 / year)
    assert f["held_inc_share"] == pytest.approx(100 / year)
    assert f["drifting_share"] == pytest.approx(50 / year)
    assert f["librating_share"] == pytest.approx(65.25 / year)
    assert f["burns_per_year"] == pytest.approx(4)
    assert f["burns_outside_holds_per_year"] == pytest.approx(1)
    assert f["relocation_starts_per_year"] == pytest.approx(1)
    assert f["median_hold_days"] == pytest.approx(125)
    assert f["lon_travelled_deg_per_year"] == pytest.approx(2.0, abs=1e-5)
    assert f["median_abs_drift_deg_per_day"] == pytest.approx(0.025)
    assert f["median_sma_offset_km"] == pytest.approx(2.5)
    assert f["sma_iqr_km"] == pytest.approx(4.5)
    assert f["proximity_flags_per_year"] == pytest.approx(2)


def test_an_object_never_held_has_hold_length_zero():
    f = bh.features(0.0, 365.25, [seg(0, 400, "drifting")], np.array([]), 0, np.array([0, 1]),
                    np.array([0.0, 1.0]), np.array([1.0, 1.0]), np.array([_R_GEO_KM, _R_GEO_KM]), 0)
    assert f[bh.FEATURES.index("median_hold_days")] == 0.0
    assert f[bh.FEATURES.index("held_share")] == 0.0


def test_travel_runs_the_longitude_on_at_the_drift_rate_across_a_wrap_and_a_gap():
    assert bh.travelled(np.array([0, 3]), np.array([170.0, 110.0]), np.array([100.0, 100.0])) == pytest.approx(300.0)
    assert bh.travelled(np.array([0, 1]), np.array([179.9, -179.9]), np.array([0.0, 0.0])) == pytest.approx(0.2)


def test_data_bar():
    assert bh.enough_data(100, 0.0, 180.0)
    assert not bh.enough_data(99, 0.0, 400.0)
    assert not bh.enough_data(500, 10.0, 189.9)


def test_scaling_logs_counts_standardises_and_clips():
    table = np.zeros((50, len(bh.FEATURES)))
    table[0, 0] = 1.0
    table[:3, 4] = [0.0, np.e - 1, np.e**2 - 1]
    table[:, 1] = 7.0
    z = bh.scaled(table)
    assert z[0, 0] == bh.CLIP
    assert z[1, 0] == pytest.approx(-1 / 7)
    assert (z[:, 1] == 0).all()
    logged = np.log1p(table[:, 4])
    assert z[:, 4] == pytest.approx(np.clip((logged - logged.mean()) / logged.std(), -bh.CLIP, bh.CLIP))
    assert z[2, 4] == bh.CLIP
    assert np.abs(z).max() <= bh.CLIP


def test_isolated_points_and_small_groups_score_high_and_a_dense_group_low():
    rng = np.random.default_rng(0)
    dense = rng.normal(0.0, 0.05, (40, 2))
    small = np.array([10.0, 10.0]) + rng.normal(0.0, 0.05, (5, 2))
    lone = np.array([[-10.0, 5.0]])
    same = np.tile([[5.0, -5.0]], (11, 1))
    score, idx = bh.kth_neighbour(np.vstack([dense, small, lone, same]))
    assert score[:40].max() < 0.3
    assert score[40:45].min() > 10.0
    assert score[45] > 10.0
    assert (score[46:] == 0).all()
    assert idx[45] != 45


def test_outside_is_the_top_five_percent():
    flags, cut = bh.outside_flags(np.arange(100.0))
    assert flags.sum() == 5 and flags[95:].all() and cut == pytest.approx(94.05)
