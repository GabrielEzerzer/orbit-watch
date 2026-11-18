# Planted-change test of orbit_watch.events: relocations, keeping stops, graveyard climbs and free burns planted in
# memory into the real element sets of held GEO satellites, scored with the state-change eval's matching rules.

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from math import ceil, log
from pathlib import Path

import numpy as np

from harness.evals.mode_events import DEFAULT_EVENTS, WINDOW_DAYS, Event, _commit
from harness.evals.state_changes import object_records, score
from orbit_watch.elements import ElementSet
from orbit_watch.events import Event as Found, burns, state_changes
from orbit_watch.modes import GRID_START, SIDEREAL_REV_PER_DAY, Segment, Track, longitude_acceleration, segments, track
from orbit_watch.sources import data_dir
from orbit_watch.truth import load_splits, read_event_rows

DEFAULT_OUT = Path("findings/state_injection")
HELD = ("controlled_lon_inc", "controlled_lon")
SEED = 20261118
MIN_HOLD_DAYS = 120.0
LEAD_DAYS = 60.0
SETTLE_DAYS = 60.0
OBSERVE_DAYS = 90.0
RATE_BINS = ((0.02, 0.05), (0.05, 0.1), (0.1, 0.3), (0.3, 1.0), (1.0, 3.0))
SLOW_MAX = 0.1
TRIALS_PER_BIN = 100
TRIALS = {"keeping_stop": 160, "graveyard": 160, "free_burn": 160}
TRUTH_TYPES = {"relocation": ("relocation_start", "relocation_end"), "keeping_stop": ("keeping_stop",),
               "graveyard": ("graveyard",), "free_burn": ("keeping_stop", "free_burn")}
KINDS = ("relocation", *TRIALS)
DISTANCE_DEG = (1.0, 20.0)
DRIFT_DAYS = (2.0, 120.0)
CLIMB_KM = (200.0, 400.0)
CLIMB_BURNS = 3
CLIMB_SPACING_DAYS = (0.5, 3.0)
FREE_BURN_KM = (1.5, 20.0)
FREE_BURN_AFTER_DAYS = (45.0, 120.0)
STEP_DAYS = 0.5
WINDOW_SETS = 4
JUMP_SIGMAS = 10.0
GUARD_DAYS = 2.0
MAX_DRAWS = 1000
TRIAL_FIELDS = ["trial", "kind", "split", "norad_id", "rate_bin", "t0", "drift_rate", "drift_days", "size",
                "truth", "extra_near", "extra_later", "untouched_days", "untouched_events"]


@dataclass(frozen=True)
class Host:
    norad_id: int
    start: float
    end: float
    mode: str
    split: str


@dataclass(frozen=True)
class Plant:
    trial: int
    kind: str
    norad_id: int
    split: str
    t0: float
    rate: float = 0.0
    days: float = 0.0
    kicks: tuple[tuple[float, float], ...] = ()
    rate_bin: str = ""


@dataclass(frozen=True)
class Smooth:
    lon_fit: np.ndarray
    lon_res: np.ndarray
    lon_slope: np.ndarray
    rate_res: np.ndarray
    offset: float
    a_km: float


def _day(d: date | datetime) -> float:
    t = d if isinstance(d, datetime) else datetime(d.year, d.month, d.day, tzinfo=GRID_START.tzinfo)
    return (t - GRID_START).total_seconds() / 86400.0


def _date(day: float) -> date:
    return (GRID_START + timedelta(days=float(day))).date()


def host_split(norad: int) -> str:
    return "dev" if int(hashlib.sha256(str(norad).encode("utf-8")).hexdigest()[-1], 16) % 2 == 0 else "test"


def excluded_objects(splits: dict[int, dict], event_rows: Sequence[dict]) -> set[int]:
    holdout = {n for n, e in splits.items() if e["split"] == "holdout"}
    return holdout | {int(r["norad_id"]) for r in event_rows if r["split"] == "test"}


def candidate_stretches(segs: Sequence[Segment], excluded: set[int]) -> dict[int, Host]:
    best: dict[int, Host] = {}
    for s in segs:
        n = s.norad_id
        if s.mode not in HELD or n in excluded:
            continue
        lo, hi = _day(s.start.date()), _day(s.end.date())
        if hi - lo >= MIN_HOLD_DAYS and (n not in best or hi - lo > best[n].end - best[n].start):
            best[n] = Host(n, lo, hi, s.mode, host_split(n))
    return dict(sorted(best.items()))


def quiet(host: Host, found: Sequence[Found]) -> bool:
    return not any(host.start <= _day(f.date) <= host.end for f in found)


def held_estimate(candidates: dict[int, Host], found_by_norad: dict[int, Sequence[Found]]) -> dict:
    years, inside = 0.0, []
    for n, h in candidates.items():
        lo, hi = h.start + WINDOW_DAYS, h.end - WINDOW_DAYS
        years += max(hi - lo, 0.0) / 365.25
        inside += [f for f in found_by_norad[n] if lo <= _day(f.date) <= hi]
    return {"what": "every event the current code dates inside a candidate held stretch, 45 days trimmed from each "
                    "end, before hosts are chosen; an upper bound on false events on held satellites",
            "stretches": len(candidates), "object_years": round(years, 3), "events": len(inside),
            "per_object_year": round(len(inside) / years, 4) if years else None,
            "by_type": dict(Counter(f.event_type for f in inside)),
            "list": [{"norad_id": f.norad_id, "event_type": f.event_type, "date": f.date.date().isoformat(),
                      "signal": f.signal} for f in inside]}


def _windows(x: np.ndarray) -> np.ndarray:
    return np.lib.stride_tricks.sliding_window_view(np.pad(x, WINDOW_SETS, mode="edge"), 2 * WINDOW_SETS + 1)


def _local_line(days: np.ndarray, u: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    t, y = _windows(days), _windows(u)
    tc, yc = t - t.mean(axis=1, keepdims=True), y - y.mean(axis=1, keepdims=True)
    den = (tc ** 2).sum(axis=1)
    slope = np.divide((tc * yc).sum(axis=1), den, out=np.zeros(len(days)), where=den > 0)
    return y.mean(axis=1) + slope * (days - t.mean(axis=1)), slope


def steps(days: np.ndarray, rate: np.ndarray, burn_days: np.ndarray) -> np.ndarray:
    jump = np.abs(np.diff(rate))
    sigma = 1.4826 * float(np.median(jump)) if len(jump) else 0.0
    big = np.flatnonzero(jump > JUMP_SIGMAS * sigma)
    return np.unique(np.r_[burn_days, 0.5 * (days[big] + days[big + 1])])


def smooth(tr: Track, burn_days: np.ndarray, host: Host) -> Smooth:
    u = np.degrees(np.unwrap(np.radians(tr.lon)))
    at = steps(tr.days, tr.rate, burn_days)
    lon_fit, slope, rate_fit = (np.zeros(len(u)) for _ in range(3))
    edges = sorted({int(c) for c in np.searchsorted(tr.days, at) if 0 < c < len(u)})
    for lo, hi in zip([0, *edges], [*edges, len(u)]):
        lon_fit[lo:hi], slope[lo:hi] = _local_line(tr.days[lo:hi], u[lo:hi])
        rate_fit[lo:hi] = _local_line(tr.days[lo:hi], tr.rate[lo:hi])[0]
    lon_res, rate_res = u - lon_fit, tr.rate - rate_fit
    near = (np.abs(tr.days[:, None] - at[None, :]) <= GUARD_DAYS).any(axis=1)
    if near.any() and not near.all():
        donor = np.flatnonzero(~near)[np.arange(int(near.sum())) % int((~near).sum())]
        lon_res[near], rate_res[near] = lon_res[donor], rate_res[donor]
    sel = (tr.days >= host.start) & (tr.days < host.end)
    return Smooth(lon_fit, white(lon_res), slope, white(rate_res), float(np.median((rate_fit - slope)[sel])),
                  float(np.median(tr.semi_major_axis_km[sel])))


def white(res: np.ndarray) -> np.ndarray:
    return np.r_[0.0, np.diff(res)] / np.sqrt(2.0)


def kick(a_km: float, da_km: float) -> float:
    return 360.0 * SIDEREAL_REV_PER_DAY * ((a_km / (a_km + da_km)) ** 1.5 - 1.0)


def free_path(t0: float, lon0: float, rate0: float, inc: float, kicks: Sequence[tuple[float, float]],
              days: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    end = max(float(days.max()), t0)
    edges = sorted({t0, *(k for k, _ in kicks if t0 <= k < end)}) + [end]
    lon, rate = lon0, rate0
    ts, ls, rs = [], [], []
    for a, b in zip(edges, edges[1:]):
        rate += sum(dv for k, dv in kicks if k == a)
        n = max(1, ceil((b - a) / STEP_DAYS))
        h = (b - a) / n
        acc = float(longitude_acceleration(lon, inc))
        for i in range(n):
            ts.append(a + i * h)
            ls.append(lon)
            rs.append(rate)
            rate += 0.5 * h * acc
            lon += h * rate
            acc = float(longitude_acceleration(lon, inc))
            rate += 0.5 * h * acc
    ts.append(end)
    ls.append(lon)
    rs.append(rate)
    return np.interp(days, ts, ls), np.interp(days, ts, rs)


def plant(records: Sequence[ElementSet], tr: Track, sm: Smooth, p: Plant) -> list[ElementSet]:
    d = tr.days
    if p.kind == "relocation":
        delta = p.rate * np.clip(d - p.t0, 0.0, p.days)
        rate = tr.rate + np.where((d >= p.t0) & (d < p.t0 + p.days), p.rate, 0.0)
    else:
        after = d >= p.t0
        i = max(int(np.argmax(after)) - 1, 0)
        lon0 = sm.lon_fit[i] + sm.lon_slope[i] * (p.t0 - d[i])
        lam, lamdot = free_path(p.t0, lon0, sm.lon_slope[i], float(tr.inclination[i]), p.kicks, d[after])
        delta, rate = np.zeros(len(d)), tr.rate.copy()
        delta[after] = lam - sm.lon_fit[after]
        rate[after] = lamdot + sm.offset + sm.rate_res[after]
    out = []
    for r, dl, rt, d0 in zip(records, delta, rate, d):
        if d0 < p.t0:
            out.append(r)
            continue
        n = SIDEREAL_REV_PER_DAY + rt / 360.0
        out.append(replace(r, mean_motion=n, mean_anomaly=float((r.mean_anomaly + dl) % 360.0),
                           semi_major_axis_km=r.semi_major_axis_km * (r.mean_motion / n) ** (2.0 / 3.0)))
    return out


def truth(p: Plant) -> list[tuple[str, float]]:
    if p.kind == "relocation":
        return [("relocation_start", p.t0), ("relocation_end", p.t0 + p.days)]
    if p.kind == "graveyard":
        return [("graveyard", p.t0)]
    if p.kind == "free_burn":
        return [("keeping_stop", p.t0), ("free_burn", p.kicks[0][0])]
    return [("keeping_stop", p.t0)]


def change_span(p: Plant) -> tuple[float, float]:
    if p.kind == "relocation":
        return p.t0, p.t0 + p.days
    return p.t0, max([p.t0, *(k for k, _ in p.kicks)])


def _log_uniform(rng, lo: float, hi: float) -> float:
    return float(np.exp(rng.uniform(log(lo), log(hi))))


def draw(rng, kind: str, trial: int, hosts: Sequence[Host], last_day: dict[int, float],
         rate_bin: tuple[float, float] | None = None) -> Plant:
    for _ in range(MAX_DRAWS):
        h = hosts[int(rng.integers(len(hosts)))]
        end = min(h.end, last_day[h.norad_id])
        if kind == "relocation":
            r = _log_uniform(rng, *rate_bin) * rng.choice((-1.0, 1.0))
            days = float(np.clip(_log_uniform(rng, *DISTANCE_DEG) / abs(r), *DRIFT_DAYS))
            hi = end - SETTLE_DAYS - days
            if hi > h.start + LEAD_DAYS:
                return Plant(trial, kind, h.norad_id, h.split, float(rng.uniform(h.start + LEAD_DAYS, hi)), r, days,
                             rate_bin=f"{rate_bin[0]:g}-{rate_bin[1]:g}")
            continue
        hi = min(end, last_day[h.norad_id] - OBSERVE_DAYS)
        if kind == "free_burn":
            hi -= FREE_BURN_AFTER_DAYS[1]
        if hi <= h.start + LEAD_DAYS:
            continue
        t0 = float(rng.uniform(h.start + LEAD_DAYS, hi))
        kicks: tuple[tuple[float, float], ...] = ()
        if kind == "graveyard":
            n = int(rng.integers(1, CLIMB_BURNS + 1))
            rise = float(rng.uniform(*CLIMB_KM))
            at = t0 + np.r_[0.0, np.cumsum(rng.uniform(*CLIMB_SPACING_DAYS, n - 1))]
            kicks = tuple((float(t), rise / n) for t in at)
        elif kind == "free_burn":
            size = _log_uniform(rng, *FREE_BURN_KM) * rng.choice((-1.0, 1.0))
            kicks = ((t0 + float(rng.uniform(*FREE_BURN_AFTER_DAYS)), size),)
        return Plant(trial, kind, h.norad_id, h.split, t0, kicks=kicks)
    raise ValueError(f"no host fits a {kind} plant")


def plan(hosts: Sequence[Host], last_day: dict[int, float]) -> list[Plant]:
    by_split = {s: [h for h in hosts if h.split == s] for s in ("dev", "test")}
    jobs = [("relocation", b, TRIALS_PER_BIN) for b in RATE_BINS] + [(k, None, n) for k, n in TRIALS.items()]
    out: list[Plant] = []
    for j, (kind, rate_bin, n) in enumerate(jobs):
        rng = np.random.default_rng([SEED, j])
        for i in range(n):
            out.append(draw(rng, kind, len(out), by_split[("dev", "test")[i % 2]], last_day, rate_bin))
    return out


def _kicks_km(p: Plant, a_km: float) -> tuple[tuple[float, float], ...]:
    return tuple((t, kick(a_km, da)) for t, da in p.kicks)


def run_trial(records: Sequence[ElementSet], tr: Track, sm: Smooth, host: Host, p: Plant) -> dict:
    found = state_changes(plant(records, tr, sm, replace(p, kicks=_kicks_km(p, sm.a_km))))
    truths = [Event(f"{p.trial}-{t}", p.norad_id, t, _date(day), p.split) for t, day in truth(p)]
    results = score(truths, {p.norad_id: found}, {p.norad_id}, set())
    matched = [r.found for r in results if r.found is not None]
    lo, hi = change_span(p)
    zone = (lo - WINDOW_DAYS, hi + WINDOW_DAYS)
    free = [f for f in found if not any(f is m for m in matched)]
    near = [f for f in free if zone[0] <= _day(f.date) <= zone[1]]
    later = [f for f in free if _day(f.date) > zone[1]] if p.kind != "relocation" else []
    spans = [(host.start, zone[0])] + ([(zone[1], host.end)] if p.kind == "relocation" else [])
    spans = [(a, b) for a, b in spans if b > a]
    untouched = [f for f in free if any(a <= _day(f.date) < b for a, b in spans)]
    return {
        "plant": p,
        "results": [{"type": r.event.event_type, "date": r.event.date.isoformat(), "status": r.status,
                     "found_type": r.found.event_type if r.found else "", "error_days": r.error_days}
                    for r in results],
        "extra_near": [f.event_type for f in near],
        "extra_later": [f.event_type for f in later],
        "untouched_days": sum(b - a for a, b in spans),
        "untouched_events": [{"event_type": f.event_type, "date": f.date.date().isoformat()} for f in untouched],
    }


def object_segments(path: Path) -> list[Segment]:
    return segments(track(object_records(path)))


def host_events(path: Path) -> tuple[list[Found], float]:
    records = object_records(path)
    return state_changes(records), _day(records[-1].epoch)


def run_host(task: tuple[Path, Host, list[Plant]]) -> list[dict]:
    path, host, plants = task
    records = object_records(path)
    tr = track(records)
    sm = smooth(tr, burns(records)[0], host)
    return [run_trial(records, tr, sm, host, p) for p in plants]


def _stats(rows: Sequence[dict], truth_type: str) -> dict:
    rs = [r for t in rows for r in t["results"] if r["type"] == truth_type]
    caught = [r for r in rs if r["status"] == "caught"]
    errors = [abs(r["error_days"]) for r in caught]
    return {"trials": len(rs), "caught": len(caught), "recall": round(len(caught) / len(rs), 4) if rs else None,
            "median_abs_error_days": float(np.median(errors)) if errors else None,
            "p90_abs_error_days": round(float(np.percentile(errors, 90)), 1) if errors else None,
            "same_type": sum(r["found_type"] == truth_type for r in caught),
            "mistyped": sum(r["found_type"] != truth_type for r in caught)}


def _group(rows: Sequence[dict], types: Sequence[str]) -> dict:
    n = len(rows)
    return {"trials": n, "by_truth_type": {t: _stats(rows, t) for t in types},
            "extra_near_per_trial": round(sum(len(r["extra_near"]) for r in rows) / n, 3) if n else None,
            "extra_later_per_trial": round(sum(len(r["extra_later"]) for r in rows) / n, 3) if n else None,
            "extra_types": dict(Counter(t for r in rows for t in r["extra_near"] + r["extra_later"]))}


def _bin_groups(rows: Sequence[dict]) -> dict[str, list[dict]]:
    out = {f"{lo:g}-{hi:g}": [r for r in rows if r["plant"].rate_bin == f"{lo:g}-{hi:g}"] for lo, hi in RATE_BINS}
    out[f"slow ({RATE_BINS[0][0]:g}-{SLOW_MAX:g})"] = [r for r in rows if abs(r["plant"].rate) <= SLOW_MAX]
    out[f"normal ({SLOW_MAX:g}-{RATE_BINS[-1][1]:g})"] = [r for r in rows if abs(r["plant"].rate) > SLOW_MAX]
    return out


def summarise(rows: Sequence[dict]) -> dict:
    out = {}
    for split in ("dev", "test"):
        rs = [r for r in rows if r["plant"].split == split]
        reloc = [r for r in rs if r["plant"].kind == "relocation"]
        kinds = {"relocation": {b: _group(g, TRUTH_TYPES["relocation"]) for b, g in _bin_groups(reloc).items()}}
        for kind in TRIALS:
            kinds[kind] = _group([r for r in rs if r["plant"].kind == kind], TRUTH_TYPES[kind])
        years = sum(r["untouched_days"] for r in rs) / 365.25
        events = [e for r in rs for e in r["untouched_events"]]
        out[split] = {"hosts": len({r["plant"].norad_id for r in rs}), "kinds": kinds,
                      "untouched": {"object_years": round(years, 3), "events": len(events),
                                    "per_object_year": round(len(events) / years, 4) if years else None,
                                    "by_type": dict(Counter(e["event_type"] for e in events))}}
    return out


def trial_row(r: dict) -> dict:
    p = r["plant"]
    size = (f"{sum(da for _, da in p.kicks):.1f} km in {len(p.kicks)}" if p.kind == "graveyard"
            else f"{p.kicks[0][1]:.2f} km" if p.kind == "free_burn"
            else f"{p.rate * p.days:.2f} deg" if p.kind == "relocation" else "")
    return {"trial": p.trial, "kind": p.kind, "split": p.split, "norad_id": p.norad_id, "rate_bin": p.rate_bin,
            "t0": _date(p.t0).isoformat(), "drift_rate": round(p.rate, 4) if p.rate else "",
            "drift_days": round(p.days, 1) if p.days else "", "size": size,
            "truth": ";".join(f"{x['type']}@{x['date']}:{x['status']}:{x['found_type']}:"
                              f"{'' if x['error_days'] is None else x['error_days']}" for x in r["results"]),
            "extra_near": ";".join(r["extra_near"]), "extra_later": ";".join(r["extra_later"]),
            "untouched_days": round(r["untouched_days"], 1),
            "untouched_events": ";".join(f"{e['event_type']}@{e['date']}" for e in r["untouched_events"])}


def table(summary: dict) -> str:
    def f(x):
        return "-" if x is None else f"{x:g}"
    head = (f"{'split':<5} {'kind':<12} {'bin':<18} {'truth':<16} {'n':>4} {'recall':>6} {'med|d|':>6} "
            f"{'p90|d|':>6} {'mistyp':>6} {'x_near':>6} {'x_late':>6}")
    lines = [head, "-" * len(head)]
    for split in ("dev", "test"):
        k = summary[split]["kinds"]
        groups = [("relocation", b, g) for b, g in k["relocation"].items()] + [(n, "", k[n]) for n in TRIALS]
        for kind, b, g in groups:
            for t, s in g["by_truth_type"].items():
                lines.append(f"{split:<5} {kind:<12} {b:<18} {t:<16} {s['trials']:>4} {f(s['recall']):>6} "
                             f"{f(s['median_abs_error_days']):>6} {f(s['p90_abs_error_days']):>6} {s['mistyped']:>6} "
                             f"{f(g['extra_near_per_trial']):>6} {f(g['extra_later_per_trial']):>6}")
        u = summary[split]["untouched"]
        lines.append(f"{split}: false events on untouched host stretches: {u['events']} over {u['object_years']} "
                     f"object-years = {f(u['per_object_year'])} per object-year")
    b = summary["belt_held_stretches"]
    lines.append(f"belt, before host selection: {b['events']} events inside {b['stretches']} held stretches over "
                 f"{b['object_years']} object-years = {f(b['per_object_year'])} per object-year")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Planted-change test of the GEO state-change events: relocations, keeping "
                                "stops, graveyard climbs and free burns planted in the element sets of held "
                                "satellites, scored per kind and drift rate on dev and test hosts.")
    p.add_argument("--geo-dir", type=Path, help="folder of <norad>.tle files; default $ORBIT_WATCH_DATA/geo")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for summary.json and trials.csv")
    a = p.parse_args(argv)
    geo_dir = a.geo_dir or data_dir() / "geo"
    excluded = excluded_objects(load_splits(), read_event_rows(DEFAULT_EVENTS)[1])
    manifest = json.loads((geo_dir / "manifest.json").read_text(encoding="utf-8"))
    norads = sorted(int(n) for n, o in manifest["objects"].items()
                    if o["by_rule"] and int(n) not in excluded and (geo_dir / f"{n}.tle").is_file())
    with ProcessPoolExecutor() as pool:
        segs = [s for ss in pool.map(object_segments, [geo_dir / f"{n}.tle" for n in norads], chunksize=8) for s in ss]
        candidates = candidate_stretches(segs, excluded)
        base = dict(zip(candidates, pool.map(host_events, [geo_dir / f"{n}.tle" for n in candidates], chunksize=4)))
        found = {n: f for n, (f, _) in base.items()}
        last_day = {n: d for n, (_, d) in base.items()}
        hosts = [h for n, h in candidates.items() if quiet(h, found[n])]
        plants = plan(hosts, last_day)
        by_host = {h.norad_id: h for h in hosts}
        tasks = [(geo_dir / f"{n}.tle", by_host[n], [q for q in plants if q.norad_id == n])
                 for n in sorted({q.norad_id for q in plants})]
        rows = sorted((r for rs in pool.map(run_host, tasks) for r in rs), key=lambda r: r["plant"].trial)

    summary = {**_commit(), "seed": SEED, "window_days": WINDOW_DAYS,
               "hosts": {"candidates": len(candidates), "quiet": len(hosts),
                         "dev": sum(h.split == "dev" for h in hosts), "test": sum(h.split == "test" for h in hosts),
                         "excluded_objects": sorted(excluded)},
               **summarise(rows), "belt_held_stretches": held_estimate(candidates, found)}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    with open(a.out / "trials.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=TRIAL_FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(trial_row(r) for r in rows)
    print(table(summary))
    print(f"wrote {a.out / 'summary.json'} and {a.out / 'trials.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
