import numpy as np
import pytest

from harness.evals import routine as ev
from harness.evals import state_injection as si
from harness.evals.state_changes import object_records
from orbit_watch.events import burns
from orbit_watch.modes import track


def _rank(values):
    order = sorted(values, key=lambda n: -values[n])
    return [{"rank": i, "norad_id": str(n), "name": "", "bits_per_year": str(values[n])}
            for i, n in enumerate(order, 1)]


def test_cited_lists_count_rateable_irregular_objects_in_the_top_5_percent_and_steady_ones_in_the_lower_half(mock_dir):
    values = {n: 0.0 for n in range(1000, 1060)}
    values.update({900001: 50.0, 900002: 40.0, 900003: 1.0, 900010: 0.0, 900011: 0.0, 900012: 30.0})
    for k in range(1060, 1100):
        values[k] = 2.0 + k / 1000
    out = ev.cited_lists(_rank(values), mock_dir / "routine" / "irregular_objects.csv",
                         mock_dir / "routine" / "steady_objects.csv")
    assert (out["irregular"]["listed"], out["irregular"]["rateable"], out["irregular"]["in_top_5_percent"]) == (4, 3, 2)
    assert out["irregular"]["file"] == "mock/routine/irregular_objects.csv"
    own = out["irregular"]["evidence_object"]
    assert (own["listed"], own["rateable"], own["in_top_5_percent"]) == (3, 2, 1)
    assert (out["steady"]["rateable"], out["steady"]["in_lower_half"]) == (3, 2)


def test_cited_lists_wait_for_the_files(tmp_path):
    assert ev.cited_lists([], tmp_path / "none.csv", tmp_path / "none2.csv") == {
        "status": "no cited irregular or steady list yet"}


def test_a_cited_list_without_a_source_column_is_refused(tmp_path):
    (tmp_path / "x.csv").write_text("norad_id,name\n1,A\n", encoding="utf-8")
    with pytest.raises(ValueError, match="source_url"):
        ev.read_cited(tmp_path / "x.csv")


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
