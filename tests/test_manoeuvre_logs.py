from datetime import date, datetime

import pytest

from orbit_watch.manoeuvre_logs import (Source, delta_a_m, parse_fengyun, parse_ids,
                                        parse_ids_line, parse_qzss)

# Rows copied verbatim from the IDS files (cs2man.txt, sp5man.txt, ja3man.txt).
CS2_TWO_BURNS = "CRYO2 2010 123 17 55 2010 124 00 35     006 2 2010 123 17 56 05.000 01.2000000000000e+02 06.5371154400000e-09 -1.1612185775596e-02 02.7189757200000e-18 05.4475962000000e-05 -9.6768214796631e+01 02.2658131000000e-14 00.0000000000000e+00 00.0000000000000e+00 00.0000000000000e+00 2010 124 00 32 47.000 03.0000000000000e+02 01.6343265300000e-08 -2.8076256438533e-02 06.7339119000000e-18 05.4477551000000e-05 -9.3587521461777e+01 02.2446373000000e-14 00.0000000000000e+00 00.0000000000000e+00 00.0000000000000e+00"
SP5_TYPE_005 = "SPOT5 2002 127 14 15 2002 127 16 00 MCC 005 2 2002 127 14 31 26.000 03.7850000000000e+02 00.0000000000000e+00 03.1845800000000e+00 00.0000000000000e+00 00.0000000000000e+00 08.4136856010568e+03 00.0000000000000e+00 00.0000000000000e+00 00.0000000000000e+00 00.0000000000000e+00 2002 127 15 22 54.000 04.1390000000000e+02 00.0000000000000e+00 03.3165800000000e+00 00.0000000000000e+00 00.0000000000000e+00 08.0129983087702e+03 00.0000000000000e+00 00.0000000000000e+00 00.0000000000000e+00 00.0000000000000e+00"
JA3_LAST = "JASO3 2026 295 23 07 2026 295 23 08     007 1 2026 295 23 07 24.321 03.6250000000000e+00 -0.0000000000000e+00 05.7300000000000e-03 00.0000000000000e+00 -0.0000000000000e+00 01.5806896551724e+03 00.0000000000000e+00 00.0000000000000e+00 00.0000000000000e+00 00.0000000000000e+00"

# Excerpt copied verbatim from ohi-qzs6.txt (Cabinet Office QZSS Operational History Information).
QZS6 = """#+SATELLITE/MANEUVER
#DATE TIME START(UTC),END(UTC),DURATION,NS/EW,DVX(m/s),DVY(m/s),DVZ(m/s)
2025-10-27 14:59:53,2025-10-27 15:00:06,00:00:13,EW,-0.056,0.0,0.001
2025-11-17 06:28:44,2025-11-17 06:32:09,00:03:25,NS-1,0.005,-3.413,0.077
2025-11-17 07:36:08,2025-11-17 07:39:33,00:03:25,NS-2,0.001,-3.413,0.081
2025-11-18 11:59:49,2025-11-18 12:00:10,00:00:21,EW,-0.082,0.0,0.002
#-SATELLITE/MANEUVER
"""


def test_ids_two_burn_row_sums_along_track():
    r = parse_ids_line(CS2_TWO_BURNS)
    assert r.start == datetime(2010, 5, 3, 17, 55) and r.end == datetime(2010, 5, 4, 0, 35)
    assert r.burn_times == (datetime(2010, 5, 3, 17, 56, 5), datetime(2010, 5, 4, 0, 32, 47))
    assert r.dv_along == pytest.approx(-1.1612185775596e-02 - 2.8076256438533e-02)
    assert abs(r.dv_cross) < 1e-16


def test_ids_spot_axes_are_pitch_roll_yaw():
    r = parse_ids_line(SP5_TYPE_005)  # 005: T (cross), R (along), L (radial); maneuver type MCC
    assert r.satellite_code == "SPOT5"
    assert r.dv_along == pytest.approx(3.18458 + 3.31658)
    assert r.dv_cross == 0 and r.dv_radial == 0


def test_ids_drops_rows_on_or_after_revision_and_duplicates():
    src = Source("ja3man.txt", "Jason-3", 41240, date(2026, 10, 22), 7714.4)
    text = "\n".join([CS2_TWO_BURNS, CS2_TWO_BURNS, JA3_LAST]) + "\n"
    rows, dropped = parse_ids(text, src)
    assert dropped == {"duplicate_rows": 1, "on_or_after_revision": 1, "kept": 1, "source_rows": 3}
    assert rows[0]["start_utc"] == "2010-05-03T17:55:00Z"
    assert rows[0]["kind"] == "along-track" and rows[0]["delta_a_est_m"] < 0


def test_ids_rejects_wrong_burn_count():
    with pytest.raises(ValueError):
        parse_ids_line(JA3_LAST[:-30])


def test_qzss_pairs_ns_burns_and_estimates_from_dvx():
    src = Source("ohi-qzs6.txt", "QZS-6", 62876, date(2026, 11, 4), 42165.9)
    rows, dropped = parse_qzss(QZS6, src)
    assert dropped["kept"] == 4
    assert [r["event_group"] for r in rows] == ["QZS-6-001", "QZS-6-002", "QZS-6-002", "QZS-6-004"]
    assert [r["kind"] for r in rows] == ["EW", "NS", "NS", "EW"]
    assert rows[0]["start_utc"] == "2025-10-27T14:59:53Z"
    assert rows[0]["delta_a_est_m"] == pytest.approx(delta_a_m(-0.056, 42165.9), abs=0.1)


# Excerpt copied verbatim from ohi-qzs1r.txt (IGSO layout: no NS/EW column).
QZS1R = """#+SATELLITE/MANEUVER
#DATE TIME START(UTC),END(UTC),DURATION,DVX(m/s),DVY(m/s),DVZ(m/s)
2022-02-08 12:56:36,2022-02-08 13:01:27,00:04:51,-4.666,-0.087,-0.028
2022-02-08 20:26:52,2022-02-08 20:31:12,00:04:20,4.376,0.111,-0.03
#-SATELLITE/MANEUVER
"""

# Lines 13-15 of manFY4A.txt.fy (dpshorten/TLE_observation_benchmark_dataset), verbatim and in
# file order, which is newest first.
FY4A = """GEO-NS-STATION-KEEPING 2016-077A "2021-03-18T18:00:00 CST" "2021-03-18T23:00:00 CST"
GEO-EW-STATION-KEEPING 2016-077A "2021-03-11T17:16:00 CST" "2021-03-11T17:44:00 CST"
GEO-EW-STATION-KEEPING 2016-077A "2021-02-09T17:16:00 CST" "2021-02-09T17:44:00 CST"
"""

# Lines 32-33 of manFY2F.txt.fy, verbatim: the one line the source repeats.
FY2F_REPEATED = """GEO-EW-STATION-KEEPING 2012-002A "2017-09-05T16:30:00 CST" "2017-09-05T17:30:00 CST"
GEO-EW-STATION-KEEPING 2012-002A "2017-09-05T16:30:00 CST" "2017-09-05T17:30:00 CST"
"""

FY4A_SRC = Source("manFY4A.txt.fy", "Fengyun-4A", 41882, date(2022, 11, 22), 0.0, "2016-077A")


def test_qzss_igso_layout_has_no_ns_ew():
    src = Source("ohi-qzs1r.txt", "QZS-1R", 49336, date(2026, 11, 4), 42165.1)
    rows, dropped = parse_qzss(QZS1R.replace("\n", "\r\n"), src)  # the files are CRLF
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
    assert first["start_utc"] == "2021-02-09T09:16:00Z"  # 17:16 read as UTC+8
    assert first["end_utc"] == "2021-02-09T17:44:00Z"  # 17:44 read as UTC
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
    # 0.1 m/s along-track at GEO (n = 7.29e-5 rad/s) is about 2.74 km.
    assert delta_a_m(0.1, 42164.0) == pytest.approx(2742, rel=1e-3)
