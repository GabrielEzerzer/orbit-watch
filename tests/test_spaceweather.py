import math
from datetime import date

import numpy as np
import pytest

from orbit_watch.spaceweather import SW_URL, load_space_weather, parse_sw_all


@pytest.fixture
def sample(mock_dir):
    return (mock_dir / "celestrak" / "SW-All-sample.csv").read_bytes()


def test_parses_observed_predicted_and_monthly_rows(sample):
    sw = parse_sw_all(sample)
    assert sw.day.tolist() == [
        date(1957, 10, 1), date(2024, 5, 10), date(2024, 5, 11),
        date(2026, 11, 13), date(2026, 11, 14), date(2027, 1, 1),
    ]
    # 2024-05-11, the May 2024 storm: KP1 is printed as 90, i.e. Kp 9.0.
    np.testing.assert_allclose(sw.kp[2], [9.0, 8.3, 8.3, 9.0, 8.7, 8.3, 7.7, 7.7])
    np.testing.assert_allclose(sw.ap[2], [400, 236, 236, 400, 300, 236, 179, 179])
    assert sw.ap_daily[2] == 271
    assert sw.f107_obs[2] == 213.7 and sw.f107_adj[2] == 218.0
    assert sw.data_type.tolist() == ["OBS", "OBS", "OBS", "OBS", "PRD", "PRM"]
    # Monthly prediction rows carry F10.7 but no Kp or Ap.
    assert np.isnan(sw.kp[5]).all() and math.isnan(sw.ap_daily[5])
    assert sw.f107_obs[5] == 117.5


def test_out_of_range_and_missing_columns_raise(sample):
    text = sample.decode()
    with pytest.raises(ValueError, match="KP1"):
        parse_sw_all(text.replace("2024-05-11,2601,21,90,", "2024-05-11,2601,21,95,").encode())
    with pytest.raises(ValueError, match="lacks columns"):
        parse_sw_all(text.replace("F10.7_OBS,", "F107,", 1).encode())


def test_download_goes_through_the_daily_cache(tmp_path, sample):
    calls = []

    def fetch(url):
        calls.append(url)
        return sample

    for _ in range(2):
        sw = load_space_weather(cache_dir=tmp_path, fetch=fetch, today=lambda: date(2026, 11, 14))
    assert calls == [SW_URL]
    assert len(sw.day) == 6
