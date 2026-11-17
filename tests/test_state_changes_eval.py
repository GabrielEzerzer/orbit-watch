from datetime import datetime, timedelta, timezone

import pytest

from harness.evals import state_changes as sc
from harness.evals.mode_events import Event
from orbit_watch.events import Event as Found

T0 = datetime(2022, 1, 1, tzinfo=timezone.utc)
N = 1000


def found(kind, day, norad=N):
    t = T0 + timedelta(days=day)
    return Found(norad, kind, t, "test", 0.0, 10.0, 20.0, "controlled_lon", "drifting", t)


def ev(kind, day, norad=N, split="dev"):
    d = (T0 + timedelta(days=day)).date()
    return Event(f"{norad}-{kind}-{d}", norad, kind, d, split)


def run(events, founds):
    return sc.score(events, {N: founds}, {N}, set())


@pytest.mark.parametrize("truth,emitted,caught", [
    ("relocation_start", "relocation_start", True),
    ("relocation_start", "graveyard", True),
    ("graveyard", "keeping_stop", True),
    ("keeping_stop", "relocation_start", True),
    ("relocation_end", "relocation_start", False),
    ("relocation_start", "relocation_end", False),
    ("ns_keeping_stop", "ns_keeping_stop", True),
    ("ns_keeping_stop", "keeping_stop", False),
    ("graveyard", "free_burn", False),
])
def test_type_families_follow_rung_one(truth, emitted, caught):
    (r,) = run([ev(truth, 100)], [found(emitted, 103)])
    assert (r.status == "caught") is caught


def test_matching_is_one_to_one_closest_first_within_45_days():
    rs = run([ev("relocation_start", 100), ev("relocation_start", 110)], [found("relocation_start", 108)])
    assert [r.status for r in rs] == ["missed", "caught"] and rs[1].error_days == -2
    (r,) = run([ev("graveyard", 100)], [found("graveyard", 146)])
    assert r.status == "missed"
    (r,) = run([ev("graveyard", 100)], [found("graveyard", 55)])
    assert r.error_days == -45


def test_stats_count_exact_type_agreement():
    rs = run([ev("graveyard", 100), ev("relocation_end", 300)], [found("relocation_start", 101), found("relocation_end", 300)])
    s = sc._stats(rs)
    assert (s["caught"], s["same_type"], s["median_abs_error_days"]) == (2, 1, 0.5)


def test_false_events_count_every_event_inside_the_log_span_per_object_year():
    lo, hi = T0, T0 + timedelta(days=365.25 * 2)
    founds = {42917: [found("relocation_start", 10, 42917), found("free_burn", 800, 42917)], 62876: []}
    fe = sc.false_events(founds, {42917: (lo, hi), 62876: (hi, hi)})
    assert fe["false_events"] == 1 and fe["object_years"] == pytest.approx(2.0)
    assert fe["per_object_year"] == 0.5 and fe["status"] == "FAIL"
