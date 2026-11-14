from datetime import date, datetime, timezone

import pytest

from orbit_watch.celestrak import USER_AGENT, CelesTrakSource


class FakeFetch:
    """Serves fixed bodies by URL and counts calls; no network."""

    def __init__(self, bodies: dict[str, bytes]):
        self.bodies, self.calls = bodies, []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        return self.bodies[url]


CATNR_URL = "https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=json"


@pytest.fixture
def iss_body(mock_dir):
    return (mock_dir / "celestrak" / "gp-CATNR-25544.json").read_bytes()


def test_catnr_query_parses_the_recorded_response(tmp_path, iss_body):
    fetch = FakeFetch({CATNR_URL: iss_body})
    source = CelesTrakSource(cache_dir=tmp_path, fetch=fetch, today=lambda: date(2026, 11, 14))
    (iss,) = source.load([25544])
    assert iss.norad_id == 25544 and iss.name == "ISS (ZARYA)"
    assert iss.epoch == datetime(2026, 11, 13, 21, 59, 13, 395264, tzinfo=timezone.utc)
    assert fetch.calls == [CATNR_URL]


def test_same_query_same_day_is_read_from_cache_and_refetched_next_day(tmp_path, iss_body):
    fetch = FakeFetch({CATNR_URL: iss_body})
    day = [date(2026, 11, 14)]
    source = CelesTrakSource(cache_dir=tmp_path, fetch=fetch, today=lambda: day[0])
    first = source.load([25544])
    assert source.load([25544]) == first
    assert len(fetch.calls) == 1
    assert (tmp_path / "2026-11-14" / "gp-CATNR-25544.json").read_bytes() == iss_body
    day[0] = date(2026, 11, 15)
    source.load([25544])
    assert len(fetch.calls) == 2


def test_bad_response_raises_and_is_not_cached(tmp_path):
    fetch = FakeFetch({CATNR_URL: b"<html>busy</html>"})
    source = CelesTrakSource(cache_dir=tmp_path, fetch=fetch, today=lambda: date(2026, 11, 14))
    with pytest.raises(ValueError):
        source.load([25544])
    assert not list(tmp_path.rglob("*.json"))


def test_no_data_answer_is_an_empty_list(tmp_path):
    url = "https://celestrak.org/NORAD/elements/gp.php?CATNR=99999&FORMAT=json"
    source = CelesTrakSource(cache_dir=tmp_path, fetch=FakeFetch({url: b"No GP data found"}))
    assert source.load([99999]) == []


def test_answer_for_another_object_is_refused(tmp_path, iss_body):
    url = "https://celestrak.org/NORAD/elements/gp.php?CATNR=55123&FORMAT=json"
    source = CelesTrakSource(cache_dir=tmp_path, fetch=FakeFetch({url: iss_body}))
    with pytest.raises(ValueError, match="other objects"):
        source.load([55123])


def test_group_query_url_and_value_check(tmp_path, iss_body):
    url = "https://celestrak.org/NORAD/elements/gp.php?GROUP=stations&FORMAT=json"
    fetch = FakeFetch({url: iss_body})
    source = CelesTrakSource(cache_dir=tmp_path, fetch=fetch)
    assert [r.norad_id for r in source.group("stations")] == [25544]
    with pytest.raises(ValueError):
        source.group("stations&FORMAT=tle")
    assert fetch.calls == [url]


def test_user_agent_names_no_person():
    assert USER_AGENT == "orbit-watch/0.1 (research prototype)"
