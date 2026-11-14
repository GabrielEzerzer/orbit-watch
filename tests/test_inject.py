"""Synthetic injection helpers. The series here are synthetic test inputs, never calibration data."""

import numpy as np

from orbit_watch.inject import Window, inject, quiet_gaps, recovered, thin, wilson
from orbit_watch.detect import Detection, pick, score_gaps
from tests.test_detect import synthetic_series

_DAY = np.timedelta64(86_400_000_000, "us")


def test_injection_moves_only_samples_after_the_gap_by_exactly_the_step():
    series, _ = synthetic_series(n=50)
    out = inject(series, [20], [150.0])
    diff_m = (out.semi_major_axis_km - series.semi_major_axis_km) * 1000.0
    assert np.allclose(diff_m[:21], 0.0)
    assert np.allclose(diff_m[21:], 150.0, atol=1e-6)
    assert np.array_equal(out.epochs, series.epochs)
    assert np.array_equal(series.semi_major_axis_km, synthetic_series(n=50)[0].semi_major_axis_km)  # input untouched


def test_quiet_mask_excludes_gaps_near_a_window():
    series, _ = synthetic_series(n=200)
    t0 = series.epochs[0]
    ev = Window(t0 + 20 * _DAY, t0 + 20 * _DAY)
    quiet = quiet_gaps(series, [ev], margin_days=3.0)
    lo, hi = series.epochs[:-1], series.epochs[1:]
    near = (lo <= ev.hi + 3 * _DAY) & (hi >= ev.lo - 3 * _DAY)
    assert near.any() and not quiet[near].any()
    assert quiet[~near].all()


def test_injected_step_is_recovered_with_its_sign_only():
    series, _ = synthetic_series(n=400)
    g = 200
    gap = Window(series.epochs[g], series.epochs[g + 1])
    dets = pick(score_gaps(inject(series, [g], [-500.0]), k=4), z_min=12, step_min_m=200)
    assert recovered(dets, gap, -500.0)
    assert not recovered(dets, gap, 500.0)
    far = Detection(series.epochs[50], series.epochs[51], -500.0, -50.0)
    assert not recovered([far], gap, -500.0)


def test_thinning_keeps_about_one_epoch_per_step():
    series, t = synthetic_series(n=400)  # about 4.5 epochs a day
    out = thin(series, 1.0)
    assert abs(len(out) - t[-1]) <= 2
    assert np.all(np.diff(out.epochs) > np.timedelta64(0, "us"))


def test_wilson_interval():
    lo, hi = wilson(50, 100)
    assert abs(lo - 0.4038) < 1e-3 and abs(hi - 0.5962) < 1e-3
    assert wilson(0, 20)[0] == 0.0 and wilson(20, 20)[1] == 1.0
