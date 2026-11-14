from datetime import date, datetime

import pytest

from orbit_watch.manoeuvre_logs import Source, delta_a_m, parse_ids, parse_ids_line, parse_qzss

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


def test_delta_a_gauss_at_geo():
    # 0.1 m/s along-track at GEO (n = 7.29e-5 rad/s) is about 2.74 km.
    assert delta_a_m(0.1, 42164.0) == pytest.approx(2742, rel=1e-3)
