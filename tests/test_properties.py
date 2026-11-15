# Property-based tests of the core logic: parsing, series collapse, detection, matching and conversions.
# Every input is generated here; nothing reads the network or calibration data.

import csv
import io
import json
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
from hypothesis import HealthCheck, assume, example, given, settings, strategies as st
from sgp4.earth_gravity import wgs72

from harness.evals import detector as ev
from orbit_watch import calibrate, generalise, holdout
from orbit_watch.detect import GapScores, Setting, detect, merge_channels, pick, score_gaps
from orbit_watch.elements import ElementSet, _tle_checksum, parse_omm_csv, parse_omm_json, parse_tle
from orbit_watch.geo import drift_rate, wrap180
from orbit_watch.inject import Window, inject, recovered
from orbit_watch.manoeuvre_logs import MU_KM3_S2, delta_a_m
from orbit_watch.propagate import propagate
from orbit_watch.series import MIN_EPOCH_GAP_S, ElementSeries, distinct_epochs, to_series

PROPERTY = settings(derandomize=True, deadline=None, database=None, max_examples=60,
                    suppress_health_check=[HealthCheck.too_slow])
SLOW = settings(PROPERTY, max_examples=15)
T0 = np.datetime64("2021-01-01T00:00:00", "us")
DAY_US = 86_400_000_000
NORAD_A, NORAD_B = 90001, 90002
FROZEN = Setting(k=4, z_min=12, step_min_m=200)
SHORT_PERIOD_K = 1.5004 * 1.33


def _implied(x: float) -> str:
    if x == 0:
        return " 00000-0"
    e = math.floor(math.log10(abs(x))) + 1
    m = round(abs(x) / 10.0 ** (e - 5))
    if m == 100000:
        m, e = 10000, e + 1
    return f"{'-' if x < 0 else ' '}{m:05d}{'-' if e < 0 else '+'}{abs(e)}"


def _signed_fraction(x: float) -> str:
    return ("-" if x < 0 else " ") + f"{abs(x):.8f}"[1:]


def _with_checksum(body: str) -> str:
    return body + str(_tle_checksum(body))


def tle_text(rec: ElementSet) -> str:
    year = rec.epoch.year
    doy = (rec.epoch - datetime(year, 1, 1, tzinfo=timezone.utc)) / timedelta(days=1) + 1
    l1 = _with_checksum(
        f"1 {rec.norad_id:05d}U 21001A   {year % 100:02d}{doy:012.8f} {_signed_fraction(rec.mean_motion_dot)} "
        f"{_implied(rec.mean_motion_ddot)} {_implied(rec.bstar)} 0  999")
    l2 = _with_checksum(
        f"2 {rec.norad_id:05d} {rec.inclination:8.4f} {rec.raan:8.4f} {f'{rec.eccentricity:.7f}'[2:]} "
        f"{rec.arg_perigee:8.4f} {rec.mean_anomaly:8.4f} {rec.mean_motion:11.8f}12345")
    return (f"{rec.name}\n" if rec.name else "") + f"{l1}\n{l2}\n"


@st.composite
def tle_records(draw):
    year = draw(st.integers(1957, 2056))
    days = 366 if year % 4 == 0 and (year % 100 or year % 400 == 0) else 365
    day = draw(st.integers(1, days))
    frac = draw(st.integers(0, 99_999_999))
    mean_motion = draw(st.integers(100_000_000, 1_650_000_000)) / 1e8
    a_km = (MU_KM3_S2 / (mean_motion * 2 * math.pi / 86400) ** 2) ** (1 / 3)
    ecc = draw(st.integers(0, 9_999_999)) / 1e7
    assume(a_km * (1 - ecc) > 6578.0)
    implied = st.one_of(st.just(0.0), st.builds(
        lambda s, m, e: s * m * 10.0 ** (e - 5), st.sampled_from((1, -1)), st.integers(10000, 99999),
        st.integers(-9, 0)))
    name = draw(st.one_of(st.none(), st.from_regex(r"[A-Z][A-Z0-9 ()-]{0,20}[A-Z0-9)]", fullmatch=True)))
    tle = tle_text(ElementSet(
        norad_id=draw(st.integers(1, 99999)), name=name,
        epoch=datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(days=day - 1, microseconds=frac * 864),
        mean_motion=mean_motion, eccentricity=ecc,
        inclination=draw(st.integers(0, 1_800_000)) / 1e4,
        raan=draw(st.integers(0, 3_599_999)) / 1e4,
        arg_perigee=draw(st.integers(0, 3_599_999)) / 1e4,
        mean_anomaly=draw(st.integers(0, 3_599_999)) / 1e4,
        bstar=draw(implied), mean_motion_dot=draw(st.integers(-99_999_999, 99_999_999)) / 1e8,
        mean_motion_ddot=draw(implied), semi_major_axis_km=0.0))
    return tle


@PROPERTY
@given(st.lists(tle_records(), min_size=1, max_size=3))
def test_tle_text_round_trips_through_the_parser(records):
    text = "".join(records)
    parsed = parse_tle(text)
    assert len(parsed) == len(records)
    assert "".join(tle_text(r) for r in parsed) == text


@SLOW
@given(tle_records(), st.integers(1, 9))
def test_any_single_digit_change_breaks_the_checksum(record, shift):
    lines = record.splitlines()
    for which in (len(lines) - 2, len(lines) - 1):
        line = lines[which]
        for col in [i for i, c in enumerate(line[:68]) if c.isdigit()]:
            changed = line[:col] + str((int(line[col]) + shift) % 10) + line[col + 1:]
            try:
                parse_tle("\n".join(lines[:which] + [changed] + lines[which + 1:]))
            except ValueError:
                continue
            raise AssertionError(f"accepted a changed digit at column {col}: {changed!r}")


def _omm_fields(rec: ElementSet) -> dict:
    return {"OBJECT_NAME": rec.name or "", "NORAD_CAT_ID": str(rec.norad_id),
            "EPOCH": rec.epoch.replace(tzinfo=None).isoformat(),
            "MEAN_MOTION": repr(rec.mean_motion), "ECCENTRICITY": repr(rec.eccentricity),
            "INCLINATION": repr(rec.inclination), "RA_OF_ASC_NODE": repr(rec.raan),
            "ARG_OF_PERICENTER": repr(rec.arg_perigee), "MEAN_ANOMALY": repr(rec.mean_anomaly),
            "BSTAR": repr(rec.bstar), "MEAN_MOTION_DOT": repr(rec.mean_motion_dot),
            "MEAN_MOTION_DDOT": repr(rec.mean_motion_ddot)}


@PROPERTY
@given(tle_records())
def test_tle_and_gp_json_and_csv_give_the_same_element_set(record):
    (rec,) = parse_tle(record)
    fields = _omm_fields(rec)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(fields))
    writer.writeheader()
    writer.writerow(fields)
    raw = json.dumps([{k: (v if k in ("OBJECT_NAME", "EPOCH") else json.loads(v)) for k, v in fields.items()}])
    assert parse_omm_json(raw) == parse_omm_csv(out.getvalue()) == [rec]


def _record(norad: int, second: int, tag: int) -> ElementSet:
    return ElementSet(norad, None, datetime(2022, 3, 1, tzinfo=timezone.utc) + timedelta(seconds=second),
                      15.5, 0.001, 51.6, 0.0, 0.0, float(tag % 360), 1e-4, 0.0, 0.0, 6790.0 + tag)


records_with_distinct_epochs = st.lists(
    st.tuples(st.sampled_from((NORAD_A, NORAD_B)), st.integers(0, 4 * 3600)),
    max_size=40, unique=True).map(lambda xs: [_record(n, s, i) for i, (n, s) in enumerate(xs)])


@PROPERTY
@given(records_with_distinct_epochs, st.randoms(use_true_random=False))
def test_series_collapse_ignores_input_order(recs, rng):
    shuffled = list(recs)
    rng.shuffle(shuffled)
    assert distinct_epochs(shuffled) == distinct_epochs(recs)


@PROPERTY
@given(st.lists(st.integers(0, 600), max_size=20))
@example([0, 0])
def test_a_record_whose_next_epoch_is_at_least_the_minimum_gap_later_is_kept(extra_s):
    seconds = np.cumsum([0.0] + [MIN_EPOCH_GAP_S + x for x in extra_s])
    recs = [_record(NORAD_A, float(t), i) for i, t in enumerate(seconds)]
    assert distinct_epochs(recs) == {NORAD_A: recs}


@PROPERTY
@given(st.lists(st.tuples(st.sampled_from((NORAD_A, NORAD_B)), st.integers(0, 4 * 3600)), max_size=40)
       .map(lambda xs: [_record(n, s, i) for i, (n, s) in enumerate(xs)]))
def test_series_collapse_is_idempotent_and_spaces_epochs(recs):
    kept = distinct_epochs(recs)
    assert distinct_epochs([r for rs in kept.values() for r in rs]) == kept
    for norad, rs in kept.items():
        gaps = [(b.epoch - a.epoch).total_seconds() for a, b in zip(rs, rs[1:])]
        assert all(g >= MIN_EPOCH_GAP_S for g in gaps)
        assert rs[-1].epoch == max(r.epoch for r in recs if r.norad_id == norad)
    series = to_series(recs)
    assert {n: len(s) for n, s in series.items()} == {n: len(rs) for n, rs in kept.items()}


gp_rows = st.lists(st.tuples(st.integers(0, 2 * 3600), st.integers(1, 10**6)), max_size=40,
                   unique_by=(lambda x: x, lambda x: x[1])).map(
    lambda xs: [{"GP_ID": str(g), "EPOCH": (datetime(2024, 5, 1) + timedelta(seconds=s)).isoformat()}
                for s, g in xs])


@PROPERTY
@given(gp_rows, st.randoms(use_true_random=False))
def test_gp_row_dedupe_is_order_free_idempotent_and_accounts_for_every_row(rows, rng):
    kept, stats = holdout.dedupe_gp_rows(rows)
    shuffled = list(rows)
    rng.shuffle(shuffled)
    assert holdout.dedupe_gp_rows(shuffled)[0] == kept
    assert holdout.dedupe_gp_rows(kept)[0] == kept
    assert not rows or max(rows, key=lambda r: int(r["GP_ID"])) in kept
    assert stats["element_sets_kept"] + stats["exact_epoch_repeats_dropped"] \
        + stats["near_epoch_reissues_dropped"] == stats["rows"] == len(rows)


@st.composite
def gap_scores(draw):
    n = draw(st.integers(2, 40))
    hours = draw(st.lists(st.integers(1, 24), min_size=n - 1, max_size=n - 1))
    epochs = T0 + np.concatenate([[0], np.cumsum(hours)]).astype("timedelta64[h]").astype("timedelta64[us]")
    value = st.one_of(st.just(float("nan")), st.floats(-50, 50, allow_nan=False))
    z = np.array(draw(st.lists(value, min_size=n - 1, max_size=n - 1)))
    step = np.where(np.isnan(z), np.nan, z * draw(st.floats(10, 100)))
    return GapScores(epochs[:-1], epochs[1:], step, z, np.ones(n - 1))


@PROPERTY
@given(gap_scores(), st.floats(0, 20), st.floats(0, 1000), st.floats(0.1, 3))
def test_non_maximum_suppression_keeps_a_spaced_maximal_subset_of_flagged_gaps(sc, z_min, step_min, nms):
    dets = pick(sc, z_min, step_min, nms)
    with np.errstate(invalid="ignore"):
        flagged = set(np.flatnonzero(sc.valid & (np.abs(sc.z) >= z_min) & (np.abs(sc.step_m) >= step_min)))
    centre = ((sc.start - sc.start[0]).astype("int64") / DAY_US
              + 0.5 * (sc.end - sc.start).astype("int64") / DAY_US)
    idx = [int(np.flatnonzero(sc.start == d.start)[0]) for d in dets]
    assert idx == sorted(idx) and set(idx) <= flagged
    assert all(d.end == sc.end[i] and d.z == sc.z[i] and d.step_m == sc.step_m[i] for d, i in zip(dets, idx))
    assert all(abs(centre[a] - centre[b]) > nms for a in idx for b in idx if a < b)
    for j in flagged - set(idx):
        assert any(abs(centre[i] - centre[j]) <= nms and abs(sc.z[i]) >= abs(sc.z[j]) for i in idx)


def synthetic_series(seed: int, n: int = 160, noise_m: float = 20.0) -> ElementSeries:
    rng = np.random.default_rng(seed)
    days = np.cumsum(rng.uniform(0.5, 1.5, n) / 4.5)
    a_m = 6_790_000.0 - 80.0 * days + rng.normal(0, noise_m, n)
    z = np.zeros(n)
    return ElementSeries(NORAD_A, T0 + (days * DAY_US).astype("timedelta64[us]"), a_m / 1000.0, z, z, z, z, z)


@SLOW
@given(st.integers(0, 2**32 - 1), st.integers(20, 138), st.floats(1000, 5000), st.sampled_from((1, -1)))
def test_a_large_injected_burn_is_recovered_with_its_sign(seed, gap, size_m, sign):
    series = synthetic_series(seed)
    assert detect(series, FROZEN) == []
    dets = detect(inject(series, [gap], [sign * size_m]), FROZEN)
    assert recovered(dets, Window(series.epochs[gap], series.epochs[gap + 1]), sign * size_m)


@SLOW
@given(st.integers(0, 2**32 - 1), st.sampled_from(("a", "i")))
def test_negating_a_series_negates_every_step_and_keeps_z(seed, channel):
    s = synthetic_series(seed, n=60)
    s = replace(s, inclination=51.6 + s.semi_major_axis_km % 0.01)
    flipped = replace(s, semi_major_axis_km=-s.semi_major_axis_km, inclination=-s.inclination)
    a, b = score_gaps(s, k=4, channel=channel), score_gaps(flipped, k=4, channel=channel)
    np.testing.assert_array_equal(b.step_m, -a.step_m)
    np.testing.assert_array_equal(b.z, -a.z)


def _centre(d):
    return d.start + (d.end - d.start) / 2


@PROPERTY
@given(gap_scores(), gap_scores(), st.floats(0.1, 3))
def test_channel_merge_keeps_every_axis_detection_and_spaces_the_added_ones(a, i, nms):
    a_dets = pick(a, 1, 0, nms)
    i_dets = pick(replace(i, channel="i"), 1, 0, nms)
    merged = merge_channels(a_dets, i_dets, nms)
    assert [d for d in merged if d.channel == "a"] == a_dets
    tol = np.timedelta64(int(nms * DAY_US), "us")
    assert all(abs(_centre(d) - _centre(x)) > tol for d in merged if d.channel == "i" for x in a_dets)
    assert [d.start for d in merged] == sorted(d.start for d in merged)


_TYPES = ("reboost", "deboost", "debris avoidance", "reboost retrograde")


@st.composite
def calibrate_events(draw, days=20):
    out = []
    for _ in range(draw(st.integers(0, 8))):
        lo = T0 + np.timedelta64(draw(st.integers(0, days * 24)), "h")
        hi = lo + np.timedelta64(draw(st.sampled_from((0, 72))), "h")
        out.append(calibrate.Event("", "", draw(st.sampled_from(_TYPES)), "", lo, hi))
    return out


@PROPERTY
@given(calibrate_events(), gap_scores())
def test_vectorised_matching_and_coverage_equal_the_calibration_versions(events, sc):
    dets = pick(sc, 0, 0, 0.3)
    m = calibrate.match(events, dets)
    assert generalise.match_near(events, dets) == m
    assert generalise.covered(events, sc) == calibrate.covered(events, sc)
    assert len(set(m.values())) == len(m)
    assert all(calibrate._overlaps(events[e], dets[d].start, dets[d].end, calibrate.TOLERANCE_DAYS)
               and calibrate._sign_ok(events[e], dets[d]) for e, d in m.items())


@st.composite
def log_events(draw, kind, days):
    out = []
    for i in range(draw(st.integers(0, 6))):
        lo = T0 + np.timedelta64(draw(st.integers(0, days * 24)), "h")
        out.append(generalise.LogEvent(f"{kind}{i}", kind, None, draw(st.sampled_from((0, 1, -1))), lo,
                                       lo + np.timedelta64(2, "h")))
    return out


@PROPERTY
@given(st.integers(0, 2**32 - 1), log_events("EW", 40), log_events("attitude", 40),
       st.integers(0, 10), st.integers(25, 40))
def test_every_detection_lands_in_at_most_one_bucket(seed, events, attitude, cov_lo, cov_hi):
    rng = np.random.default_rng(seed)
    day = np.arange(0, 40, 0.3)
    a = 42164.0 + np.cumsum(rng.normal(0, 0.05, len(day))) + rng.normal(0, 0.02, len(day))
    flat = np.zeros(len(day))
    series = ElementSeries(NORAD_A, T0 + (day * DAY_US).astype("timedelta64[us]"), a, flat, flat, flat, flat,
                           flat)
    obj = ev.Obj(NORAD_A, "x", "IGSO", "test", series, events, attitude,
                 (T0 + cov_lo * np.timedelta64(DAY_US, "us"), T0 + cov_hi * np.timedelta64(DAY_US, "us")),
                 generalise.LATE_DAYS)
    r = ev.score_object(obj, Setting(k=4, z_min=2, step_min_m=10, nms_days=0.5), T0, T0 + 40 * np.timedelta64(
        DAY_US, "us"))
    fa = {tuple(x.values()) for x in r["_detail"]["false_alarm_list"]}
    dup = {tuple(x.values()) for x in r["_detail"]["duplicate_list"]}
    assert not fa & dup
    assert r["matched_detections"] + r["dropped_attitude_or_unplanned"] + r["false_alarms"] \
        + r["duplicates"] <= r["detections"]


@PROPERTY
@given(st.floats(-1, 1), st.floats(-5, 5), st.integers(2, 30), st.floats(0.05, 1))
def test_longitude_wrap_then_unwrap_recovers_the_drift_rate(offset, rate, n, step):
    days = np.arange(n) * step
    lon = wrap180(180.0 + offset + rate * (days - days[n // 2]))
    assert np.all((lon >= -180) & (lon < 180))
    assert math.isclose(drift_rate(days, lon), rate, abs_tol=1e-6)


@PROPERTY
@given(tle_records())
@example(tle_text(ElementSet(1, None, datetime(2021, 1, 1, tzinfo=timezone.utc), 1.0, 0.8442747, 90.0, 0.0,
                             180.0, 0.0, 0.0, 0.0, 0.0, 0.0)))
@example(tle_text(ElementSet(1, None, datetime(2021, 1, 1, tzinfo=timezone.utc), 3.25, 0.0, 90.0, 0.0,
                             90.0, 0.0, 0.0, 0.0, 0.0, 0.0)))
def test_propagated_state_at_epoch_agrees_with_the_derived_semi_major_axis(record):
    (rec,) = parse_tle(record)
    (r,), (v,) = propagate(rec, [rec.epoch])
    a = rec.semi_major_axis_km
    a_osc = 1.0 / (2.0 / np.linalg.norm(r) - np.dot(v, v) / wgs72.mu)
    bound = SHORT_PERIOD_K * wgs72.j2 * (wgs72.radiusearthkm / a) ** 2 * (1 - rec.eccentricity) ** -3
    assert abs(a_osc - a) < bound * a


@PROPERTY
@given(st.floats(6578, 42200), st.floats(-1.0, 1.0))
def test_gauss_delta_a_matches_vis_viva_for_small_burns(a_km, dv):
    v = math.sqrt(MU_KM3_S2 / a_km)
    a_after = 1.0 / (2.0 / a_km - (v + dv / 1000.0) ** 2 / MU_KM3_S2)
    exact_m = (a_after - a_km) * 1000.0
    assert math.isclose(delta_a_m(dv, a_km), exact_m, rel_tol=4 * abs(dv) / 1000.0 / v + 1e-9, abs_tol=1e-6)
