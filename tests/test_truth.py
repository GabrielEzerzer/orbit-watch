import json
from pathlib import Path

import pytest

from orbit_watch import generalise, truth
from orbit_watch.truth import SPLITS_PATH, HoldoutError, load_splits, make_splits, require_allowed

QZS2 = 42738
QZS3 = 42917


def test_committed_splits_follow_the_rule():
    assert json.loads(SPLITS_PATH.read_text(encoding="utf-8")) == make_splits()


def test_previously_scored_objects_are_train_and_holdout_is_not_empty():
    splits = load_splits()
    assert all(o["split"] == "train" for o in splits.values() if o["previously_scored"])
    holdout = {o["regime"] for o in splits.values() if o["split"] == "holdout"}
    assert holdout == {"GEO", "IGSO"}


def test_guard_refuses_holdout_unless_final():
    assert load_splits()[QZS2]["split"] == "holdout"
    with pytest.raises(HoldoutError):
        require_allowed(QZS2)
    assert require_allowed(QZS2, final=True)["name"] == "QZS-2"
    assert require_allowed(QZS3)["split"] == "train"


def test_guard_refuses_unassigned_objects():
    with pytest.raises(HoldoutError):
        require_allowed(99999)
    with pytest.raises(HoldoutError):
        require_allowed(99999, final=True)


def test_scoring_loaders_refuse_holdout(tmp_path):
    csv_path = tmp_path / "t.csv"
    csv_path.write_text("event_id,norad_id,start_utc,end_utc,kind,delta_a_est_m\n", encoding="utf-8")
    with pytest.raises(HoldoutError):
        generalise.load_log_events(csv_path, QZS2)
    assert generalise.load_log_events(csv_path, QZS2, final=True) == []
    with pytest.raises(HoldoutError):
        generalise.Satellite("QZS-2", QZS2, "IGSO", csv_path, tmp_path)
    with pytest.raises(FileNotFoundError):
        generalise.Satellite("QZS-2", QZS2, "IGSO", csv_path, tmp_path, final=True)


def test_cli_final_flag_reaches_the_loaders(monkeypatch, tmp_path):
    seen = {}

    def fake_run(*args, final=False):
        seen["final"] = final
        return {"regimes": {}}

    monkeypatch.setattr(generalise, "run", fake_run)
    generalise.main(["--truth-dir", str(tmp_path), "--tle-dir", str(tmp_path), "--out",
                     str(tmp_path), "--final"])
    assert seen["final"] is True


def test_split_rule_does_not_depend_on_object_order():
    shuffled = tuple(reversed(truth.OBJECTS))
    by_id = lambda d: {o["norad_id"]: o["split"] for o in d["objects"]}
    assert by_id(make_splits(shuffled)) == by_id(make_splits())


def test_every_truth_file_named_in_splits_exists():
    for o in load_splits().values():
        for f in o["truth_files"]:
            assert (Path(truth.GROUNDTRUTH) / f).is_file(), f


def test_generalise_run_refuses_final_before_reading_anything(monkeypatch, tmp_path):
    def must_not_run(*args, **kwargs):
        raise AssertionError("final=True got past the refusal")

    monkeypatch.setattr(generalise, "Satellite", must_not_run)
    monkeypatch.setattr(generalise, "tune", must_not_run)
    with pytest.raises(HoldoutError, match="frozen setting chosen on train objects"):
        generalise.run(tmp_path, tmp_path, tmp_path / "out", final=True)
    assert not (tmp_path / "out").exists()


def test_series_guard_refuses_holdout_element_sets(mock_dir):
    from dataclasses import replace

    from orbit_watch import DirectorySource, to_series

    iss = DirectorySource(mock_dir / "elements").load([25544])
    qzs2 = [replace(r, norad_id=QZS2) for r in iss]
    with pytest.raises(HoldoutError, match="QZS-2"):
        to_series(qzs2)
    with pytest.raises(HoldoutError):
        to_series(iss + qzs2)
    assert len(to_series(qzs2, final=True)[QZS2]) == 2
    unlisted = [replace(r, norad_id=99999) for r in iss]
    assert set(to_series(iss + unlisted)) == {25544, 99999}


def test_require_not_holdout_lets_unlisted_objects_through():
    assert truth.require_not_holdout(99999) is None
    assert truth.require_not_holdout(QZS3)["split"] == "train"
    with pytest.raises(HoldoutError):
        truth.require_not_holdout(QZS2)


REPO = Path(truth.__file__).resolve().parents[1]
SCANNED_DIRS = ("orbit_watch", "harness")
LABEL_READERS_ALLOWED = {"orbit_watch/truth.py", "orbit_watch/manoeuvre_logs.py"}
BULK_READERS_ALLOWED = {"orbit_watch/jobs/geo_belt.py"}


def _scanned_files():
    allowed = LABEL_READERS_ALLOWED | BULK_READERS_ALLOWED
    return [p.relative_to(REPO).as_posix() for d in SCANNED_DIRS for p in sorted((REPO / d).rglob("*.py"))
            if p.relative_to(REPO).as_posix() not in allowed]


def _file_readers(tree):
    import ast

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
        if name == "open" and isinstance(f, ast.Name):
            mode = node.args[1] if len(node.args) > 1 else next(
                (k.value for k in node.keywords if k.arg == "mode"), None)
            if not (isinstance(mode, ast.Constant) and set(str(mode.value)) & set("wax")):
                found.append((node.lineno, "open() for reading"))
        elif name in ("reader", "DictReader"):
            arg = node.args[0] if node.args else None
            is_stringio = (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Attribute)
                           and arg.func.attr == "StringIO")
            if not is_stringio:
                found.append((node.lineno, f"csv.{name} on a file"))
        elif name in ("read_csv", "loadtxt", "genfromtxt"):
            found.append((node.lineno, name))
    return found


def test_only_truth_py_opens_ground_truth_files():
    import ast

    files = _scanned_files()
    assert "harness/evals/detector.py" in files and "orbit_watch/generalise.py" in files
    offenders = []
    for rel in files:
        tree = ast.parse((REPO / rel).read_text(encoding="utf-8"))
        offenders += [f"{rel}:{line} {what}" for line, what in _file_readers(tree)]
    assert offenders == []


def test_the_scan_catches_a_direct_label_read():
    import ast

    src = ('import csv\nwith open("groundtruth/qzss_manoeuvres.csv") as f:\n'
           '    rows = list(csv.DictReader(f))\n')
    assert [what for _, what in _file_readers(ast.parse(src))] == [
        "open() for reading", "csv.DictReader on a file"]


def test_label_reader_refuses_holdout_and_filters_by_object(tmp_path):
    p = tmp_path / "t.csv"
    p.write_text(f"event_id,norad_id\na,{QZS3}\nb,{QZS2}\n", encoding="utf-8")
    assert [r["event_id"] for r in truth.read_label_rows(p, QZS3)] == ["a"]
    with pytest.raises(HoldoutError):
        truth.read_label_rows(p, QZS2)


def test_geo_fallback_refuses_holdout_objects(tmp_path, mock_dir):
    from orbit_watch.elements import _tle_checksum

    def renumber(line):
        line = line[:2] + f"{QZS2:05d}" + line[7:68]
        return line + str(_tle_checksum(line))

    tle_dir, geo_dir = tmp_path / "spacetrack", tmp_path / "geo"
    tle_dir.mkdir()
    geo_dir.mkdir()
    lines = (mock_dir / "geo" / "bundle-sample.txt").read_text(encoding="utf-8").splitlines()[:4]
    (geo_dir / f"{QZS2}.tle").write_text("".join(renumber(x) + "\n" for x in lines), encoding="utf-8")
    with pytest.raises(HoldoutError, match="QZS-2"):
        generalise.load_series(QZS2, tle_dir)
    series, label, _ = generalise.load_series(QZS2, tle_dir, final=True)
    assert label == f"geo/{QZS2}.tle" and len(series) == 2


CITED_OBJECT_FILES = ("irregular_objects.csv", "steady_objects.csv")


def _cited_rows(name):
    import csv

    with open(Path(truth.GROUNDTRUTH) / name, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


@pytest.mark.parametrize("name", CITED_OBJECT_FILES)
def test_cited_object_lists_parse_with_unique_norad_ids(name):
    fields, rows = _cited_rows(name)
    assert fields == ["norad_id", "name", "claim", "source_url", "quote"]
    assert rows
    ids = [int(r["norad_id"]) for r in rows]
    assert len(ids) == len(set(ids))
    assert all(1 <= i <= 99999 for i in ids)
    for r in rows:
        assert all(r[k].strip() for k in ("name", "claim", "source_url", "quote"))
        assert len(r["source_url"].split(" ; ")) == len(r["quote"].split(" || "))


def test_cited_object_lists_do_not_overlap():
    irregular, steady = ({int(r["norad_id"]) for r in _cited_rows(n)[1]} for n in CITED_OBJECT_FILES)
    assert not irregular & steady
