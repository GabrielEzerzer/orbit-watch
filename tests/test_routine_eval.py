from collections import Counter
from math import comb

import numpy as np
import pytest

from harness.evals import routine as ev
from harness.evals import state_injection as si
from harness.evals.state_changes import object_records
from orbit_watch.events import burns
from orbit_watch.modes import track


def _rank(values):
    order = sorted(values, key=lambda n: -values[n])
    return [{"rank": i, "norad_id": str(n), "name": "", "bits_per_year": str(values[n]),
             "departures": str(int(values[n] > 0))} for i, n in enumerate(order, 1)]


def test_cited_lists_count_rateable_irregular_objects_in_the_top_5_percent_and_steady_ones_in_the_lower_half(mock_dir):
    values = {n: 0.0 for n in range(1000, 1060)}
    values.update({900001: 50.0, 900002: 40.0, 900003: 1.0, 900010: 0.0, 900011: 0.0, 900012: 30.0})
    for k in range(1060, 1100):
        values[k] = 2.0 + k / 1000
    out = ev.cited_lists(_rank(values), mock_dir / "routine" / "irregular_objects.csv",
                         mock_dir / "routine" / "steady_objects.csv")
    assert (out["irregular"]["listed"], out["irregular"]["rateable"], out["irregular"]["in_top_5_percent"]) == (4, 3, 2)
    shown = (mock_dir / "routine" / "irregular_objects.csv").resolve().relative_to(ev.GROUNDTRUTH.parent)
    assert out["irregular"]["file"] == shown.as_posix() and not shown.is_absolute()
    own = out["irregular"]["evidence_object"]
    assert (own["listed"], own["rateable"], own["in_top_5_percent"]) == (3, 2, 1)
    assert (out["steady"]["rateable"], out["steady"]["in_lower_half"]) == (3, 2)
    steady = out["steady"]
    assert (steady["no_scored_departure"], steady["rated"], steady["rated_no_scored_departure"]) == (2, 106, 62)
    chance = (comb(62, 2) * 44 + comb(62, 3)) / comb(106, 3)
    assert steady["chance_of_at_least_as_many_in_a_random_draw"] == pytest.approx(chance, rel=1e-3)


def test_check_3_scores_cited_relocation_starts_and_reports_end_of_life_ones_apart():
    def row(kind, status, found="", flagged=False, model="rate"):
        return {"split": "dev", "event_type": kind, "status": status, "found_type": found,
                "scored": found == "relocation_start", "model": model if found == "relocation_start" else "",
                "flagged": flagged}
    rows = [row("relocation_start", "caught", "relocation_start", True), row("relocation_start", "missed"),
            row("relocation_start", "caught", "graveyard"), row("graveyard", "caught", "graveyard"),
            row("keeping_stop", "caught", "relocation_start"), row("keeping_stop", "missed")]
    cited = Counter({("dev", True): 4, ("dev", False): 3})
    out = ev.cited_summary(rows, cited, ("dev",))["dev"]
    assert (out["cited_relocation_starts"], out["held_a_year_before"], out["caught"], out["flagged"]) == (4, 3, 2, 1)
    assert (out["caught_unscored"], out["caught_typed_end_of_life"]) == (1, 1)
    assert out["flagged_by_model"] == {"stays": [0, 0], "rate": [1, 1]}
    assert out["end_of_life"] == {"cited": 3, "held_a_year_before": 3, "caught": 2, "typed_end_of_life": 1}


def test_cited_lists_wait_for_the_files(tmp_path):
    assert ev.cited_lists([], tmp_path / "none.csv", tmp_path / "none2.csv") == {
        "status": "no cited irregular or steady list yet"}


def test_a_cited_list_without_a_source_column_is_refused(tmp_path):
    (tmp_path / "x.csv").write_text("norad_id,name\n1,A\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source_url"):
        ev.read_cited(tmp_path / "x.csv")


def test_the_hand_audit_counts_each_groups_classes_and_refuses_unknown_ones(tmp_path):
    key, verdicts = tmp_path / "key.csv", tmp_path / "verdicts.csv"
    key.write_text("audit_id,group,rank,bits_per_year\nA01,top,1,9\nA02,top,2,8\nA03,middle,200,0\n",
                   encoding="utf-8")
    verdicts.write_text("audit_id,norad_id,class,departures_real,evidence\nA01,1,irregular,yes,e\n"
                        "A02,2,end_of_life,partly,e\nA03,3,none,n/a,e\n", encoding="utf-8")
    out = ev.hand_audit(key, verdicts)
    assert out["top"]["objects"] == 2 and out["top"]["class"]["irregular"] == 1
    assert out["top"]["class"]["end_of_life"] == 1 and out["top"]["departures_real"] == {"partly": 1, "yes": 1}
    assert out["middle"]["class"]["none"] == 1 and out["middle"]["class"]["irregular"] == 0
    assert ev.hand_audit(key, tmp_path / "none.csv") == {"status": "no audit verdicts yet"}
    verdicts.write_text("audit_id,norad_id,class,departures_real,evidence\nA01,1,odd,yes,e\n"
                        "A02,2,none,no,e\nA03,3,none,n/a,e\n", encoding="utf-8")
    with pytest.raises(ValueError, match="odd"):
        ev.hand_audit(key, verdicts)


def test_a_cited_row_with_unknown_evidence_is_refused(tmp_path):
    (tmp_path / "x.csv").write_text("norad_id,name,claim,source_url,quote,evidence\n1,A,c,u,q,rumour\n",
                                    encoding="utf-8")
    with pytest.raises(ValueError, match="evidence"):
        ev.read_cited(tmp_path / "x.csv")


def test_the_audit_sample_is_the_top_30_and_20_from_the_middle_in_a_fixed_shuffled_order():
    rank = [{"rank": str(i), "norad_id": str(1000 + i), "name": f"O{i}", "bits_per_year": "1"} for i in range(1, 201)]
    s = ev.audit_sample(rank)
    assert len(s) == 50 and len({x["audit_id"] for x in s}) == 50
    assert sorted(x["rank"] for x in s if x["group"] == "top") == list(range(1, 31))
    assert sorted(x["rank"] for x in s if x["group"] == "middle") == list(range(91, 111))
    assert [x["rank"] for x in s][:30] != list(range(1, 31)) and ev.audit_sample(rank) == s


def test_planted_moves_shift_the_longitude_by_each_move_and_back(mock_dir):
    recs = object_records(mock_dir / "geo" / "37344_every_2_days.tle")
    tr = track(recs)
    host = si.Host(recs[0].norad_id, float(tr.days[0]), float(tr.days[-1]), "controlled_lon", "dev")
    sm = si.smooth(tr, burns(recs)[0], host)
    t0 = float(tr.days[10]) + 0.3
    moves = [(t0, 8.0, 0.5), (t0 + 30.0, 8.0, -0.5)]
    new = track(ev.plant_moves(recs, tr, sm, recs[0].norad_id, moves))
    wrap = (new.lon - tr.lon + 180.0) % 360.0 - 180.0
    between = (tr.days >= t0 + 8.0) & (tr.days < t0 + 30.0)
    after = tr.days >= t0 + 38.0
    assert between.sum() >= 5 and after.sum() >= 5
    assert np.allclose(wrap[between], 4.0, atol=1e-6) and np.allclose(wrap[after], 0.0, atol=1e-6)
    assert ev.plant_moves(recs, tr, sm, recs[0].norad_id, moves)[:10] == recs[:10]
