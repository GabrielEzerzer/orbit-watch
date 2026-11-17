import json
from dataclasses import replace

import numpy as np
import pytest

from orbit_watch import DirectorySource, parse_tle, to_series
from orbit_watch.generalise import load_series
from orbit_watch.holdout import load_gp_history
from orbit_watch.sources import data_dir


def test_data_dir_comes_from_orbit_watch_data(monkeypatch, tmp_path):
    monkeypatch.setenv("ORBIT_WATCH_DATA", str(tmp_path))
    assert data_dir() == tmp_path
    monkeypatch.delenv("ORBIT_WATCH_DATA")
    with pytest.raises(RuntimeError, match="ORBIT_WATCH_DATA"):
        data_dir()


def test_directory_source_reads_every_format_and_filters(mock_dir):
    source = DirectorySource(mock_dir / "elements")
    records = source.load([55123, 25544])
    assert sorted(r.norad_id for r in records) == [25544, 25544, 55123, 55123, 55123]
    assert {r.norad_id for r in source.load([25544])} == {25544}
    assert source.load([99999]) == []


def test_directory_source_names_the_bad_file(tmp_path):
    (tmp_path / "broken.tle").write_text("ISS\nnot a tle\n")
    (tmp_path / "notes.md").write_text("ignored")
    with pytest.raises(ValueError, match="broken.tle"):
        DirectorySource(tmp_path).load([25544])


def test_directory_source_turns_a_csv_error_into_value_error(tmp_path):
    (tmp_path / "huge.csv").write_text("NORAD_CAT_ID,OBJECT_NAME\n25544," + "x" * 200_000 + "\n")
    with pytest.raises(ValueError, match="huge.csv"):
        DirectorySource(tmp_path).load([25544])


def test_directory_source_requires_a_directory(tmp_path):
    with pytest.raises(NotADirectoryError):
        DirectorySource(tmp_path / "missing")


def test_series_sorted_and_deduplicated(mock_dir):
    records = DirectorySource(mock_dir / "elements").load([55123, 25544])
    series = to_series(reversed(records))
    iss, mario = series[25544], series[55123]
    assert len(iss) == 2 and len(mario) == 1
    assert iss.epochs[0] < iss.epochs[1]
    assert iss.epochs[0] == np.datetime64("2019-12-09T16:38:29.363424")
    assert iss.semi_major_axis_km.shape == iss.inclination.shape == iss.eccentricity.shape == (2,)


def test_later_duplicate_wins(mock_dir):
    rec = DirectorySource(mock_dir / "elements").load([55123])[0]
    restated = replace(rec, inclination=51.0)
    assert to_series([rec, restated])[55123].inclination.tolist() == [51.0]
    assert to_series([restated, rec])[55123].inclination.tolist() == [rec.inclination]


def _tle(day: float, mm: float = 1.00273956) -> str:
    def checksum(line):
        return str(sum(int(c) if c.isdigit() else c == "-" for c in line) % 10)
    l1 = f"1 37951U 11074B   {21000 + day:14.8f} -.00000034  00000-0  00000-0 0  999"
    l2 = f"2 37951   3.7193 109.4207 0001930 192.9377 176.7807 {mm:11.8f} 3321"
    return f"{l1}{checksum(l1)}\n{l2}{checksum(l2)}\n"


NEAR_DAYS = [1.0, 1.0 + 30 / 86400, 1.5, 1.5 + 59 / 86400, 1.5 + 120 / 86400, 2.0]


def test_epochs_under_60_s_apart_collapse_to_the_later():
    recs = parse_tle("".join(_tle(d) for d in NEAR_DAYS))
    s = to_series(reversed(recs))[37951]
    assert s.epochs.tolist() == [recs[i].epoch.replace(tzinfo=None) for i in (1, 3, 4, 5)]
    assert len(s.semi_major_axis_km) == len(s.bstar) == 4


def test_a_chain_under_60_s_apart_keeps_only_its_last_epoch():
    recs = parse_tle("".join(_tle(d) for d in (1.0, 1.0 + 40 / 86400, 1.0 + 80 / 86400, 2.0)))
    s = to_series(recs)[37951]
    assert s.epochs.tolist() == [recs[i].epoch.replace(tzinfo=None) for i in (2, 3)]


def test_every_loader_gets_the_collapse(tmp_path):
    days = sorted(NEAR_DAYS + [3.0 + 0.5 * i for i in range(20)])
    jitter = [1.00273956 + 1e-8 * (i * 7 % 5) for i in range(len(days))]
    (tmp_path / "37951.tle").write_text("".join(_tle(d, m) for d, m in zip(days, jitter)), encoding="utf-8")
    series, _, dropped = load_series(37951, tmp_path / "spacetrack", tmp_path)
    assert len(series) == len(days) - 2 and dropped == 2
    rows = [{"EPOCH": f"2021-01-01T00:00:{s:02d}.000000", "GP_ID": str(i + 1), "NORAD_CAT_ID": "25544",
             "MEAN_MOTION": "15.5", "ECCENTRICITY": "0.0003", "INCLINATION": "51.6", "RA_OF_ASC_NODE": "10",
             "ARG_OF_PERICENTER": "20", "MEAN_ANOMALY": "30", "BSTAR": "0.0001", "MEAN_MOTION_DOT": "0",
             "MEAN_MOTION_DDOT": "0", "OBJECT_NAME": "ISS"} for i, s in enumerate((0, 30))]
    (tmp_path / "gp.json").write_text(json.dumps(rows), encoding="utf-8")
    series, stats = load_gp_history(tmp_path / "gp.json")
    assert len(series) == 1 and stats["near_epoch_reissues_dropped"] == 1
