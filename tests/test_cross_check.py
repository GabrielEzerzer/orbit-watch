from datetime import date

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


def _claim(i, claim_type, when, precision="day", kind="press", norad=1, end="", url="u"):
    return {"claim_id": f"C{i}", "norad_id": str(norad), "name": "X", "claim_type": claim_type, "date": when,
            "date_end": end, "date_precision": precision, "source_url": url, "publisher": "P", "quote": "q",
            "source_kind": kind, "says": ""}


def _event(event_type, when, norad=1):
    return {"norad_id": norad, "event_type": event_type, "date": date.fromisoformat(when)}


def test_score_matches_by_type_and_window_and_names_the_reason_for_a_miss():
    events = [_event("relocation_start", "2023-03-10"), _event("relocation_end", "2023-06-01"),
              _event("graveyard", "2024-05-01")]
    claims = [_claim(1, "relocation_start", "2023-03", "month"), _claim(2, "free_burn", "2023-06-03"),
              _claim(3, "relocation_end", "2023-08-20"), _claim(4, "relocation_end", "2025-01-01"),
              _claim(5, "graveyard", "2024-01", "quarter", end="2024-03")]
    by = {r["claim"]["claim_id"]: r for r in cc.score_claims(claims, events)}
    assert by["C1"]["status"] == "matched" and by["C1"]["error"] == -5
    assert by["C2"]["status"] == "listed_with_another_type" and by["C2"]["nearest"]["event_type"] == "relocation_end"
    assert by["C3"]["status"] == "listed_outside_window" and by["C3"]["nearest_offset"] == -80
    assert by["C4"]["status"] == "not_listed"
    assert by["C5"]["status"] == "matched" and by["C5"]["error"] == 31


def test_stayed_claim_reports_whether_the_list_shows_an_event_in_the_period():
    events = [_event("relocation_start", "2022-07-01", norad=2)]
    claims = [_claim(1, "stayed", "2022", "year", norad=2, end="2022"),
              _claim(2, "stayed", "2023-01", "month", norad=2, end="2023-06")]
    by = {r["claim"]["claim_id"]: r for r in cc.score_claims(claims, events)}
    assert by["C1"]["status"] == "stayed_event_listed" and len(by["C1"]["inside"]) == 1
    assert by["C2"]["status"] == "stayed_no_event_listed"


def test_tle_derived_claims_are_kept_apart_from_independent_ones():
    events = [_event("relocation_start", "2023-03-10")]
    claims = [_claim(1, "relocation_start", "2023-03-09"),
              _claim(2, "relocation_start", "2023-03-11", kind="tle_derived", url="v"),
              _claim(3, "relocation_end", "2023-09-01", kind="tle_derived", url="v")]
    sample = [{"norad_id": "1", "group": "top30", "already_cited": "0"}]
    s = cc.summarise(cc.score_claims(claims, events), events, sample)
    assert s["independent"]["all"]["claims"] == 1 and s["independent"]["all"]["matched"] == 1
    assert s["tle_derived"]["all"]["claims"] == 2 and s["tle_derived"]["all"]["matched"] == 1
    assert "tle_derived" not in s["independent"]["by_source_kind"]
    assert s["top30_relocation_starts"] == {"listed": 1, "confirmed_independent": 1, "confirmed_tle_derived": 1}
    assert [d["claim_id"] for d in s["disagreements"]] == ["C3"]


def test_verify_finds_each_quoted_passage_on_the_saved_copy_and_flags_the_rest(tmp_path):
    (tmp_path / "a.html").write_text("<html><body><p>The satellite \u2019moved\u2019 on 3\u00a0May.</p>"
                                     "<script>hidden text</script><p>It  arrived later.</p></body></html>",
                                     encoding="utf-8")
    (tmp_path / "index.csv").write_text("file,url,fetched_utc,sha256\na.html,u,t,s\n", encoding="utf-8")
    claims = [_claim(1, "relocation_start", "2023-05-03") | {"quote": "The satellite 'moved' on 3 May. ... it arrived"},
              _claim(2, "relocation_start", "2023-05-03") | {"quote": "hidden text"},
              _claim(3, "relocation_start", "2023-05-03", url="w") | {"quote": "moved"}]
    assert [c for c, _ in cc.verify(claims, tmp_path)] == ["C2", "C3"]
