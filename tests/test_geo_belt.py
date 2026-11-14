import json
import zipfile
from datetime import datetime, timezone

import pytest

from orbit_watch.elements import parse_tle
from orbit_watch.jobs import geo_belt
from orbit_watch.jobs.geo_belt import LineCount, build, bundle_paths, in_geo_region, tle_pairs, write
from orbit_watch.spacetrack import SpaceTrackSource


@pytest.fixture
def sample(mock_dir):
    return mock_dir / "geo" / "bundle-sample.txt"


def _checksum(line: str) -> str:
    return str(sum(int(c) if c.isdigit() else c == "-" for c in line[:68]) % 10)


def synthetic(norad: int, epoch: str, inc: float, ecc: float, mm: float) -> str:
    """A made-up but well-formed TLE pair (Luch 5A's layout and other fields) for rule edge cases."""
    line1 = f"1 {norad:05d}U 11074B   {epoch} -.00000034  00000-0  00000-0 0  999"
    line2 = f"2 {norad:05d} {inc:8.4f} 109.4207 {round(ecc * 1e7):07d} 192.9377 176.7807 {mm:11.8f}33212"
    assert len(line1) == len(line2) == 68
    line1, line2 = line1 + _checksum(line1), line2 + _checksum(line2)
    parse_tle(f"{line1}\n{line2}\n")  # well-formed by our own parser
    return f"{line1}\n{line2}\n"


def run(tmp_path, text: str, **period):
    bundle = tmp_path / "bundle.txt"
    bundle.write_text(text, encoding="ascii")
    files = build("test", [bundle], **period)
    return files, json.loads(files["manifest.json"])


def test_rule_bounds_are_inclusive_and_each_one_matters():
    assert in_geo_region(1.0027, 0.0002, 0.05)
    assert in_geo_region(0.9, 0.2, 70.0) and in_geo_region(1.1, 0.0, 0.0)
    assert not in_geo_region(0.8999, 0.0, 0.0)
    assert not in_geo_region(1.1001, 0.0, 0.0)
    assert not in_geo_region(1.0, 0.2001, 0.0)
    assert not in_geo_region(1.0, 0.0, 70.0001)


def test_gto_and_24h_eccentric_orbits_stay_out_and_arrival_history_is_kept(tmp_path):
    text = (
        synthetic(90001, "21010.50000000", 27.0, 0.7300000, 2.25)  # GTO only
        + synthetic(90002, "21010.50000000", 63.4, 0.2700000, 1.0027)  # 24 h, e > 0.2 (Sirius-like)
        + synthetic(90003, "21010.50000000", 75.0, 0.0002000, 1.0027)  # 24 h, too inclined
        + synthetic(90004, "21010.50000000", 27.0, 0.7300000, 2.25)  # GTO, then arrives at GEO
        + synthetic(90004, "21020.50000000", 0.1, 0.0003000, 1.0027)
        + synthetic(90005, "20360.50000000", 0.1, 0.0003000, 1.0027)  # in GEO only before the period
        + synthetic(90005, "21010.50000000", 9.0, 0.0003000, 0.95)  # then still in the box
        + synthetic(90006, "20360.50000000", 0.1, 0.0003000, 1.0027)  # in GEO only before the period
        + synthetic(90006, "21010.50000000", 0.1, 0.0003000, 1.2)  # then leaves the box
    )
    files, manifest = run(tmp_path, text)
    assert set(manifest["objects"]) == {"90004", "90005"}
    arrival = manifest["objects"]["90004"]
    assert arrival["tle_count"] == 2 and arrival["in_region_count"] == 1  # the GTO set is kept
    assert arrival["first_epoch"].startswith("2021-01-10")
    assert manifest["objects"]["90005"]["tle_count"] == 1  # the 2020 set is outside the period
    assert len(parse_tle(files["90004.tle"])) == 2


def test_real_bundle_selects_geo_objects_and_drops_the_iss(tmp_path, sample):
    files = build("mock", [sample])
    manifest = json.loads(files["manifest.json"])
    assert set(manifest["objects"]) == {"37951", "40258", "55841"}
    assert manifest["objects"]["37951"]["tle_count"] == 2
    assert manifest["object_count"] == 3 and manifest["tle_count"] == 4
    (bundle,) = manifest["bundles"]
    assert bundle["name"] == "bundle-sample.txt" and len(bundle["sha256"]) == 64
    assert (bundle["lines"], bundle["pairs"], bundle["rejected_lines"]) == (10, 5, 0)
    assert manifest["rule"]["eccentricity_max"] == 0.2
    # Lines are written as read, in epoch order.
    assert files["37951.tle"] == "".join(sample.read_text().splitlines(keepends=True)[:4])


def test_period_end_is_exclusive(tmp_path, sample):
    end = datetime(2023, 3, 13, 17, 43, 56, 444736, tzinfo=timezone.utc)  # 55841's only epoch
    manifest = json.loads(build("mock", [sample], end=end)["manifest.json"])
    assert "55841" not in manifest["objects"]


def test_zip_bundle_with_names_bad_lines_and_restated_epochs(tmp_path, sample):
    real = sample.read_text().splitlines()
    luch1, luch2 = real[0], real[1]
    corrupt = luch2[:-1] + str((int(luch2[-1]) + 1) % 10)  # checksum broken
    restated = synthetic(37951, luch1[18:32], 3.7193, 0.0001930, 1.00273999)  # same epoch, new lines
    member = "\n".join(
        ["0 LUCH 5A", luch1, luch2, "garbage", "0 LUCH 5A", luch1, corrupt, *restated.splitlines(), "1 orphan"]
    )
    bundle = tmp_path / "tle2021.zip"
    with zipfile.ZipFile(bundle, "w") as zf:
        zf.writestr("data/exports/tle2021.txt", member + "\n")
    manifest = json.loads(build("zip", [bundle])["manifest.json"])
    luch = manifest["objects"]["37951"]
    assert luch["names"] == ["LUCH 5A"]
    assert luch["tle_count"] == 1 and luch["invalid_pairs"] == 1 and luch["epoch_conflicts"] == 1
    assert manifest["bundles"][0]["rejected_lines"] == 2  # "garbage" and "1 orphan"
    files = build("zip", [bundle])
    assert files["37951.tle"] == restated  # the later record with the same epoch wins


def test_tle_pairs_counts_orphans():
    count = LineCount()
    lines = ["0 NAME ONLY", "2 " + "x" * 67, "1 " + "a" * 67, "1 " + "b" * 67, "2 " + "c" * 67, "tail"]
    pairs = list(tle_pairs(lines, count))
    assert pairs == [(None, "1 " + "b" * 67, "2 " + "c" * 67)]
    assert (count.lines, count.pairs, count.rejected_lines) == (6, 1, 4)


def test_output_to_directory_or_zip(tmp_path, sample):
    files = build("mock", [sample])
    write(files, tmp_path / "geo")
    assert sorted(p.name for p in (tmp_path / "geo").iterdir()) == sorted(files)
    write(files, tmp_path / "geo.zip")
    with zipfile.ZipFile(tmp_path / "geo.zip") as zf:
        assert sorted(zf.namelist()) == sorted(files)
        assert zf.read("40258.tle").decode() == files["40258.tle"]


def test_bundle_paths_expand_globs_and_refuse_no_match(tmp_path):
    (tmp_path / "tle2025.txt" / "data").mkdir(parents=True)  # a directory named like the file
    (tmp_path / "tle2025.txt" / "data" / "tle2025.txt").write_text("")
    assert bundle_paths([str(tmp_path / "**" / "tle2025.txt")]) == [tmp_path / "tle2025.txt" / "data" / "tle2025.txt"]
    with pytest.raises(FileNotFoundError):
        bundle_paths([str(tmp_path / "**" / "tle2024.txt")])


class FakeSession:
    def __init__(self, body: bytes):
        self.body, self.calls = body, []

    def post(self, url, form):
        self.calls.append(url)
        return 200, b""

    def get(self, url):
        self.calls.append(url)
        return 200, self.body


def test_satcat_is_one_cached_query_merged_into_the_manifest(tmp_path, sample):
    rows = [
        {"NORAD_CAT_ID": "37951", "OBJECT_NAME": "LUCH 5A", "OBJECT_TYPE": "PAYLOAD", "INTLDES": "2011-074B",
         "COUNTRY": "CIS", "LAUNCH": "2011-12-11", "DECAY": None},
        {"NORAD_CAT_ID": "40258", "OBJECT_NAME": "LUCH", "OBJECT_TYPE": "PAYLOAD", "INTLDES": "2014-058A",
         "COUNTRY": "CIS", "LAUNCH": "2014-09-27", "DECAY": None},
    ]  # the field names and value types of Space-Track's SATCAT class, values as published
    session = FakeSession(json.dumps(rows).encode())
    st = SpaceTrackSource("u", "p", geo_belt.START.date(), geo_belt.END.date(), session=session, cache_dir=tmp_path)
    fields = ("NORAD_CAT_ID", *geo_belt.SATCAT_FIELDS)
    got, query = st.satcat(fields)
    assert got == rows and "/class/satcat/predicates/NORAD_CAT_ID,OBJECT_NAME" in query
    assert st.satcat(fields)[0] == rows
    assert len([c for c in session.calls if "/class/satcat/" in c]) == 1  # the second came from disk

    manifest = geo_belt.add_satcat(json.loads(build("mock", [sample])["manifest.json"]), got, query)
    assert manifest["objects"]["37951"]["satcat"]["OBJECT_TYPE"] == "PAYLOAD"
    assert manifest["objects"]["55841"]["satcat"] is None
    assert manifest["satcat"]["objects_missing"] == 1
