# Fetch Space-Track gp_history 2021-01-01..2026-01-01 for the objects added in splits.json.
# Prints only counts and file sizes, never the environment.

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from orbit_watch.spacetrack import RateLimiter, SpaceTrackSource
from orbit_watch.truth import load_splits

START, END = date(2021, 1, 1), date(2026, 1, 1)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fetch Space-Track gp_history 2021-01-01..2026-01-01 for the objects added in splits.json.")
    p.add_argument("--cache-dir", type=Path, help="default: $ORBIT_WATCH_DATA/spacetrack")
    args = p.parse_args(argv)
    source = SpaceTrackSource.from_env(START, END, cache_dir=args.cache_dir, limiter=RateLimiter())
    if source is None:
        print("SPACETRACK_USER / SPACETRACK_PASSWORD not set; run through hush run")
        return 2
    for norad, entry in load_splits().items():
        if entry["previously_scored"]:
            continue
        records = source.history(norad)
        path = source.cache_dir / f"gp_history-{norad}-{START}--{END}.json"
        print(f"{norad} {entry['name']}: {len(records)} element sets, {path.stat().st_size / 1e6:.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
