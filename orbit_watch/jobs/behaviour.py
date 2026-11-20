# Behaviour table of every GEO-region object: `belt` reads the element sets once for what the routine cache lacks
# (mode segments, every detected burn, daily drift rate); `table` joins it with the routine cache, builds the
# 12 features, the 10th-neighbour score and the top-5% "outside" flag, and writes them.

from __future__ import annotations

import argparse
import csv
import json
import pickle
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from orbit_watch import behaviour as bh
from orbit_watch.clean import drop_snapback_blocks
from orbit_watch.elements import parse_tle
from orbit_watch.events import HELD, burns, readable_segments
from orbit_watch.jobs.routine import event_days, satcat, write_csv
from orbit_watch.jobs.state_changes import commit
from orbit_watch.modes import N_DAYS, day_of, track
from orbit_watch.series import distinct_epochs
from orbit_watch.sources import data_dir
from orbit_watch.truth import load_splits

DEFAULT_OUT = Path("findings/behaviour")
DEFAULT_OBJECTS = Path("dataset/objects.csv")
FEATURE_FIELDS = ["rank", "norad_id", "name", "owner", "object_type", "tracked_days", *bh.FEATURES, "score", "outside"]
SHORT_FIELDS = ["norad_id", "object_type", "sets", "tracked_days"]


def object_pass(path: Path) -> dict:
    norad = int(path.stem)
    (recs,) = distinct_epochs(parse_tle(path.read_text(encoding="utf-8"))).values()
    kept, _ = drop_snapback_blocks(recs)
    out = {"norad": norad, "segments": [], "burns": np.array([]), "days": np.array([], dtype=np.int16),
           "rate": np.array([], dtype=np.float32)}
    if kept:
        tr = track(kept)
        dayi = np.floor(tr.days).astype(int)
        _, first = np.unique(dayi, return_index=True)
        ok = (dayi[first] >= 0) & (dayi[first] < N_DAYS)
        out.update(segments=readable_segments(tr), burns=burns(kept)[0], days=dayi[first][ok].astype(np.int16),
                   rate=tr.rate[first][ok].astype(np.float32))
    return out


def belt(geo_dir: Path, cache: Path) -> int:
    t0 = time.monotonic()
    manifest = json.loads((geo_dir / "manifest.json").read_text(encoding="utf-8"))
    holdout = {n for n, e in load_splits().items() if e["split"] == "holdout"}
    norads = sorted(int(n) for n, o in manifest["objects"].items() if o["by_rule"] and int(n) not in holdout)
    with ProcessPoolExecutor() as pool:
        objects = list(pool.map(object_pass, [geo_dir / f"{n}.tle" for n in norads], chunksize=4))
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump({**commit(), "objects": objects}, f)
    tmp.replace(cache)
    print(json.dumps({"objects": len(objects), "cache": str(cache), "run_seconds": round(time.monotonic() - t0, 1)}))
    return 0


def table(geo_dir: Path, cache: Path, routine_cache: Path, objects_csv: Path, out: Path) -> int:
    t0 = time.monotonic()
    mine = pickle.loads(cache.read_bytes())
    base = pickle.loads(routine_cache.read_bytes())
    extra = {o["norad"]: o for o in mine["objects"]}
    objects = base["objects"]
    if sorted(extra) != sorted(o["norad"] for o in objects):
        raise SystemExit("the behaviour cache and the routine cache hold different objects; rebuild one of them")
    sat = satcat(geo_dir)
    with open(objects_csv, newline="", encoding="utf-8") as fh:
        named = {int(r["norad_id"]): r for r in csv.DictReader(fh)}
    events = {o["norad"]: event_days(o["events"]) for o in objects}
    rows, short, mismatched = [], [], {"days": 0, "holds": 0}
    for o in objects:
        n, x = o["norad"], extra[o["norad"]]
        kind = sat.get(n, {}).get("OBJECT_TYPE") or ""
        tracked = o["last_day"] - o["first_day"]
        held = [(day_of(s.start), day_of(s.end)) for s in x["segments"] if s.mode in HELD]
        mismatched["days"] += not np.array_equal(x["days"], o["days"])
        mismatched["holds"] += len(held) != len(o["holds"]) or not np.allclose(held, o["holds"])
        if not bh.enough_data(o["sets"], o["first_day"], o["last_day"]):
            short.append({"norad_id": n, "object_type": kind, "sets": o["sets"], "tracked_days": round(tracked, 1)})
            continue
        f = bh.features(o["first_day"], o["last_day"], x["segments"], x["burns"],
                        sum(k == "relocation_start" for _, k in events[n]), o["days"], o["lon"], x["rate"], o["sma"])
        rows.append((n, kind, tracked, f))
    raw = np.array([f for *_, f in rows])
    if not np.isfinite(raw).all():
        raise SystemExit("a feature is not finite for an object that passes the data bar")
    score, _ = bh.kth_neighbour(bh.scaled(raw))
    is_out, cut = bh.outside_flags(score)
    out.mkdir(parents=True, exist_ok=True)
    order = sorted(range(len(rows)), key=lambda i: (-score[i], rows[i][0]))
    write_csv(out / "features.csv", FEATURE_FIELDS,
              [{"rank": r, "norad_id": rows[i][0], "name": named.get(rows[i][0], {}).get("name", ""),
                "owner": named.get(rows[i][0], {}).get("owner", ""), "object_type": rows[i][1],
                "tracked_days": round(rows[i][2], 1), **{k: round(float(v), 6) for k, v in zip(bh.FEATURES, rows[i][3])},
                "score": round(float(score[i]), 4), "outside": int(is_out[i])} for r, i in enumerate(order, 1)])
    write_csv(out / "not_enough_data.csv", SHORT_FIELDS, short)
    summary = {
        **commit(),
        "behaviour_cache_commit": mine["commit"],
        "routine_cache_commit": base["commit"],
        "objects": len(objects),
        "scored": len(rows),
        "not_enough_data": len(short),
        "min_sets": bh.MIN_SETS,
        "min_tracked_days": bh.MIN_TRACKED_DAYS,
        "neighbours": bh.NEIGHBOURS,
        "outside_share": bh.OUTSIDE_SHARE,
        "score_cut": round(cut, 4),
        "outside": int(is_out.sum()),
        "objects_whose_daily_samples_differ_from_the_routine_cache": mismatched["days"],
        "objects_whose_holds_differ_from_the_routine_cache": mismatched["holds"],
        "run_seconds": round(time.monotonic() - t0, 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(summary))
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Behaviour table of every GEO-region object: 12 features from the "
                                "pipeline, the distance to the 10th nearest object and the top-5% outside flag.")
    sub = p.add_subparsers(dest="step", required=True)
    b = sub.add_parser("belt", help="read every element set once and write the behaviour cache")
    t = sub.add_parser("table", help="build the features, scores and outside flags from both caches")
    t.add_argument("--routine-cache", type=Path, help="routine belt cache; default $ORBIT_WATCH_DATA/routine/belt.pkl")
    t.add_argument("--objects", type=Path, default=DEFAULT_OBJECTS,
                   help="object table with name and owner (default %(default)s)")
    t.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for the results (default %(default)s)")
    for q in (b, t):
        q.add_argument("--geo-dir", type=Path, help="folder of <norad>.tle files and manifest.json; "
                       "default $ORBIT_WATCH_DATA/geo")
        q.add_argument("--cache", type=Path, help="behaviour cache; default $ORBIT_WATCH_DATA/behaviour/belt.pkl")
    a = p.parse_args(argv)
    geo_dir = a.geo_dir or data_dir() / "geo"
    cache = a.cache or data_dir() / "behaviour" / "belt.pkl"
    if a.step == "belt":
        return belt(geo_dir, cache)
    return table(geo_dir, cache, a.routine_cache or data_dir() / "routine" / "belt.pkl", a.objects, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
