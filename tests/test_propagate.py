from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from orbit_watch import PropagationError, parse_tle, propagate

ISS_L1 = "1 25544U 98067A   19343.69339541  .00001764  00000-0  38792-4 0  9991"
ISS_L2 = "2 25544  51.6439 211.2001 0007417  17.6667  85.6398 15.50103472202482"


def _tcppver(path):
    blocks, current = {}, None
    for line in path.read_text().splitlines():
        fields = line.split()
        if fields[-1] == "xx":
            current = blocks.setdefault(int(fields[0]), [])
        else:
            values = [float(x) for x in fields[:7]]
            current.append((values[0], values[1:4], values[4:7]))
    return blocks


def test_matches_vallado_verification_vectors(mock_dir):
    text = (mock_dir / "vallado" / "SGP4-VER-subset.tle").read_text()
    records = {r.norad_id: r for r in parse_tle(text)}
    expected = _tcppver(mock_dir / "vallado" / "tcppver-subset.out")
    assert set(expected) == set(records) == {5, 4632, 6251}
    for norad_id, rows in expected.items():
        rec = records[norad_id]
        times = [rec.epoch + timedelta(minutes=tsince) for tsince, _, _ in rows]
        r, v = propagate(rec, times)
        np.testing.assert_allclose(r, [row[1] for row in rows], rtol=0, atol=2e-7,
                                   err_msg="sgp4's own test suite uses this tolerance against this file")
        np.testing.assert_allclose(v, [row[2] for row in rows], rtol=0, atol=2e-7)


def test_matches_sgp4_readme_example():
    (rec,) = parse_tle(f"{ISS_L1}\n{ISS_L2}\n")
    r, v = propagate(rec, [datetime(2019, 12, 9, 20, 42, tzinfo=timezone.utc)])
    np.testing.assert_allclose(r[0], [-6088.92, -936.13, -2866.44], atol=0.01)
    np.testing.assert_allclose(v[0], [-1.525, -5.538, 5.068], atol=0.001)


def test_sgp4_error_raises():
    (rec,) = parse_tle(f"{ISS_L1}\n{ISS_L2}\n")
    doomed = replace(rec, bstar=0.5)
    with pytest.raises(PropagationError, match="SGP4 error"):
        propagate(doomed, [rec.epoch + timedelta(days=30)])


def test_naive_time_is_rejected():
    (rec,) = parse_tle(f"{ISS_L1}\n{ISS_L2}\n")
    with pytest.raises(ValueError, match="naive"):
        propagate(rec, [datetime(2019, 12, 9, 20, 42)])
