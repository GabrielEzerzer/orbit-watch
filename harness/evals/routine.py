# Checks of the routine score and irregularity rank: dead objects, logged keepers, cited departures, a planted
# rhythm test in held satellites' element sets, stability across the period, as-of reruns on cut data, cited
# irregular and steady objects, and the hand-audit sample with one chart per object.

from __future__ import annotations

import argparse
import csv
import json
import pickle
import random
import sys
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from datetime import date, datetime, timedelta
from math import log
from pathlib import Path

import numpy as np

from harness.evals.mode_events import DEFAULT_EVENTS, Event, _commit, load_events
from harness.evals.state_changes import KEPT_OBJECTS, kept_station, object_records, score
from harness.evals.state_injection import Host, Plant, drift_base, load_hosts, smooth
from orbit_watch import routine as rt
from orbit_watch.clean import drop_snapback_blocks
from orbit_watch.events import Event as Found, burns, state_changes
from orbit_watch.jobs.routine import (AS_OF, DEAD_TYPES, N_DAYS, day_of, holds_of, iso, read_events, run_scores,
                                      satcat)
from orbit_watch.modes import GRID_START, SIDEREAL_REV_PER_DAY, track
from orbit_watch.sources import data_dir
from orbit_watch.truth import GROUNDTRUTH, load_splits, read_event_rows

OUT = Path("findings/routine")
IRREGULAR = GROUNDTRUTH / "irregular_objects.csv"
STEADY = GROUNDTRUTH / "steady_objects.csv"
CITED_FIELDS = ("norad_id", "name", "claim", "source_url", "quote", "evidence")
EVIDENCE = ("object", "programme")
SPLIT_DAY = date(2023, 7, 1)
STABLE_TOP, STABLE_WIDE = 30, 60
TOP_SHARE = 0.05
HELD_BEFORE_YEARS = 1.0
AS_OF_HELD_SHARE = 0.9
SEED = 20261119
TRIALS = 100
VARIANTS = {"3+1": 3, "4+1": 4}
STAY_DAYS = (45.0, 120.0)
RATE_DEG_DAY = (0.1, 1.0)
DISTANCE_DEG = (1.0, 10.0)
MOVE_DAYS = (2.0, 60.0)
JITTER = 0.05
OFF_FACTOR = (1.6, 2.5)
LEAD_DAYS = 60.0
SETTLE_DAYS = 60.0
ON_MAX_BITS = 2.0
AUDIT_TOP, AUDIT_MIDDLE = 30, 20
AUDIT_SEED = "orbit-watch routine audit 2026-11-19"
TRIAL_FIELDS = ["trial", "variant", "split", "norad_id", "rhythm", "stay_days", "last_stay_days", "move_days",
                "drift_rate", "rhythm_caught", "caught", "found_date", "scored", "model", "past_stays", "bits"]


def rows_of(path: Path) -> list[dict]:
    return read_event_rows(path)[1]


def load(out: Path, geo_dir: Path, cache: Path) -> dict:
    belt = pickle.loads(cache.read_bytes())
    return {"rank": rows_of(out / "rank.csv"), "departures": rows_of(out / "departures.csv"),
            "overruns": rows_of(out / "overruns.csv"), "sat": satcat(geo_dir), "belt": belt,
            "objects": {o["norad"]: o for o in belt["objects"]}}


def off_rows(d: dict) -> list[tuple[int, float, str]]:
    deps = [(int(r["norad_id"]), day_of(date.fromisoformat(r["date"])), r["event_type"])
            for r in d["departures"] if r["off_routine"] == "1"]
    return deps + [(int(r["norad_id"]), day_of(date.fromisoformat(r["date"])), "overrun") for r in d["overruns"]]


def dead_objects(d: dict) -> dict:
    dead = {n for n, o in d["objects"].items() if d["sat"].get(n, {}).get("OBJECT_TYPE") in DEAD_TYPES}
    years = sum((min(d["objects"][n]["last_day"], N_DAYS) - max(d["objects"][n]["first_day"], 0.0)) / rt.YEAR_DAYS
                for n in dead)
    rows = [r for r in off_rows(d) if r[0] in dead]
    rated = [int(r["norad_id"]) for r in d["rank"] if int(r["norad_id"]) in dead]
    return {"objects": len(dead), "object_years": round(years, 1), "rated": len(rated), "off_routine_rows": len(rows),
            "per_object_year": round(len(rows) / years, 4) if years else None, "target_per_object_year": 0.01,
            "rows": [{"norad_id": n, "date": iso(day), "kind": k} for n, day, k in rows]}


def logged_keepers(d: dict, geo_dir: Path) -> dict:
    rows = off_rows(d)
    per, years, total = {}, 0.0, 0
    for norad, (name, log_path) in KEPT_OBJECTS.items():
        st = kept_station(norad, name, log_path, object_records(geo_dir / f"{norad}.tle"))
        spans = [(day_of(lo), day_of(hi)) for lo, hi in st.spans]
        inside = [r for r in rows if r[0] == norad and any(lo <= r[1] < hi for lo, hi in spans)]
        deps = [r for r in d["departures"] if int(r["norad_id"]) == norad
                and any(lo <= day_of(date.fromisoformat(r["date"])) < hi for lo, hi in spans)]
        y = sum(hi - lo for lo, hi in spans) / rt.YEAR_DAYS
        per[name] = {"norad_id": norad, "object_years": round(y, 3), "off_routine_rows": len(inside),
                     "departures_listed": len(deps)}
        years += y
        total += len(inside)
    return {"objects": per, "object_years": round(years, 2), "off_routine_rows": total, "target": 0}


def as_found(r: dict) -> Found:
    def dt(s: str) -> datetime:
        x = date.fromisoformat(s)
        return datetime(x.year, x.month, x.day, tzinfo=GRID_START.tzinfo)

    def num(s: str) -> float:
        return float(s) if s else float("nan")
    return Found(int(r["norad_id"]), r["event_type"], dt(r["date"]), r["signal"], float(r["size"]),
                 num(r["lon_before"]), num(r["lon_after"]), r["mode_before"], r["mode_after"], dt(r["mode_change"]))


def cited_departures(d: dict, events_csv: Path, splits: Sequence[str]) -> dict:
    cited = [e for e in load_events(DEFAULT_EVENTS) if e.split in splits and e.event_type in rt.DEPARTURES]
    holdout = {n for n, e in load_splits().items() if e["split"] == "holdout"}
    found = {n: [as_found(r) for r in rows] for n, rows in read_events(events_csv).items()}
    eligible, skipped = [], []
    for e in cited:
        o = d["objects"].get(e.norad_id)
        held = rt.held_years(o["holds"], day_of(e.date)) if o else 0.0
        (eligible if held >= HELD_BEFORE_YEARS and e.norad_id not in holdout else skipped).append((e, held))
    results = score([e for e, _ in eligible], defaultdict(list, found), {e.norad_id for e, _ in eligible}, holdout)
    deps = {(int(r["norad_id"]), r["date"], r["event_type"]): r for r in d["departures"]}
    out = []
    for r, (_, held) in zip(results, eligible):
        row = deps.get((r.found.norad_id, r.found.date.date().isoformat(), r.found.event_type)) if r.found else None
        out.append({"event_id": r.event.event_id, "split": r.event.split, "held_years_before": round(held, 2),
                    "status": r.status, "found_date": r.found.date.date().isoformat() if r.found else "",
                    "scored": bool(row and row["scored"] == "1"), "model": row["model"] if row else "",
                    "bits": float(row["bits"]) if row and row["bits"] else None,
                    "flagged": bool(row and row["off_routine"] == "1")})
    summary = {}
    for split in splits:
        rs = [x for x in out if x["split"] == split]
        caught = [x for x in rs if x["status"] == "caught"]
        summary[split] = {"cited_departures": sum(e.split == split for e in cited),
                          "held_a_year_before": len(rs), "caught": len(caught),
                          "flagged": sum(x["flagged"] for x in caught),
                          "caught_unscored": sum(not x["scored"] for x in caught),
                          "flagged_by_model": {m: [sum(x["flagged"] for x in caught if x["model"] == m),
                                                   sum(x["model"] == m for x in caught)] for m in ("stays", "rate")}}
    return {**summary, "events": out}


def window_values(d: dict, rows, overruns, lo: float, hi: float, objects: dict) -> dict[int, float]:
    out = {}
    for n, o in objects.items():
        s = rt.standing(n, rows[n], overruns[n], o["holds"], o["last_day"], lo, hi)
        if s.rated:
            out[n] = s.bits_per_year
    return out


def order(values: dict[int, float]) -> list[int]:
    return sorted(values, key=lambda n: (-values[n], n))


def full_scores(d: dict, events_csv: Path):
    events = {n: [(day_of(date.fromisoformat(r["date"])), r["event_type"]) for r in rs]
              for n, rs in read_events(events_csv).items()}
    return run_scores(list(d["objects"].values()), events, float(N_DAYS))


def stability(d: dict, rows, overruns) -> dict:
    cut = day_of(SPLIT_DAY)
    first = window_values(d, rows, overruns, 0.0, cut, d["objects"])
    second = window_values(d, rows, overruns, cut, float(N_DAYS), d["objects"])
    both = set(first) & set(second)
    a = order({n: first[n] for n in both if first[n] > 0})
    b = order({n: second[n] for n in both if second[n] > 0})
    hit, n = rt.overlap(a, b, STABLE_TOP, STABLE_WIDE)
    return {"periods": [f"2021-01-01..{SPLIT_DAY}", f"{SPLIT_DAY}..2025-12-31"], "rated_in_both": len(both),
            "with_bits_first": sum(first[x] > 0 for x in both), "with_bits_second": sum(second[x] > 0 for x in both),
            f"top_{STABLE_TOP}_first_in_top_{STABLE_WIDE}_second": hit, "of": n,
            "spearman": rt.spearman([first[x] for x in sorted(both)], [second[x] for x in sorted(both)])}


def causality(d: dict, rows, overruns) -> dict:
    if not d["belt"].get("as_of"):
        return {"status": "belt cache built without --as-of"}
    final = {n: rt.standing(n, rows[n], overruns[n], o["holds"], o["last_day"]) for n, o in d["objects"].items()}
    out = {}
    for c in AS_OF:
        key, end = c.isoformat(), day_of(c)
        objs = {o["norad"]: {"norad": o["norad"], **o["as_of"][key]} for o in d["belt"]["objects"]
                if o["as_of"][key].get("sets") and "error" not in o["as_of"][key]}
        errors = sum("error" in o["as_of"][key] for o in d["belt"]["objects"])
        events = {n: o["events"] for n, o in objs.items()}
        _, crow, cover = run_scores(list(objs.values()), events, end)
        bar = min(rt.MIN_HELD_YEARS, AS_OF_HELD_SHARE * end / rt.YEAR_DAYS)
        asof, trunc, gap = {}, {}, {}
        for n, o in objs.items():
            s = rt.standing(n, crow[n], cover[n], o["holds"], o["last_day"], hi=end)
            if s.held_years >= bar and n in d["objects"]:
                full = d["objects"][n]
                t = rt.standing(n, rows[n], overruns[n], full["holds"], full["last_day"], hi=end)
                asof[n], trunc[n], gap[n] = s.bits_per_year, t.bits_per_year, abs(s.bits - t.bits)
        ids = sorted(asof)
        out[key] = {"held_years_bar": round(bar, 2), "objects": len(ids), "errors": errors,
                    "with_bits_as_of": sum(asof[n] > 0 for n in ids),
                    "spearman_vs_full_run_cut_at_same_date": _round(rt.spearman([asof[n] for n in ids],
                                                                                [trunc[n] for n in ids])),
                    "spearman_vs_full_run_final": _round(rt.spearman([asof[n] for n in ids],
                                                                     [final[n].bits_per_year for n in ids])),
                    "objects_whose_bits_differ_from_full_run_cut_by_0.1_or_more": sum(gap[n] >= 0.1 for n in ids),
                    "largest_bits_difference": round(max(gap.values(), default=0.0), 3),
                    "largest_bits_per_year_difference": round(max((abs(asof[n] - trunc[n]) for n in ids),
                                                                  default=0.0), 3)}
    return out


def _round(x: float | None) -> float | None:
    return None if x is None else round(x, 3)


def read_cited(path: Path) -> list[tuple[int, str]]:
    rows = rows_of(path)
    missing = [f for f in CITED_FIELDS if rows and f not in rows[0]]
    if missing:
        raise ValueError(f"{path}: missing columns {missing}")
    bad = sorted({r["evidence"] for r in rows} - set(EVIDENCE))
    if bad:
        raise ValueError(f"{path}: evidence must be one of {EVIDENCE}, found {bad}")
    return [(int(r["norad_id"]), r["evidence"]) for r in rows]


def _top(values: dict[int, float], ids: Sequence[int]) -> dict:
    hit, n = rt.top_share(values, ids, TOP_SHARE)
    return {"listed": len(ids), "rateable": n, f"in_top_{int(TOP_SHARE * 100)}_percent": hit,
            "share": round(hit / n, 3) if n else None}


def _shown(path: Path) -> str:
    repo = GROUNDTRUTH.parent
    full = path.resolve()
    return full.relative_to(repo).as_posix() if full.is_relative_to(repo) else path.name


def cited_lists(rank: Sequence[dict], irregular: Path | None, steady: Path | None) -> dict:
    values = {int(r["norad_id"]): float(r["bits_per_year"]) for r in rank}
    out = {}
    if irregular is not None and irregular.is_file():
        rows = read_cited(irregular)
        out["irregular"] = {"file": _shown(irregular), **_top(values, [n for n, _ in rows]),
                            "evidence_object": _top(values, [n for n, e in rows if e == "object"])}
    if steady is not None and steady.is_file():
        ids = [n for n, _ in read_cited(steady)]
        hit, n = rt.lower_half(values, ids)
        out["steady"] = {"file": _shown(steady), "listed": len(ids), "rateable": n, "in_lower_half": hit,
                         "share": round(hit / n, 3) if n else None}
    return out or {"status": "no cited irregular or steady list yet"}


def checks(a, geo_dir: Path, cache: Path) -> int:
    d = load(a.out, geo_dir, cache)
    splits = ("dev", "test") if a.split == "all" else ("dev",)
    _, rows, overruns = full_scores(d, a.events)
    result = {**_commit(), "events_file": a.events.as_posix(), "splits": list(splits),
              "dead_objects": dead_objects(d), "logged_keepers": logged_keepers(d, geo_dir),
              "cited_departures": cited_departures(d, a.events, splits), "stability": stability(d, rows, overruns),
              "causality": causality(d, rows, overruns),
              "cited_lists": cited_lists(d["rank"], a.irregular, a.steady)}
    path = a.out / f"checks_{a.split}.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    brief = {k: v for k, v in result.items() if k not in ("dead_objects", "cited_departures")}
    brief["dead_objects"] = {k: v for k, v in result["dead_objects"].items() if k != "rows"}
    brief["cited_departures"] = {k: v for k, v in result["cited_departures"].items() if k != "events"}
    print(json.dumps(brief, indent=1))
    print(f"wrote {path}")
    return 0


def _log_uniform(rng, lo: float, hi: float) -> float:
    return float(np.exp(rng.uniform(log(lo), log(hi))))


def draw(rng, trial: int, variant: str, on: bool, hosts: Sequence[Host]) -> dict:
    n = VARIANTS[variant]
    for _ in range(1000):
        h = hosts[int(rng.integers(len(hosts)))]
        stay = _log_uniform(rng, *STAY_DAYS)
        rate = _log_uniform(rng, *RATE_DEG_DAY) * rng.choice((-1.0, 1.0))
        move = float(np.clip(_log_uniform(rng, *DISTANCE_DEG) / abs(rate), *MOVE_DAYS))
        stays = [stay * (1 + rng.uniform(-JITTER, JITTER)) for _ in range(n - 1)]
        factor = 1 + rng.uniform(-JITTER, JITTER) if on else _log_uniform(rng, *OFF_FACTOR) ** rng.choice((-1, 1))
        stays.append(stay * factor)
        span = LEAD_DAYS + (n + 1) * move + sum(stays) + SETTLE_DAYS
        end = min(h.end, h.last_day)
        if end - h.start < span:
            continue
        t = float(rng.uniform(h.start + LEAD_DAYS, end - span + LEAD_DAYS))
        moves = []
        for i in range(n + 1):
            moves.append((t, move, rate * (-1) ** i))
            t += move + (stays[i] if i < n else 0.0)
        return {"trial": trial, "variant": variant, "split": h.split, "norad_id": h.norad_id, "host": h,
                "rhythm": "on" if on else "off", "stay": stay, "last_stay": stays[-1], "move": move, "rate": rate,
                "moves": moves}
    raise ValueError("no host fits a rhythm plant")


def plan(hosts: Sequence[Host], splits: Sequence[str]) -> list[dict]:
    out = []
    for v, variant in enumerate(VARIANTS):
        for s, split in enumerate(("dev", "test")):
            rng = np.random.default_rng([SEED, v, s])
            pool = [h for h in hosts if h.split == split]
            for i in range(TRIALS):
                t = draw(rng, len(out), variant, i % 2 == 0, pool)
                if split in splits:
                    out.append(t)
    return out


def plant_moves(records, tr, sm, norad: int, moves: Sequence[tuple[float, float, float]]):
    d = tr.days
    delta, rate = np.zeros(len(d)), tr.rate.copy()
    shift = 0.0
    for t0, days, r in moves:
        lon0, rate0 = drift_base(d, sm, Plant(0, "relocation", norad, "", t0, r, days))
        sel = (d >= t0) & (d < t0 + days)
        delta[sel] = lon0 + shift + (rate0 + r) * (d[sel] - t0) + sm.lon_res[sel] - sm.lon[sel]
        rate[sel] = rate0 + r + sm.offset + sm.rate_res[sel]
        shift += r * days
        delta[d >= t0 + days] = shift
    out = []
    for rec, dl, rt_, d0 in zip(records, delta, rate, d):
        if d0 < moves[0][0]:
            out.append(rec)
            continue
        n = SIDEREAL_REV_PER_DAY + rt_ / 360.0
        out.append(replace(rec, mean_motion=n, mean_anomaly=float((rec.mean_anomaly + dl) % 360.0),
                           semi_major_axis_km=rec.semi_major_axis_km * (rec.mean_motion / n) ** (2.0 / 3.0)))
    return out


def _truth(norad: int, trial: int, k: int, day: float) -> Event:
    return Event(f"{trial}-{k}", norad, "relocation_start", (GRID_START + timedelta(days=float(day))).date(), "dev")


def run_trials(task) -> list[dict]:
    path, host, trials, priors = task
    records = object_records(path)
    tr = track(records)
    sm = smooth(tr, burns(records)[0], host)
    at = rt.prior_lookup(priors)
    first, last = day_of(records[0].epoch), day_of(records[-1].epoch)
    out = []
    for t in trials:
        planted = plant_moves(records, tr, sm, host.norad_id, t["moves"])
        found = state_changes(planted)
        kept, _ = drop_snapback_blocks(planted)
        holds = holds_of(track(kept))
        rows, _ = rt.score_object(host.norad_id, [(day_of(f.date), f.event_type) for f in found], holds, first,
                                  min(last, float(N_DAYS)), at)
        truths = [_truth(host.norad_id, t["trial"], k, m[0]) for k, m in enumerate(t["moves"])]
        res = score(truths, {host.norad_id: found}, {host.norad_id}, set())
        last_res = res[-1]
        row = None
        if last_res.found is not None:
            day = day_of(last_res.found.date)
            row = next((r for r in rows if abs(r.day - day) < 1e-6), None)
        out.append({"trial": t["trial"], "variant": t["variant"], "split": t["split"], "norad_id": host.norad_id,
                    "rhythm": t["rhythm"], "stay_days": round(t["stay"], 1), "last_stay_days": round(t["last_stay"], 1),
                    "move_days": round(t["move"], 1), "drift_rate": round(t["rate"], 3),
                    "rhythm_caught": sum(r.status == "caught" for r in res[:-1]),
                    "caught": int(last_res.status == "caught"),
                    "found_date": last_res.found.date.date().isoformat() if last_res.found else "",
                    "scored": int(bool(row and row.scored)), "model": row.model if row else "",
                    "past_stays": row.past_stays if row else "", "bits": round(row.bits, 3) if row and row.bits else ""})
    return out


def read_priors(path: Path) -> list[rt.Prior]:
    def f(x: str) -> float:
        return float("inf") if x == "inf" else float(x)
    return [rt.Prior(day_of(date.fromisoformat(r["date"])), float(r["belt_rate_per_held_year"]), f(r["alpha"]),
                     f(r["beta_held_years"]), int(r["objects"]), float(r["held_years"]), int(r["departures"]))
            for r in rows_of(path)]


def planted_summary(rows: Sequence[dict], splits: Sequence[str]) -> dict:
    out = {}
    for split in splits:
        for variant in VARIANTS:
            rs = [r for r in rows if r["split"] == split and r["variant"] == variant]
            ok = [r for r in rs if r["caught"] and r["scored"]]
            on = [float(r["bits"]) for r in ok if r["rhythm"] == "on"]
            off = [float(r["bits"]) for r in ok if r["rhythm"] == "off"]
            full = [r for r in ok if r["rhythm_caught"] == VARIANTS[variant]]
            out[f"{split} {variant}"] = {
                "trials": len(rs), "last_move_caught_and_scored": len(ok),
                "all_rhythm_moves_caught": len(full),
                "on_rhythm": {"n": len(on), f"under_{ON_MAX_BITS:g}_bits": sum(b < ON_MAX_BITS for b in on),
                              "median_bits": _med(on)},
                "off_rhythm": {"n": len(off), f"at_least_{rt.OFF_ROUTINE_BITS:g}_bits":
                               sum(b >= rt.OFF_ROUTINE_BITS for b in off), "median_bits": _med(off)},
                "by_model": {m: sum(r["model"] == m for r in ok) for m in ("stays", "rate")},
                "both_targets_share": round((sum(b < ON_MAX_BITS for b in on) + sum(b >= rt.OFF_ROUTINE_BITS
                                                                                    for b in off)) / len(ok), 3)
                if ok else None}
    return out


def _med(x: Sequence[float]) -> float | None:
    return round(float(np.median(x)), 2) if x else None


def planted(a, geo_dir: Path) -> int:
    splits = ("dev", "test") if a.split == "all" else ("dev",)
    hosts = [h for h in load_hosts().values() if h.quiet and (geo_dir / f"{h.norad_id}.tle").is_file()]
    trials = plan(hosts, splits)
    priors = read_priors(a.out / "belt_prior.csv")
    by_host = defaultdict(list)
    for t in trials:
        by_host[t["norad_id"]].append(t)
    tasks = [(geo_dir / f"{n}.tle", ts[0]["host"], ts, priors) for n, ts in sorted(by_host.items())]
    with ProcessPoolExecutor() as pool:
        rows = sorted((r for rs in pool.map(run_trials, tasks) for r in rs), key=lambda r: r["trial"])
    summary = {**_commit(), "seed": SEED, "splits": list(splits), "trials_per_split_and_variant": TRIALS,
               "hosts": {s: len({t["norad_id"] for t in trials if t["split"] == s}) for s in splits},
               **planted_summary(rows, splits)}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"planted_{a.split}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8",
                                                   newline="\n")
    with open(a.out / f"planted_{a.split}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=TRIAL_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(json.dumps(summary, indent=1))
    return 0


def audit_sample(rank: Sequence[dict]) -> list[dict]:
    mid = len(rank) // 2
    top = [("top", r) for r in rank[:AUDIT_TOP]]
    middle = [("middle", r) for r in rank[mid - AUDIT_MIDDLE // 2:mid + AUDIT_MIDDLE // 2]]
    picked = top + middle
    random.Random(AUDIT_SEED).shuffle(picked)
    return [{"audit_id": f"A{k:02d}", "norad_id": int(r["norad_id"]), "name": r["name"], "group": g,
             "rank": int(r["rank"]), "bits_per_year": r["bits_per_year"]} for k, (g, r) in enumerate(picked, 1)]


def chart(path: Path, title: str, records, events: Sequence[dict], holds: Sequence[tuple[float, float]]) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    kept, _ = drop_snapback_blocks(records)
    tk = track(kept)
    fig, ax = plt.subplots(4, 1, figsize=(12, 10), sharex=True)
    series = [("mean longitude (deg)", tk.lon), ("drift rate (deg/day)", tk.rate),
              ("semi-major axis - 42164 (km)", tk.semi_major_axis_km - 42164.0), ("inclination (deg)", tk.inclination)]
    for a, (label, y) in zip(ax, series):
        a.plot(tk.days, y, ".", color="#246", ms=2)
        a.set_ylabel(label, fontsize=8)
        for s, e in holds:
            a.axvspan(s, e, alpha=0.1, color="#2a2")
        for ev in events:
            a.axvline(day_of(date.fromisoformat(ev["date"])), color="#c33" if ev["event_type"] in rt.DEPARTURES
                      else "#888", lw=0.8, ls="-" if ev["event_type"] in rt.DEPARTURES else "--")
    for ev in events:
        ax[0].text(day_of(date.fromisoformat(ev["date"])), 1.01, ev["event_type"], rotation=90, fontsize=6,
                   transform=ax[0].get_xaxis_transform(), va="bottom")
    ticks = [day_of(date(y, 1, 1)) for y in range(2021, 2027)]
    ax[-1].set_xticks(ticks, [str(y) for y in range(2021, 2027)])
    ax[-1].set_xlim(0, N_DAYS)
    fig.suptitle(title + "  (green: held; red: departures; grey dashed: other changes)", y=0.995, fontsize=10)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=80)
    plt.close(fig)


def audit(a, geo_dir: Path, cache: Path) -> int:
    rank = rows_of(a.out / "rank.csv")
    sample = audit_sample(rank)
    blind = [{k: s[k] for k in ("audit_id", "norad_id", "name")} | {"chart": f"{s['audit_id']}.png"} for s in sample]
    with open(a.out / "audit_sample.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(blind[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(blind)
    with open(a.out / "audit_key.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["audit_id", "group", "rank", "bits_per_year"], lineterminator="\n")
        w.writeheader()
        w.writerows({k: s[k] for k in ("audit_id", "group", "rank", "bits_per_year")} for s in sample)
    objects = {o["norad"]: o for o in pickle.loads(cache.read_bytes())["objects"]}
    events = read_events(a.events)
    charts = a.charts or data_dir() / "routine" / "audit_charts"
    for s in sample:
        n = s["norad_id"]
        chart(charts / f"{s['audit_id']}.png", f"{s['audit_id']}: {n} {s['name']}", object_records(geo_dir / f"{n}.tle"),
              events.get(n, []), objects[n]["holds"])
        print(s["audit_id"], n, s["name"], flush=True)
    print(f"wrote {a.out / 'audit_sample.csv'}, {a.out / 'audit_key.csv'} and {len(sample)} charts in {charts}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Checks of the routine score and irregularity rank.")
    p.add_argument("step", choices=("checks", "planted", "audit"))
    p.add_argument("--split", choices=("dev", "all"), default="dev",
                   help="dev while building; all adds the test split (cited events, planted hosts), once at the end")
    p.add_argument("--events", type=Path, default=Path("findings/state_changes/events.csv"))
    p.add_argument("--out", type=Path, default=OUT, help="results folder of the routine job (default %(default)s)")
    p.add_argument("--geo-dir", type=Path, help="default $ORBIT_WATCH_DATA/geo")
    p.add_argument("--cache", type=Path, help="belt cache; default $ORBIT_WATCH_DATA/routine/belt.pkl")
    p.add_argument("--irregular", type=Path, default=IRREGULAR, help="cited irregular objects (default %(default)s)")
    p.add_argument("--steady", type=Path, default=STEADY, help="cited steady keepers (default %(default)s)")
    p.add_argument("--charts", type=Path, help="audit chart folder; default $ORBIT_WATCH_DATA/routine/audit_charts")
    a = p.parse_args(argv)
    geo_dir = a.geo_dir or data_dir() / "geo"
    cache = a.cache or data_dir() / "routine" / "belt.pkl"
    if a.step == "checks":
        return checks(a, geo_dir, cache)
    if a.step == "planted":
        return planted(a, geo_dir)
    return audit(a, geo_dir, cache)


if __name__ == "__main__":
    sys.exit(main())
