from harness.evals.behaviour import count_checks


def row(n, rank, outside, kind="PAYLOAD", moves=0.0, burns=0.0):
    return {"rank": str(rank), "norad_id": str(n), "name": f"OBJ {n}", "object_type": kind, "score": str(10 - rank),
            "outside": str(outside), "relocation_starts_per_year": str(moves), "burns_per_year": str(burns)}


ROWS = [row(1, 1, 1), row(9, 2, 1, "DEBRIS", burns=9.0), row(4, 3, 0, moves=1.0), row(3, 4, 0, moves=1.0),
        row(2, 5, 0, moves=1.0), row(5, 6, 0), row(6, 7, 0), row(10, 8, 0, "ROCKET BODY", burns=8.0)]


def test_counts_each_check_and_breaks_plain_ties_by_the_lower_norad_id():
    r = count_checks(ROWS, [1, 2, 3, 99], [5])
    c = r["checks"]
    assert c["1_cited_irregular_outside"] == {"listed": 4, "scored": 3, "outside": 1, "target": "at least 75% of 4",
                                              "pass": False}
    assert c["2_cited_steady_outside"]["outside"] == 0 and c["2_cited_steady_outside"]["pass"]
    assert c["3_rocket_bodies_and_debris_outside"]["objects"] == 2
    assert c["3_rocket_bodies_and_debris_outside"]["outside"] == 1
    assert not c["3_rocket_bodies_and_debris_outside"]["pass"]
    four = c["4_against_plain_rankings"]
    assert (four["cut_objects"], four["outlier_score"], four["relocation_starts_per_year"], four["burns_per_year"]) \
        == (2, 1, 2, 0)
    assert not four["pass"] and r["verdict"] == "fail"
    by = {o["norad_id"]: o for o in r["irregular_objects"]}
    assert by[99]["rank"] is None and by[99]["outside"] == 0
    assert by[2]["rank_relocation_starts_per_year"] == 1 and by[3]["rank_relocation_starts_per_year"] == 2
    assert by[1]["rank"] == 1 and by[1]["outside"] == 1


def test_passes_only_when_all_four_pass():
    rows = [row(1, 1, 1), row(2, 2, 1)] + [row(n, n, 0, moves=5.0, burns=5.0) for n in range(3, 400)]
    rows += [row(n, n, 0, "DEBRIS") for n in range(400, 500)]
    r = count_checks(rows, [1, 2], [7])
    assert all(c["pass"] for c in r["checks"].values()) and r["verdict"] == "pass"
    r = count_checks(rows, [1, 2], [2])
    assert not r["checks"]["2_cited_steady_outside"]["pass"] and r["verdict"] == "fail"
