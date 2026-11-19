import math

import numpy as np
import pytest

from orbit_watch import routine as rt

PRIOR = rt.Prior(0.0, 0.1, 0.2, 2.0, 100, 500.0, 50)
HELD = [(0.0, 3000.0)]


def at(_day):
    return PRIOR


def hopper(stays, last_stay, move=10.0, start=400.0):
    events, t = [], start
    for s in [*stays, last_stay]:
        events += [(t, "relocation_end"), (t + s, "relocation_start")]
        t += s + move
    return events


def last_bits(events, holds=HELD, first_day=0.0, end_day=3000.0):
    rows, _ = rt.score_object(1, events, holds, first_day, end_day, at)
    return rows[-1]


def test_a_departure_on_the_objects_own_rhythm_scores_low_once_it_has_three_stays():
    on = last_bits(hopper([90, 92, 88], 91))
    off = last_bits(hopper([90, 92, 88], 30))
    assert on.model == "stays" and on.bits < 1.0
    assert off.bits >= rt.OFF_ROUTINE_BITS and off.off_routine


def test_two_stays_are_not_enough_for_the_stay_model():
    row = last_bits(hopper([90, 92], 91))
    assert row.model == "rate" and row.past_stays == 2


def test_identical_stays_use_the_floored_spread():
    row = last_bits(hopper([90, 90, 90], 110))
    assert row.model == "stays" and 0.5 < row.bits < 2.0


def test_a_first_departure_scores_at_the_belt_rate():
    row = last_bits([(1000.0, "keeping_stop")])
    years = 1000.0 / rt.YEAR_DAYS
    expect = -math.log2(1 - (1 + (30 / rt.YEAR_DAYS) / (PRIOR.beta + years)) ** -PRIOR.alpha)
    assert row.model == "rate" and row.bits == pytest.approx(expect)
    assert row.bits > 7.0


def test_an_object_that_often_leaves_is_less_surprising_than_the_belt():
    events = [(500.0 + 40 * i, "keeping_stop") for i in range(8)]
    rows, _ = rt.score_object(1, events, [(400.0, 800.0)], 0.0, 3000.0, at)
    assert rows[-1].bits < 3.0 < rows[0].bits


def test_scores_never_change_when_later_events_are_added():
    events = hopper([90, 92, 88], 91)
    before, _ = rt.score_object(1, events, HELD, 0.0, 3000.0, at)
    after, _ = rt.score_object(1, events + [(2500.0, "graveyard")], HELD, 0.0, 3000.0, at)
    assert after[:len(before)] == before


def test_the_belt_prior_uses_only_departures_before_its_date():
    holds = {1: [(0.0, 1800.0)], 2: [(0.0, 1800.0)], 3: [(0.0, 900.0)]}
    deps = {1: [100.0, 700.0], 2: [300.0]}
    base = rt.belt_priors(holds, deps, 1800.0)
    more = rt.belt_priors(holds, {**deps, 3: [600.0]}, 1800.0)
    early = [p for p in base if p.day <= 600.0]
    assert early and more[:len(early)] == early and more[len(early)] != base[len(early)]
    assert base[-1].rate == pytest.approx(3 / ((1800.0 * 2 + 900.0) / rt.YEAR_DAYS))
    assert rt.prior_lookup(base)(10.0) is None and rt.prior_lookup(base)(65.0).day == 60.0


def test_departures_in_the_first_180_days_are_not_scored():
    rows, _ = rt.score_object(1, [(150.0, "keeping_stop"), (200.0, "graveyard")], HELD, 10.0, 3000.0, at)
    assert [r.scored for r in rows] == [False, True]
    assert not rows[0].off_routine


def test_a_stay_past_its_own_99th_percentile_gets_one_dated_overrun():
    events = hopper([90, 90, 90], 60)[:-1]
    arrival = events[-1][0]
    _, overruns = rt.score_object(1, events, HELD, 0.0, arrival + 400.0, at)
    assert len(overruns) == 1
    assert overruns[0].day == pytest.approx(arrival + 90 * math.exp(rt.Z_OVERRUN * rt.SD_FLOOR))
    _, none = rt.score_object(1, hopper([90, 90, 90], 100), HELD, 0.0, 3000.0, at)
    assert none == []


def test_only_objects_held_two_years_are_rated_and_scored_per_year_since_first_hold():
    rows = [rt.Scored(1, "keeping_stop", 900.0, True, "rate", 0, 0, 2.0, None, 0.01, 6.0)]
    short = rt.standing(1, rows, [], [(100.0, 100.0 + 1.9 * rt.YEAR_DAYS)], 1800.0)
    long = rt.standing(1, rows, [], [(100.0, 100.0 + 2.1 * rt.YEAR_DAYS)], 1800.0)
    assert not short.rated and long.rated
    assert long.bits_per_year == pytest.approx(6.0 / (1700.0 / rt.YEAR_DAYS))
    assert long.departures_per_held_year == pytest.approx(1 / 2.1)
    assert [s.norad_id for s in rt.ranked([short, long])] == [1]


def _belt(other_lon=10.05, other_from=0, sma_gap=0.0, owner="B", launch="2010-001"):
    n = 120
    lon = np.full((3, n), np.nan)
    sma = np.full((3, n), 42164.0)
    lon[0, 50:] = 10.0
    lon[0, :40] = 30.0
    lon[1, :] = 12.0
    lon[1, other_from:] = other_lon
    lon[2, :] = 80.0
    sma[1] += sma_gap
    return lon, sma, [10, 11, 12], ["A", owner, "C"], ["2020-001", launch, "2015-001"]


def test_an_arrival_beside_another_owners_satellite_already_there_is_flagged():
    f = rt.proximity(0, 50, *_belt())
    assert f is not None and f.other == 11 and f.sep_deg == pytest.approx(0.05, abs=1e-3)


@pytest.mark.parametrize("change", [dict(other_lon=10.15), dict(other_from=45), dict(sma_gap=12.0),
                                    dict(owner="A"), dict(launch="2020-001")])
def test_an_arrival_is_not_flagged_when_any_proximity_rule_fails(change):
    assert rt.proximity(0, 50, *_belt(**change)) is None


def test_cited_list_shares_and_overlap():
    values = {n: float(n) for n in range(1, 101)}
    values.update({n: 0.0 for n in range(101, 141)})
    assert rt.top_share(values, [100, 99, 50, 999], 0.05) == (2, 3)
    assert rt.lower_half(values, [1, 120, 100]) == (2, 3)
    assert rt.overlap([1, 2, 3, 4], [4, 9, 2, 8, 7], 3, 4) == (1, 3)
    assert rt.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert rt.spearman([1, 2, 3, 4], [4, 3, 2, 1]) == pytest.approx(-1.0)
