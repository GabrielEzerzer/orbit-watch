from datetime import date, datetime

import pytest

from orbit_watch.manoeuvre_logs import Source, delta_a_m, parse_fengyun, parse_qzss

QZS6 = """#+SATELLITE/MANEUVER
#DATE TIME START(UTC),END(UTC),DURATION,NS/EW,DVX(m/s),DVY(m/s),DVZ(m/s)
2025-10-27 14:59:53,2025-10-27 15:00:06,00:00:13,EW,-0.056,0.0,0.001
2025-11-17 06:28:44,2025-11-17 06:32:09,00:03:25,NS-1,0.005,-3.413,0.077
2025-11-17 07:36:08,2025-11-17 07:39:33,00:03:25,NS-2,0.001,-3.413,0.081
2025-11-18 11:59:49,2025-11-18 12:00:10,00:00:21,EW,-0.082,0.0,0.002
#-SATELLITE/MANEUVER
"""


def test_qzss_pairs_ns_burns_and_estimates_from_dvx():
    src = Source("ohi-qzs6.txt", "QZS-6", 62876, date(2026, 11, 4), 42165.9)
    rows, dropped = parse_qzss(QZS6, src)
    assert dropped["kept"] == 4
    assert [r["event_group"] for r in rows] == ["QZS-6-001", "QZS-6-002", "QZS-6-002", "QZS-6-004"]
    assert [r["kind"] for r in rows] == ["EW", "NS", "NS", "EW"]
    assert rows[0]["start_utc"] == "2025-10-27T14:59:53Z"
    assert rows[0]["delta_a_est_m"] == pytest.approx(delta_a_m(-0.056, 42165.9), abs=0.1)


QZS1R = """#+SATELLITE/MANEUVER
#DATE TIME START(UTC),END(UTC),DURATION,DVX(m/s),DVY(m/s),DVZ(m/s)
2022-02-08 12:56:36,2022-02-08 13:01:27,00:04:51,-4.666,-0.087,-0.028
2022-02-08 20:26:52,2022-02-08 20:31:12,00:04:20,4.376,0.111,-0.03
#-SATELLITE/MANEUVER
"""

FY4A = """GEO-NS-STATION-KEEPING 2016-077A "2021-03-18T18:00:00 CST" "2021-03-18T23:00:00 CST"
GEO-EW-STATION-KEEPING 2016-077A "2021-03-11T17:16:00 CST" "2021-03-11T17:44:00 CST"
GEO-EW-STATION-KEEPING 2016-077A "2021-02-09T17:16:00 CST" "2021-02-09T17:44:00 CST"
"""

FY2F_REPEATED = """GEO-EW-STATION-KEEPING 2012-002A "2017-09-05T16:30:00 CST" "2017-09-05T17:30:00 CST"
GEO-EW-STATION-KEEPING 2012-002A "2017-09-05T16:30:00 CST" "2017-09-05T17:30:00 CST"
"""

FY4A_SRC = Source("manFY4A.txt.fy", "Fengyun-4A", 41882, date(2022, 11, 22), 0.0, "2016-077A")


def test_qzss_igso_layout_has_no_ns_ew():
    src = Source("ohi-qzs1r.txt", "QZS-1R", 49336, date(2026, 11, 4), 42165.1)
    rows, dropped = parse_qzss(QZS1R.replace("\n", "\r\n"), src)
    assert dropped["kept"] == 2
    assert [(r["ns_ew"], r["kind"], r["event_group"]) for r in rows] == [
        ("", "unspecified", "QZS-1R-001"), ("", "unspecified", "QZS-1R-002")]
    assert rows[1]["dvx_m_s"] == "4.376" and rows[1]["end_utc"] == "2022-02-08T20:31:12Z"


def test_fengyun_window_covers_both_time_zone_readings_and_sorts():
    rows, dropped = parse_fengyun(FY4A, FY4A_SRC)
    assert dropped == {"duplicate_rows": 0, "kept": 3, "source_rows": 3}
    assert [r["kind"] for r in rows] == ["EW", "EW", "NS"]
    first = rows[0]
    assert first["event_id"] == "Fengyun-4A-001"
    assert first["start_utc"] == "2021-02-09T09:16:00Z"
    assert first["end_utc"] == "2021-02-09T17:44:00Z"
    assert first["source_start"] == "2021-02-09T17:16:00 CST"
    assert first["delta_a_est_m"] == ""
    assert FY4A_SRC.url.endswith("/raw_data/manoeuvres/manFY4A.txt.fy")


def test_fengyun_repeated_line_is_kept_once():
    src = Source("manFY2F.txt.fy", "Fengyun-2F", 38049, date(2022, 11, 22), 0.0, "2012-002A")
    rows, dropped = parse_fengyun(FY2F_REPEATED, src)
    assert dropped == {"duplicate_rows": 1, "kept": 1, "source_rows": 2}
    assert rows[0]["start_utc"] == "2017-09-05T08:30:00Z"


def test_fengyun_rejects_a_line_for_another_satellite():
    with pytest.raises(ValueError):
        parse_fengyun(FY4A.replace("2016-077A", "2018-050A", 1), FY4A_SRC)


def test_delta_a_gauss_at_geo():
    assert delta_a_m(0.1, 42164.0) == pytest.approx(2742, rel=1e-3), (
        "0.1 m/s along-track at GEO (n = 7.29e-5 rad/s) is about 2.74 km")
