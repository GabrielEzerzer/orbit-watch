import json
from datetime import timedelta

import numpy as np
import pytest

from orbit_watch import modes as M
from orbit_watch.elements import _build, parse_tle
from orbit_watch.geo import gmst_deg
from orbit_watch.jobs import geo_modes

EDGES = M.window_edges()


def element_sets(days, lon, *, inc=0.05, ecc=0.0002, drift=None, norad=90001, n_offset=0.0):
    """Synthetic element sets with the given mean longitude (deg) at each day since GRID_START.
    The mean motion carries ``drift`` (deg/day, default: the slope of ``lon``) plus ``n_offset``."""
    days, lon = np.asarray(days, float), np.asarray(lon, float)
    drift = np.gradient(lon, days) if drift is None else np.broadcast_to(drift, days.shape)
    inc = np.broadcast_to(inc, days.shape)
    out = []
    for d, l, r, i in zip(days, lon, drift, inc):
        epoch = M.GRID_START + timedelta(days=float(d))
        out.append(_build(norad, None, epoch, M.SIDEREAL_REV_PER_DAY + r / 360.0 + n_offset, ecc, float(i),
                          0.0, 0.0, (l + gmst_deg(epoch)) % 360.0, 0.0, 0.0, 0.0))
    return out


def kept(days, lon0, seed=0, box=0.04):
    """A station-kept longitude: a 14-day east-west cycle of +-``box`` deg plus 0.003 deg of TLE noise."""
    rng = np.random.default_rng(seed)
    return lon0 + box * np.sin(2 * np.pi * days / 14.0) + rng.normal(0, 0.003, len(days))


def free_motion(lon0, days, dt=0.05):
    """A free object released at rest at ``lon0``, integrated with the natural acceleration."""
    t = np.arange(0.0, days[-1] + dt, dt)
    lon, v = np.empty_like(t), 0.0
    lon[0] = lon0
    for k in range(1, len(t)):  # velocity Verlet
        a = M.longitude_acceleration(lon[k - 1])
        lon[k] = lon[k - 1] + v * dt + 0.5 * a * dt**2
        v += 0.5 * (a + M.longitude_acceleration(lon[k])) * dt
    return np.interp(days, t, lon)


def modes_of(records):
    return [w.mode for w in M.classify(M.track(records))]


def test_stable_points_match_esa():
    # ESA, Classification of Geosynchronous Objects, issue 21, section 2: stable points 75 E and 105 W.
    assert M.STABLE_EAST_DEG == pytest.approx(75.0, abs=0.5)
    assert M.STABLE_WEST_DEG == pytest.approx(255.0, abs=0.5)
    # The lower barrier (11 W) is the one librating_both objects cross.
    assert M.BARRIER_LOW_DEG == pytest.approx(348.5, abs=1.0)
    assert M.BARRIER_HIGH_DEG == pytest.approx(162.0, abs=1.0)


def test_station_kept_object_is_controlled():
    days = np.arange(0.0, EDGES[6], 0.5)
    assert set(modes_of(element_sets(days, kept(days, 10.0), inc=0.05))) == {"controlled_lon_inc"}
    assert set(modes_of(element_sets(days, kept(days, 10.0), inc=2.0))) == {"controlled_lon"}


def test_drifter_is_drifting():
    days = np.arange(0.0, EDGES[6], 0.5)
    lon = (2.0 * days + 180.0) % 360.0 - 180.0  # 2 deg/day east, wrapping
    assert set(modes_of(element_sets(days, lon, drift=2.0, inc=3.0))) == {"drifting"}


@pytest.mark.parametrize("lon0, expected", [(90.0, "librating_75E"), (240.0, "librating_105W"),
                                            (150.0, "librating_both")])
def test_free_librator_is_librating_and_never_controlled(lon0, expected):
    v = M.tesseral_potential(lon0)
    if expected == "librating_both":
        assert M.tesseral_potential(M.BARRIER_LOW_DEG) < v < M.tesseral_potential(M.BARRIER_HIGH_DEG)
    days = np.arange(0.0, (M.GRID_END - M.GRID_START).days, 1.0)
    lon = free_motion(lon0, days)  # released at the turning point of its swing
    found = modes_of(element_sets(days, (lon + 180.0) % 360.0 - 180.0, inc=6.0))
    assert set(found) <= {expected, "undetermined"}
    assert found.count(expected) >= 0.85 * len(found)


def test_relocation_gives_three_segments_on_the_window_grid():
    # Kept at 10 E for three windows, drifting west at 0.5 deg/day for two, kept at -20 E after.
    days = np.arange(EDGES[0], EDGES[9], 0.5)
    lon = np.where(days < EDGES[3], kept(days, 10.0),
                   np.where(days < EDGES[5], 10.0 - 0.5 * (days - EDGES[3]), kept(days, -20.0, seed=1)))
    segs = M.segments(M.track(element_sets(days, lon)))
    assert [s.mode for s in segs] == ["controlled_lon_inc", "drifting", "controlled_lon_inc"]
    day = lambda k: M.GRID_START + timedelta(days=float(EDGES[k]))  # noqa: E731
    assert [(s.start, s.end) for s in segs] == [(day(0), day(3)), (day(3), day(5)), (day(5), day(9))]
    assert segs[0].lon_max == pytest.approx(10.05, abs=0.05) and segs[2].lon_min == pytest.approx(-20.05, abs=0.05)
    assert segs[1].drift_mean == pytest.approx(-0.5, abs=0.01)


def test_relocation_inside_windows_is_dated_to_the_window_holding_it():
    # The burns fall 10 days into windows 3 and 5: the partial windows must read as drifting,
    # not as held or librating, so each change is dated to the window that contains it.
    start, stop = EDGES[3] + 10, EDGES[5] + 10
    days = np.arange(EDGES[0], EDGES[9], 0.5)
    lon = np.where(days < start, kept(days, 10.0),
                   np.where(days < stop, 10.0 - 0.5 * (days - start), kept(days, -20.0, seed=1)))
    segs = M.segments(M.track(element_sets(days, lon)))
    assert [s.mode for s in segs] == ["controlled_lon_inc", "drifting", "controlled_lon_inc"]
    assert segs[1].start == M.GRID_START + timedelta(days=float(EDGES[3]))
    assert segs[1].end == M.GRID_START + timedelta(days=float(EDGES[6]))


def test_short_park_far_from_a_stable_point_is_control():
    # One window at rest at 45 E between drifts: no 90-day run holds the same longitude, but a free
    # object there accelerates by about 0.0017 deg/day^2 and could not sit this still for 30 days.
    days = np.arange(EDGES[0], EDGES[3], 0.5)
    lon = np.where(days < EDGES[1], 45.0 - 0.6 * (days - EDGES[1]),
                   np.where(days < EDGES[2], kept(days, 45.0, box=0.02), 45.0 + 0.6 * (days - EDGES[2])))
    assert modes_of(element_sets(days, lon)) == ["drifting", "controlled_lon_inc", "drifting"]


def test_sparse_window_is_undetermined_and_far_orbit_is_out_of_region():
    days = np.concatenate([np.arange(0.0, EDGES[3], 0.5), [EDGES[3] + 1, EDGES[3] + 9, EDGES[3] + 20],
                           np.arange(EDGES[4], EDGES[7], 0.5)])
    c1 = "controlled_lon_inc"
    assert modes_of(element_sets(days, kept(days, 10.0))) == [c1, c1, c1, "undetermined", c1, c1, c1]
    days = np.arange(0.0, EDGES[3], 0.5)
    # Mean motion 2.25 rev/day, eccentricity 0.7: a transfer orbit.
    gto = element_sets(days, np.zeros_like(days), drift=0.0, ecc=0.7, n_offset=1.25)
    assert set(modes_of(gto)) == {"out_of_region"}
    assert set(modes_of(element_sets(days, kept(days, 10.0), inc=40.0))) == {"inclined"}


def test_elektro_l1_librates_over_both_stable_points(mock_dir):
    # Elektro-L No. 1 (2011-001A, NORAD 37344) is listed in ESA's Classification of Geosynchronous
    # Objects, issue 21 (2019), section 4.7, as L3, libration around both stable points, with
    # lambda_min 177.9 deg E and a swing of 328.5 deg, so it turns back east of the high barrier
    # at 177.9 + 328.5 - 360 = 146.4 deg E. Real element sets, one every two days, 2021-2025.
    records = parse_tle((mock_dir / "geo" / "37344_every_2_days.tle").read_text(encoding="utf-8"))
    tr = M.track(records)
    found = [w.mode for w in M.classify(tr)]
    assert set(found) <= {"librating_both", "undetermined"}
    assert found.count("librating_both") >= 0.9 * len(found)
    assert tr.lon.max() == pytest.approx(146.4, abs=2.0)  # its eastern turning point, early 2023
    assert tr.lon[-1] < M.BARRIER_LOW_DEG - 360.0  # and by the end of 2025 it is west of the low barrier


def test_year_end_counts_and_transitions():
    t = lambda y, m, d: M.GRID_START.replace(year=y, month=m, day=d)  # noqa: E731
    seg = lambda a, b, mode: M.Segment(1, a, b, mode, 1, 10, 0, 0, 0, 0, 0)  # noqa: E731
    by_object = {
        1: [seg(t(2021, 1, 1), t(2022, 6, 1), "controlled_lon_inc"), seg(t(2022, 6, 1), t(2022, 7, 1), "undetermined"),
            seg(t(2022, 7, 1), t(2026, 1, 1), "controlled_lon_inc")],
        2: [seg(t(2023, 3, 1), t(2024, 1, 15), "drifting")],
    }
    counts = geo_modes.year_end_counts(by_object)
    assert counts[2021] == {"controlled_lon_inc": 1, "no_data": 1}
    assert counts[2023] == {"controlled_lon_inc": 1, "drifting": 1}
    assert counts[2024] == {"controlled_lon_inc": 1, "no_data": 1}
    per_all, per_det, types_all, types_det = geo_modes.transitions(by_object)
    assert per_all == {2: 1, 0: 1} and per_det == {0: 2}
    assert types_all == {("controlled_lon_inc", "undetermined"): 1, ("undetermined", "controlled_lon_inc"): 1}
    assert types_det == {}


def test_job_skips_holdout_and_non_region_objects_before_opening_them(tmp_path, mock_dir):
    from orbit_watch.truth import load_splits

    holdout = sorted(n for n, e in load_splits().items() if e["split"] == "holdout")
    geo = tmp_path / "geo"
    geo.mkdir()
    (geo / "37344.tle").write_text((mock_dir / "geo" / "37344_every_2_days.tle").read_text(), encoding="utf-8")
    # No files exist for the holdout object or the LEO object: opening either would raise.
    objects = {"37344": {"by_rule": True}, str(holdout[0]): {"by_rule": True}, "27421": {"by_rule": False}}
    (geo / "manifest.json").write_text(json.dumps({"object_count": 3, "objects": objects}), encoding="utf-8")
    assert geo_modes.main(["--geo-dir", str(geo), "--out", str(tmp_path / "out"),
                           "--summary-dir", str(tmp_path / "summary")]) == 0
    summary = json.loads((tmp_path / "summary" / "summary.json").read_text())
    assert summary["skipped_holdout"] == [holdout[0]] and summary["skipped_not_by_rule"] == [27421]
    assert summary["objects_classified"] == 1
    rows = (tmp_path / "out" / "segments.csv").read_text().splitlines()
    assert rows[0].startswith("norad_id,start,end,mode") and all(r.startswith("37344,") for r in rows[1:])
