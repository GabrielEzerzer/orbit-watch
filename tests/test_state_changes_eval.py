from datetime import datetime, timedelta, timezone

import pytest

from harness.evals import state_changes as sc
from harness.evals.mode_events import Event
from orbit_watch.events import Event as Found

T0 = datetime(2022, 1, 1, tzinfo=timezone.utc)
N = 1000


def found(kind, day, norad=N):
    t = T0 + timedelta(days=day)
    return Found(norad, kind, t, "test", 0.0, 10.0, 20.0, "controlled_lon", "drifting", t)


def ev(kind, day, norad=N, split="dev"):
    d = (T0 + timedelta(days=day)).date()
    return Event(f"{norad}-{kind}-{d}", norad, kind, d, split)


def run(events, founds):
    return sc.score(events, {N: founds}, {N}, set())


@pytest.mark.parametrize("truth,emitted,caught", [
    ("relocation_start", "relocation_start", True),
    ("relocation_start", "graveyard", True),
    ("graveyard", "keeping_stop", True),
    ("keeping_stop", "relocation_start", True),
    ("relocation_end", "relocation_start", False),
    ("relocation_start", "relocation_end", False),
    ("ns_keeping_stop", "ns_keeping_stop", True),
    ("ns_keeping_stop", "keeping_stop", False),
    ("graveyard", "free_burn", False),
])
def test_type_families_follow_rung_one(truth, emitted, caught):
    (r,) = run([ev(truth, 100)], [found(emitted, 103)])
    assert (r.status == "caught") is caught


def test_matching_is_one_to_one_closest_first_within_45_days():
    rs = run([ev("relocation_start", 100), ev("relocation_start", 110)], [found("relocation_start", 108)])
    assert [r.status for r in rs] == ["missed", "caught"] and rs[1].error_days == -2
    (r,) = run([ev("graveyard", 100)], [found("graveyard", 146)])
    assert r.status == "missed"
    (r,) = run([ev("graveyard", 100)], [found("graveyard", 55)])
    assert r.error_days == -45


def test_stats_count_exact_type_agreement():
    rs = run([ev("graveyard", 100), ev("relocation_end", 300)], [found("relocation_start", 101), found("relocation_end", 300)])
    s = sc._stats(rs)
    assert (s["caught"], s["same_type"], s["median_abs_error_days"]) == (2, 1, 0.5)


def test_false_events_count_every_event_inside_the_log_spans_per_object_year():
    lo, hi = T0, T0 + timedelta(days=365.25 * 2)
    mid = T0 + timedelta(days=365.25)
    founds = {42917: [found("relocation_start", 10, 42917), found("free_burn", 800, 42917)],
              62876: [found("keeping_stop", 400, 62876)]}
    stations = [sc.Station(42917, "QZS-3", ((lo, hi),)),
                sc.Station(62876, "QZS-6", ((lo, mid), (mid + timedelta(days=60), hi)), ((mid, mid + timedelta(days=60)),))]
    fe = sc.false_events(founds, stations)
    assert fe["objects"]["QZS-6"]["false_events"] == 0
    assert fe["false_events"] == 1 and fe["object_years"] == pytest.approx(4.0 - 60 / 365.25, abs=1e-3)
    assert fe["status"] == "FAIL" and fe["objects"]["QZS-6"]["excluded"] == [["2023-01-01", "2023-03-02"]]


def _log(tmp_path, rows):
    path = tmp_path / "log.csv"
    lines = ["norad_id,start_utc,end_utc,kind"] + [f"43491,{a},{b},{k}" for a, b, k in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def test_station_spans_run_from_the_first_to_the_last_log_row_and_drop_breaks_in_the_keeping_cadence(tmp_path):
    rows = [("2020-12-20T00:00:00Z", "2020-12-20T10:00:00Z", "NS")]
    day = datetime(2021, 1, 1, tzinfo=timezone.utc)
    for gap in (0, 30, 30, 30, 120, 30):
        day += timedelta(days=gap)
        rows.append((day.strftime("%Y-%m-%dT%H:%M:%SZ"), (day + timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%SZ"), "EW"))
    spans, excluded = sc.station_spans(_log(tmp_path, rows), 43491)
    assert spans[0][0] == datetime(2020, 12, 20, tzinfo=timezone.utc)
    assert spans[-1][1] == datetime(2021, 8, 29, 8, tzinfo=timezone.utc)
    assert excluded == [(datetime(2021, 4, 1, 8, tzinfo=timezone.utc), datetime(2021, 7, 30, tzinfo=timezone.utc))]
    assert [s[1] for s in spans[:-1]] == [e[0] for e in excluded]


def test_kept_station_clips_the_log_spans_to_the_element_sets_and_the_period(tmp_path):
    rows = [("2020-06-01T00:00:00Z", "2020-06-01T08:00:00Z", "EW"), ("2021-06-01T00:00:00Z", "2021-06-01T08:00:00Z", "EW")]

    class Rec:
        def __init__(self, t):
            self.epoch = t
    recs = [Rec(datetime(2020, 1, 1, tzinfo=timezone.utc)), Rec(datetime(2021, 3, 1, tzinfo=timezone.utc))]
    st = sc.kept_station(43491, "Fengyun-2H", _log(tmp_path, rows), recs)
    assert st.spans == ((datetime(2021, 1, 1, tzinfo=timezone.utc), datetime(2021, 3, 1, tzinfo=timezone.utc)),)


def test_the_final_path_runs_the_same_event_code(mock_dir):
    from orbit_watch.events import burns, state_changes
    recs = sc.object_records(mock_dir / "geo" / "37344_every_2_days.tle")
    days, steps = sc.final_burns(recs)
    want_days, want_steps = burns(recs)
    assert days.tolist() == want_days.tolist() and steps.tolist() == want_steps.tolist()
    assert sc.final_state_changes(recs) == state_changes(recs)

