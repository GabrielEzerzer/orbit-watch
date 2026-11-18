import csv
import json

from harness.evals import state_audit as sa
from orbit_watch.events import EVENT_TYPES


def committed_sample():
    return sa.draw(sa.read_events(), sa.excluded_objects())


def test_sample_is_deterministic_and_stratified():
    a, b = committed_sample(), committed_sample()
    assert a == b
    assert len(a) == sa.SAMPLE_SIZE
    for t in EVENT_TYPES:
        assert sum(e["event_type"] == t for e in a) >= sa.MIN_PER_TYPE
    assert sa.draw(sa.read_events(), sa.excluded_objects(), seed="another seed") != a


def test_sample_excludes_holdout_and_test_event_objects():
    excluded = sa.excluded_objects()
    with open(sa.GEO_EVENTS, newline="", encoding="utf-8") as f:
        test_objects = {int(r["norad_id"]) for r in csv.DictReader(f) if r["split"] == "test"}
    assert test_objects and test_objects <= excluded
    holdout = {n for n, e in sa.load_splits().items() if e["split"] == "holdout"}
    assert holdout and holdout <= excluded
    assert not {int(e["norad_id"]) for e in committed_sample()} & excluded


def test_quotas_floor_then_proportional():
    q = sa.quotas({"a": 600, "b": 100, "c": 3}, total=50, floor=5)
    assert sum(q.values()) == 50
    assert q["c"] == 3
    assert q["b"] >= 5 and q["a"] > q["b"]


def test_committed_audit_matches_sample_and_summary():
    rows = sa.read_events(sa.OUT / "audit.csv")
    assert sa.check_rows(rows, committed_sample()) == []
    summary = sa.summarise(rows)
    with open(sa.OUT / "summary.json", encoding="utf-8") as f:
        assert json.load(f) == {"sample_seed": sa.SEED, **summary, "public_sources": sa.PUBLIC_SOURCES}
    audited = {(int(r["norad_id"]), r["event_type"], r["date"]): r["est_date"] for r in rows}
    assert all(audited[(x["norad_id"], x["event_type"], x["date"])] == x["est_date"] for x in sa.PUBLIC_SOURCES)


def test_check_rows_flags_bad_rows():
    sample = committed_sample()[:2]
    rows = [dict(s, verdict="real", correct_type="", evidence="x") for s in sample]
    assert sa.check_rows(rows, sample) == []
    assert sa.check_rows(rows[::-1], sample)
    assert sa.check_rows([dict(rows[0], verdict="maybe"), rows[1]], sample)
    assert sa.check_rows([dict(rows[0], verdict="wrong_type"), rows[1]], sample)
    assert sa.check_rows([dict(rows[0], correct_type="graveyard"), rows[1]], sample)
    assert sa.check_rows([dict(rows[0], evidence=""), rows[1]], sample)


def test_summarise_counts_real_and_errors():
    rows = [
        {"event_type": "graveyard", "verdict": "real", "correct_type": "", "date_error_days": "-4"},
        {"event_type": "graveyard", "verdict": "real", "correct_type": "", "date_error_days": "unclear"},
        {"event_type": "free_burn", "verdict": "wrong_type", "correct_type": "graveyard", "date_error_days": ""},
        {"event_type": "free_burn", "verdict": "duplicate", "correct_type": "", "date_error_days": ""},
    ]
    s = sa.summarise(rows)
    assert s["real_right_type"] == 2 and s["real_any_type"] == 3
    assert s["real_date_dated"] == 1 and s["real_date_unclear"] == 1
    assert s["real_median_abs_error_days"] == 4.0
    assert s["corrected_types"] == {"graveyard": 1}
    assert s["verdicts_by_type"]["free_burn"] == {"wrong_type": 1, "duplicate": 1}
