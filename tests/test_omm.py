import json

import pytest

from orbit_watch import parse_omm_csv, parse_omm_json, parse_tle


def test_json_csv_and_tle_give_the_same_record(mock_dir):
    d = mock_dir / "elements"
    (from_tle,) = parse_tle((d / "mario.tle").read_text())
    (from_csv,) = parse_omm_csv((d / "mario.csv").read_text())
    (from_json,) = parse_omm_json((d / "mario.json").read_text())
    assert from_csv == from_json == from_tle
    assert from_tle.name == "MARIO"
    assert from_tle.norad_id == 55123


def _mario(mock_dir) -> dict:
    return json.loads((mock_dir / "elements" / "mario.json").read_text())[0]


def test_single_object_json_is_accepted(mock_dir):
    (rec,) = parse_omm_json(json.dumps(_mario(mock_dir)))
    assert rec.norad_id == 55123


def test_epoch_with_offset_is_converted_to_utc(mock_dir):
    fields = _mario(mock_dir) | {"EPOCH": "2023-04-25T12:45:30.642912+02:00"}
    (rec,) = parse_omm_json(json.dumps(fields))
    (ref,) = parse_omm_json(json.dumps(_mario(mock_dir)))
    assert rec.epoch == ref.epoch


@pytest.mark.parametrize(
    "change, message",
    [
        ({"MEAN_MOTION": None}, "missing"),
        ({"ECCENTRICITY": 1.2}, "eccentricity"),
        ({"INCLINATION": 200}, "inclination"),
        ({"BSTAR": "abc"}, "could not convert"),
        ({"NORAD_CAT_ID": "x1"}, "invalid literal"),
        ({"EPOCH": "yesterday"}, "isoformat"),
    ],
)
def test_bad_fields_are_rejected(mock_dir, change, message):
    with pytest.raises(ValueError, match=message):
        parse_omm_json(json.dumps(_mario(mock_dir) | change))


def test_csv_without_header_is_rejected():
    with pytest.raises(ValueError, match="NORAD_CAT_ID"):
        parse_omm_csv("MARIO,1998-067UQ\n")
