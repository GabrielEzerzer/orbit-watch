import csv
import json
import shutil
from datetime import date, datetime, timedelta, timezone

import pytest

from harness.evals import mode_events as me
from orbit_watch.modes import Segment
from orbit_watch.truth import GROUNDTRUTH

T0 = datetime(2022, 1, 1, tzinfo=timezone.utc)
N = 1000


def seg(mode, start_day, end_day, lon=(10.0, 10.2), norad=N):
    return Segment(norad, T0 + timedelta(days=start_day), T0 + timedelta(days=end_day), mode, 1, 10,
                   lon[0], lon[1], 0.0, 0.0, 0.1)


def ev(event_type, day, norad=N, split="dev"):
    d = (T0 + timedelta(days=day)).date()
    return me.Event(f"{norad}-{event_type}-{d}", norad, event_type, d, split)


def run(events, segs, geo=None, holdout=frozenset()):
    return me.score(events, {N: segs}, {N} if geo is None else geo, set(holdout))


def one(event_type, segs, day=100):
    (r,) = run([ev(event_type, day)], segs)
    return r


@pytest.mark.parametrize("event_type,before,after,caught", [
    ("relocation_start", "controlled_lon_inc", "drifting", True),
    ("relocation_start", "controlled_lon", "out_of_region", True),
    ("relocation_start", "drifting", "controlled_lon", False),
    ("relocation_end", "drifting", "controlled_lon_inc", True),
    ("relocation_end", "out_of_region", "controlled_lon", True),
    ("relocation_end", "controlled_lon", "drifting", False),
    ("graveyard", "controlled_lon_inc", "librating_75E", True),
    ("graveyard", "controlled_lon", "out_of_region", True),
    ("graveyard", "drifting", "out_of_region", False),
    ("keeping_stop", "controlled_lon_inc", "librating_both", True),
    ("keeping_stop", "controlled_lon", "out_of_region", False),
    ("ns_keeping_stop", "controlled_lon_inc", "controlled_lon", True),
    ("ns_keeping_stop", "controlled_lon_inc", "drifting", False),
])
def test_each_event_type_accepts_only_its_mode_changes(event_type, before, after, caught):
    r = one(event_type, [seg(before, 0, 100, lon=(10, 10.2)), seg(after, 100, 300, lon=(10, 10.2))])
    assert (r.status == "caught") is caught


def test_held_to_held_with_disjoint_longitudes_is_a_jump_for_relocations_only():
    jump = [seg("controlled_lon", 0, 100, lon=(10, 10.2)), seg("controlled_lon", 100, 300, lon=(30, 30.2))]
    stay = [seg("controlled_lon", 0, 100, lon=(10, 10.2)), seg("controlled_lon_inc", 100, 300, lon=(10.1, 10.3))]
    assert one("relocation_start", jump).status == "caught"
    assert one("relocation_end", jump).status == "caught"
    assert one("graveyard", jump).status == "missed"
    assert one("relocation_start", stay).status == "missed"


def test_jump_reads_longitude_arcs_across_the_dateline():
    across = [seg("controlled_lon", 0, 100, lon=(179.9, -179.9)), seg("controlled_lon", 100, 300, lon=(-179.95, -179.8))]
    assert one("relocation_start", across).status == "missed"
    apart = [seg("controlled_lon", 0, 100, lon=(179.9, -179.9)), seg("controlled_lon", 100, 300, lon=(170, 170.2))]
    assert one("relocation_start", apart).status == "caught"


def test_window_is_45_days_inclusive_and_error_is_transition_minus_event():
    segs = [seg("controlled_lon_inc", 0, 100), seg("drifting", 100, 300)]
    assert one("keeping_stop", segs, day=55).error_days == 45
    assert one("keeping_stop", segs, day=145).error_days == -45
    assert one("keeping_stop", segs, day=54).status == "missed"
    assert one("keeping_stop", segs, day=146).status == "missed"


def test_matches_are_one_to_one_closest_first():
    segs = [seg("controlled_lon_inc", 0, 100), seg("drifting", 100, 300)]
    near, far = ev("keeping_stop", 105), ev("graveyard", 90)
    r_far, r_near = run([far, near], segs)
    assert (r_near.status, r_near.error_days) == ("caught", -5)
    assert r_far.status == "missed"


def test_one_to_one_assignment_lets_each_event_take_its_own_transition():
    segs = [seg("controlled_lon_inc", 0, 100), seg("drifting", 100, 130),
            seg("controlled_lon_inc", 130, 150), seg("drifting", 150, 300)]
    a, b = run([ev("keeping_stop", 110), ev("keeping_stop", 115)], segs)
    assert (a.error_days, b.error_days) == (-10, 35)


def test_undetermined_segments_are_skipped_and_the_change_dates_at_the_next_start():
    segs = [seg("controlled_lon_inc", 0, 100), seg("undetermined", 100, 130), seg("drifting", 130, 300)]
    r = one("keeping_stop", segs, day=120)
    assert (r.status, r.transition.label, r.error_days) == ("caught", "controlled_lon_inc->drifting", 10)


def test_unscored_reasons():
    segs = [seg("controlled_lon_inc", 0, 100), seg("drifting", 100, 300)]
    held_out, other = ev("keeping_stop", 100, norad=7), ev("keeping_stop", 100, norad=8)
    early = me.Event("x", N, "keeping_stop", date(2020, 12, 31), "dev")
    late = me.Event("y", N, "keeping_stop", date(2026, 1, 1), "dev")
    edge = me.Event("z", N, "keeping_stop", date(2021, 1, 1), "dev")
    rs = me.score([held_out, other, early, late, edge], {N: segs, 7: segs}, {N, 7}, {7})
    assert [r.status for r in rs] == ["holdout", "not_in_geo_set", "outside_period", "outside_period", "missed"]


def test_summary_counts_recall_and_error_percentiles():
    segs = [seg("controlled_lon_inc", 0, 100), seg("drifting", 100, 200), seg("controlled_lon", 200, 300)]
    rs = run([ev("keeping_stop", 96), ev("relocation_end", 210, split="test"), ev("graveyard", 290),
              ev("graveyard", 100, norad=9)], segs)
    s = me.summarise(rs)
    assert (s["dev"]["events"], s["dev"]["scored"], s["dev"]["caught"], s["dev"]["recall"]) == (3, 2, 1, 0.5)
    assert s["overall"]["median_abs_error_days"] == 7.0
    assert s["overall"]["p90_abs_error_days"] == pytest.approx(9.4)
    assert s["test"]["by_event_type"]["relocation_end"]["caught"] == 1
    assert s["unscored"] == [{"event_id": rs[3].event.event_id, "reason": "not_in_geo_set"}]


def test_timeline_lists_determined_modes_near_the_event():
    segs = [seg("controlled_lon_inc", 0, 100), seg("undetermined", 100, 130), seg("drifting", 130, 400),
            seg("controlled_lon", 400, 500)]
    assert me.timeline(segs, (T0 + timedelta(days=60)).date()) == (
        "controlled_lon_inc 2022-01-01..2022-04-11 | drifting 2022-05-11..")


def test_month_dates_score_as_the_15th_and_bad_dates_fail():
    assert me.event_date("2023-05", "month") == date(2023, 5, 15)
    with pytest.raises(ValueError):
        me.event_date("2023-05", "day")


def test_row_problems_catch_each_rule():
    good = {"event_id": "1-graveyard-2022-01-02", "norad_id": "1", "event_type": "graveyard",
            "date": "2022-01-02", "date_precision": "day"}
    good["split"] = me.split_of(good["event_id"])
    assert me.row_problems([good]) == []
    for change in ({"event_type": "retired"}, {"date_precision": "year"}, {"event_id": "1-graveyard-2022-01-03"},
                   {"split": "test" if good["split"] == "dev" else "dev"}, {"date": "2022-01"}):
        assert me.row_problems([{**good, **change}]), change
    assert me.row_problems([good, good])


def event_files(mock_dir):
    files = [mock_dir / "geo_events" / "geo_events.csv"]
    return files + [p for p in [GROUNDTRUTH / "geo_events.csv"] if p.is_file()]


def test_event_files_follow_the_id_split_type_and_precision_rules(mock_dir):
    for path in event_files(mock_dir):
        with open(path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == me.FIELDS, path
            assert me.row_problems(list(reader)) == [], path
        assert me.load_events(path)


def test_main_writes_summary_and_events_from_the_current_mode_code(mock_dir, tmp_path):
    geo = tmp_path / "geo"
    geo.mkdir()
    shutil.copy(mock_dir / "geo" / "37344_every_2_days.tle", geo / "37344.tle")
    eid = "37344-keeping_stop-2023-06-01"
    events = tmp_path / "events.csv"
    events.write_text(",".join(me.FIELDS) + "\n" + f"{eid},37344,x,keeping_stop,2023-06-01,day,,,u,q,{me.split_of(eid)}\n"
                      + "4-graveyard-2023-06,4,x,graveyard,2023-06,month,,,u,q," + me.split_of("4-graveyard-2023-06") + "\n",
                      encoding="utf-8")
    out = tmp_path / "out"
    assert me.main(["--events", str(events), "--geo-dir", str(geo), "--out", str(out)]) == 0
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["overall"]["scored"] == 1 and summary["overall"]["caught"] == 0
    rows = list(csv.DictReader(open(out / "events.csv", encoding="utf-8")))
    assert [r["status"] for r in rows] == ["missed", "not_in_geo_set"]
    assert rows[0]["timeline"] == "librating_both .."
