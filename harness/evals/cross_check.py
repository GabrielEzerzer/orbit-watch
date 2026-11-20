# Independent cross-check of the state-change list and the routine rank against public sources not used to
# build them: `sample` fixes the objects to research before any search, `verify` checks every quote against
# the saved page copies, and `score` matches the claims to the list with the cited-event rule.

from __future__ import annotations

import argparse
import csv
import random
import sys
from pathlib import Path

from orbit_watch.truth import GROUNDTRUTH

RANK = Path("findings/routine/rank.csv")
UNRATED = Path("findings/routine/unrated.csv")
EVENTS = Path("findings/state_changes/events.csv")
SAMPLE = GROUNDTRUTH / "cross_check_sample.csv"
CITED = tuple(GROUNDTRUTH / n for n in ("geo_events.csv", "irregular_objects.csv", "steady_objects.csv"))
SEED = "orbit-watch cross-check 2026-11-20"
TOP_N = 30
DRAWN_N = 20
SAMPLE_FIELDS = ["norad_id", "name", "group", "rank", "already_cited", "sources_found", "searches"]


def _rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def draw_sample(rank: list[dict], unrated: list[dict], event_norads: set[int], cited: set[int]) -> list[dict]:
    names = {int(r["norad_id"]): r["name"] for r in (*rank, *unrated)}
    ranks = {int(r["norad_id"]): int(r["rank"]) for r in rank}
    top = [int(r["norad_id"]) for r in sorted(rank, key=lambda r: int(r["rank"]))[:TOP_N]]
    pool = sorted(event_norads - set(top))
    drawn = random.Random(SEED).sample(pool, DRAWN_N)
    return [{"norad_id": n, "name": names[n], "group": group, "rank": ranks.get(n, ""),
             "already_cited": int(n in cited), "sources_found": "", "searches": ""}
            for group, ns in (("top30", top), ("drawn", drawn)) for n in ns]


def cited_norads(paths=CITED) -> set[int]:
    return {int(r["norad_id"]) for p in paths for r in _rows(p)}


def sample_rows() -> list[dict]:
    return draw_sample(_rows(RANK), _rows(UNRATED), {int(r["norad_id"]) for r in _rows(EVENTS)}, cited_norads())


def write_sample(path: Path = SAMPLE) -> list[dict]:
    rows = sample_rows()
    if path.is_file():
        kept = {int(r["norad_id"]): r for r in _rows(path)}
        for r in rows:
            old = kept.get(r["norad_id"], {})
            r["sources_found"], r["searches"] = old.get("sources_found", ""), old.get("searches", "")
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SAMPLE_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return rows


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Cross-check the state-change list and the routine rank against "
                                "independent public sources.")
    cmd = p.add_subparsers(dest="cmd", required=True)
    cmd.add_parser("sample", help=f"write {SAMPLE.name}: the top {TOP_N} of the rank and {DRAWN_N} objects drawn "
                   "with a fixed seed from the other objects on the event list")
    a = p.parse_args(argv)
    if a.cmd == "sample":
        rows = write_sample()
        print(f"wrote {len(rows)} objects to {SAMPLE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
