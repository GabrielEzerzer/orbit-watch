from harness.evals import cross_check as cc


def _rank(n):
    return [{"rank": str(i + 1), "norad_id": str(1000 + i), "name": f"R{i}"} for i in range(n)]


def test_sample_takes_the_top_of_the_rank_and_draws_the_rest_from_listed_objects_only():
    rank = _rank(40)
    unrated = [{"norad_id": str(5000 + i), "name": f"U{i}"} for i in range(30)]
    listed = {1000, 1001, *range(1030, 1040), *range(5000, 5030)}
    rows = cc.draw_sample(rank, unrated, listed, cited={1000, 5003})
    top = [r for r in rows if r["group"] == "top30"]
    drawn = [r for r in rows if r["group"] == "drawn"]
    assert [r["norad_id"] for r in top] == list(range(1000, 1030))
    assert len(drawn) == cc.DRAWN_N and len({r["norad_id"] for r in drawn}) == cc.DRAWN_N
    assert all(r["norad_id"] in listed and r["norad_id"] >= 1030 for r in drawn)
    assert rows == cc.draw_sample(rank, unrated, listed, cited={1000, 5003})
    by = {r["norad_id"]: r for r in rows}
    assert by[1000]["already_cited"] == 1 and by[1001]["already_cited"] == 0
    assert all(r["rank"] == "" for r in drawn if r["norad_id"] >= 5000)
