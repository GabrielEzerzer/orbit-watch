import numpy as np

from orbit_watch import calibrate
from orbit_watch.detect import Detection, GapScores
from orbit_watch.generalise import (LogEvent, covered, drop_near_duplicates, load_log_events,
                                    match_near, split_date)
from orbit_watch.series import ElementSeries


def ev(lo, hi, sign=0, da=500.0, eid="e"):
    return LogEvent(eid, "along-track", da, sign, np.datetime64(lo, "us"), np.datetime64(hi, "us"))


def det(start, end, step):
    return Detection(np.datetime64(start, "us"), np.datetime64(end, "us"), step, 20.0)


def test_sign_is_enforced_only_when_known():
    t = ("2024-01-10T12:00", "2024-01-10T12:05")
    down = [det("2024-01-10T10:00", "2024-01-10T14:00", -300.0)]
    assert match_near([ev(*t, sign=1)], down) == {}
    assert match_near([ev(*t, sign=-1)], down) == {0: 0}
    assert match_near([ev(*t, sign=0)], down) == {0: 0}


def test_match_near_keeps_original_indices():
    events = [ev("2024-03-01T00:00", "2024-03-01T00:10")]
    dets = [det("2024-01-01T00:00", "2024-01-01T06:00", 300.0),
            det("2024-02-29T20:00", "2024-03-01T04:00", 300.0)]
    assert match_near(events, dets) == {0: 1}


def test_late_tolerance_only_widens_after_the_burn():
    e = [ev("2024-03-01T00:00", "2024-03-01T00:10")]
    late = [det("2024-03-02T12:00", "2024-03-02T20:00", 300.0)]  # starts 1.5 days after
    early = [det("2024-02-27T12:00", "2024-02-28T00:00", 300.0)]  # ends 1 day before
    assert match_near(e, late) == {}
    assert match_near(e, late, late_days=2.0) == {0: 0}
    assert match_near(e, early, late_days=2.0) == {}


def test_delta_a_bins():
    assert ev("2024-01-01", "2024-01-01", da=-49.9).bin == "<50 m"
    assert ev("2024-01-01", "2024-01-01", da=200.0).bin == "200-500 m"
    assert ev("2024-01-01", "2024-01-01", da=-3200.0).bin == "2-5 km"
    assert ev("2024-01-01", "2024-01-01", da=12600.0).bin == ">5 km"


def test_split_is_month_start_of_the_quantile_event():
    events = [ev(f"2024-{m:02d}-15", f"2024-{m:02d}-15") for m in range(1, 11)]
    assert split_date(events) == np.datetime64("2024-06-01", "us")  # 6th of 10 events


def test_match_and_cover_agree_with_calibrate():
    rng = np.random.default_rng(7)
    base = np.datetime64("2024-01-01T00:00", "us")
    hour = np.timedelta64(3600_000_000, "us")
    events = [ev(base + int(h) * hour, base + int(h) * hour + 2 * hour, sign=int(sg), eid=str(i))
              for i, (h, sg) in enumerate(zip(rng.integers(0, 2000, 60), rng.integers(-1, 2, 60)))]
    t = base + np.sort(rng.integers(0, 2100, 300)) * hour
    t = np.unique(t)
    dets = [det(t[i], t[i + 1], float(rng.normal(0, 300))) for i in range(0, len(t) - 1, 3)]
    assert match_near(events, dets) == calibrate.match(events, dets)
    valid = rng.random(len(t) - 1) > 0.3
    z = np.where(valid, 1.0, np.nan)
    scores = GapScores(t[:-1], t[1:], z, z, z)
    assert covered(events, scores) == calibrate.covered(events, scores)


def test_burn_and_counter_burn_merge_into_one_event(tmp_path):
    p = tmp_path / "s.csv"
    p.write_text(
        "event_id,satellite,norad_id,start_utc,end_utc,n_burns,burn_times_utc,dv_radial_m_s,"
        "dv_along_m_s,dv_cross_m_s,kind,delta_a_est_m,source_file,source_revision,source_url\n"
        "S-1,S,54754,2025-06-20T11:57:00Z,2025-06-20T11:58:00Z,1,a,0,0.1,0,along-track,364.1,f,r,u\n"
        "S-2,S,54754,2025-06-20T16:14:00Z,2025-06-20T16:15:00Z,1,a,0,-0.1,0,along-track,-346.2,f,r,u\n"
        "S-3,S,54754,2025-06-21T16:14:00Z,2025-06-21T16:15:00Z,1,a,0,0.01,0,along-track,30.0,f,r,u\n",
        encoding="utf-8")
    e = load_log_events(p, 54754)
    assert [(x.event_id, x.n_rows, x.delta_a_est_m, x.expected_sign) for x in e] == [
        ("S-1+S-2", 2, 17.9, 0), ("S-3", 1, 30.0, 1)]


def test_qzss_ns_pair_is_one_event_with_either_sign(tmp_path):
    p = tmp_path / "q.csv"
    p.write_text(
        "event_id,event_group,satellite,norad_id,start_utc,end_utc,duration,ns_ew,dvx_m_s,dvy_m_s,"
        "dvz_m_s,kind,delta_a_est_m,source_file,source_revision,source_url\n"
        "Q-1,Q-1,Q,62876,2025-11-17T06:28:44Z,2025-11-17T06:32:09Z,00:03:25,NS-1,0.005,-3.413,0.077,NS,137.1,f,r,u\n"
        "Q-2,Q-1,Q,62876,2025-11-17T07:36:08Z,2025-11-17T07:39:33Z,00:03:25,NS-2,0.001,-3.413,0.081,NS,27.4,f,r,u\n"
        "Q-3,Q-3,Q,62876,2025-11-18T11:59:49Z,2025-11-18T12:00:10Z,00:00:21,EW,-0.082,0.0,0.002,EW,-2248.6,f,r,u\n",
        encoding="utf-8")
    e = load_log_events(p, 62876)
    assert [(x.event_id, x.kind, x.delta_a_est_m, x.expected_sign) for x in e] == [
        ("Q-1+Q-2", "NS", 164.5, 0), ("Q-3", "EW", -2248.6, 0)]
    assert e[0].lo == np.datetime64("2025-11-17T06:28:44", "us")
    assert e[0].hi == np.datetime64("2025-11-17T07:39:33", "us")


def test_ids_along_track_sign_follows_delta_v(tmp_path):
    p = tmp_path / "i.csv"
    p.write_text(
        "event_id,satellite,norad_id,start_utc,end_utc,n_burns,burn_times_utc,dv_radial_m_s,"
        "dv_along_m_s,dv_cross_m_s,kind,delta_a_est_m,source_file,source_revision,source_url\n"
        "C-1,C,36508,2010-05-03T17:55:00Z,2010-05-04T00:35:00Z,2,a;b,0,-0.0396884,0,along-track,-75.1,f,r,u\n"
        "C-2,C,36508,2010-06-03T17:55:00Z,2010-06-03T18:35:00Z,1,a,0,0.001,0.02,cross-track,1.9,f,r,u\n",
        encoding="utf-8")
    assert [x.expected_sign for x in load_log_events(p, 36508)] == [-1, 0]


def test_near_duplicate_epochs_keep_the_later_set():
    t = np.array(["2024-01-01T00:00:00", "2024-01-01T00:00:00.4", "2024-01-01T08:00:00",
                  "2024-01-01T08:00:59", "2024-01-01T16:00:00"], dtype="datetime64[us]")
    a = np.array([7000.0, 7000.1, 7000.2, 7000.3, 7000.4])
    s = ElementSeries(1, t, a, a, a, a, a, a)
    out = drop_near_duplicates(s)
    assert list(out.semi_major_axis_km) == [7000.1, 7000.3, 7000.4]
    assert len(out.epochs) == len(out.bstar) == 3
