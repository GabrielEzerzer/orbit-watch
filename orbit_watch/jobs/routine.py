# Routine score and irregularity rank of every GEO-region object: `belt` reads the element sets once (holds, daily
# longitude, steps outside holds, and with --as-of the event list and holds rebuilt on data cut at year-ends);
# `score` turns that cache and the published state-change list into the rank, the scored departures and the flags.

from __future__ import annotations

import argparse
import csv
import json
import math
import pickle
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

from orbit_watch import routine as rt
from orbit_watch.clean import drop_snapback_blocks
from orbit_watch.elements import parse_tle
from orbit_watch.events import as_row, burns, events_from_track, holds_of, state_changes
from orbit_watch.jobs.state_changes import commit
from orbit_watch.modes import GRID_END, GRID_START, N_DAYS, day_of, track
from orbit_watch.series import distinct_epochs
from orbit_watch.sources import data_dir
from orbit_watch.truth import load_splits, read_event_rows

AS_OF = (date(2022, 1, 1), date(2023, 1, 1), date(2024, 1, 1), date(2025, 1, 1))
DEFAULT_EVENTS = Path("findings/state_changes/events.csv")
DEFAULT_OUT = Path("findings/routine")
DEAD_TYPES = ("ROCKET BODY", "DEBRIS")
RANK_FIELDS = ["rank", "norad_id", "name", "owner", "bits_per_year", "stay_bits_per_year", "rate_bits_per_year",
               "departures_per_held_year", "held_years", "years_since_first_hold", "departures", "end_of_life",
               "off_routine", "overruns", "proximity_flags"]
DEPARTURE_FIELDS = ["norad_id", "name", "event_type", "date", "scored", "end_of_life", "model", "past_stays",
                    "past_departures", "held_years_before", "stay_days", "p", "bits", "off_routine"]
OVERRUN_FIELDS = ["norad_id", "name", "date", "arrival_date", "p99_stay_days", "past_stays"]
FLAG_FIELDS = ["norad_id", "name", "owner", "date", "other_norad_id", "other_name", "other_owner", "sep_deg",
               "sma_gap_km", "neighbours"]
UNRATED_FIELDS = ["norad_id", "name", "object_type", "held_years", "events", "steps_outside_holds_unchecked",
                  "proximity_flags"]
PRIOR_FIELDS = ["date", "belt_rate_per_held_year", "alpha", "beta_held_years", "objects", "held_years", "departures"]


def iso(day: float) -> str:
    return (GRID_START + timedelta(days=float(day))).date().isoformat()


def as_of(recs, cut: date) -> dict:
    part = [r for r in recs if r.epoch < datetime(cut.year, cut.month, cut.day, tzinfo=GRID_START.tzinfo)]
    if not part:
        return {"sets": 0}
    try:
        kept, _ = drop_snapback_blocks(part)
        return {"sets": len(part), "first_day": day_of(part[0].epoch), "last_day": day_of(part[-1].epoch),
                "holds": holds_of(track(kept)) if kept else [],
                "events": [(day_of(e.date), e.event_type) for e in state_changes(part)]}
    except Exception as ex:
        return {"sets": len(part), "error": repr(ex)}


def object_pass(task: tuple[Path, bool]) -> dict:
    path, cuts = task
    norad = int(path.stem)
    (recs,) = distinct_epochs(parse_tle(path.read_text(encoding="utf-8"))).values()
    kept, _ = drop_snapback_blocks(recs)
    out = {"norad": norad, "first_day": day_of(recs[0].epoch), "last_day": day_of(recs[-1].epoch), "sets": len(recs),
           "holds": [], "steps_outside": 0, "events": [], "days": np.array([], dtype=np.int16),
           "lon": np.array([], dtype=np.float32), "sma": np.array([], dtype=np.float32)}
    if kept:
        tr = track(kept)
        burn_days, steps = burns(kept)
        holds = holds_of(tr)
        dayi = np.floor(tr.days).astype(int)
        _, first = np.unique(dayi, return_index=True)
        ok = (dayi[first] >= 0) & (dayi[first] < N_DAYS)
        out.update(holds=holds, steps_outside=rt.outside(burn_days, holds),
                   events=[as_row(e) for e in events_from_track(tr, burn_days, steps)],
                   days=dayi[first][ok].astype(np.int16), lon=tr.lon[first][ok].astype(np.float32),
                   sma=tr.semi_major_axis_km[first][ok].astype(np.float32))
    if cuts:
        out["as_of"] = {c.isoformat(): as_of(recs, c) for c in AS_OF}
    return out


def belt(geo_dir: Path, cache: Path, cuts: bool) -> int:
    t0 = time.monotonic()
    manifest = json.loads((geo_dir / "manifest.json").read_text(encoding="utf-8"))
    holdout = {n for n, e in load_splits().items() if e["split"] == "holdout"}
    norads = sorted(int(n) for n, o in manifest["objects"].items() if o["by_rule"] and int(n) not in holdout)
    with ProcessPoolExecutor() as pool:
        objects = list(pool.map(object_pass, [(geo_dir / f"{n}.tle", cuts) for n in norads], chunksize=4))
    cache.parent.mkdir(parents=True, exist_ok=True)
    tmp = cache.with_suffix(".tmp")
    with open(tmp, "wb") as f:
        pickle.dump({**commit(), "as_of": cuts, "objects": objects}, f)
    tmp.replace(cache)
    errors = sum("error" in c for o in objects for c in o.get("as_of", {}).values())
    print(json.dumps({"objects": len(objects), "as_of_errors": errors, "cache": str(cache),
                      "run_seconds": round(time.monotonic() - t0, 1)}))
    return 0


def read_events(path: Path) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for r in read_event_rows(path)[1]:
        out[int(r["norad_id"])].append(r)
    return out


def event_days(rows: list[dict]) -> list[tuple[float, str]]:
    return [(day_of(date.fromisoformat(r["date"])), r["event_type"]) for r in rows]


def satcat(geo_dir: Path) -> dict[int, dict]:
    manifest = json.loads((geo_dir / "manifest.json").read_text(encoding="utf-8"))
    return {int(n): (o.get("satcat") or {}) for n, o in manifest["objects"].items()}


def run_scores(objects: list[dict], events: dict[int, list[tuple[float, str]]], end_day: float):
    holds = {o["norad"]: o["holds"] for o in objects}
    deps = {n: [d for d, k in evs if k in rt.SCORED] for n, evs in events.items()}
    priors = rt.belt_priors(holds, deps, end_day)
    at = rt.prior_lookup(priors)
    rows, overruns = {}, {}
    for o in objects:
        rows[o["norad"]], overruns[o["norad"]] = rt.score_object(o["norad"], events.get(o["norad"], []), o["holds"],
                                                                 o["first_day"], min(o["last_day"], end_day), at)
    return priors, rows, overruns


def daily_table(objects: list[dict]) -> tuple[np.ndarray, np.ndarray]:
    lon = np.full((len(objects), N_DAYS), np.nan, np.float32)
    sma = np.full((len(objects), N_DAYS), np.nan, np.float32)
    for k, o in enumerate(objects):
        lon[k, o["days"]] = o["lon"]
        sma[k, o["days"]] = o["sma"]
    return lon, sma


def flags(objects: list[dict], events: dict[int, list[tuple[float, str]]], sat: dict[int, dict]) -> list[rt.Flag]:
    lon, sma = daily_table(objects)
    norads = [o["norad"] for o in objects]
    owners = [sat.get(n, {}).get("COUNTRY") for n in norads]
    launches = [(sat.get(n, {}).get("INTLDES") or "")[:8] or None for n in norads]
    out = []
    for k, n in enumerate(norads):
        for d, kind in events.get(n, []):
            if kind == rt.ARRIVAL:
                f = rt.proximity(k, int(math.floor(d)), lon, sma, norads, owners, launches)
                if f is not None:
                    out.append(f)
    return out


def write_csv(path: Path, fields: list[str], rows) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = list(rows)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    return len(rows)


def _r(x: float | None, nd: int = 3) -> float | str:
    return "" if x is None else round(x, nd)


def score(geo_dir: Path, cache: Path, events_path: Path, out: Path) -> int:
    t0 = time.monotonic()
    belt_data = pickle.loads(cache.read_bytes())
    objects = belt_data["objects"]
    sat = satcat(geo_dir)
    name = {n: s.get("OBJECT_NAME") or "" for n, s in sat.items()}
    raw = read_events(events_path)
    events = {n: event_days(rs) for n, rs in raw.items()}
    end_day = float(N_DAYS)
    priors, rows, overruns = run_scores(objects, events, end_day)
    standings = {o["norad"]: rt.standing(o["norad"], rows[o["norad"]], overruns[o["norad"]], o["holds"],
                                         o["last_day"]) for o in objects}
    found = flags(objects, events, sat)
    flag_count = Counter(f.norad_id for f in found)
    order = rt.ranked(list(standings.values()))
    rank_rows = [{"rank": i, "norad_id": s.norad_id, "name": name.get(s.norad_id, ""),
                  "owner": sat.get(s.norad_id, {}).get("COUNTRY") or "", "bits_per_year": round(s.bits_per_year, 3),
                  "stay_bits_per_year": round(s.stay_bits_per_year, 3),
                  "rate_bits_per_year": round(s.rate_bits_per_year, 3),
                  "departures_per_held_year": round(s.departures_per_held_year, 3),
                  "held_years": round(s.held_years, 3), "years_since_first_hold": round(s.years, 3),
                  "departures": s.departures, "end_of_life": s.end_of_life, "off_routine": s.off_routine, "overruns": s.overruns,
                  "proximity_flags": flag_count[s.norad_id]} for i, s in enumerate(order, 1)]
    by_obj = {o["norad"]: o for o in objects}
    unrated = [{"norad_id": n, "name": name.get(n, ""), "object_type": sat.get(n, {}).get("OBJECT_TYPE") or "",
                "held_years": round(s.held_years, 3), "events": len(raw.get(n, [])),
                "steps_outside_holds_unchecked": by_obj[n]["steps_outside"], "proximity_flags": flag_count[n]}
               for n, s in sorted(standings.items()) if not s.rated]
    deps = [r for n in sorted(rows) for r in rows[n]]
    dep_rows = [{"norad_id": r.norad_id, "name": name.get(r.norad_id, ""), "event_type": r.event_type,
                 "date": iso(r.day), "scored": int(r.scored), "end_of_life": int(r.end_of_life), "model": r.model, "past_stays": r.past_stays,
                 "past_departures": r.past_departures, "held_years_before": round(r.held_years, 3),
                 "stay_days": _r(r.stay_days, 1), "p": _r(r.p, 6), "bits": _r(r.bits, 3),
                 "off_routine": int(r.off_routine)} for r in sorted(deps, key=lambda r: (r.day, r.norad_id))]
    ovs = sorted((o for n in overruns for o in overruns[n]), key=lambda o: (o.day, o.norad_id))
    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "rank.csv", RANK_FIELDS, rank_rows)
    write_csv(out / "unrated.csv", UNRATED_FIELDS, unrated)
    write_csv(out / "departures.csv", DEPARTURE_FIELDS, dep_rows)
    write_csv(out / "off_routine.csv", DEPARTURE_FIELDS, [r for r in dep_rows if r["off_routine"]])
    write_csv(out / "overruns.csv", OVERRUN_FIELDS,
              [{"norad_id": o.norad_id, "name": name.get(o.norad_id, ""), "date": iso(o.day),
                "arrival_date": iso(o.arrival_day), "p99_stay_days": round(o.p99_days, 1),
                "past_stays": o.past_stays} for o in ovs])
    write_csv(out / "flagged_arrivals.csv", FLAG_FIELDS,
              [{"norad_id": f.norad_id, "name": name.get(f.norad_id, ""), "owner": sat.get(f.norad_id, {}).get("COUNTRY") or "",
                "date": iso(f.day), "other_norad_id": f.other, "other_name": name.get(f.other, ""),
                "other_owner": sat.get(f.other, {}).get("COUNTRY") or "", "sep_deg": f.sep_deg,
                "sma_gap_km": f.sma_gap_km, "neighbours": f.neighbours} for f in sorted(found, key=lambda f: (f.day, f.norad_id))])
    write_csv(out / "belt_prior.csv", PRIOR_FIELDS,
              [{"date": iso(p.day), "belt_rate_per_held_year": round(p.rate, 5),
                "alpha": "inf" if not math.isfinite(p.alpha) else round(p.alpha, 4),
                "beta_held_years": "inf" if not math.isfinite(p.beta) else round(p.beta, 3), "objects": p.objects,
                "held_years": round(p.held_years, 2), "departures": p.departures} for p in priors])
    code_rows = {(int(r["norad_id"]), r["event_type"], r["date"]) for o in objects for r in o["events"]}
    csv_rows = {(n, r["event_type"], r["date"]) for n, rs in raw.items() for r in rs}
    scored = [r for r in deps if r.scored]
    arrivals = sum(k == rt.ARRIVAL for evs in events.values() for _, k in evs)
    summary = {
        **commit(),
        "belt_cache_commit": belt_data["commit"],
        "events_file": events_path.as_posix(),
        "events_file_rows": sum(map(len, raw.values())),
        "events_file_rows_not_rebuilt_by_this_code": len(csv_rows - code_rows),
        "events_rebuilt_not_in_file": len(code_rows - csv_rows),
        "objects": len(objects),
        "rated": len(order),
        "unrated": len(unrated),
        "unrated_never_held": sum(s.held_years == 0 for s in standings.values()),
        "rated_with_bits": sum(s.bits > 0 for s in order),
        "departures": len(deps),
        "departures_scored": len(scored),
        "departures_end_of_life_unscored": sum(r.end_of_life for r in deps),
        "departures_unscored_commissioning": sum(not r.scored and not r.end_of_life for r in deps),
        "scored_by_model": dict(Counter(r.model for r in scored)),
        "off_routine_departures": sum(r.off_routine for r in deps),
        "overruns": len(ovs),
        "arrivals": arrivals,
        "flagged_arrivals": len(found),
        "flagged_objects": len(flag_count),
        "belt_rate_per_held_year_at_end": round(priors[-1].rate, 4),
        "belt_rate_per_held_year_by_year": belt_rate_by_year(objects, events),
        "top_20": [{k: r[k] for k in ("rank", "norad_id", "name", "bits_per_year", "stay_bits_per_year",
                                      "rate_bits_per_year", "departures_per_held_year", "end_of_life",
                                      "proximity_flags")} for r in rank_rows[:20]],
        "run_seconds": round(time.monotonic() - t0, 1),
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in summary.items() if k != "top_20"}))
    return 0


def belt_rate_by_year(objects: list[dict], events: dict[int, list[tuple[float, str]]]) -> dict[str, float | None]:
    out = {}
    for y in range(GRID_START.year, GRID_END.year):
        lo, hi = day_of(date(y, 1, 1)), day_of(date(y + 1, 1, 1))
        h = sum(rt.held_years(o["holds"], hi, lo) for o in objects)
        k = sum(lo <= d < hi for evs in events.values() for d, kind in evs if kind in rt.SCORED)
        out[str(y)] = round(k / h, 4) if h else None
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Routine score and irregularity rank of every GEO-region object, from "
                                "its held spans and the published state-change list.")
    sub = p.add_subparsers(dest="step", required=True)
    b = sub.add_parser("belt", help="read every element set once and write the belt cache")
    b.add_argument("--as-of", action="store_true", help="also rebuild events and holds on data cut at the year-ends "
                   + ", ".join(c.isoformat() for c in AS_OF) + " (for the causality check)")
    s = sub.add_parser("score", help="score departures, rank objects and flag arrivals from the belt cache")
    s.add_argument("--events", type=Path, default=DEFAULT_EVENTS, help="state-change list (default %(default)s)")
    s.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for the results (default %(default)s)")
    for q in (b, s):
        q.add_argument("--geo-dir", type=Path, help="folder of <norad>.tle files and manifest.json; "
                       "default $ORBIT_WATCH_DATA/geo")
        q.add_argument("--cache", type=Path, help="belt cache; default $ORBIT_WATCH_DATA/routine/belt.pkl")
    a = p.parse_args(argv)
    geo_dir = a.geo_dir or data_dir() / "geo"
    cache = a.cache or data_dir() / "routine" / "belt.pkl"
    if a.step == "belt":
        return belt(geo_dir, cache, a.as_of)
    return score(geo_dir, cache, a.events, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
