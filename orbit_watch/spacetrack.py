"""Element-set history from Space-Track's ``gp_history`` class. Off unless credentials are set.

Written from Space-Track's public documentation and never run against the live API: log in with
``POST /ajaxauth/login`` (form fields ``identity`` and ``password``), then query
``/basicspacedata/query/class/gp_history/NORAD_CAT_ID/<id>/EPOCH/<a>--<b>/orderby/EPOCH asc/format/json``.

Space-Track's rules, kept here: fewer than 30 requests a minute and 300 an hour, and
``gp_history`` is "1 / lifetime": once an object's history is downloaded it is stored and never
downloaded again. Every answer is therefore kept under ``data/spacetrack/`` with no expiry, and
a query that is already on disk never reaches the network.

``SpaceTrackSource.from_env`` returns ``None`` unless both ``SPACETRACK_USER`` and
``SPACETRACK_PASSWORD`` are set (they come from the hush vault through ``hush run``).
"""

from __future__ import annotations

import http.cookiejar
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from collections.abc import Callable, Iterable
from datetime import date
from pathlib import Path
from typing import Protocol

from orbit_watch.celestrak import USER_AGENT
from orbit_watch.elements import ElementSet, parse_omm_json

BASE_URL = "https://www.space-track.org"
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "spacetrack"
LIMITS = ((60.0, 29), (3600.0, 299))  # (window seconds, most requests in it): under 30/min, 300/h


class Session(Protocol):
    """The two HTTP calls Space-Track needs. Implementations keep the login cookie."""

    def post(self, url: str, form: dict[str, str]) -> tuple[int, bytes]: ...

    def get(self, url: str) -> tuple[int, bytes]: ...


class UrllibSession:
    """``Session`` over urllib with a cookie jar; non-2xx answers come back as their status."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    def _open(self, request: urllib.request.Request) -> tuple[int, bytes]:
        request.add_header("User-Agent", USER_AGENT)
        try:
            with self._opener.open(request, timeout=120) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    def post(self, url: str, form: dict[str, str]) -> tuple[int, bytes]:
        return self._open(urllib.request.Request(url, data=urllib.parse.urlencode(form).encode()))

    def get(self, url: str) -> tuple[int, bytes]:
        return self._open(urllib.request.Request(url))


class RateLimiter:
    """Sleeps before a request that would break any of ``LIMITS``."""

    def __init__(
        self,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.clock, self.sleep = clock, sleep
        self.sent: deque[float] = deque()

    def wait(self) -> None:
        for window, most in LIMITS:
            recent = [t for t in self.sent if t > self.clock() - window]
            if len(recent) >= most:
                self.sleep(recent[-most] + window - self.clock())
        self.sent.append(self.clock())
        while self.sent and self.sent[0] <= self.clock() - max(w for w, _ in LIMITS):
            self.sent.popleft()


class SpaceTrackSource:
    """``gp_history`` element sets with epochs from ``start`` to ``end`` (UTC dates, Space-Track's ``a--b`` range)."""

    def __init__(
        self,
        user: str,
        password: str,
        start: date,
        end: date,
        session: Session | None = None,
        cache_dir: Path = CACHE_DIR,
        limiter: RateLimiter | None = None,
    ) -> None:
        if not end > start:
            raise ValueError(f"end {end} must be after start {start}")
        self._user, self._password = user, password
        self.start, self.end = start, end
        self.session = session if session is not None else UrllibSession()
        self.cache_dir = Path(cache_dir)
        self.limiter = limiter if limiter is not None else RateLimiter()
        self._logged_in = False

    @classmethod
    def from_env(cls, start: date, end: date, **kwargs) -> SpaceTrackSource | None:
        """A source using ``SPACETRACK_USER``/``SPACETRACK_PASSWORD``, or ``None`` if either is unset."""
        user, password = os.environ.get("SPACETRACK_USER"), os.environ.get("SPACETRACK_PASSWORD")
        if not user or not password:
            return None
        return cls(user, password, start, end, **kwargs)

    def _login(self) -> None:
        self.limiter.wait()
        status, body = self.session.post(
            f"{BASE_URL}/ajaxauth/login", {"identity": self._user, "password": self._password}
        )
        # The open-source `spacetrack` client treats this body as a refused login.
        if status != 200 or b'"Login":"Failed"' in body:
            raise PermissionError(f"Space-Track login refused (HTTP {status})")
        self._logged_in = True

    def history(self, norad_id: int) -> list[ElementSet]:
        norad_id = int(norad_id)
        path = self.cache_dir / f"gp_history-{norad_id}-{self.start}--{self.end}.json"
        if path.is_file():
            return parse_omm_json(path.read_text(encoding="utf-8"))
        if not self._logged_in:
            self._login()
        url = (
            f"{BASE_URL}/basicspacedata/query/class/gp_history/NORAD_CAT_ID/{norad_id}"
            f"/EPOCH/{self.start}--{self.end}/orderby/EPOCH%20asc/format/json"
        )
        self.limiter.wait()
        status, body = self.session.get(url)
        if status != 200:
            raise RuntimeError(f"Space-Track gp_history for {norad_id}: HTTP {status}")
        text = body.decode("utf-8")
        records = parse_omm_json(text)
        if any(r.norad_id != norad_id for r in records):
            raise ValueError(f"Space-Track gp_history for {norad_id} returned other objects")
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".partial")
        partial.write_text(text, encoding="utf-8")
        partial.replace(path)
        return records

    def load(self, norad_ids: Iterable[int]) -> list[ElementSet]:
        return [r for norad in norad_ids for r in self.history(norad)]
