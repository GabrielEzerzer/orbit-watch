# Scores the GEO mode layer against a cited list of real GEO events: for each event, does the
# determined-mode timeline show the matching mode change within 45 days, and how many days off is it.

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from orbit_watch.jobs.geo_modes import object_segments
from orbit_watch.modes import Segment
from orbit_watch.sources import data_dir
from orbit_watch.truth import GROUNDTRUTH, load_splits

HERE = Path(__file__).resolve().parent
DEFAULT_EVENTS = GROUNDTRUTH / "geo_events.csv"
DEFAULT_OUT = Path("findings/geo_events")
FIELDS = ["event_id", "norad_id", "name", "event_type", "date", "date_precision", "lon_from_deg",
          "lon_to_deg", "source_url", "quote", "split"]
HELD = ("controlled_lon_inc", "controlled_lon")
FREE = ("drifting", "librating_75E", "librating_105W", "librating_both", "inclined")
OUT_OF_REGION = "out_of_region"
EVENT_TYPES = ("relocation_start", "relocation_end", "graveyard", "ns_keeping_stop", "keeping_stop")
PRECISIONS = ("day", "month")
SPLITS = ("dev", "test")
WINDOW_DAYS = 45
TIMELINE_DAYS = 90
PERIOD = (date(2021, 1, 1), date(2025, 12, 31))
HOLDOUT, OUTSIDE_PERIOD, NOT_IN_GEO_SET = "holdout", "outside_period", "not_in_geo_set"
EVENT_FIELDS = ["event_id", "split", "event_type", "status", "transition", "transition_date", "error_days",
                "timeline"]


@dataclass(frozen=True)
class Event:
    event_id: str
    norad_id: int
    event_type: str
    date: date
    split: str


@dataclass(frozen=True)
class Transition:
    before: Segment
    after: Segment

    @property
    def date(self) -> date:
        return self.after.start.date()

    @property
    def label(self) -> str:
        return f"{self.before.mode}->{self.after.mode}"


@dataclass(frozen=True)
class Result:
    event: Event
    status: str
    transition: Transition | None = None

    @property
    def error_days(self) -> int | None:
        return None if self.transition is None else (self.transition.date - self.event.date).days


def split_of(event_id: str) -> str:
    return "dev" if int(hashlib.sha256(event_id.encode("utf-8")).hexdigest()[-1], 16) % 2 == 0 else "test"


def event_date(text: str, precision: str) -> date:
    if precision == "day" and re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
        return date.fromisoformat(text)
    if precision == "month" and re.fullmatch(r"\d{4}-\d{2}", text):
        return date.fromisoformat(f"{text}-15")
    raise ValueError(f"date {text!r} does not match precision {precision!r}")


def row_problems(rows: Sequence[dict]) -> list[str]:
    out = []
    seen = set()
    for i, r in enumerate(rows, start=2):
        where = f"line {i} ({r.get('event_id')})"
        if r.get("event_type") not in EVENT_TYPES:
            out.append(f"{where}: event_type {r.get('event_type')!r} is not one of {EVENT_TYPES}")
        if r.get("date_precision") not in PRECISIONS:
            out.append(f"{where}: date_precision {r.get('date_precision')!r} is not one of {PRECISIONS}")
        else:
            try:
                event_date(r.get("date", ""), r["date_precision"])
            except ValueError as e:
                out.append(f"{where}: {e}")
        if not re.fullmatch(r"\d+", r.get("norad_id", "")):
            out.append(f"{where}: norad_id {r.get('norad_id')!r} is not a number")
        want_id = f"{r.get('norad_id')}-{r.get('event_type')}-{r.get('date')}"
        if r.get("event_id") != want_id:
            out.append(f"{where}: event_id should be {want_id!r}")
        if r.get("split") != split_of(r.get("event_id", "")):
            out.append(f"{where}: split should be {split_of(r.get('event_id', ''))!r} by the sha256 rule")
        if r.get("event_id") in seen:
            out.append(f"{where}: event_id is repeated")
        seen.add(r.get("event_id"))
    return out


def load_events(path: Path) -> list[Event]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != FIELDS:
            raise ValueError(f"{path}: header should be {','.join(FIELDS)}")
        rows = list(reader)
    problems = row_problems(rows)
    if problems:
        raise ValueError(f"{path}:\n" + "\n".join(problems))
    return [Event(r["event_id"], int(r["norad_id"]), r["event_type"], event_date(r["date"], r["date_precision"]),
                  r["split"]) for r in rows]


def determined(segs: Iterable[Segment]) -> list[Segment]:
    return [s for s in segs if s.mode != "undetermined"]


def transitions_of(segs: Sequence[Segment]) -> list[Transition]:
    d = determined(segs)
    return [Transition(a, b) for a, b in zip(d, d[1:])]


def _arcs_overlap(a: Segment, b: Segment) -> bool:
    def inside(x: float, s: Segment) -> bool:
        return (x - s.lon_min) % 360.0 <= (s.lon_max - s.lon_min) % 360.0
    return inside(a.lon_min, b) or inside(b.lon_min, a)


def is_jump(t: Transition) -> bool:
    a, b = t.before, t.after
    if a.mode not in HELD or b.mode not in HELD:
        return False
    if any(np.isnan(x) for x in (a.lon_min, a.lon_max, b.lon_min, b.lon_max)):
        return False
    return not _arcs_overlap(a, b)


def accepts(event_type: str, t: Transition) -> bool:
    a, b = t.before.mode, t.after.mode
    held_to_gone = a in HELD and (b in FREE or b == OUT_OF_REGION)
    if event_type == "relocation_start":
        return held_to_gone or is_jump(t)
    if event_type == "relocation_end":
        return ((a in FREE or a == OUT_OF_REGION) and b in HELD) or is_jump(t)
    if event_type == "graveyard":
        return held_to_gone
    if event_type == "keeping_stop":
        return a in HELD and b in FREE
    if event_type == "ns_keeping_stop":
        return a == "controlled_lon_inc" and b == "controlled_lon"
    raise ValueError(f"unknown event type {event_type!r}")


def unscored_reason(event: Event, geo_norads: set[int], holdout: set[int]) -> str | None:
    if event.norad_id in holdout:
        return HOLDOUT
    if not PERIOD[0] <= event.date <= PERIOD[1]:
        return OUTSIDE_PERIOD
    if event.norad_id not in geo_norads:
        return NOT_IN_GEO_SET
    return None


def score(events: Sequence[Event], segments_by_norad: dict[int, Sequence[Segment]], geo_norads: set[int],
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
        trans = transitions_of(segments_by_norad[norad])
        pairs = sorted((abs((t.date - e.date).days), e.date, t.date, i, j)
                       for i, e in enumerate(evs) for j, t in enumerate(trans)
                       if abs((t.date - e.date).days) <= WINDOW_DAYS and accepts(e.event_type, t))
        used_e, used_t = set(), set()
        for _, _, _, i, j in pairs:
            if i not in used_e and j not in used_t:
                used_e.add(i)
                used_t.add(j)
                results[evs[i].event_id] = Result(evs[i], "caught", trans[j])
        for i, e in enumerate(evs):
            if i not in used_e:
                results[e.event_id] = Result(e, "missed")
    return [results[e.event_id] for e in events]


def timeline(segs: Sequence[Segment], around: date) -> str:
    lo, hi = around - timedelta(days=TIMELINE_DAYS), around + timedelta(days=TIMELINE_DAYS)
    parts = []
    for s in determined(segs):
        start, end = s.start.date(), s.end.date()
        if end <= lo or start > hi:
            continue
        a = start.isoformat() if start >= lo else ""
        b = end.isoformat() if end <= hi else ""
        parts.append(f"{s.mode} {a}..{b}")
    return " | ".join(parts)


def _stats(results: Sequence[Result]) -> dict:
    scored = [r for r in results if r.status in ("caught", "missed")]
    errors = [abs(r.error_days) for r in scored if r.status == "caught"]
    return {"events": len(results), "scored": len(scored), "caught": len(errors),
            "recall": round(len(errors) / len(scored), 4) if scored else None,
            "median_abs_error_days": float(np.median(errors)) if errors else None,
            "p90_abs_error_days": float(np.percentile(errors, 90)) if errors else None}


def summarise(results: Sequence[Result]) -> dict:
    groups = {name: [r for r in results if r.event.split == name] for name in SPLITS}
    groups["overall"] = list(results)
    out = {}
    for name, rs in groups.items():
        out[name] = {**_stats(rs), "by_event_type": {t: _stats([r for r in rs if r.event.event_type == t])
                                                    for t in EVENT_TYPES}}
    out["unscored"] = [{"event_id": r.event.event_id, "reason": r.status}
                       for r in results if r.status not in ("caught", "missed")]
    return out


def _commit() -> dict:
    def git(*a):
        return subprocess.run(["git", *a], cwd=HERE, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}


def table(summary: dict) -> str:
    def f(x):
        return "-" if x is None else f"{x:g}"
    head = f"{'split':<8} {'event_type':<17} {'events':>6} {'scored':>6} {'caught':>6} {'recall':>6} {'med|d|':>6} {'p90|d|':>6}"
    lines = [head, "-" * len(head)]
    for name in (*SPLITS, "overall"):
        g = summary[name]
        rows = [("all", g)] + [(t, s) for t, s in g["by_event_type"].items() if s["events"]]
        for t, s in rows:
            lines.append(f"{name:<8} {t:<17} {s['events']:>6} {s['scored']:>6} {s['caught']:>6} {f(s['recall']):>6} "
                         f"{f(s['median_abs_error_days']):>6} {f(s['p90_abs_error_days']):>6}")
    lines.append(f"unscored: {len(summary['unscored'])}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Score the GEO mode layer against a cited list of real GEO events: "
                                "recall and dating error of the matching mode change.")
    p.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    p.add_argument("--geo-dir", type=Path, help="folder of <norad>.tle files; default $ORBIT_WATCH_DATA/geo")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="folder for summary.json and events.csv")
    a = p.parse_args(argv)
    geo_dir = a.geo_dir or data_dir() / "geo"
    events = load_events(a.events)
    holdout = {n for n, e in load_splits().items() if e["split"] == "holdout"}
    geo_norads = {e.norad_id for e in events if e.norad_id not in holdout and (geo_dir / f"{e.norad_id}.tle").is_file()}
    norads = sorted(geo_norads)
    with ProcessPoolExecutor() as pool:
        segs = dict(zip(norads, pool.map(object_segments, [geo_dir / f"{n}.tle" for n in norads])))
    results = score(events, segs, geo_norads, holdout)

    a.out.mkdir(parents=True, exist_ok=True)
    summary = {**_commit(), "events_file": a.events.name, "window_days": WINDOW_DAYS, **summarise(results)}
    (a.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
    with open(a.out / "events.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=EVENT_FIELDS, lineterminator="\n")
        w.writeheader()
        for r in results:
            t = r.transition
            w.writerow({"event_id": r.event.event_id, "split": r.event.split, "event_type": r.event.event_type,
                        "status": r.status, "transition": t.label if t else "",
                        "transition_date": t.date.isoformat() if t else "",
                        "error_days": "" if r.error_days is None else r.error_days,
                        "timeline": timeline(segs[r.event.norad_id], r.event.date) if r.event.norad_id in segs else ""})
    print(table(summary))
    print(f"wrote {a.out / 'summary.json'} and {a.out / 'events.csv'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
