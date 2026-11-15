from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from orbit_watch import parse_tle
from orbit_watch.geo import drift_rate, gmst_deg, longitude_deg, wrap180

LUCH_L1 = "1 37951U 11074B   21001.58537451 -.00000034  00000-0  00000-0 0  9998"
LUCH_L2 = "2 37951   3.7193 109.4207 0001930 192.9377 176.7807  1.00273956 33212"


def test_gmst_matches_meeus_example_12a():
    assert gmst_deg(datetime(1987, 4, 10, tzinfo=timezone.utc)) == pytest.approx(197.693195, abs=1e-5)


def test_gmst_at_j2000_epoch():
    assert gmst_deg(datetime(2000, 1, 1, 12, tzinfo=timezone.utc)) == pytest.approx(280.46061837, abs=1e-6), (
        "IAU 1982 constant term: 67310.54841 s at 2000-01-01 12:00 UT1 is 280.46061837 deg")


def test_geo_longitude_stays_put_over_a_day():
    (rec,) = parse_tle(f"{LUCH_L1}\n{LUCH_L2}\n")
    lons = np.array([longitude_deg(rec, rec.epoch + timedelta(hours=h)) for h in range(0, 25, 3)])
    assert np.ptp(lons) < 0.2
    assert -180 <= lons.min() and lons.max() < 180


def test_drift_rate_unwraps_across_the_antimeridian():
    days = np.array([0.0, 1.0, 2.0, 3.0])
    lon = wrap180(np.array([178.0, 179.0, 180.0, 181.0]))
    assert drift_rate(days, lon) == pytest.approx(1.0)
