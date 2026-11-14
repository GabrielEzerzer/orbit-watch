import numpy as np

from orbit_watch.calibrate import Event, load_events, match
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
