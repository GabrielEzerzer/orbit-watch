# Fetch Space-Track gp_history for the satellites in the generalisation run, once each, over their log spans.
# Prints only counts and file sizes, never the environment.

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta

from orbit_watch.spacetrack import RateLimiter, SpaceTrackSource

PAD_DAYS = 10
TODAY = date(2026, 11, 14)

SPANS = {
    54754: (date(2023, 1, 11), date(2026, 11, 5)),
    41240: (date(2016, 1, 19), date(2026, 10, 22)),
    42917: (date(2017, 10, 16), date(2026, 10, 23)),
    62876: (date(2025, 8, 2), date(2026, 10, 30)),
    36508: (date(2010, 4, 15), date(2026, 10, 30)),
    27421: (date(2002, 5, 7), date(2015, 12, 9)),
}


def span(norad: int) -> tuple[date, date]:
    first, last = SPANS[norad]
    return first - timedelta(days=PAD_DAYS), min(last + timedelta(days=PAD_DAYS), TODAY)


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("norad", type=int, nargs="*", help="NORAD ids to fetch (default: every object in SPANS)")
    wanted = p.parse_args(argv).norad or list(SPANS)
    limiter = RateLimiter()
    for norad in wanted:
        start, end = span(norad)
        source = SpaceTrackSource.from_env(start, end, limiter=limiter)
        if source is None:
            print("SPACETRACK_USER / SPACETRACK_PASSWORD not set; run through hush run")
            return 2
        records = source.history(norad)
        path = source.cache_dir / f"gp_history-{norad}-{start}--{end}.json"
        print(f"{norad}: {len(records)} element sets, {path.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
