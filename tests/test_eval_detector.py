import json
import math

import numpy as np
import pytest

from harness.evals import detector as ev
from orbit_watch.elements import parse_omm_json
from orbit_watch.generalise import LATE_DAYS, TOLERANCE_DAYS, LogEvent, Setting, load_series
from orbit_watch.series import to_series
from orbit_watch.truth import HoldoutError, load_splits

from test_generalise import _geo_omm

D = np.timedelta64(86_400_000_000, "us")


def t(s):
    return np.datetime64(s, "us")


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
    assert r["subsets"]["all"] == {"events": 1, "covered": 1, "matched": 1}
    assert r["subsets"]["EW"]["matched"] == 1
    assert r["false_alarms"] == 1  # the unlogged step on day 40
    fa_start = t(r["_detail"]["false_alarms"][0]["start_utc"].rstrip("Z"))
    assert abs((fa_start - t("2021-04-10T02:24")) / D) < 1
    # Exposure is scored time minus the burn's match zone: below the 70-day series, above it less
    # the zone and the k-epoch edges at both ends.
    zone_days = (burn.hi - burn.lo) / D + TOLERANCE_DAYS + LATE_DAYS
    assert (70 - zone_days - 3) / 365.25 < r["object_years"] < (70 - zone_days) / 365.25
    # Same detections, burn outside the period: neither matched nor a false alarm (its zone stays out).
    r2 = ev.score_object(obj, s, t("2021-03-20"), t("2022-01-01"))
    assert r2["subsets"]["all"]["events"] == 0 and r2["false_alarms"] == 1


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
