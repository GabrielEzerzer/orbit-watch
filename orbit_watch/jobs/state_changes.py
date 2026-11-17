# Dated station-keeping state changes of every GEO-region object, 2021-2025, from orbit_watch.events over the belt.
# Holdout objects and objects outside the rule are skipped before any file is opened.

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import time
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from orbit_watch.elements import parse_tle
from orbit_watch.events import EVENT_TYPES, ROW_FIELDS, Event, as_row, state_changes
from orbit_watch.series import distinct_epochs
from orbit_watch.sources import data_dir
from orbit_watch.truth import load_splits

YEARS = range(2021, 2026)
COMMIT_CSV_MAX_BYTES = 2_000_000
HERE = Path(__file__).resolve().parent


def object_events(path: Path) -> list[Event]:
    (recs,) = distinct_epochs(parse_tle(path.read_text(encoding="utf-8"))).values()
    return state_changes(recs)


def counts(events: Sequence[Event]) -> dict[str, dict[str, int]]:
    c = Counter((e.event_type, e.date.year) for e in events)
    return {t: {str(y): c[t, y] for y in YEARS} for t in EVENT_TYPES}


def write_events(events: Sequence[Event], path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=ROW_FIELDS, lineterminator="\n")
        w.writeheader()
        for e in events:
            w.writerow(as_row(e))
    return path.stat().st_size


def commit() -> dict:
    def git(*a):
        return subprocess.run(["git", *a], cwd=HERE, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"), "dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Dated station-keeping state changes of every GEO-region object, 2021-2025 "
                                "(orbit_watch.events over the belt).")
    p.add_argument("--geo-dir", type=Path, help="folder of <norad>.tle files and manifest.json; default $ORBIT_WATCH_DATA/geo")
    p.add_argument("--out", type=Path, help="folder for events.csv; default $ORBIT_WATCH_DATA/state_changes")
    p.add_argument("--summary-dir", type=Path, default=Path("findings/state_changes"))
    args = p.parse_args(argv)
    t0 = time.monotonic()
    source = commit()
    geo_dir = args.geo_dir or data_dir() / "geo"
    out = args.out or data_dir() / "state_changes"

    manifest = json.loads((geo_dir / "manifest.json").read_text(encoding="utf-8"))
    holdout = {n for n, e in load_splits().items() if e["split"] == "holdout"}
    in_region = sorted(int(n) for n, o in manifest["objects"].items() if o["by_rule"])
    not_by_rule = sorted(int(n) for n, o in manifest["objects"].items() if not o["by_rule"])
    skipped_holdout = sorted(n for n in in_region if n in holdout)
    norads = [n for n in in_region if n not in holdout]

    with ProcessPoolExecutor() as pool:
        found = [e for evs in pool.map(object_events, [geo_dir / f"{n}.tle" for n in norads], chunksize=8)
                 for e in evs]

    size = write_events(found, out / "events.csv")
    sd = args.summary_dir
    sd.mkdir(parents=True, exist_ok=True)
    committed = size <= COMMIT_CSV_MAX_BYTES
    if committed:
        write_events(found, sd / "events.csv")
    summary = {
        **source,
        "geo_dir_object_count": manifest["object_count"],
        "skipped_not_by_rule": not_by_rule,
        "skipped_holdout": skipped_holdout,
        "objects_processed": len(norads),
        "objects_with_events": len({e.norad_id for e in found}),
        "events": len(found),
        "events_by_type": dict(Counter(e.event_type for e in found)),
        "events_by_type_and_year": counts(found),
        "events_csv_bytes": size,
        "events_csv_committed": committed,
        "run_seconds": round(time.monotonic() - t0, 1),
    }
    (sd / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in summary.items() if k not in ("skipped_not_by_rule", "events_by_type_and_year")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
