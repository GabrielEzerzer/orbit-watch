import numpy as np

import pytest

from orbit_watch.calibrate import Event, load_events, load_truth, match
from orbit_watch.detect import Detection


def ev(lo, hi, type_="reboost"):
    return Event("2022-01-01", "", type_, "", np.datetime64(lo, "us"), np.datetime64(hi, "us"))


def det(start, end, step=500.0, z=10.0):
    return Detection(np.datetime64(start, "us"), np.datetime64(end, "us"), step, z)


def test_one_to_one_closest_first():
    events = [ev("2022-01-10T12:00", "2022-01-10T12:00"), ev("2022-01-11T00:00", "2022-01-11T00:00")]
    dets = [det("2022-01-10T10:00", "2022-01-10T14:00")]
    assert match(events, dets) == {0: 0}


def test_tolerance_widens_detection_interval():
    events = [ev("2022-01-10T12:00", "2022-01-10T12:00")]
    near = [det("2022-01-10T18:00", "2022-01-10T20:00")]  # 6 h after
    far = [det("2022-01-11T06:00", "2022-01-11T08:00")]  # 18 h after
    assert match(events, near, tol_days=0.5) == {0: 0}
    assert match(events, far, tol_days=0.5) == {}


def test_date_only_events_get_one_day_each_side(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text(
        "date_utc,time_utc,type,vehicle,delta_v_m_s,source_url,quote\n"
        "2022-01-12,,reboost,P,0.7,u,q\n"
        "2022-04-23,13:25,reboost (planned as PDAM),P,1.0,u,q\n"
        "2021-07-29,16:45,other (unplanned attitude/thruster event),N,,u,q\n"
        '2022-06-20,,"reboost (test burn, aborted after 5 s)",P,,u,q\n',
        encoding="utf-8",
    )
    e = load_events(p)
    assert e[0].lo == np.datetime64("2022-01-11T00:00", "us")
    assert e[0].hi == np.datetime64("2022-01-14T00:00", "us")
    assert e[1].lo == e[1].hi == np.datetime64("2022-04-23T13:25", "us")
    assert [x.category for x in e] == ["reboost", "reboost", "unplanned", "test/aborted burn"]


def test_step_sign_must_fit_the_burn():
    t = ("2022-01-10T12:00", "2022-01-10T12:00")
    down = [det("2022-01-10T10:00", "2022-01-10T14:00", step=-500.0)]
    up = [det("2022-01-10T10:00", "2022-01-10T14:00", step=500.0)]
    assert match([ev(*t, "reboost")], down) == {}
    assert match([ev(*t, "reboost")], up) == {0: 0}
    assert match([ev(*t, "debris avoidance (retrograde)")], up) == {}
    assert match([ev(*t, "debris avoidance")], down) == {0: 0}


NASA_HEADER = "date_utc,time_utc,type,vehicle,delta_v_m_s,source_url,quote\n"
ROSCOSMOS_HEADER = "date_utc,time_utc,type,vehicle,delta_v_m_s,source_url,quote,source_time_zone\n"


def test_truth_files_join_and_roscosmos_types_score_like_nasa_ones(tmp_path):
    nasa, ros = tmp_path / "nasa.csv", tmp_path / "ros.csv"
    nasa.write_text(NASA_HEADER + "2023-03-06,12:42,debris avoidance,P,,u,q\n"
                    "2021-12-03,07:58,debris avoidance (retrograde),P,,u,q\n", encoding="utf-8")
    ros.write_text(ROSCOSMOS_HEADER + "2021-12-24,01:18,deboost,Progress MS-18,,u,q,MSK (UTC+3)\n"
                   "2023-03-14,11:54,debris_avoidance,Progress MS-22,0.3,u,q,MSK (UTC+3)\n", encoding="utf-8")
    e = load_truth([nasa, ros])
    assert [x.date_utc for x in e] == ["2023-03-06", "2021-12-03", "2021-12-24", "2023-03-14"]
    assert e[3].lo == e[3].hi == np.datetime64("2023-03-14T11:54", "us")
    assert [x.category for x in e] == ["debris/collision avoidance", "debris/collision avoidance",
                                       "other burn", "debris/collision avoidance"]
    assert [x.expected_sign for x in e] == [0, -1, -1, 0]


def test_an_event_in_two_truth_files_is_refused(tmp_path):
    nasa, ros = tmp_path / "nasa.csv", tmp_path / "ros.csv"
    nasa.write_text(NASA_HEADER + "2024-11-13,,reboost,P,,u,q\n", encoding="utf-8")  # date only: 12th to 15th
    ros.write_text(ROSCOSMOS_HEADER + "2024-11-15,10:00,reboost,Progress MS-28,,u,q,MSK (UTC+3)\n", encoding="utf-8")
    with pytest.raises(ValueError, match="same event"):
        load_truth([nasa, ros])
    ros.write_text(ROSCOSMOS_HEADER + "2024-11-15,13:00,reboost,Progress MS-28,,u,q,MSK (UTC+3)\n", encoding="utf-8")
    assert len(load_truth([nasa, ros])) == 2  # 13 h after the window: more than half a day


def test_real_truth_files_share_no_event():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "groundtruth"
    e = load_truth([root / "iss_manoeuvres.csv", root / "iss_roscosmos_manoeuvres.csv"])
    assert len(e) == len(load_events(root / "iss_manoeuvres.csv")) + 14
