from datetime import date

import pytest

from orbit_watch.spacetrack import BASE_URL, RateLimiter, SpaceTrackSource

START, END = date(2019, 12, 1), date(2020, 1, 31)
QUERY = (
    f"{BASE_URL}/basicspacedata/query/class/gp_history/NORAD_CAT_ID/25544"
    "/EPOCH/2019-12-01--2020-01-31/orderby/EPOCH%20asc/format/json"
)


class FakeSession:
    def __init__(self, get_body: bytes, login_body: bytes = b"", status: int = 200):
        self.get_body, self.login_body, self.status = get_body, login_body, status
        self.calls = []

    def post(self, url, form):
        self.calls.append(("POST", url, dict(form)))
        return 200, self.login_body

    def get(self, url):
        self.calls.append(("GET", url))
        return self.status, self.get_body


class FakeClock:
    def __init__(self):
        self.now, self.slept = 0.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def sample(mock_dir):
    return (mock_dir / "spacetrack" / "gp_history-25544-format-sample.json").read_bytes()


def source(session, tmp_path, **kwargs):
    return SpaceTrackSource("user", "pw", START, END, session=session, cache_dir=tmp_path, **kwargs)


def test_off_unless_both_credentials_are_set(monkeypatch):
    monkeypatch.delenv("SPACETRACK_USER", raising=False)
    monkeypatch.delenv("SPACETRACK_PASSWORD", raising=False)
    assert SpaceTrackSource.from_env(START, END) is None
    monkeypatch.setenv("SPACETRACK_USER", "user")
    assert SpaceTrackSource.from_env(START, END) is None
    monkeypatch.setenv("SPACETRACK_PASSWORD", "pw")
    assert SpaceTrackSource.from_env(START, END, session=FakeSession(b"[]")) is not None


def test_logs_in_then_queries_gp_history_and_parses(tmp_path, sample):
    session = FakeSession(sample)
    records = source(session, tmp_path).load([25544])
    assert session.calls == [
        ("POST", f"{BASE_URL}/ajaxauth/login", {"identity": "user", "password": "pw"}),
        ("GET", QUERY),
    ]
    assert [r.norad_id for r in records] == [25544, 25544]
    assert records[0].epoch < records[1].epoch


def test_history_is_downloaded_once_ever(tmp_path, sample):
    first = FakeSession(sample)
    source(first, tmp_path).load([25544])
    again = FakeSession(b"must not be read")
    assert len(source(again, tmp_path).load([25544])) == 2
    assert again.calls == []


def test_refused_login_and_bad_answers_raise_without_caching(tmp_path, sample):
    with pytest.raises(PermissionError):
        source(FakeSession(sample, login_body=b'{"Login":"Failed"}'), tmp_path).load([25544])
    with pytest.raises(RuntimeError, match="HTTP 500"):
        source(FakeSession(sample, status=500), tmp_path).load([25544])
    with pytest.raises(ValueError, match="other objects"):
        source(FakeSession(sample), tmp_path).load([55123])
    assert not list(tmp_path.iterdir())


def test_rate_limiter_keeps_under_30_a_minute_and_300_an_hour():
    clock = FakeClock()
    limiter = RateLimiter(clock=clock, sleep=clock.sleep)
    for _ in range(29):
        limiter.wait()
    assert clock.slept == []
    limiter.wait()
    assert clock.slept == [60.0]
    for _ in range(400):
        limiter.wait()
    times = list(limiter.sent)
    assert all(b - a >= 60.0 for a, b in zip(times, times[29:]))
    assert all(b - a >= 3600.0 for a, b in zip(times, times[299:]))
