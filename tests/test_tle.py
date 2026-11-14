from datetime import datetime, timezone

import pytest
from sgp4.api import Satrec

from orbit_watch import parse_tle

ISS_L1 = "1 25544U 98067A   19343.69339541  .00001764  00000-0  38792-4 0  9991"
ISS_L2 = "2 25544  51.6439 211.2001 0007417  17.6667  85.6398 15.50103472202482"


def test_three_line_name_and_mixed_two_line(mock_dir):
    first, second = parse_tle((mock_dir / "elements" / "iss.tle").read_text())
    assert first.name == "ISS (ZARYA)"
    assert second.name is None
    assert first.norad_id == second.norad_id == 25544
    assert first.epoch == datetime(2019, 12, 9, 16, 38, 29, 363424, tzinfo=timezone.utc)
    assert first.mean_motion == 15.50103472
    assert first.eccentricity == 0.0007417
    assert first.bstar == 0.38792e-4


def test_day_366_of_a_non_leap_year_rolls_into_next_year(mock_dir):
    # Same case and expected epoch as sgp4's own test_december_32.
    second = parse_tle((mock_dir / "elements" / "iss.tle").read_text())[1]
    assert second.epoch == datetime(2020, 1, 1, 19, 42, 47, 134368, tzinfo=timezone.utc)


def test_space_track_zero_prefixed_name_line():
    (rec,) = parse_tle(f"0 ISS (ZARYA)\n{ISS_L1}\n{ISS_L2}\n")
    assert rec.name == "ISS (ZARYA)"


def test_checksum_mismatch_is_rejected():
    bad = ISS_L2[:-1] + "3"
    with pytest.raises(ValueError, match="checksum"):
        parse_tle(f"{ISS_L1}\n{bad}\n")


def _with_checksum(line: str) -> str:
    total = sum(int(c) if c.isdigit() else c == "-" for c in line[:68])
    return line[:68] + str(total % 10)


def test_blank_eccentricity_is_rejected_not_read_as_zero():
    blank = _with_checksum(ISS_L2[:26] + " " * 7 + ISS_L2[33:])
    with pytest.raises(ValueError, match="eccentricity"):
        parse_tle(f"{ISS_L1}
{blank}
")


def test_catalog_number_mismatch_is_rejected():
    # Line 2 of a different object, with a valid checksum.
    other = "2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667"
    with pytest.raises(ValueError, match="catalog numbers"):
        parse_tle(f"{ISS_L1}\n{other}\n")


def test_dangling_name_or_line_is_rejected():
    with pytest.raises(ValueError):
        parse_tle(f"ISS\n{ISS_L1}\n")
    with pytest.raises(ValueError):
        parse_tle("ISS\nNOT A TLE\n")


def test_fields_match_sgp4s_own_tle_reader(mock_dir):
    text = (mock_dir / "vallado" / "SGP4-VER-subset.tle").read_text()
    lines = text.splitlines()
    records = parse_tle(text)
    assert len(records) == 3
    for rec, l1, l2 in zip(records, lines[0::2], lines[1::2]):
        ours, ref = rec.satrec(), Satrec.twoline2rv(l1, l2)
        for attr in ("no_kozai", "ecco", "inclo", "nodeo", "argpo", "mo", "bstar", "a"):
            assert getattr(ours, attr) == pytest.approx(getattr(ref, attr), rel=1e-12, abs=1e-15), attr
        assert ours.jdsatepoch + ours.jdsatepochF == pytest.approx(
            ref.jdsatepoch + ref.jdsatepochF, abs=1e-9
        )


def test_iss_semi_major_axis():
    (rec,) = parse_tle(f"{ISS_L1}\n{ISS_L2}\n")
    # ISS at ~410 km altitude; Brouwer mean a from SGP4 init, WGS72 radius.
    assert 6780 < rec.semi_major_axis_km < 6810
    assert rec.semi_major_axis_km == pytest.approx(Satrec.twoline2rv(ISS_L1, ISS_L2).a * 6378.135)
