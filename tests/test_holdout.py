import numpy as np
import pytest

from orbit_watch.calibrate import Event
from orbit_watch.detect import Detection
from orbit_watch.holdout import dedupe_gp_rows, loyo_folds, period_masks


def row(epoch, gp_id, mm="15.5"):
    return {"EPOCH": epoch, "GP_ID": str(gp_id), "MEAN_MOTION": mm}


def test_restated_epochs_keep_the_latest_issue():
    rows = [
        row("2023-05-18T09:40:15.083904", 20, "a"),  # reissue a few ms off, issued later
        row("2023-05-18T09:40:15.080448", 10, "b"),
        row("2023-05-18T12:00:00.000000", 31, "c"),  # exact repeat of one epoch
        row("2023-05-18T12:00:00.000000", 30, "d"),
        row("2023-05-18T12:00:10.500000", 40, "e"),  # 10.5 s later: a distinct element set
    ]
    kept, stats = dedupe_gp_rows(rows)
    assert [r["MEAN_MOTION"] for r in kept] == ["a", "c", "e"]
    assert stats == {"rows": 5, "exact_epoch_repeats_dropped": 1, "near_epoch_reissues_dropped": 1,
                     "element_sets_kept": 3}


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
    dets = [Detection(t, t + np.timedelta64(2, "h"), 500.0, 20.0)]  # starts 2023, ends 2024
    assert period_masks(events, dets, (2024,)) == ([False, True], [False])
    assert period_masks(events, dets, (2023,)) == ([True, False], [True])
