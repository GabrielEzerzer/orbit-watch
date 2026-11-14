import json
from pathlib import Path

import pytest

from orbit_watch import generalise, truth
from orbit_watch.truth import SPLITS_PATH, HoldoutError, load_splits, make_splits, require_allowed

SARAL = 39086  # holdout in the committed splits.json
CRYOSAT2 = 36508  # train


def test_committed_splits_follow_the_rule():
    assert json.loads(SPLITS_PATH.read_text(encoding="utf-8")) == make_splits()


def test_previously_scored_objects_are_train_and_holdout_is_not_empty():
    splits = load_splits()
    assert all(o["split"] == "train" for o in splits.values() if o["previously_scored"])
    holdout = {o["regime"] for o in splits.values() if o["split"] == "holdout"}
    assert holdout == {"LEO", "GEO", "IGSO"}


def test_guard_refuses_holdout_unless_final():
    assert load_splits()[SARAL]["split"] == "holdout"
    with pytest.raises(HoldoutError):
        require_allowed(SARAL)
    assert require_allowed(SARAL, final=True)["name"] == "SARAL"
    assert require_allowed(CRYOSAT2)["split"] == "train"


def test_guard_refuses_unassigned_objects():
    with pytest.raises(HoldoutError):
        require_allowed(99999)
    with pytest.raises(HoldoutError):
        require_allowed(99999, final=True)


def test_scoring_loaders_refuse_holdout(tmp_path):
    csv_path = tmp_path / "t.csv"
    csv_path.write_text("event_id,norad_id,start_utc,end_utc,kind,delta_a_est_m\n", encoding="utf-8")
    with pytest.raises(HoldoutError):
        generalise.load_log_events(csv_path, SARAL)
    assert generalise.load_log_events(csv_path, SARAL, final=True) == []
    with pytest.raises(HoldoutError):  # refused before any element-set file is looked for
        generalise.Satellite("SARAL", SARAL, "LEO", csv_path, tmp_path)
    with pytest.raises(ValueError):  # with final=True it gets past the guard to the empty dir
        generalise.Satellite("SARAL", SARAL, "LEO", csv_path, tmp_path, final=True)


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
    by_id = lambda d: {o["norad_id"]: o["split"] for o in d["objects"]}  # noqa: E731
    assert by_id(make_splits(shuffled)) == by_id(make_splits())


def test_every_truth_file_named_in_splits_exists():
    for o in load_splits().values():
        for f in o["truth_files"]:
            assert (Path(truth.GROUNDTRUTH) / f).is_file(), f
