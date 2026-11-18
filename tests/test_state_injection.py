from datetime import datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest

from harness.evals import state_injection as si
from harness.evals.state_changes import object_records
from orbit_watch.events import burns
from orbit_watch.modes import longitude_acceleration, track


def _wrap(x):
    return (np.asarray(x) + 180.0) % 360.0 - 180.0


def _mock(mock_dir):
    recs = object_records(mock_dir / "geo" / "37344_every_2_days.tle")
    tr = track(recs)
    host = si.Host(recs[0].norad_id, float(tr.days[0]), float(tr.days[-1]), "controlled_lon", "dev")
    return recs, tr, si.smooth(tr, burns(recs)[0], host)


def test_a_planted_relocation_drifts_burn_free_and_keeps_each_element_set_consistent(mock_dir):
    recs, tr, sm = _mock(mock_dir)
    t0, rate, days = float(tr.days[20]) + 0.3, 0.5, 30.0
    p = si.Plant(0, "relocation", recs[0].norad_id, "dev", t0, rate, days)
    out = si.plant(recs, tr, sm, p)
    new = track(out)
    lon0, base = si.drift_base(tr.days, sm, p)
    inside, later = (tr.days >= t0) & (tr.days < t0 + days), tr.days >= t0 + days
    assert inside.sum() >= 10 and later.sum() > 0
    assert np.allclose((new.rate - sm.offset - sm.rate_res)[inside], base + rate, atol=1e-9)
    assert np.allclose(_wrap(new.lon - lon0 - (base + rate) * (tr.days - t0) - sm.lon_res)[inside], 0.0, atol=1e-6)
    assert np.allclose(_wrap(new.lon - tr.lon)[later], rate * days, atol=1e-6)
    assert np.allclose(new.rate[later], tr.rate[later]) and out[:20] == recs[:20]
    for r, o in zip(recs, out):
        assert o.semi_major_axis_km == pytest.approx(r.semi_major_axis_km * (r.mean_motion / o.mean_motion) ** (2 / 3))
        assert (o.eccentricity, o.inclination, o.raan, o.arg_perigee) == (r.eccentricity, r.inclination, r.raan,
                                                                          r.arg_perigee)


def test_a_planted_stop_drifts_at_the_planted_rate_under_the_longitude_acceleration(mock_dir):
    recs, tr, sm = _mock(mock_dir)
    t0 = float(tr.days[20]) + 0.3
    p = si.Plant(0, "keeping_stop", recs[0].norad_id, "dev", t0)
    new = track(si.plant(recs, tr, sm, p))
    lon0, rate0 = si.drift_base(tr.days, sm, p)
    span = (tr.days >= t0) & (tr.days <= t0 + 20.0)
    t, lon = tr.days[span], lon0 + _wrap(new.lon - sm.lon_res - lon0)[span]
    rate = (new.rate - sm.offset - sm.rate_res)[span]
    assert span.sum() >= 8
    assert np.allclose(np.diff(lon) / np.diff(t), 0.5 * (rate[1:] + rate[:-1]), atol=1e-6)
    acc = longitude_acceleration(0.5 * (lon[1:] + lon[:-1]), float(tr.inclination[20]))
    assert np.abs(acc).min() > 1e-5
    assert np.allclose(np.diff(rate) / np.diff(t), acc, rtol=0.02)
    first = float(longitude_acceleration(0.5 * (lon0 + lon[0]), float(tr.inclination[20])))
    assert lon[0] - lon0 - rate0 * (t[0] - t0) == pytest.approx(0.5 * first * (t[0] - t0) ** 2, rel=0.05)


def seg(n, mode, start, end):
    return SimpleNamespace(norad_id=n, mode=mode, start=datetime.fromisoformat(start).replace(tzinfo=timezone.utc),
                           end=datetime.fromisoformat(end).replace(tzinfo=timezone.utc))


def test_host_selection_drops_holdout_and_test_event_objects_and_keeps_the_longest_held_stretch():
    splits = {1: {"split": "holdout"}, 2: {"split": "dev"}, 3: {"split": "dev"}, 4: {"split": "test"}}
    events = [{"norad_id": "3", "split": "test"}, {"norad_id": "2", "split": "dev"}]
    excluded = si.excluded_objects(splits, events)
    assert excluded == {1, 3}
    segs = [seg(n, "controlled_lon", "2022-01-01T06:00", "2022-12-31T18:00") for n in (1, 2, 3)]
    segs += [seg(2, "controlled_lon_inc", "2023-01-01", "2023-06-01"), seg(4, "controlled_lon", "2022-01-01", "2022-04-01"),
             seg(4, "drifting", "2022-04-01", "2023-04-01")]
    hosts = si.candidate_stretches(segs, excluded)
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


def test_the_frozen_hosts_hold_no_holdout_or_test_event_object_and_read_back_exactly():
    from orbit_watch.truth import load_splits, read_event_rows
    from harness.evals.mode_events import DEFAULT_EVENTS
    hosts = si.load_hosts()
    excluded = si.excluded_objects(load_splits(), read_event_rows(DEFAULT_EVENTS)[1])
    assert hosts and not set(hosts) & excluded
    assert all(h.end - h.start >= si.MIN_HOLD_DAYS and h.split == si.host_split(n) for n, h in hosts.items())
    assert all(si.read_host(si.host_record(h)) == h for h in hosts.values())
