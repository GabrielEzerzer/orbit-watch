import json
import math
from dataclasses import replace

import numpy as np
import pytest

from harness.evals import detector as ev
from orbit_watch.detect import Detection, detect, score_gaps
from orbit_watch.elements import parse_omm_json
from orbit_watch.generalise import LATE_DAYS, TOLERANCE_DAYS, LogEvent, Setting, load_series, match_near
from orbit_watch.series import ElementSeries, to_series
from orbit_watch.truth import HoldoutError, load_splits

from test_generalise import _geo_omm

D = np.timedelta64(86_400_000_000, "us")
T0 = np.datetime64("2021-01-01T00:00", "us")
YEAR = (np.datetime64("2021-01-01", "us"), np.datetime64("2022-01-01", "us"))


def t(s):
    return np.datetime64(s, "us")


def _series(every_days, days, steps_km, seed=1):
    """A near-GEO semi-major axis with 20 m scatter, one element set every ``every_days`` from T0,
    and a ``+km`` step after each day in ``steps_km``."""
    rng = np.random.default_rng(seed)
    day = np.arange(0, days, every_days)
    a = 42164.0 + sum(km * (day > d) for d, km in steps_km.items()) + rng.normal(0, 0.02, len(day))
    flat = np.zeros(len(day))
    return ElementSeries(43491, T0 + (day * 86_400e6).astype("timedelta64[us]"), a, flat + 1.0, flat, flat,
                         flat, flat)


def _obj(series, events, days):
    return ev.Obj(43491, "x", "GEO", "test", series, events, [], (T0, T0 + days * D), LATE_DAYS)


def _burn(name, day, kind="EW"):
    return LogEvent(name, kind, None, 0, T0 + int(day * 24) * np.timedelta64(1, "h"),
                    T0 + int(day * 24 + 2) * np.timedelta64(1, "h"))


# ---- arithmetic

def test_wilson_interval_matches_hand_values():
    assert ev.wilson(0, 0) is None
    lo, hi = ev.wilson(5, 10)  # p = 0.5: symmetric, 0.5 -/+ 0.2634
    assert (round(lo, 4), round(hi, 4)) == (0.2366, 0.7634)
    lo, hi = ev.wilson(10, 10)  # all hits: upper bound 1, lower n / (n + z^2)
    assert math.isclose(hi, 1.0) and math.isclose(lo, 10 / (10 + ev.Z95 ** 2))
    lo, hi = ev.wilson(0, 3)
    assert math.isclose(lo, 0.0, abs_tol=1e-12) and math.isclose(hi, ev.Z95 ** 2 / (3 + ev.Z95 ** 2))


def test_recall_is_over_covered_and_reports_all_events_separately():
    r = ev.recall(matched=3, covered_n=4, events=6)
    assert r["recall"] == 0.75 and r["recall_all_events"] == 0.5
    assert r["ci95_width"] == round(r["ci95"][1] - r["ci95"][0], 4)
    assert ev.recall(0, 0, 2)["recall"] is None


def test_false_alarm_rate_and_exposure():
    span = (t("2024-01-01"), t("2025-01-01"))  # 366 days
    zones = [(t("2024-03-01"), t("2024-03-03")), (t("2024-03-02"), t("2024-03-11")),  # overlap: 10 days
             (t("2023-12-01"), t("2024-01-02"))]  # clipped at the span start: 1 day
    stretches = ev.subtract(span, zones)
    assert stretches == [(t("2024-01-02"), t("2024-03-01")), (t("2024-03-11"), t("2025-01-01"))]
    assert math.isclose(ev.years(stretches), (366 - 11) / 365.25)
    assert ev.fa_rate(2, 0.5) == 4.0
    assert ev.fa_rate(1, 0.0) is None


def test_score_object_counts_matches_and_false_alarms_on_scored_no_burn_time():
    t0 = np.datetime64("2021-03-01T00:00", "s")
    # GEO-like series, 3 sets a day for 70 days: a logged burn on day 10, an unlogged step on day 40.
    recs = parse_omm_json(json.dumps(_geo_omm(t0, 70, {10.1: 3.0, 40.1: 3.0})))
    series = to_series(recs)[43491]
    burn = LogEvent("B", "EW", None, 0, t("2021-03-11T01:00"), t("2021-03-11T03:00"))
    cov = (t("2021-03-01"), t("2021-05-10"))
    obj = ev.Obj(43491, "x", "GEO", "test", series, [burn], [], cov, LATE_DAYS)
    s = Setting(4, 12, 200)
    r = ev.score_object(obj, s, t("2021-01-01"), t("2022-01-01"))
    assert r["subsets"]["all"] == {"events": 1, "covered": 1, "matched": 1, "matched_all": 1}
    assert r["subsets"]["EW"]["matched"] == 1
    assert r["false_alarms"] == 1  # the unlogged step on day 40
    fa_start = t(r["_detail"]["false_alarm_list"][0]["start_utc"].rstrip("Z"))
    assert abs((fa_start - t("2021-04-10T02:24")) / D) < 1
    # Exposure is scored time minus the burn's match zone: below the 70-day series, above it less
    # the zone and the k-epoch edges at both ends.
    zone_days = (burn.hi - burn.lo) / D + TOLERANCE_DAYS + LATE_DAYS
    assert (70 - zone_days - 3) / 365.25 < r["object_years"] < (70 - zone_days) / 365.25
    # Same detections, burn outside the period: neither matched nor a false alarm (its zone stays out).
    r2 = ev.score_object(obj, s, t("2021-03-20"), t("2022-01-01"))
    assert r2["subsets"]["all"]["events"] == 0 and r2["false_alarms"] == 1


# ---- the frozen reference, peak gaps, one-to-one matching, duplicates

def test_reference_is_score_gaps_rule_at_k4():
    # Spacing 1.05 days puts 4 sets 3.15 days apart, just past the span limit; 2.5 days, past the gap limit.
    rng = np.random.default_rng(5)
    irregular = replace(_series(1, 300, {}), epochs=T0 + (np.cumsum(rng.uniform(0.2, 2.4, 300)) * 86_400e6)
                        .astype("timedelta64[us]"))
    assert 0 < ev.reference_scored(irregular.epochs).sum() < len(irregular) - 1  # scored and unscored gaps
    for series in [_series(every, days, {}) for every, days in ((0.9, 30), (1.05, 30), (0.31, 20), (2.5, 40))] + [
            irregular]:
        want = score_gaps(series, k=4, max_span_days=3.0, max_gap_days=2.0).valid
        assert np.array_equal(ev.reference_scored(series.epochs), want)
    assert ev.reference_scored(_series(0.5, 3, {}).epochs).sum() == 0  # under 2k epochs


def test_coverage_is_the_k4_reference_whatever_the_setting_scores():
    # One set every 0.9 day: 4 sets span 2.7 days (the reference scores every gap), 6 span 4.5 (k=6 none).
    obj = _obj(_series(0.9, 60, {20.05: 3.0}), [_burn("B", 20.05)], 60)
    r4 = ev.score_object(obj, Setting(4, 12, 200), *YEAR)
    assert r4["subsets"]["all"] == {"events": 1, "covered": 1, "matched": 1, "matched_all": 1}
    r6 = ev.score_object(obj, Setting(6, 12, 200), *YEAR)
    assert r6["detections"] == 0
    # The burn stays in the denominator as a miss; it does not leave it.
    assert r6["subsets"]["all"] == {"events": 1, "covered": 1, "matched": 0, "matched_all": 0}


def test_exposure_is_the_union_of_reference_and_setting_scored_time():
    obj = _obj(_series(0.9, 60, {}), [], 60)
    r4 = ev.score_object(obj, Setting(4, 12, 200), *YEAR)
    assert r4["object_years"] > 50 / 365.25 and r4["no_burn_years"] == pytest.approx(60 / 365.25)
    # k=6 scores nothing here; the reference's scored time stays exposure.
    assert ev.score_object(obj, Setting(6, 12, 200), *YEAR)["object_years"] == r4["object_years"]
    # One set every 1.1 day: the reference (4 sets span 3.3 days) scores nothing, k=3 (2.2 days) every
    # gap. Time only the setting scores is exposure, so detections of its unlogged step are false alarms.
    obj = _obj(_series(1.1, 60, {30.05: 3.0}), [], 60)
    r3 = ev.score_object(obj, Setting(3, 12, 200), *YEAR)
    assert r3["false_alarms"] >= 1 and r3["object_years"] > 50 / 365.25
    r4 = ev.score_object(obj, Setting(4, 12, 200), *YEAR)
    assert r4["object_years"] == 0 and r4["no_burn_years"] > 50 / 365.25


def test_matching_and_false_alarms_use_the_peak_gap_not_the_interval():
    # A logged burn on day 10 that the data does not show, and an unlogged step on day 40.
    series = _series(1 / 3, 70, {40.05: 3.0})
    obj = _obj(series, [_burn("B", 10.05)], 70)
    s = Setting(4, 12, 200)
    (d,) = obj.detections(s)
    assert ev.score_object(obj, s, *YEAR)["false_alarms"] == 1
    # The same detection with its interval widened back over the burn: still a miss and a false alarm.
    obj.detections = lambda s: [replace(d, start=series.epochs[20])]
    r = ev.score_object(obj, s, *YEAR)
    assert r["subsets"]["all"] == {"events": 1, "covered": 1, "matched": 0, "matched_all": 0}
    assert r["false_alarms"] == 1
    # A peak that is not one gap of the series is refused.
    obj.detections = lambda s: [Detection(series.epochs[20], d.end, d.step_m, d.z)]
    with pytest.raises(ValueError, match="one gap"):
        ev.score_object(obj, s, *YEAR)


def test_match_gives_each_detection_only_its_nearest_event():
    # An NS burn 19 h before an EW burn (QZSS events carry no expected sign), the EW step detected
    # once at the EW burn and again a day later.
    ns = LogEvent("NS", "NS", None, 0, t("2021-07-21T01:00"), t("2021-07-21T02:00"))
    ew = LogEvent("EW", "EW", None, 0, t("2021-07-21T20:00"), t("2021-07-21T21:00"))
    first = Detection(t("2021-07-21T19:00"), t("2021-07-21T23:00"), -3000.0, -300.0)
    second = Detection(t("2021-07-22T23:00"), t("2021-07-23T03:00"), -3100.0, -80.0)
    assert match_near([ns, ew], [first, second], TOLERANCE_DAYS, LATE_DAYS) == {1: 0, 0: 1}
    assert ev.match([ns, ew], [first, second], TOLERANCE_DAYS, LATE_DAYS) == {1: 0}  # second is no NS hit
    # An event two detections pick goes to the nearer, whichever comes first in the list.
    assert ev.match([ns, ew], [second, first], TOLERANCE_DAYS, LATE_DAYS) == {1: 1}
    # A tie between two events goes to the earlier one, whatever the list order.
    a = LogEvent("A", "EW", None, 0, t("2021-01-01T00:00"), t("2021-01-01T00:00"))
    b = LogEvent("B", "EW", None, 0, t("2021-01-01T12:00"), t("2021-01-01T12:00"))
    mid = Detection(t("2021-01-01T05:00"), t("2021-01-01T07:00"), 500.0, 20.0)
    assert ev.match([b, a], [mid]) == {1: 0}
    # The sign still decides eligibility: a nearer event of the wrong sign is passed over.
    up = replace(a, expected_sign=1)
    assert ev.match([up, b], [replace(mid, step_m=-500.0)]) == {1: 0}


def test_extra_detections_at_a_burn_are_duplicates_not_hits_or_false_alarms():
    series = _series(1 / 3, 70, {10.05: 3.0})
    obj = _obj(series, [_burn("B", 10.05)], 70)
    s = Setting(4, 12, 200)
    (d,) = obj.detections(s)
    j = int(np.searchsorted(series.epochs, d.peak_start)) + 4  # four gaps (1.3 days) later
    extra = Detection(series.epochs[j], series.epochs[j + 1], d.step_m, d.z / 2, "a",
                      series.epochs[j], series.epochs[j + 1])
    obj.detections = lambda s: [d, extra]
    r = ev.score_object(obj, s, *YEAR)
    assert r["subsets"]["all"]["matched"] == 1
    assert (r["false_alarms"], r["duplicates"], r["matched_detections"]) == (0, 1, 1)



def test_a_north_south_hit_needs_the_inclination_channel():
    # A step at a logged NS burn, seen on the semi-major axis: matched (no duplicate, no false
    # alarm) but no hit, in the NS subset or in "all".
    series = _series(1 / 3, 70, {10.05: 3.0})
    obj = _obj(series, [_burn("N", 10.05, kind="NS")], 70)
    s = Setting(4, 12, 200)
    (d,) = obj.detections(s)
    r = ev.score_object(obj, s, *YEAR)
    assert r["subsets"]["NS"]["matched"] == 0 and r["subsets"]["all"]["matched_all"] == 0
    assert (r["matched_detections"], r["wrong_channel"], r["false_alarms"], r["duplicates"]) == (1, 1, 0, 0)
    assert [x["event_id"] for x in r["_detail"]["wrong_channel_list"]] == ["N"]
    # The same detection on the inclination channel, alone or merged with the a channel, is a hit.
    for ch in ("i", "a+i"):
        obj.detections = lambda s, ch=ch: [replace(d, channel=ch)]
        r = ev.score_object(obj, s, *YEAR)
        assert r["subsets"]["NS"]["matched"] == 1 and r["wrong_channel"] == 0
    # EW and EW+NS events keep the old rule: a semi-major-axis detection hits them.
    for kind in ("EW", "EW+NS"):
        obj = _obj(series, [_burn("E", 10.05, kind=kind)], 70)
        r = ev.score_object(obj, s, *YEAR)
        assert r["subsets"][kind]["matched"] == 1 and r["wrong_channel"] == 0


def test_the_eval_grades_what_detect_reports_on_both_channels():
    # a-steps on days 10 and 40; inclination steps on day 10.4 (within nms_days of the a-step, so
    # merge_channels drops it) and day 25 (kept).
    rng = np.random.default_rng(2)
    series = _series(1 / 3, 70, {10.05: 3.0, 40.05: -2.0})
    day = (series.epochs - T0).astype("int64") / 86_400e6
    inc = 0.05 + rng.normal(0, 1e-4, len(day)) - 0.02 * (day > 10.4) + 0.03 * (day > 25.05)
    series = replace(series, inclination=inc)
    off, on = Setting(4, 12, 200), Setting(4, 12, 200, inc_z_min=12, inc_step_min_deg=0.011)
    assert [d.channel for d in detect(series, off)] == ["a", "a"]
    dets = _obj(series, [], 70).detections(on)
    assert [d.channel for d in dets] == ["a", "i", "a"]
    assert dets == detect(series, on)


# ---- split and loader

def test_split_json_agrees_with_groundtruth_splits():
    spec = json.loads(ev.SPLIT_PATH.read_text(encoding="utf-8"))
    splits = load_splits()
    listed = {o["norad_id"]: side for side in ("train", "holdout") for o in spec["objects"][side]}
    assert listed == {n: o["split"] for n, o in splits.items()}
    assert spec["periods"]["test"]["requires_final"] is True


def test_test_split_needs_final(tmp_path):
    with pytest.raises(HoldoutError):
        ev.evaluate("test", ev.DEFAULT_SETTINGS, tmp_path)
    with pytest.raises(HoldoutError):
        ev.evaluate("dev", ev.DEFAULT_SETTINGS, tmp_path, final=True)


def test_load_series_falls_back_to_geo_tle(tmp_path, mock_dir):
    tle_dir, geo_dir = tmp_path / "spacetrack", tmp_path / "geo"
    tle_dir.mkdir()
    geo_dir.mkdir()
    with pytest.raises(FileNotFoundError):
        load_series(37951, tle_dir)
    (geo_dir / "37951.tle").write_text((mock_dir / "geo" / "bundle-sample.txt").read_text(encoding="utf-8"),
                                       encoding="utf-8")
    series, label, _ = load_series(37951, tle_dir)  # default geo_dir: tle_dir/../geo
    assert label == "geo/37951.tle" and len(series) > 1 and series.norad_id == 37951
    # A gp_history file, when present, wins over the fallback.
    (tle_dir / "gp_history-43491-x.json").write_text(
        json.dumps(_geo_omm(np.datetime64("2021-03-01T00:00", "s"), 5, {})), encoding="utf-8")
    (geo_dir / "43491.tle").write_text("not read\n", encoding="utf-8")
    series, label, _ = load_series(43491, tle_dir)
    assert label == "gp_history-43491-x.json" and len(series) == 15
