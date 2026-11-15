"""Operating modes of every GEO-region object, 2021-2025 (``orbit_watch.modes`` over the belt).

    python -m orbit_watch.jobs.geo_modes --geo-dir data/geo --out data/geo_modes

Reads ``<geo-dir>/manifest.json`` and one ``<norad>.tle`` per object. Objects the manifest marks
``by_rule: false`` (LEO calibration satellites) are skipped, and so are holdout objects of
``groundtruth/splits.json``, taken from ``truth.load_splits`` before any file is opened.

Writes ``<out>/segments.csv`` (one row per mode segment; big, keep it under the git-ignored
``data/``) and, under ``--summary-dir`` (default ``findings/geo_modes``):

* ``year_end_counts.csv``: objects per mode in the segment that holds 31 December 12:00 UTC of
  each year 2021-2025; ``no_data`` counts objects whose history does not reach that instant;
* ``transitions_per_object.csv``: how many objects have 0, 1, 2, ... mode changes, counted over
  all segments and again with undetermined segments dropped (neighbours then merge);
* ``transition_types.csv``: mode changes by (from, to), both ways of counting;
* ``summary.json``: object counts, skips and the run time.
"""

from __future__ import annotations

import argparse
import csv
import json
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from orbit_watch.elements import parse_tle
from orbit_watch.modes import MODES, Segment, segments, track
from orbit_watch.series import to_series
from orbit_watch.truth import load_splits

YEARS = range(2021, 2026)
SEGMENT_FIELDS = ["norad_id", "start", "end", "mode", "windows", "n_sets", "lon_min", "lon_max",
                  "drift_mean", "inc_min", "inc_max"]


def object_segments(path: Path) -> list[Segment]:
    records = parse_tle(path.read_text(encoding="utf-8"))
    by_epoch = {r.epoch: r for r in records}  # same de-duplication as to_series: later wins
    recs = [by_epoch[e] for e in sorted(by_epoch)]
    to_series(recs)  # the holdout guard; raises truth.HoldoutError for a holdout object
    return segments(track(recs))


def year_end_counts(by_object: dict[int, list[Segment]]) -> dict[int, Counter]:
    out = {}
    for year in YEARS:
        t = datetime(year, 12, 31, 12, tzinfo=timezone.utc)
        c = Counter()
        for segs in by_object.values():
            c[next((s.mode for s in segs if s.start <= t < s.end), "no_data")] += 1
        out[year] = c
    return out


def without_undetermined(modes: list[str]) -> list[str]:
    """The mode sequence with undetermined segments dropped and equal neighbours merged."""
    out: list[str] = []
    for m in modes:
        if m != "undetermined" and (not out or out[-1] != m):
            out.append(m)
    return out


def transitions(by_object: dict[int, list[Segment]]) -> tuple[Counter, Counter, Counter, Counter]:
    per_all, per_det, types_all, types_det = Counter(), Counter(), Counter(), Counter()
    for segs in by_object.values():
        modes = [s.mode for s in segs]
        det = without_undetermined(modes)
        per_all[len(modes) - 1] += 1
        per_det[max(len(det) - 1, 0)] += 1
        types_all.update(zip(modes, modes[1:]))
        types_det.update(zip(det, det[1:]))
    return per_all, per_det, types_all, types_det


def _fmt(x: float) -> str:
    return "" if x != x else f"{x:.4f}"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--geo-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True, help="directory for segments.csv (git-ignored)")
    p.add_argument("--summary-dir", type=Path, default=Path("findings/geo_modes"))
    args = p.parse_args(argv)
    t0 = time.monotonic()

    manifest = json.loads((args.geo_dir / "manifest.json").read_text(encoding="utf-8"))
    holdout = {n for n, e in load_splits().items() if e["split"] == "holdout"}
    in_region = sorted(int(n) for n, o in manifest["objects"].items() if o["by_rule"])
    not_by_rule = sorted(int(n) for n, o in manifest["objects"].items() if not o["by_rule"])
    skipped_holdout = sorted(n for n in in_region if n in holdout)
    norads = [n for n in in_region if n not in holdout]

    with ProcessPoolExecutor() as pool:
        results = pool.map(object_segments, [args.geo_dir / f"{n}.tle" for n in norads], chunksize=8)
        by_object = dict(zip(norads, results))

    args.out.mkdir(parents=True, exist_ok=True)
    with open(args.out / "segments.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=SEGMENT_FIELDS)
        w.writeheader()
        for segs in by_object.values():
            for s in segs:
                row = asdict(s)
                row["start"], row["end"] = s.start.date().isoformat(), s.end.date().isoformat()
                w.writerow({k: _fmt(v) if isinstance(v, float) else v for k, v in row.items()})

    sd = args.summary_dir
    sd.mkdir(parents=True, exist_ok=True)
    counts = year_end_counts(by_object)
    with open(sd / "year_end_counts.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["mode", *YEARS])
        for m in (*MODES, "no_data"):
            w.writerow([m, *(counts[y][m] for y in YEARS)])
    per_all, per_det, types_all, types_det = transitions(by_object)
    with open(sd / "transitions_per_object.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["transitions", "objects_all_segments", "objects_ignoring_undetermined"])
        for k in range(max(max(per_all), max(per_det)) + 1):
            if per_all[k] or per_det[k]:
                w.writerow([k, per_all[k], per_det[k]])
    with open(sd / "transition_types.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["from", "to", "count_all_segments", "count_ignoring_undetermined"])
        for a, b in sorted(set(types_all) | set(types_det), key=lambda k: -types_all[k]):
            w.writerow([a, b, types_all[a, b], types_det[a, b]])
    summary = {
        "geo_dir_object_count": manifest["object_count"],
        "skipped_not_by_rule": not_by_rule,
        "skipped_holdout": skipped_holdout,
        "objects_classified": len(by_object),
        "segments": sum(len(s) for s in by_object.values()),
        "transitions_all_segments": sum(types_all.values()),
        "transitions_ignoring_undetermined": sum(types_det.values()),
        "run_seconds": round(time.monotonic() - t0, 1),
    }
    (sd / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
