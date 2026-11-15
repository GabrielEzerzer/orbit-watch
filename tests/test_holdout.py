import json

import numpy as np
import pytest

from orbit_watch.calibrate import Event
from orbit_watch.detect import Detection
from orbit_watch.holdout import Scored, dedupe_gp_rows, load_gp_history, loyo_folds, period_masks
from orbit_watch.inject import load_series
from orbit_watch.series import ElementSeries


def row(epoch, gp_id, mm="15.5"):
    return {"EPOCH": epoch, "GP_ID": str(gp_id), "MEAN_MOTION": mm}


def test_restated_epochs_keep_the_latest_issue():
    rows = [
        row("2023-05-18T09:40:15.083904", 20, "a"),
        row("2023-05-18T09:40:15.080448", 10, "b"),
        row("2023-05-18T12:00:00.000000", 31, "c"),
        row("2023-05-18T12:00:00.000000", 30, "d"),
        row("2023-05-18T12:01:00.000000", 40, "e"),
    ]
    kept, stats = dedupe_gp_rows(rows)
    assert [r["MEAN_MOTION"] for r in kept] == ["a", "c", "e"]
    assert stats == {"rows": 5, "exact_epoch_repeats_dropped": 1, "near_epoch_reissues_dropped": 1,
                     "element_sets_kept": 3}


def test_latest_issue_wins_over_later_epoch_under_60_s(tmp_path):
    base = {"NORAD_CAT_ID": "25544", "ECCENTRICITY": "0.0003", "INCLINATION": "51.6",
            "RA_OF_ASC_NODE": "10", "ARG_OF_PERICENTER": "20", "MEAN_ANOMALY": "30", "BSTAR": "0.0001",
            "MEAN_MOTION_DOT": "0", "MEAN_MOTION_DDOT": "0", "OBJECT_NAME": "ISS"}
    rows = [{**base, "EPOCH": "2022-01-13T04:19:37.000000", "GP_ID": "200", "MEAN_MOTION": "15.50"},
            {**base, "EPOCH": "2022-01-13T04:20:35.000000", "GP_ID": "100", "MEAN_MOTION": "15.51"}]
    (tmp_path / "gp.json").write_text(json.dumps(rows), encoding="utf-8")
    series, stats = load_gp_history(tmp_path / "gp.json")
    assert series.epochs.tolist() == [np.datetime64("2022-01-13T04:19:37", "us").item()]
    assert series.mean_motion.tolist() == [15.50]
    assert stats["near_epoch_reissues_dropped"] == 1
    assert load_series(tmp_path / "gp.json").epochs.tolist() == series.epochs.tolist()


def test_rows_without_gp_id_are_refused():
    with pytest.raises(ValueError):
        dedupe_gp_rows([{"EPOCH": "2023-01-01T00:00:00"}])


def test_leave_one_year_out_folds():
    folds = loyo_folds((2021, 2022, 2023))
    assert folds == [((2022, 2023), 2021), ((2021, 2023), 2022), ((2021, 2022), 2023)]


def test_period_masks_follow_event_date_and_detection_start():
    t = np.datetime64("2023-12-31T23:00", "us")
    events = [Event("2023-12-31", "", "reboost", "", t, t + np.timedelta64(2, "D")),
              Event("2024-01-01", "", "reboost", "", t, t)]
    dets = [Detection(t, t + np.timedelta64(2, "h"), 500.0, 20.0)]
    assert period_masks(events, dets, (2024,)) == ([False, True], [False])
    assert period_masks(events, dets, (2023,)) == ([True, False], [True])


def test_fold_tuning_never_matches_across_years():
    t0 = np.datetime64("2021-12-01T00:00", "us")
    n = 250
    epochs = t0 + np.arange(n) * np.timedelta64(288, "m")
    days = (epochs - t0).astype("int64") / 86_400e6
    a_m = 6_790_000.0 - 80.0 * days + np.random.default_rng(5).normal(0, 3.0, n)
    s1, s2 = np.datetime64("2021-12-15T10:00", "us"), np.datetime64("2021-12-31T22:00", "us")
    a_m[epochs > s1] += 1000.0
    a_m[epochs > s2] += 1000.0
    z = np.zeros(n)
    series = ElementSeries(25544, epochs, a_m / 1000.0, z, z, z, z, z)
    held_out = np.datetime64("2022-01-01T01:00", "us")
    events = [Event("2021-12-15", "10:00", "reboost", "", s1, s1),
              Event("2022-01-01", "01:00", "reboost", "", held_out, held_out)]
    st = Scored(series, events)
    _, d = st.score({"k": 4, "z_min": 12, "step_min_m": 200}, (2021,))
    assert [x.start.astype("datetime64[D]") for x in d["dets"]] == [np.datetime64("2021-12-15"),
                                                                     np.datetime64("2021-12-31")]
    assert st.choose((2021,))["f1"] == round(2 / 3, 4)
