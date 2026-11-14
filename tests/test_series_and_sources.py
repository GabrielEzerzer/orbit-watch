from dataclasses import replace

import numpy as np
import pytest

from orbit_watch import DirectorySource, to_series


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
    # A field over the csv module's size limit raises csv.Error inside the reader.
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
    assert len(iss) == 2 and len(mario) == 1  # three MARIO files restate one element set
    assert iss.epochs[0] < iss.epochs[1]
    assert iss.epochs[0] == np.datetime64("2019-12-09T16:38:29.363424")
    assert iss.semi_major_axis_km.shape == iss.inclination.shape == iss.eccentricity.shape == (2,)


def test_later_duplicate_wins(mock_dir):
    rec = DirectorySource(mock_dir / "elements").load([55123])[0]
    restated = replace(rec, inclination=51.0)  # synthetic restatement at the same epoch
    assert to_series([rec, restated])[55123].inclination.tolist() == [51.0]
    assert to_series([restated, rec])[55123].inclination.tolist() == [rec.inclination]
