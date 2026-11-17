# Scores dated state-change events against the cited GEO event list (rung 1's file, split and matching rule),
# and counts false events on QZS-3 and QZS-6, whose operator logs show them kept on station throughout.

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from harness.evals.mode_events import (DEFAULT_EVENTS, EVENT_TYPES, SPLITS, WINDOW_DAYS, Event, _commit,
                                       load_events, unscored_reason)
from orbit_watch.elements import parse_tle
from orbit_watch.events import DEPARTURES, Event as Found, as_row, state_changes
from orbit_watch.generalise import log_coverage
from orbit_watch.series import distinct_epochs
from orbit_watch.sources import data_dir
from orbit_watch.truth import GROUNDTRUTH, load_splits

DEFAULT_OUT = Path("findings/state_changes")
KEPT_OBJECTS = {42917: "QZS-3", 62876: "QZS-6"}
KEPT_LOG = GROUNDTRUTH / "qzss_manoeuvres.csv"
FALSE_EVENT_TARGET = 0.2
ACCEPTS = {"relocation_start": DEPARTURES, "graveyard": DEPARTURES, "keeping_stop": DEPARTURES,
           "relocation_end": ("relocation_end",), "ns_keeping_stop": ("ns_keeping_stop",)}
PERIOD_DT = (datetime(2021, 1, 1, tzinfo=timezone.utc), datetime(2026, 1, 1, tzinfo=timezone.utc))
EVENT_FIELDS = ["event_id", "split", "event_type", "status", "found_type", "found_date", "error_days", "signal",
                "size", "mode_change"]


@dataclass(frozen=True)
class Result:
    event: Event
    status: str
    found: Found | None = None

    @property
    def error_days(self) -> int | None:
        return None if self.found is None else (self.found.date.date() - self.event.date).days


def accepts(event_type: str, found: Found) -> bool:
    return found.event_type in ACCEPTS[event_type]


def score(events: Sequence[Event], found_by_norad: dict[int, Sequence[Found]], geo_norads: set[int],
          holdout: set[int]) -> list[Result]:
    results: dict[str, Result] = {}
    scored: dict[int, list[Event]] = {}
    for e in events:
        reason = unscored_reason(e, geo_norads, holdout)
        if reason:
            results[e.event_id] = Result(e, reason)
        else:
            scored.setdefault(e.norad_id, []).append(e)
    for norad, evs in scored.items():
        found = list(found_by_norad[norad])
        pairs = sorted((abs((f.date.date() - e.date).days), e.date, f.date, i, j)
                       for i, e in enumerate(evs) for j, f in enumerate(found)
                       if abs((f.date.date() - e.date).days) <= WINDOW_DAYS and accepts(e.event_type, f))
        used_e, used_f = set(), set()
        for _, _, _, i, j in pairs:
            if i not in used_e and j not in used_f:
                used_e.add(i)
                used_f.add(j)
                results[evs[i].event_id] = Result(evs[i], "caught", found[j])
        for i, e in enumerate(evs):
            if i not in used_e:
                results[e.event_id] = Result(e, "missed")
    return [results[e.event_id] for e in events]


def _stats(results: Sequence[Result]) -> dict:
    scored = [r for r in results if r.status in ("caught", "missed")]
    caught = [r for r in scored if r.status == "caught"]
    errors = [abs(r.error_days) for r in caught]
    return {"events": len(results), "scored": len(scored), "caught": len(caught),
            "recall": round(len(caught) / len(scored), 4) if scored else None,
            "median_abs_error_days": float(np.median(errors)) if errors else None,
            "p90_abs_error_days": float(np.percentile(errors, 90)) if errors else None,
            "same_type": sum(r.found.event_type == r.event.event_type for r in caught)}


def summarise(results: Sequence[Result], splits: Sequence[str]) -> dict:
    out = {}
    for name in splits:
        rs = [r for r in results if r.event.split == name]
        out[name] = {**_stats(rs), "by_event_type": {t: _stats([r for r in rs if r.event.event_type == t])
                                                    for t in EVENT_TYPES}}
    out["unscored"] = [{"event_id": r.event.event_id, "reason": r.status}
                       for r in results if r.status not in ("caught", "missed")]
    return out


def false_events(found_by_norad: dict[int, Sequence[Found]], spans: dict[int, tuple[datetime, datetime]]) -> dict:
    per, total_years, total = {}, 0.0, 0
    for norad, (lo, hi) in spans.items():
        inside = [f for f in found_by_norad.get(norad, []) if lo <= f.date < hi]
        years = max((hi - lo).total_seconds(), 0.0) / (365.25 * 86400.0)
        per[KEPT_OBJECTS[norad]] = {"norad_id": norad, "from": lo.date().isoformat(), "to": hi.date().isoformat(),
                                    "object_years": round(years, 3), "false_events": len(inside),
                                    "events": [as_row(f) for f in inside]}
        total_years += years
        total += len(inside)
    rate = total / total_years if total_years else None
    return {"objects": per, "object_years": round(total_years, 3), "false_events": total,
            "per_object_year": None if rate is None else round(rate, 4), "target": FALSE_EVENT_TARGET,
            "status": None if rate is None else ("PASS" if rate <= FALSE_EVENT_TARGET else "FAIL")}


def kept_span(norad: int, records) -> tuple[datetime, datetime]:
    lo, hi = log_coverage(KEPT_LOG, norad)
    as_dt = lambda t: datetime.fromisoformat(str(t.astype("datetime64[s]"))).replace(tzinfo=timezone.utc)
    lo = max(as_dt(lo), records[0].epoch, PERIOD_DT[0])
    hi = min(as_dt(hi), records[-1].epoch, PERIOD_DT[1])
    return lo, hi


def object_records(path: Path):
    (recs,) = distinct_epochs(parse_tle(path.read_text(encoding="utf-8"))).values()
    return recs


def object_events(path: Path) -> list[Found]:
    return state_changes(object_records(path))


def table(summary: dict, fe: dict, splits: Sequence[str]) -> str:
    def f(x):
        return "-" if x is None else f"{x:g}"
    head = (f"{'split':<6} {'event_type':<17} {'events':>6} {'scored':>6} {'caught':>6} {'recall':>6} "
            f"{'med|d|':>6} {'p90|d|':>6} {'type=':>5}")
    lines = [head, "-" * len(head)]
    for name in splits:
        g = summary[name]
        rows = [("all", g)] + [(t, s) for t, s in g["by_event_type"].items() if s["events"]]
        for t, s in rows:
            lines.append(f"{name:<6} {t:<17} {s['events']:>6} {s['scored']:>6} {s['caught']:>6} {f(s['recall']):>6} "
                         f"{f(s['median_abs_error_days']):>6} {f(s['p90_abs_error_days']):>6} {s['same_type']:>5}")
    lines.append(f"unscored: {len(summary['unscored'])}")
    lines.append(f"false events on QZS-3 and QZS-6: {fe['false_events']} over {fe['object_years']} object-years = "
                 f"{f(fe['per_object_year'])} per object-year (target <= {FALSE_EVENT_TARGET}: {fe['status']})")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Score dated GEO state-change events against the cited GEO event list "
                                "(recall and dating error), and count false events on QZS-3 and QZS-6.")
    p.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    p.add_argument("--geo-dir", type=Path, help="folder of <norad>.tle files; default $ORBIT_WATCH_DATA/geo")
    p.add_argument("--split", choices=("dev", "all"), default="dev",
                   help="dev while building; all adds the test split, scored once at the end")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for eval_<split>.json and eval_<split>.csv")
    a = p.parse_args(argv)
    geo_dir = a.geo_dir or data_dir() / "geo"
    splits = SPLITS if a.split == "all" else ("dev",)
    events = [e for e in load_events(a.events) if e.split in splits]
    holdout = {n for n, e in load_splits().items() if e["split"] == "holdout"}
    geo_norads = {e.norad_id for e in events if e.norad_id not in holdout and (geo_dir / f"{e.norad_id}.tle").is_file()}
    norads = sorted(geo_norads | set(KEPT_OBJECTS))
    with ProcessPoolExecutor() as pool:
        found = dict(zip(norads, pool.map(object_events, [geo_dir / f"{n}.tle" for n in norads])))
    results = score(events, found, geo_norads, holdout)
    spans = {n: kept_span(n, object_records(geo_dir / f"{n}.tle")) for n in KEPT_OBJECTS}
    fe = false_events(found, spans)

    a.out.mkdir(parents=True, exist_ok=True)
    summary = {**_commit(), "events_file": a.events.name, "window_days": WINDOW_DAYS, **summarise(results, splits),
               "false_events": fe}
    (a.out / f"eval_{a.split}.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    with open(a.out / f"eval_{a.split}.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=EVENT_FIELDS, lineterminator="\n")
        w.writeheader()
        for r in results:
            f = r.found
            w.writerow({"event_id": r.event.event_id, "split": r.event.split, "event_type": r.event.event_type,
                        "status": r.status, "found_type": f.event_type if f else "",
                        "found_date": f.date.date().isoformat() if f else "",
                        "error_days": "" if r.error_days is None else r.error_days,
                        "signal": f.signal if f else "", "size": f.size if f else "",
                        "mode_change": f.mode_change.date().isoformat() if f else ""})
    print(table(summary, fe, splits))
    print(f"wrote {a.out / f'eval_{a.split}.json'} and {a.out / f'eval_{a.split}.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
