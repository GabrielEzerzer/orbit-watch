"""CelesTrak downloads: current GP element sets, and the polite fetch-and-cache they share.

CelesTrak blocks clients that download the same data again and again
(https://celestrak.org/usage-policy.php). So every download here goes through ``cached_fetch``:
the body is kept under ``data/celestrak/<UTC date>/<query key>`` and a query already cached
today is read from disk, never fetched again. Requests carry a generic User-Agent with no
personal details, and any non-200 answer raises, which stops the caller at the first error.
"""

from __future__ import annotations

import urllib.request
from collections.abc import Callable, Iterable
from datetime import date, datetime, timezone
from pathlib import Path

from orbit_watch.elements import ElementSet, parse_omm_json

USER_AGENT = "orbit-watch/0.1 (research prototype)"
GP_URL = "https://celestrak.org/NORAD/elements/gp.php"
CACHE_DIR = Path(__file__).resolve().parents[1] / "data" / "celestrak"
NO_DATA = "No GP data found"  # CelesTrak's plain-text answer for a query that matches nothing

Fetch = Callable[[str], bytes]  # URL -> response body


def http_get(url: str) -> bytes:
    """GET ``url`` with our User-Agent; raises on anything but HTTP 200."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:  # raises HTTPError on 4xx/5xx
        if response.status != 200:
            raise RuntimeError(f"{url}: HTTP {response.status}")
        return response.read()


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def cached_fetch(
    url: str,
    key: str,
    parse: Callable[[bytes], object],
    *,
    cache_dir: Path = CACHE_DIR,
    fetch: Fetch = http_get,
    today: Callable[[], date] = utc_today,
):
    """``parse(body)`` for ``url``, downloading it at most once per UTC day.

    The body is written to the cache only after ``parse`` accepts it, so a bad answer is never
    served from disk later. Returns what ``parse`` returns.
    """
    path = cache_dir / today().isoformat() / key
    if path.is_file():
        return parse(path.read_bytes())
    body = fetch(url)
    parsed = parse(body)
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".partial")
    partial.write_bytes(body)
    partial.replace(path)
    return parsed


def parse_gp_json(body: bytes) -> list[ElementSet]:
    text = body.decode("utf-8")
    if text.strip() == NO_DATA:
        return []
    return parse_omm_json(text)


class CelesTrakSource:
    """Current GP element sets from CelesTrak ``gp.php`` (``FORMAT=json``), cached per UTC day.

    ``load`` makes one ``CATNR`` query per object; ``group`` one ``GROUP`` query. Pass ``fetch``
    to replace the network (tests do).
    """

    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        fetch: Fetch = http_get,
        today: Callable[[], date] = utc_today,
    ) -> None:
        self.cache_dir, self.fetch, self.today = Path(cache_dir), fetch, today

    def _query(self, param: str, value: str) -> list[ElementSet]:
        if not value.replace("-", "").isalnum():
            raise ValueError(f"unexpected {param} value {value!r}")
        return cached_fetch(
            f"{GP_URL}?{param}={value}&FORMAT=json",
            f"gp-{param}-{value}.json",
            parse_gp_json,
            cache_dir=self.cache_dir,
            fetch=self.fetch,
            today=self.today,
        )

    def load(self, norad_ids: Iterable[int]) -> list[ElementSet]:
        records: list[ElementSet] = []
        for norad in norad_ids:
            got = self._query("CATNR", str(int(norad)))
            if any(r.norad_id != norad for r in got):
                raise ValueError(f"CelesTrak CATNR={norad} answered with other objects")
            records.extend(got)
        return records

    def group(self, name: str) -> list[ElementSet]:
        """Every object in a CelesTrak group, e.g. ``"stations"`` or ``"active"``."""
        return self._query("GROUP", name)
