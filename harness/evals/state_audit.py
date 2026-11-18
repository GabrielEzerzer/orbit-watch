# Hand audit of the belt's dated state changes: a fixed, stratified sample of findings/state_changes/events.csv,
# one chart and one numeric digest per sampled event from its element sets, and a summary of the hand verdicts.

from __future__ import annotations

import argparse
import csv
import json
import random
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from orbit_watch.clean import drop_snapback_blocks
from orbit_watch.elements import parse_tle
from orbit_watch.events import EVENT_TYPES, burns
from orbit_watch.modes import GRID_START, track
from orbit_watch.series import distinct_epochs
from orbit_watch.sources import data_dir
from orbit_watch.truth import GROUNDTRUTH, load_splits, read_event_rows

REPO = Path(__file__).resolve().parents[2]
EVENTS = REPO / "findings" / "state_changes" / "events.csv"
GEO_EVENTS = GROUNDTRUTH / "geo_events.csv"
OUT = REPO / "findings" / "state_audit"
SEED = "orbit-watch state audit 2026-11-18"
SAMPLE_SIZE = 50
MIN_PER_TYPE = 5
HALF_WINDOW_DAYS = 60
VERDICTS = ("real", "artefact", "wrong_type", "duplicate")
AUDIT_FIELDS = ["norad_id", "name", "event_type", "date", "verdict", "correct_type", "est_date", "date_error_days",
                "evidence"]


def excluded_objects(splits_path: Path | None = None, geo_events: Path = GEO_EVENTS) -> set[int]:
    splits = load_splits() if splits_path is None else load_splits(splits_path)
    out = {n for n, e in splits.items() if e["split"] == "holdout"}
    out |= {int(r["norad_id"]) for r in read_event_rows(geo_events)[1] if r["split"] == "test"}
    return out


def read_events(path: Path = EVENTS) -> list[dict]:
    return read_event_rows(path)[1]


def quotas(available: dict[str, int], total: int = SAMPLE_SIZE, floor: int = MIN_PER_TYPE) -> dict[str, int]:
    q = {t: min(floor, n) for t, n in available.items()}
    left = total - sum(q.values())
    pool = sum(available.values())
    share = {t: left * n / pool for t, n in available.items()}
    for t in q:
        q[t] = min(available[t], q[t] + int(share[t]))
    for t in sorted(available, key=lambda t: (-(share[t] - int(share[t])), t)):
        if sum(q.values()) >= total:
            break
        if q[t] < available[t]:
            q[t] += 1
    return q


def draw(events: Sequence[dict], excluded: set[int], seed: str = SEED) -> list[dict]:
    eligible = [e for e in events if int(e["norad_id"]) not in excluded]
    by_type = {t: sorted((e for e in eligible if e["event_type"] == t), key=lambda e: (int(e["norad_id"]), e["date"]))
               for t in EVENT_TYPES}
    q = quotas({t: len(v) for t, v in by_type.items() if v})
    picked = [e for t in EVENT_TYPES if t in q for e in random.Random(f"{seed}:{t}").sample(by_type[t], q[t])]
    return sorted(picked, key=lambda e: (EVENT_TYPES.index(e["event_type"]), int(e["norad_id"]), e["date"]))


def _names(geo_dir: Path) -> dict[int, str]:
    manifest = json.loads((geo_dir / "manifest.json").read_text(encoding="utf-8"))
    return {int(n): (o.get("satcat") or {}).get("OBJECT_NAME") or "" for n, o in manifest["objects"].items()}


def _segments(path: Path, norad: int) -> list[dict]:
    return [r for r in read_event_rows(path)[1] if int(r["norad_id"]) == norad]


def _day(d: str | date) -> float:
    d = date.fromisoformat(d) if isinstance(d, str) else d
    return float((datetime(d.year, d.month, d.day, tzinfo=timezone.utc) - GRID_START).days)


def _iso(day: float) -> str:
    return (GRID_START + timedelta(days=float(day))).date().isoformat()


def digest(e: dict, records, segs: Sequence[dict], neighbours: Sequence[dict]) -> dict:
    kept, blocks = drop_snapback_blocks(records)
    tr = track(records)
    tk = track(kept)
    t = _day(e["date"])
    sel = (tk.days >= t - HALF_WINDOW_DAYS) & (tk.days <= t + HALF_WINDOW_DAYS)
    burn_days, steps = burns(kept) if len(kept) > 10 else (np.array([]), np.array([]))
    near = np.abs(burn_days - t) <= HALF_WINDOW_DAYS

    def side(lo: float, hi: float) -> dict:
        s = (tk.days >= t + lo) & (tk.days < t + hi)
        if not s.any():
            return {"n": 0}
        u = np.degrees(np.unwrap(np.radians(tk.lon[s])))
        return {"n": int(s.sum()), "rate": round(float(np.median(tk.rate[s])), 4),
                "lon": round(float(np.median(tk.lon[s])), 3), "lon_spread": round(float(np.ptp(u)), 3),
                "sma": round(float(np.median(tk.semi_major_axis_km[s])), 2),
                "inc": round(float(np.median(tk.inclination[s])), 3)}

    gaps = np.diff(tk.days[sel]) if sel.sum() > 1 else np.array([])
    return {
        "norad_id": int(e["norad_id"]), "event_type": e["event_type"], "date": e["date"], "signal": e["signal"],
        "size": e["size"], "first_set": _iso(tr.days[0]), "last_set": _iso(tr.days[-1]),
        "sets_in_window": int(sel.sum()), "max_gap_days": round(float(gaps.max()), 1) if len(gaps) else None,
        "dropped_by_clean_in_window": int(((tr.days >= t - HALF_WINDOW_DAYS) & (tr.days <= t + HALF_WINDOW_DAYS)).sum()
                                          - sel.sum()),
        "snapback_blocks_near": [b.start.date().isoformat() + ":" + b.channel for b in blocks
                                 if abs(_day(b.start.date()) - t) <= HALF_WINDOW_DAYS],
        "before_30_5": side(-30, -5), "before_5_0": side(-5, 0), "after_0_5": side(0, 5), "after_5_30": side(5, 30),
        "burns_in_window": [f"{_iso(d)}:{s:+.0f}m" for d, s in zip(burn_days[near], steps[near])],
        "neighbours": [f"{n['date']}:{n['event_type']}" for n in neighbours if n is not e],
        "segments": [f"{s['start']}..{s['end']}:{s['mode']}" for s in segs
                     if _day(s["end"]) >= t - HALF_WINDOW_DAYS - 30 and _day(s["start"]) <= t + HALF_WINDOW_DAYS + 30],
    }


def chart(e: dict, name: str, records, segs: Sequence[dict], neighbours: Sequence[dict], path: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    kept, _ = drop_snapback_blocks(records)
    tr, tk = track(records), track(kept)
    t = _day(e["date"])
    lo, hi = t - HALF_WINDOW_DAYS, t + HALF_WINDOW_DAYS
    raw = (tr.days >= lo) & (tr.days <= hi)
    sel = (tk.days >= lo) & (tk.days <= hi)
    dx = tk.days[sel] - t
    node = np.radians([r.raan for r in kept])
    ix, iy = tk.inclination * np.cos(node), tk.inclination * np.sin(node)
    fig, ax = plt.subplots(5, 1, figsize=(10, 12), sharex=True)
    series = [("mean longitude (deg)", tk.lon, tr.lon), ("drift rate (deg/day)", tk.rate, tr.rate),
              ("semi-major axis - 42164 (km)", tk.semi_major_axis_km - 42164.0, tr.semi_major_axis_km - 42164.0),
              ("i cos RAAN (deg)", ix, None), ("i sin RAAN (deg)", iy, None)]
    for a, (label, kept_y, raw_y) in zip(ax, series):
        if raw_y is not None:
            a.plot(tr.days[raw] - t, raw_y[raw], "x", color="#c44", ms=3, label="all sets")
        a.plot(dx, kept_y[sel], ".", color="#246", ms=3, label="after snap-back filter")
        a.set_ylabel(label, fontsize=8)
        a.axvline(0, color="#d22", lw=1.5)
        for n in neighbours:
            if n is not e and lo <= _day(n["date"]) <= hi:
                a.axvline(_day(n["date"]) - t, color="#888", lw=1, ls="--")
        for s in segs:
            s0, s1 = max(_day(s["start"]), lo) - t, min(_day(s["end"]), hi) - t
            if s0 < s1:
                a.axvspan(s0, s1, alpha=0.08, color="#2a2" if s["mode"].startswith("controlled") else "#aa2")
    for s in segs:
        s0, s1 = max(_day(s["start"]), lo) - t, min(_day(s["end"]), hi) - t
        if s0 < s1:
            ax[0].text((s0 + s1) / 2, 1.01, s["mode"], transform=ax[0].get_xaxis_transform(), ha="center", fontsize=7)
    for n in neighbours:
        if n is not e and lo <= _day(n["date"]) <= hi:
            ax[1].text(_day(n["date"]) - t, 0.95, n["event_type"], transform=ax[1].get_xaxis_transform(),
                       rotation=90, va="top", fontsize=7, color="#555")
    ax[0].legend(fontsize=7, loc="lower left")
    ax[-1].set_xlabel(f"days from {e['date']}")
    fig.suptitle(f"{e['norad_id']} {name}: {e['event_type']} {e['date']} ({e['signal']}, size {e['size']})", y=0.995)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=90)
    plt.close(fig)


def summarise(rows: Sequence[dict]) -> dict:
    per = {t: dict(Counter(r["verdict"] for r in rows if r["event_type"] == t)) for t in EVENT_TYPES}
    real = [r for r in rows if r["verdict"] == "real"]
    errors = [abs(int(r["date_error_days"])) for r in real if r["date_error_days"] not in ("", "unclear")]
    return {
        "events": len(rows),
        "verdicts": dict(Counter(r["verdict"] for r in rows)),
        "verdicts_by_type": per,
        "real_right_type": len(real),
        "real_any_type": len(real) + sum(r["verdict"] == "wrong_type" for r in rows),
        "real_date_dated": len(errors),
        "real_date_unclear": len(real) - len(errors),
        "real_median_abs_error_days": float(np.median(errors)) if errors else None,
        "real_p90_abs_error_days": float(np.percentile(errors, 90)) if errors else None,
        "real_within_3_days": sum(x <= 3 for x in errors),
        "corrected_types": dict(Counter(r["correct_type"] for r in rows if r["verdict"] == "wrong_type")),
    }


def check_rows(rows: Sequence[dict], sample: Sequence[dict]) -> list[str]:
    out = []
    want = [(int(s["norad_id"]), s["event_type"], s["date"]) for s in sample]
    got = [(int(r["norad_id"]), r["event_type"], r["date"]) for r in rows]
    if got != want:
        out.append("audit rows do not match the sample, in order")
    for r in rows:
        where = f"{r['norad_id']} {r['event_type']} {r['date']}"
        if r["verdict"] not in VERDICTS:
            out.append(f"{where}: verdict {r['verdict']!r}")
        if (r["verdict"] == "wrong_type") != bool(r["correct_type"]):
            out.append(f"{where}: correct_type is set exactly when the verdict is wrong_type")
        if not r["evidence"]:
            out.append(f"{where}: no evidence")
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Hand audit of the belt's dated state changes: draw the fixed sample, "
                                "chart each sampled event, or summarise the hand verdicts.")
    p.add_argument("step", choices=("sample", "chart", "summary"))
    p.add_argument("--out", type=Path, default=OUT, help="folder for audit.csv and summary.json")
    a = p.parse_args(argv)
    sample = draw(read_events(), excluded_objects())
    if a.step == "sample":
        w = csv.DictWriter(sys.stdout, fieldnames=list(sample[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(sample)
        return 0
    if a.step == "summary":
        rows = read_events(a.out / "audit.csv")
        problems = check_rows(rows, sample)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            return 1
        summary = {"sample_seed": SEED, **summarise(rows)}
        (a.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8", newline="\n")
        print(json.dumps(summary, indent=2))
        return 0
    geo = data_dir() / "geo"
    scratch = data_dir() / "state_audit"
    names = _names(geo)
    every = read_events()
    digests = []
    for k, e in enumerate(sample):
        norad = int(e["norad_id"])
        (records,) = distinct_epochs(parse_tle((geo / f"{norad}.tle").read_text(encoding="utf-8"))).values()
        segs = _segments(data_dir() / "geo_modes" / "segments.csv", norad)
        neighbours = [n for n in every if int(n["norad_id"]) == norad]
        d = {"row": k + 1, "name": names.get(norad, ""), **digest(e, records, segs, neighbours)}
        digests.append(d)
        chart(e, d["name"], records, segs, neighbours, scratch / f"{k + 1:02d}_{norad}_{e['event_type']}_{e['date']}.png")
        print(f"{k + 1:02d} {norad} {e['event_type']} {e['date']}", flush=True)
    (scratch / "digests.json").write_text(json.dumps(digests, indent=1) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
