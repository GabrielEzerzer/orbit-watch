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
    rng = np.random.default_rng(seed)
    return lon0 + box * np.sin(2 * np.pi * days / 14.0) + rng.normal(0, 0.003, len(days))


def free_motion(lon0, days, dt=0.05, inc=0.0, kicks=(), accel_scale=1.0):
    t = np.arange(0.0, days[-1] + dt, dt)
    lon, v = np.empty_like(t), 0.0
    lon[0] = lon0
    kicks = sorted(kicks)
    for k in range(1, len(t)):
        a = accel_scale * M.longitude_acceleration(lon[k - 1], inc)
        lon[k] = lon[k - 1] + v * dt + 0.5 * a * dt**2
        v += 0.5 * (a + accel_scale * M.longitude_acceleration(lon[k], inc)) * dt
        while kicks and kicks[0][0] <= t[k]:
            v += kicks.pop(0)[1]
    return np.interp(days, t, lon)


def at_rest_with_energy(e, inc, west, east):
    grid = np.linspace(west, east, 20001)
    return float(grid[np.argmin([abs(M.tesseral_potential(x, inc) - e) for x in grid])])


def window_of(day):
    return int(np.searchsorted(EDGES, day, side="right")) - 1


def modes_of(records):
    return [w.mode for w in M.classify(M.track(records))]


def test_stable_points_match_esa():
    assert M.STABLE_EAST_DEG == pytest.approx(75.0, abs=0.5), "ESA issue 21, section 2: stable points 75 E and 105 W"
    assert M.STABLE_WEST_DEG == pytest.approx(255.0, abs=0.5)
    assert M.BARRIER_LOW_DEG == pytest.approx(348.5, abs=1.0)
    assert M.BARRIER_HIGH_DEG == pytest.approx(162.0, abs=1.0)


def test_station_kept_object_is_controlled():
    days = np.arange(0.0, EDGES[6], 0.5)
    assert set(modes_of(element_sets(days, kept(days, 10.0), inc=0.05))) == {"controlled_lon_inc"}
    assert set(modes_of(element_sets(days, kept(days, 10.0), inc=2.0))) == {"controlled_lon"}


def test_drifter_is_drifting():
    days = np.arange(0.0, EDGES[6], 0.5)
    lon = (2.0 * days + 180.0) % 360.0 - 180.0
    assert set(modes_of(element_sets(days, lon, drift=2.0, inc=3.0))) == {"drifting"}


@pytest.mark.parametrize("lon0, expected", [(90.0, "librating_75E"), (240.0, "librating_105W"),
                                            (150.0, "librating_both")])
def test_free_librator_is_librating_and_never_controlled(lon0, expected):
    v = M.tesseral_potential(lon0, 6.0)
    if expected == "librating_both":
        assert M.tesseral_potential(M.BARRIER_LOW_DEG, 6.0) < v < M.tesseral_potential(M.BARRIER_HIGH_DEG, 6.0)
    days = np.arange(0.0, (M.GRID_END - M.GRID_START).days, 1.0)
    lon = free_motion(lon0, days, inc=6.0)
    found = modes_of(element_sets(days, (lon + 180.0) % 360.0 - 180.0, inc=6.0))
    assert set(found) <= {expected, "undetermined"}
    assert found.count(expected) >= 0.85 * len(found)


def test_inclined_potential_uses_kaulas_inclination_functions():
    assert [M._inclination_function(n, m, 0.0) for n, m in [(2, 2), (3, 1), (3, 3)]] == pytest.approx([3, -1.5, 15]), (
        "Kaula, Theory of Satellite Geodesy (1966), table 1: at i = 0 the GEO-resonant terms are P_nm(0)")
    half = (1 + np.cos(np.radians(12.0))) / 2
    assert M._inclination_function(2, 2, 12.0) == pytest.approx(3 * half**2)
    assert M._inclination_function(3, 3, 12.0) == pytest.approx(15 * half**3)
    assert M._inclination_function(3, 1, 90.0) == pytest.approx(15 / 16 - 0.75)


def test_inclined_librator_near_the_low_barrier_keeps_one_mode():
    inc, low = 12.0, M.BARRIER_LOW_DEG - 360.0
    lon0 = at_rest_with_energy(0.99 * M.tesseral_potential(M.BARRIER_LOW_DEG, inc), inc, low - 30.0, low - 0.01)
    days = np.arange(0.0, (M.GRID_END - M.GRID_START).days, 1.0)
    lon = free_motion(lon0, days, inc=inc)
    assert lon.max() < low
    found = modes_of(element_sets(days, (lon + 180.0) % 360.0 - 180.0, inc=inc))
    assert set(found) <= {"librating_105W", "undetermined"}
    assert found.count("librating_105W") >= 0.85 * len(found)
    found = modes_of(element_sets(days, (lon + 180.0) % 360.0 - 180.0, inc=0.05))
    assert set(found) <= {"librating_105W", "undetermined"}
    assert found.count("librating_105W") >= 0.85 * len(found)


def test_librator_whose_acceleration_is_a_tenth_off_the_model_keeps_one_mode():
    inc, low = 12.0, M.BARRIER_LOW_DEG - 360.0
    lon0 = at_rest_with_energy(0.97 * M.tesseral_potential(M.BARRIER_LOW_DEG, inc), inc, low - 40.0, low - 0.01)
    days = np.arange(0.0, (M.GRID_END - M.GRID_START).days, 1.0)
    lon = free_motion(lon0, days, inc=inc, accel_scale=1.1)
    assert lon.max() < low
    found = modes_of(element_sets(days, (lon + 180.0) % 360.0 - 180.0, inc=inc))
    assert set(found) <= {"librating_105W", "undetermined"}
    assert found.count("librating_105W") >= 0.85 * len(found)


@pytest.mark.parametrize("norad, expected, crosses", [(22269, "librating_both", "low"), (25110, "drifting", "high")])
def test_a_path_over_a_barrier_is_not_trapped_behind_it(mock_dir, norad, expected, crosses):
    tr = M.track(parse_tle((mock_dir / "geo" / f"{norad}_every_4_days.tle").read_text(encoding="utf-8")))
    barrier = M.BARRIER_LOW_DEG if crosses == "low" else M.BARRIER_HIGH_DEG
    assert tr.lon.min() < M.wrap180(barrier) < tr.lon.max()
    found = [w.mode for w in M.classify(tr)]
    assert set(found) <= {expected, "undetermined"} and found.count("undetermined") <= 1


def test_manoeuvre_between_two_windows_ends_the_free_run():
    days = np.arange(EDGES[0], EDGES[14], 0.5)
    lon = free_motion(90.0, days, inc=6.0)
    at = days >= EDGES[6]
    lon[at] = lon[np.argmax(at) - 1] - 3.0 * (days[at] - EDGES[6])
    found = modes_of(element_sets(days, (lon + 180.0) % 360.0 - 180.0, inc=6.0))
    assert set(found[:6]) <= {"librating_75E", "undetermined"} and "librating_75E" in found[:6]
    assert set(found[6:]) == {"drifting"}


def test_librator_with_outlier_element_sets_stays_one_mode():
    days = np.arange(0.0, (M.GRID_END - M.GRID_START).days, 0.5)
    lon = free_motion(90.0, days, inc=6.0)
    rng = np.random.default_rng(3)
    for k in (15, 40):
        bad = (days >= EDGES[k]) & (days < EDGES[k + 1])
        lon[bad] += rng.normal(0.0, 0.03, bad.sum())
    found = modes_of(element_sets(days, lon, inc=6.0, drift=0.0))
    assert set(found) <= {"librating_75E", "undetermined"}
    assert found.count("librating_75E") >= 0.85 * len(found)


def test_manoeuvre_of_a_librator_is_still_drifting():
    days = np.arange(0.0, (M.GRID_END - M.GRID_START).days, 0.5)
    burn_day = (EDGES[25] + EDGES[26]) / 2
    lon = free_motion(90.0, days, inc=6.0, kicks=[(burn_day, 0.1)])
    found = modes_of(element_sets(days, lon, inc=6.0, drift=0.0))
    assert found[window_of(burn_day)] == "drifting"
    assert found.count("drifting") <= 2


def librator_with_a_gap(gap_windows, kicks=()):
    days = np.arange(0.0, (M.GRID_END - M.GRID_START).days, 1.0)
    lon = free_motion(90.0, days, inc=6.0, kicks=kicks)
    keep = (days < EDGES[31]) | (days >= EDGES[31 + gap_windows])
    return days[keep], lon[keep]


@pytest.mark.parametrize("gap_windows, n_bad", [(1, 4), (4, 4), (1, 8)])
def test_librator_with_bad_element_sets_before_a_gap_stays_librating(gap_windows, n_bad):
    days, lon = librator_with_a_gap(gap_windows)
    off_km = 6.0
    off_drift = -1.5 * 360.0 * M.SIDEREAL_REV_PER_DAY * off_km / 42164.17
    bad = np.flatnonzero(days < EDGES[31])[-n_bad:]
    drift = np.gradient(lon, days)
    lon[bad] += off_drift * (days[bad] - days[bad[0]] + 1.0)
    drift[bad] += off_drift
    found = modes_of(element_sets(days, lon, inc=6.0, drift=drift))
    assert found[30] == "librating_75E"
    assert set(found) <= {"librating_75E", "undetermined"}


@pytest.mark.parametrize("gap_windows", [1, 4])
def test_burn_before_a_gap_is_still_drifting(gap_windows):
    burn_day = EDGES[31] - 8.0
    days, lon = librator_with_a_gap(gap_windows, kicks=[(burn_day, 0.03)])
    found = modes_of(element_sets(days, lon, inc=6.0, drift=0.0))
    assert found[window_of(burn_day)] == "drifting"


def test_small_libration_about_a_stable_point_is_not_control():
    days = np.arange(0.0, (M.GRID_END - M.GRID_START).days, 1.0)
    lon = free_motion(M.STABLE_EAST_DEG + 2.0, days, inc=6.0)
    found = modes_of(element_sets(days, lon, inc=6.0))
    assert not {"controlled_lon", "controlled_lon_inc"} & set(found)
    assert found.count("librating_75E") >= 0.5 * len(found)


def stable_point(inc, near=M.STABLE_EAST_DEG):
    grid = np.linspace(near - 1.0, near + 1.0, 200001)
    return float(grid[np.argmin(M.tesseral_potential(grid, inc))])


FIVE_YEARS = np.arange(0.0, (M.GRID_END - M.GRID_START).days, 1.0)
CONTROLLED = {"controlled_lon", "controlled_lon_inc"}


@pytest.mark.parametrize("swing", [0.1, 0.3, 1.0, 2.0])
def test_small_free_librator_at_a_stable_point_is_never_controlled(swing):
    lon = free_motion(stable_point(6.0) + swing / 2, FIVE_YEARS, inc=6.0)
    assert lon.max() - lon.min() == pytest.approx(swing, rel=0.05)
    found = modes_of(element_sets(FIVE_YEARS, lon, inc=6.0))
    assert set(found) <= {"librating_75E", "undetermined"} and "librating_75E" in found


def test_free_librator_off_the_model_is_never_controlled():
    west = stable_point(6.0, M.STABLE_WEST_DEG) - 360.0
    lon = free_motion(west + 0.15, FIVE_YEARS, inc=6.0, accel_scale=1.1) - 0.3
    found = modes_of(element_sets(FIVE_YEARS, lon, inc=6.0))
    assert set(found) <= {"librating_105W", "undetermined"} and "librating_105W" in found


def test_keeper_parked_at_a_stable_point_is_control():
    found = modes_of(element_sets(FIVE_YEARS, kept(FIVE_YEARS, stable_point(3.0), box=0.01), inc=3.0))
    assert set(found) == {"controlled_lon"}


def test_free_libration_with_the_inclination_held_is_c1():
    lon = free_motion(stable_point(0.05) + 0.1, FIVE_YEARS, inc=0.05)
    assert set(modes_of(element_sets(FIVE_YEARS, lon, inc=0.05))) == {"controlled_lon_inc"}


def test_dead_librator_passing_under_the_c1_inclination_is_never_controlled():
    inc = np.hypot(0.85 * (FIVE_YEARS - 400.0) / 365.25, 0.05)
    lon = free_motion(stable_point(1.0) + 0.1, FIVE_YEARS, inc=1.0)
    found = modes_of(element_sets(FIVE_YEARS, lon, inc=inc))
    assert set(found) <= {"librating_75E", "undetermined"} and "librating_75E" in found


def test_quiet_hold_under_a_year_near_a_stable_point_is_undetermined():
    days = np.arange(EDGES[0], EDGES[8], 0.5)
    arc = free_motion(stable_point(3.0) + 0.5, days - EDGES[2], inc=3.0)
    lon = np.where(days < EDGES[2], arc[np.argmax(days >= EDGES[2])] - 0.5 * (days - EDGES[2]),
                   np.where(days < EDGES[6], arc, arc[np.argmax(days >= EDGES[6])] + 0.5 * (days - EDGES[6])))
    found = modes_of(element_sets(days, lon, inc=3.0))
    assert found[2:6] == ["undetermined"] * 4 and not CONTROLLED & set(found)


def test_tight_keeper_near_a_stable_point_is_control():
    days = np.arange(0.0, EDGES[8], 0.5)
    found = modes_of(element_sets(days, kept(days, M.STABLE_EAST_DEG + 1.0, box=0.01)))
    assert found == ["controlled_lon_inc"] * 8


@pytest.mark.parametrize("phase", [0.0, 150.0])
def test_inclination_sawtooth_under_control_stays_c1(phase):
    days = np.arange(0.0, EDGES[20], 0.5)
    inc = 0.45 * ((days + phase) % 200.0) / 200.0
    assert inc[-1] > M.C1_MAX_INCLINATION_DEG
    assert set(modes_of(element_sets(days, kept(days, 10.0), inc=inc))) == {"controlled_lon_inc"}


def test_rise_after_a_single_earlier_excursion_is_c2_at_the_record_end():
    days = np.arange(0.0, EDGES[20], 0.5)
    inc = np.where(days < 200.0, 0.45 * (days % 200.0) / 200.0, 0.02 + 0.8 * np.clip(days - 450.0, 0.0, None) / 365.25)
    found = modes_of(element_sets(days, kept(days, 10.0), inc=inc))
    assert found[-1] == "controlled_lon" and found[0] == "controlled_lon_inc"


@pytest.mark.parametrize("rise", [
    lambda d: 0.02 + 0.03 * np.clip(d - 570.0, 0.0, None),
    lambda d: np.minimum(0.02 + 0.01 * np.clip(d - 400.0, 0.0, None), 0.4),
], ids=["higher", "longer"])
def test_rise_past_two_earlier_excursions_is_c2_at_the_record_end(rise):
    days = np.arange(0.0, EDGES[20], 0.5)
    inc = np.where(days < 400.0, 0.45 * (days % 200.0) / 200.0, rise(days))
    found = modes_of(element_sets(days, kept(days, 10.0), inc=inc))
    tail = window_of(days[np.argmax((days > 400.0) & (inc > M.C1_MAX_INCLINATION_DEG))])
    assert found[tail:] == ["controlled_lon"] * (len(found) - tail) and found[0] == "controlled_lon_inc"


def crossing_window(days, inc):
    return window_of(days[np.argmax(inc > M.C1_MAX_INCLINATION_DEG)])


def test_inclination_growing_past_the_c1_limit_changes_mode_once_at_the_crossing():
    days = np.arange(0.0, EDGES[40], 0.5)
    inc = 0.02 + 0.8 * days / 365.25
    found = modes_of(element_sets(days, kept(days, 10.0), inc=inc))
    changes = sum(a != b for a, b in zip(found, found[1:]))
    assert found[0] == "controlled_lon_inc" and found[-1] == "controlled_lon" and changes == 1
    assert abs(found.index("controlled_lon") - crossing_window(days, inc)) <= 1


def test_stop_eight_months_before_the_record_ends_is_c2():
    days = np.arange(0.0, EDGES[30] + 240.0, 0.5)
    inc = 0.02 + 0.8 * np.clip(days - EDGES[30], 0.0, None) / 365.25
    found = modes_of(element_sets(days, kept(days, 10.0), inc=inc))
    assert found[-1] == "controlled_lon" and sum(a != b for a, b in zip(found, found[1:])) == 1
    assert abs(found.index("controlled_lon") - crossing_window(days, inc)) <= 1


def test_stop_and_restart_over_a_year_apart_are_dated_at_the_crossings():
    days = np.arange(0.0, EDGES[50], 0.5)
    peak = 0.02 + 0.8 * 600.0 / 365.25
    inc = np.where(days < 100.0, 0.02, np.where(days < 700.0, 0.02 + 0.8 * (days - 100.0) / 365.25,
                                                np.maximum(peak - 1.6 * (days - 700.0) / 365.25, 0.02)))
    found = modes_of(element_sets(days, kept(days, 10.0), inc=inc))
    c2 = [k for k, m in enumerate(found) if m == "controlled_lon"]
    assert set(found) == {"controlled_lon_inc", "controlled_lon"} and c2 == list(range(c2[0], c2[-1] + 1))
    back = window_of(days[len(days) - 1 - np.argmax(inc[::-1] > M.C1_MAX_INCLINATION_DEG)])
    assert abs(c2[0] - crossing_window(days, inc)) <= 1 and abs(c2[-1] - back) <= 1


@pytest.mark.parametrize("drift, every", [(2.0, 3.5), (60.0, 6.0)])
def test_fast_drifter_sampled_sparsely_is_drifting(drift, every):
    days = np.arange(0.0, EDGES[6], every)
    lon = (drift * days + 180.0) % 360.0 - 180.0
    assert set(modes_of(element_sets(days, lon, drift=drift, inc=3.0))) == {"drifting"}


def test_eccentricity_alone_puts_an_orbit_out_of_region():
    days = np.arange(0.0, EDGES[3], 0.5)
    assert set(modes_of(element_sets(days, kept(days, 10.0), ecc=0.3))) == {"out_of_region"}


def test_relocation_gives_three_segments_on_the_window_grid():
    days = np.arange(EDGES[0], EDGES[9], 0.5)
    lon = np.where(days < EDGES[3], kept(days, 10.0),
                   np.where(days < EDGES[5], 10.0 - 0.5 * (days - EDGES[3]), kept(days, -20.0, seed=1)))
    segs = M.segments(M.track(element_sets(days, lon)))
    assert [s.mode for s in segs] == ["controlled_lon_inc", "drifting", "controlled_lon_inc"]
    day = lambda k: M.GRID_START + timedelta(days=float(EDGES[k]))
    assert [(s.start, s.end) for s in segs] == [(day(0), day(3)), (day(3), day(5)), (day(5), day(9))]
    assert segs[0].lon_max == pytest.approx(10.05, abs=0.05) and segs[2].lon_min == pytest.approx(-20.05, abs=0.05)
    assert segs[1].drift_mean == pytest.approx(-0.5, abs=0.01)


def test_relocation_inside_windows_is_dated_to_the_window_holding_it():
    start, stop = EDGES[3] + 10, EDGES[5] + 10
    days = np.arange(EDGES[0], EDGES[9], 0.5)
    lon = np.where(days < start, kept(days, 10.0),
                   np.where(days < stop, 10.0 - 0.5 * (days - start), kept(days, -20.0, seed=1)))
    segs = M.segments(M.track(element_sets(days, lon)))
    assert [s.mode for s in segs] == ["controlled_lon_inc", "drifting", "controlled_lon_inc"]
    assert segs[1].start == M.GRID_START + timedelta(days=float(EDGES[3]))
    assert segs[1].end == M.GRID_START + timedelta(days=float(EDGES[6]))


def test_short_park_far_from_a_stable_point_is_control():
    days = np.arange(EDGES[0], EDGES[3], 0.5)
    lon = np.where(days < EDGES[1], 45.0 - 0.6 * (days - EDGES[1]),
                   np.where(days < EDGES[2], kept(days, 45.0, box=0.02), 45.0 + 0.6 * (days - EDGES[2])))
    assert modes_of(element_sets(days, lon)) == ["drifting", "controlled_lon_inc", "drifting"]


def test_short_park_between_two_moves_near_a_stable_point_is_control():
    slot, park = M.STABLE_EAST_DEG + 1.0, M.STABLE_EAST_DEG - 1.4
    out, back = EDGES[3] + 15, EDGES[6] + 10
    days = np.arange(EDGES[0], EDGES[10], 0.5)
    lon = np.select([days < out, days < out + 6, days < back, days < back + 6],
                    [kept(days, slot, box=0.01), slot - 0.4 * (days - out), kept(days, park, box=0.01, seed=1),
                     park + 0.4 * (days - back)], kept(days, slot, box=0.01, seed=2))
    found = modes_of(element_sets(days, lon))
    assert found[3] == found[6] == "drifting" and found[4:6] == ["controlled_lon_inc"] * 2


def test_park_window_holding_the_arrival_tail_is_not_bracketed():
    slot, park = M.STABLE_EAST_DEG + 1.0, M.STABLE_EAST_DEG - 1.4
    out, back = EDGES[4] - 4.5, EDGES[5] + 10
    days = np.arange(EDGES[0], EDGES[10], 0.5)
    lon = np.select([days < out, days < out + 6, days < back, days < back + 6],
                    [kept(days, slot, box=0.01), slot - 0.4 * (days - out), kept(days, park, box=0.01, seed=1),
                     park + 0.4 * (days - back)], kept(days, slot, box=0.01, seed=2))
    found = modes_of(element_sets(days, lon))
    assert found[4] == "undetermined" and found[5] == "drifting"


def test_free_libration_over_a_year_between_two_moves_is_not_bracketed():
    out, back = EDGES[3] + 15, EDGES[20] + 10
    days = np.arange(EDGES[0], EDGES[24], 0.5)
    lib = free_motion(stable_point(6.0) + 0.15, np.clip(days - out - 6, 0.0, None), inc=6.0)
    slot, end = lib[0] + 2.4, lib[np.argmax(days >= back)]
    lon = np.select([days < out, days < out + 6, days < back, days < back + 6],
                    [kept(days, slot, box=0.01), slot - 0.4 * (days - out), lib, end + 0.4 * (days - back)],
                    kept(days, end + 2.4, box=0.01, seed=2))
    found = modes_of(element_sets(days, lon, inc=6.0))
    assert found[3] == found[20] == "drifting" and set(found[4:20]) == {"librating_75E"}


def test_wide_box_keeper_is_controlled_by_its_burns():
    lon0, w = 20.0, 1.0
    a = float(M.longitude_acceleration(lon0))
    period = np.sqrt(8 * w / abs(a))
    days = np.arange(0.0, EDGES[8], 0.5)
    t = days % period - period / 2
    lon = lon0 + np.sign(a) * (0.5 * abs(a) * t**2 - w / 2) + np.random.default_rng(2).normal(0, 0.003, len(days))
    assert set(modes_of(element_sets(days, lon, drift=a * t))) == {"controlled_lon_inc"}


def test_window_holding_the_end_of_a_relocation_is_drifting():
    arrive = EDGES[3] + 3
    days = np.arange(EDGES[0], EDGES[7], 0.5)
    lon = np.where(days < arrive, -20.0 - 2.0 * (days - arrive), kept(days, -20.0))
    c1 = "controlled_lon_inc"
    assert modes_of(element_sets(days, lon)) == ["drifting"] * 4 + [c1, c1, c1]


def test_sparse_window_is_undetermined_and_far_orbit_is_out_of_region():
    days = np.concatenate([np.arange(0.0, EDGES[3], 0.5), [EDGES[3] + 1, EDGES[3] + 9, EDGES[3] + 20],
                           np.arange(EDGES[4], EDGES[7], 0.5)])
    c1 = "controlled_lon_inc"
    assert modes_of(element_sets(days, kept(days, 10.0))) == [c1, c1, c1, "undetermined", c1, c1, c1]
    days = np.arange(0.0, EDGES[3], 0.5)
    gto = element_sets(days, np.zeros_like(days), drift=0.0, ecc=0.7, n_offset=1.25)
    assert set(modes_of(gto)) == {"out_of_region"}
    assert set(modes_of(element_sets(days, kept(days, 10.0), inc=40.0))) == {"inclined"}


def test_elektro_l1_librates_over_both_stable_points(mock_dir):
    records = parse_tle((mock_dir / "geo" / "37344_every_2_days.tle").read_text(encoding="utf-8"))
    tr = M.track(records)
    found = [w.mode for w in M.classify(tr)]
    assert set(found) <= {"librating_both", "undetermined"}
    assert found.count("librating_both") >= 0.9 * len(found)
    assert tr.lon.max() == pytest.approx(146.4, abs=2.0)
    assert tr.lon[-1] < M.BARRIER_LOW_DEG - 360.0


def test_year_end_counts_and_transitions():
    t = lambda y, m, d: M.GRID_START.replace(year=y, month=m, day=d)
    seg = lambda a, b, mode: M.Segment(1, a, b, mode, 1, 10, 0, 0, 0, 0, 0)
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


def test_transition_types_with_equal_counts_sort_by_name(tmp_path, mock_dir):
    geo = tmp_path / "geo"
    geo.mkdir()
    (geo / "22269.tle").write_text((mock_dir / "geo" / "22269_every_4_days.tle").read_text(), encoding="utf-8")
    manifest = {"object_count": 1, "objects": {"22269": {"by_rule": True}}}
    (geo / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert geo_modes.main(["--geo-dir", str(geo), "--out", str(tmp_path / "out"),
                           "--summary-dir", str(tmp_path / "summary")]) == 0
    rows = (tmp_path / "summary" / "transition_types.csv").read_text().splitlines()
    assert rows[1:] == ["librating_both,undetermined,1,0", "undetermined,librating_both,1,0"]


def test_job_skips_holdout_and_non_region_objects_before_opening_them(tmp_path, mock_dir):
    from orbit_watch.truth import load_splits

    holdout = sorted(n for n, e in load_splits().items() if e["split"] == "holdout")
    geo = tmp_path / "geo"
    geo.mkdir()
    (geo / "37344.tle").write_text((mock_dir / "geo" / "37344_every_2_days.tle").read_text(), encoding="utf-8")
    objects = {"37344": {"by_rule": True}, str(holdout[0]): {"by_rule": True}, "27421": {"by_rule": False}}
    (geo / "manifest.json").write_text(json.dumps({"object_count": 3, "objects": objects}), encoding="utf-8")
    assert geo_modes.main(["--geo-dir", str(geo), "--out", str(tmp_path / "out"),
                           "--summary-dir", str(tmp_path / "summary")]) == 0
    summary = json.loads((tmp_path / "summary" / "summary.json").read_text())
    assert summary["skipped_holdout"] == [holdout[0]] and summary["skipped_not_by_rule"] == [27421]
    assert summary["objects_classified"] == 1
    rows = (tmp_path / "out" / "segments.csv").read_text().splitlines()
    assert rows[0].startswith("norad_id,start,end,mode") and all(r.startswith("37344,") for r in rows[1:])
