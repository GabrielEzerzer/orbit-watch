"""Detector tests. The series here are synthetic, labelled test inputs, never calibration data."""

import numpy as np
import pytest

from orbit_watch.detect import Detection, Setting, merge_channels, pick, pick_setting, score_gaps
from orbit_watch.series import ElementSeries


def synthetic_series(steps_m=(), n=400, per_day=4.5, decay_m_per_day=80.0, noise_m=20.0, seed=0, drop=()):
    rng = np.random.default_rng(seed)
    t_days = np.cumsum(rng.uniform(0.5, 1.5, n) / per_day)
    a_m = 6_790_000.0 - decay_m_per_day * t_days + rng.normal(0, noise_m, n)
    for at_day, size in steps_m:
        a_m[t_days > at_day] += size
    keep = np.ones(n, bool)
    for lo, hi in drop:
        keep &= ~((t_days > lo) & (t_days < hi))
    t_days, a_m = t_days[keep], a_m[keep]
    epochs = np.datetime64("2021-01-01T00:00:00", "us") + (t_days * 86_400e6).astype("timedelta64[us]")
    z = np.zeros(len(t_days))
    return ElementSeries(25544, epochs, a_m / 1000.0, z, z, z, z, z), t_days


def test_finds_injected_steps_with_sign_and_size():
    series, t = synthetic_series(steps_m=((20.3, 500.0), (50.7, -400.0)))
    dets = pick(score_gaps(series, k=6), z_min=6, step_min_m=100)
    assert len(dets) == 2
    starts = (dets[0].start, dets[1].start)
    day = lambda d: (d - series.epochs[0]).astype("int64") / 86_400e6
    # Within the 0.5-day tolerance calibration allows: a median plateau can sit one epoch off.
    assert day(dets[0].start) - 0.5 <= 20.3 <= day(dets[0].end) + 0.5
    assert day(dets[1].start) - 0.5 <= 50.7 <= day(dets[1].end) + 0.5
    assert abs(dets[0].step_m - 500) < 60 and dets[0].sign == 1
    assert abs(dets[1].step_m + 400) < 60 and dets[1].sign == -1
    assert starts[0] < starts[1]


def test_no_detection_on_pure_decay_and_noise():
    series, _ = synthetic_series()
    assert pick(score_gaps(series, k=6), z_min=6, step_min_m=100) == []


def test_noise_scale_is_estimated_from_the_data():
    quiet, _ = synthetic_series(noise_m=10.0)
    loud, _ = synthetic_series(noise_m=40.0)
    s_q = np.nanmedian(score_gaps(quiet).sigma_m)
    s_l = np.nanmedian(score_gaps(loud).sigma_m)
    assert 5 < s_q < 14 and 3 < s_l / s_q < 5  # MAD of k points about their median runs low


def test_no_score_across_a_data_gap():
    series, t = synthetic_series(steps_m=((40.0, 500.0),), drop=((38.5, 42.0),))
    sc = score_gaps(series, k=6, max_gap_days=2.0)
    i = int(np.flatnonzero(np.diff(series.epochs).astype("int64") > 2 * 86_400e6)[0])
    assert not sc.valid[i]
    assert pick(sc, z_min=6, step_min_m=100) == []


def test_inclination_channel_finds_a_plane_change_the_a_channel_misses():
    series, t = synthetic_series()  # semi-major axis: decay and noise only
    rng = np.random.default_rng(1)
    inc = 0.08 + 0.001 * t + rng.normal(0, 1e-4, len(t))  # degrees: lunisolar drift, TLE scatter
    inc[t > 30.2] -= 0.015  # a north-south burn
    series = ElementSeries(series.norad_id, series.epochs, series.semi_major_axis_km, inc,
                           series.eccentricity, series.raan, series.mean_motion, series.bstar)
    assert pick(score_gaps(series, k=4), z_min=12, step_min_m=200) == []
    (d,) = pick(score_gaps(series, k=4, channel="i"), z_min=12, step_min_m=0.005)
    day = lambda x: (x - series.epochs[0]).astype("int64") / 86_400e6
    assert d.channel == "i" and abs(d.step_m + 0.015) < 0.002
    assert day(d.start) - 0.5 <= 30.2 <= day(d.end) + 0.5


def test_merge_channels_keeps_a_and_drops_an_inclination_detection_within_nms_days():
    t0 = np.datetime64("2025-01-01T00:00", "us")
    h = lambda x: t0 + np.timedelta64(int(x * 3_600e6), "us")
    a = [Detection(h(0), h(6), -3000.0, -300.0)]
    i_near = Detection(h(20), h(26), -0.01, -40.0, "i")  # centres 20 h apart
    i_far = Detection(h(30), h(36), 0.02, 50.0, "i")  # 30 h apart
    assert merge_channels(a, [i_near, i_far], nms_days=1.0) == [a[0], i_far]
    assert merge_channels([], [i_near], nms_days=1.0) == [i_near]


def test_setting_needs_both_inclination_thresholds_or_neither():
    with pytest.raises(ValueError, match="inc_step_min_deg=None"):
        Setting(4, 12, 200, inc_z_min=12)
    with pytest.raises(ValueError, match="inc_z_min=None"):
        Setting(4, 12, 200, inc_step_min_deg=0.011)
    assert not Setting(4, 12, 200).inc_channel
    on = Setting(4, 12, 200, inc_z_min=12, inc_step_min_deg=0.011)
    series, _ = synthetic_series()
    with pytest.raises(ValueError, match="inclination scores"):
        pick_setting(score_gaps(series, k=4), None, on)
