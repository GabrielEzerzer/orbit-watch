# Scores dated state-change events against the cited GEO event list (rung 1's file, split and matching rule),
# and counts false events on satellites whose logs show them kept on station: QZS-3, QZS-6, Fengyun-2H, and
# with --final the holdout Fengyun-2F and Fengyun-4A.

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
from orbit_watch.clean import drop_snapback_blocks
from orbit_watch.detect import detect
from orbit_watch.elements import parse_tle
from orbit_watch.events import DEPARTURES, Event as Found, as_row, events_from_track, state_changes
from orbit_watch.generalise import FROZEN
from orbit_watch.modes import GRID_START, track
from orbit_watch.series import distinct_epochs, to_series
from orbit_watch.sources import data_dir
from orbit_watch.truth import GROUNDTRUTH, load_splits, read_label_rows, require_allowed

DEFAULT_OUT = Path("findings/state_changes")
QZSS_LOG = GROUNDTRUTH / "qzss_manoeuvres.csv"
FENGYUN_LOG = GROUNDTRUTH / "fengyun_manoeuvres.csv"
KEPT_OBJECTS = {42917: ("QZS-3", QZSS_LOG), 62876: ("QZS-6", QZSS_LOG), 43491: ("Fengyun-2H", FENGYUN_LOG)}
FINAL_KEPT_OBJECTS = {38049: ("Fengyun-2F", FENGYUN_LOG), 41882: ("Fengyun-4A", FENGYUN_LOG)}
FINAL_OUT = "false_events_final.json"
CADENCE_GAP_FACTOR = 2.0
FALSE_EVENT_TARGET = 0.2
ACCEPTS = {"relocation_start": DEPARTURES, "graveyard": DEPARTURES, "keeping_stop": DEPARTURES,
           "relocation_end": ("relocation_end",), "ns_keeping_stop": ("ns_keeping_stop",),
           "free_burn": ("free_burn",)}
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


@dataclass(frozen=True)
class Station:
    norad_id: int
    name: str
    spans: tuple[tuple[datetime, datetime], ...]
    excluded: tuple[tuple[datetime, datetime], ...] = ()


def _years(spans) -> float:
    return sum(max((hi - lo).total_seconds(), 0.0) for lo, hi in spans) / (365.25 * 86400.0)


def _dates(spans) -> list[list[str]]:
    return [[lo.date().isoformat(), hi.date().isoformat()] for lo, hi in spans]


def false_events(found_by_norad: dict[int, Sequence[Found]], stations: Sequence[Station]) -> dict:
    per, total_years, total = {}, 0.0, 0
    for st in stations:
        inside = [f for f in found_by_norad.get(st.norad_id, []) if any(lo <= f.date < hi for lo, hi in st.spans)]
        years = _years(st.spans)
        per[st.name] = {"norad_id": st.norad_id, "spans": _dates(st.spans), "excluded": _dates(st.excluded),
                        "object_years": round(years, 3), "false_events": len(inside),
                        "per_object_year": round(len(inside) / years, 4) if years else None,
                        "events": [as_row(f) for f in inside]}
        total_years += years
        total += len(inside)
    rate = total / total_years if total_years else None
    return {"objects": per, "object_years": round(total_years, 3), "false_events": total,
            "per_object_year": None if rate is None else round(rate, 4), "target": FALSE_EVENT_TARGET,
            "status": None if rate is None else ("PASS" if rate <= FALSE_EVENT_TARGET else "FAIL")}


def _utc(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def station_spans(log: Path, norad: int, *, final: bool = False
                  ) -> tuple[list[tuple[datetime, datetime]], list[tuple[datetime, datetime]]]:
    rows = read_label_rows(log, norad, final=final)
    if not rows:
        raise ValueError(f"{log}: no log rows for NORAD {norad}")
    lo, hi = min(_utc(r["start_utc"]) for r in rows), max(_utc(r["end_utc"]) for r in rows)
    ew = sorted((_utc(r["start_utc"]), _utc(r["end_utc"])) for r in rows if r["kind"] == "EW")
    gaps = [(b[0] - a[0]).total_seconds() for a, b in zip(ew, ew[1:])]
    limit = CADENCE_GAP_FACTOR * float(np.median(gaps)) if gaps else float("inf")
    excluded = [(a[1], b[0]) for a, b, g in zip(ew, ew[1:], gaps) if g > limit]
    spans, start = [], lo
    for a, b in excluded:
        spans.append((start, a))
        start = b
    spans.append((start, hi))
    return spans, excluded


def kept_station(norad: int, name: str, log: Path, records, *, final: bool = False) -> Station:
    spans, excluded = station_spans(log, norad, final=final)
    first, last = max(records[0].epoch, PERIOD_DT[0]), min(records[-1].epoch, PERIOD_DT[1])
    clip = [(max(lo, first), min(hi, last)) for lo, hi in spans]
    return Station(norad, name, tuple((lo, hi) for lo, hi in clip if lo < hi),
                   tuple((lo, hi) for lo, hi in excluded if lo < last and hi > first))


def object_records(path: Path, *, final: bool = False):
    (recs,) = distinct_epochs(parse_tle(path.read_text(encoding="utf-8")), final=final).values()
    return recs


def object_events(path: Path) -> list[Found]:
    return state_changes(object_records(path))


def final_burns(records) -> tuple[np.ndarray, np.ndarray]:
    (series,) = to_series(records, final=True).values()
    dets = detect(series, FROZEN)
    start = np.datetime64(GRID_START.replace(tzinfo=None), "us")
    days = [(d.peak_start + (d.peak_end - d.peak_start) / 2 - start) / np.timedelta64(1, "D") for d in dets]
    return np.array(days, dtype=float), np.array([d.step_m for d in dets], dtype=float)


def final_state_changes(records) -> list[Found]:
    kept, _ = drop_snapback_blocks(records)
    return events_from_track(track(kept), *final_burns(kept)) if kept else []


def final_check(geo_dir: Path) -> dict:
    stations, found = [], {}
    for norad, (name, log) in FINAL_KEPT_OBJECTS.items():
        require_allowed(norad, final=True)
        recs = object_records(geo_dir / f"{norad}.tle", final=True)
        stations.append(kept_station(norad, name, log, recs, final=True))
        found[norad] = final_state_changes(recs)
    return false_events(found, stations)


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
    lines.append(false_line(fe))
    return "\n".join(lines)


def false_line(fe: dict) -> str:
    rate = "-" if fe["per_object_year"] is None else f"{fe['per_object_year']:g}"
    each = ", ".join(f"{name} {o['false_events']} in {o['object_years']}" for name, o in fe["objects"].items())
    return (f"false events on kept satellites ({each}): {fe['false_events']} over {fe['object_years']} "
            f"object-years = {rate} per object-year (target <= {FALSE_EVENT_TARGET}: {fe['status']})")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Score dated GEO state-change events against the cited GEO event list "
                                "(recall and dating error), and count false events on satellites logged as kept "
                                "on station (QZS-3, QZS-6, Fengyun-2H).")
    p.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    p.add_argument("--geo-dir", type=Path, help="folder of <norad>.tle files; default $ORBIT_WATCH_DATA/geo")
    p.add_argument("--split", choices=("dev", "all"), default="dev",
                   help="dev while building; all adds the test split, scored once at the end")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for eval_<split>.json and eval_<split>.csv")
    p.add_argument("--final", action="store_true",
                   help=f"also count false events on the holdout Fengyun-2F and Fengyun-4A, run once at the end; "
                        f"writes OUT/{FINAL_OUT}")
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
    stations = [kept_station(n, name, log, object_records(geo_dir / f"{n}.tle"))
                for n, (name, log) in KEPT_OBJECTS.items()]
    fe = false_events(found, stations)

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
    if a.final:
        final = {**_commit(), "false_events": final_check(geo_dir)}
        (a.out / FINAL_OUT).write_text(json.dumps(final, indent=2) + "\n", encoding="utf-8", newline="\n")
        print("final, holdout: " + false_line(final["false_events"]))
        print(f"wrote {a.out / FINAL_OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
