from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from orbit_watch import parse_tle
from orbit_watch.geo import drift_rate, gmst_deg, longitude_deg, wrap180

# Luch 5A (NORAD 37951), a TLE from the public OndroNR/tle-archive, epoch 2021-01-01.
LUCH_L1 = "1 37951U 11074B   21001.58537451 -.00000034  00000-0  00000-0 0  9998"
LUCH_L2 = "2 37951   3.7193 109.4207 0001930 192.9377 176.7807  1.00273956 33212"


def test_gmst_matches_meeus_example_12a():
    # Meeus, Astronomical Algorithms (2nd ed.), Example 12.a: 1987 April 10, 0h UT,
    # mean sidereal time at Greenwich 13h 10m 46.3668s = 197.693195 deg.
    assert gmst_deg(datetime(1987, 4, 10, tzinfo=timezone.utc)) == pytest.approx(197.693195, abs=1e-5)


def test_gmst_at_j2000_epoch():
    # IAU 1982 constant term: 67310.54841 s at 2000-01-01 12:00 UT1 = 280.46061837 deg.
    assert gmst_deg(datetime(2000, 1, 1, 12, tzinfo=timezone.utc)) == pytest.approx(280.46061837, abs=1e-6)


def test_geo_longitude_stays_put_over_a_day():
    # Mean motion 1.00273956 rev/day is 360 * (n - 1.00273791) = +0.0006 deg/day of drift, so over
    # one day the sub-satellite longitude moves only by the daily inclination/eccentricity wobble
    # (inclination 3.7 deg gives an east-west figure-eight of about +-0.06 deg).
    (rec,) = parse_tle(f"{LUCH_L1}\n{LUCH_L2}\n")
    lons = np.array([longitude_deg(rec, rec.epoch + timedelta(hours=h)) for h in range(0, 25, 3)])
    assert np.ptp(lons) < 0.2
    assert -180 <= lons.min() and lons.max() < 180


def test_drift_rate_unwraps_across_the_antimeridian():
    days = np.array([0.0, 1.0, 2.0, 3.0])
    lon = wrap180(np.array([178.0, 179.0, 180.0, 181.0]))
    assert drift_rate(days, lon) == pytest.approx(1.0)
