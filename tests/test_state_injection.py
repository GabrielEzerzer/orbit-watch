import numpy as np
import pytest

from harness.evals import state_injection as si
from harness.evals.state_changes import object_records
from orbit_watch.modes import track


def _wrap(x):
    return (np.asarray(x) + 180.0) % 360.0 - 180.0


def test_a_planted_relocation_adds_the_drift_and_keeps_each_element_set_consistent(mock_dir):
    recs = object_records(mock_dir / "geo" / "37344_every_2_days.tle")
    tr = track(recs)
    t0, rate, days = float(tr.days[20]) + 0.3, 0.5, 30.0
    p = si.Plant(0, "relocation", recs[0].norad_id, "dev", t0, rate, days)
    out = si.plant(recs, tr, None, p)
    new = track(out)
    inside = (tr.days >= t0) & (tr.days < t0 + days)
    assert np.allclose(new.rate - tr.rate, np.where(inside, rate, 0.0), atol=1e-9)
    assert np.allclose(_wrap(new.lon - tr.lon), rate * np.clip(tr.days - t0, 0.0, days), atol=1e-6)
    assert inside.sum() >= 10 and (tr.days >= t0 + days).sum() > 0
    for r, o in zip(recs, out):
        assert o.semi_major_axis_km == pytest.approx(r.semi_major_axis_km * (r.mean_motion / o.mean_motion) ** (2 / 3))
        assert (o.eccentricity, o.inclination, o.raan, o.arg_perigee) == (r.eccentricity, r.inclination, r.raan,
                                                                          r.arg_perigee)


def test_host_selection_drops_holdout_and_test_event_objects_and_keeps_the_longest_held_stretch():
    splits = {1: {"split": "holdout"}, 2: {"split": "dev"}, 3: {"split": "dev"}, 4: {"split": "test"}}
    events = [{"norad_id": "3", "split": "test"}, {"norad_id": "2", "split": "dev"}]
    excluded = si.excluded_objects(splits, events)
    assert excluded == {1, 3}
    rows = [{"norad_id": str(n), "mode": "controlled_lon", "start": "2022-01-01", "end": "2022-12-31"}
            for n in (1, 2, 3)]
    rows += [{"norad_id": "2", "mode": "controlled_lon_inc", "start": "2023-01-01", "end": "2023-06-01"},
             {"norad_id": "4", "mode": "controlled_lon", "start": "2022-01-01", "end": "2022-04-01"},
             {"norad_id": "4", "mode": "drifting", "start": "2022-04-01", "end": "2023-04-01"}]
    hosts = si.candidate_stretches(rows, excluded)
    assert list(hosts) == [2]
    assert hosts[2].end - hosts[2].start == 364.0 and hosts[2].split == si.host_split(2)


def test_a_one_km_raise_slows_the_drift_by_about_0_0128_deg_per_day():
    assert si.kick(42164.0, 1.0) == pytest.approx(-0.01284, abs=2e-4)
    assert si.kick(42164.0, -1.0) == pytest.approx(0.01284, abs=2e-4)


def test_the_plan_is_fixed_by_the_seed_and_alternates_dev_and_test_hosts():
    hosts = [si.Host(n, 0.0, 1500.0, "controlled_lon", si.host_split(n)) for n in range(100, 140)]
    last = {h.norad_id: 1800.0 for h in hosts}
    a, b = si.plan(hosts, last), si.plan(hosts, last)
    assert a == b
    assert [p.split for p in a[:6]] == ["dev", "test"] * 3
    assert all(abs(p.rate) >= 0.02 for p in a if p.kind == "relocation")
