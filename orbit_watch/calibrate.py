"""Calibrate the step detector against announced ISS manoeuvres.

    python -m orbit_watch.calibrate --tle data/archive/25544.tle \\
        --truth groundtruth/iss_manoeuvres.csv groundtruth/iss_roscosmos_manoeuvres.csv --out out

``--truth`` takes one or more event files; ``load_truth`` joins them and refuses an event that
appears in two of them. ``--frozen`` skips the choice below and scores ``FROZEN`` as it stands.

Holdout discipline: the window ``k``, the ``|z|`` threshold and the minimum
``|step|`` are chosen by F1 on 2021-2022 events only (ties go to the stricter
setting). The chosen setting is then frozen and 2023 is scored once with it;
2023 is the honest number.

An event matches a detection when the event's time (a point when ``time_utc``
is given, otherwise its date widened by one day either side) overlaps the
detection's interval (epoch before to epoch after the step) widened by
``TOLERANCE_DAYS``, and the step has the sign the burn implies: up for a
reboost (test burns included), down for a deboost or a burn the source calls
retrograde, either for the rest. Matching is one-to-one, closest centres first.

Recall counts events the detector could score: at least one scored gap overlaps
the event's window. Other events are listed as excluded for coverage. Precision
counts every detection in the period; a detection that matches no listed event
is a false positive, even though the list is a lower bound (announcements that were not
found are missing). The two unplanned attitude events are scored apart: a detection
matching one is reported with them and left out of the main precision.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from orbit_watch.detect import Detection, GapScores, pick, score_gaps
from orbit_watch.elements import parse_tle
from orbit_watch.series import to_series
from orbit_watch.truth import read_label_rows

ISS = 25544
TOLERANCE_DAYS = 0.5
HOLDOUT_START = np.datetime64("2023-01-01T00:00:00", "us")
K_GRID = (4, 6, 8)
Z_GRID = (3, 4, 5, 6, 7, 8, 10, 12, 15, 20, 25, 30)
STEP_GRID_M = (0, 50, 100, 150, 200, 300, 400)
UNPLANNED = "unplanned"
FROZEN = {"k": 4, "z_min": 12, "step_min_m": 200}  # run's choice on the archive, 2021-2022, NASA truth


@dataclass(frozen=True)
class Event:
    date_utc: str
    time_utc: str
    type: str
    delta_v_m_s: str
    lo: np.datetime64
    hi: np.datetime64

    @property
    def category(self) -> str:
        t = self.type
        if "unplanned" in t:
            return UNPLANNED
        if "test burn" in t or "aborted" in t:
            return "test/aborted burn"
        if t.startswith("reboost"):
            return "reboost"
        if "avoidance" in t:
            return "debris/collision avoidance"
        return "other burn"

    @property
    def expected_sign(self) -> int:
        """+1 if the step must go up, -1 if down, 0 if either."""
        if "retrograde" in self.type or "deboost" in self.type:
            return -1
        if self.type.startswith("reboost"):
            return 1
        return 0


def load_events(path: Path) -> list[Event]:
    events = []
    for row in read_label_rows(path, ISS):
        day = datetime.strptime(row["date_utc"], "%Y-%m-%d")
        if row["time_utc"]:
            hh, mm = map(int, row["time_utc"].split(":"))
            lo = hi = day + timedelta(hours=hh, minutes=mm)
        else:  # US-local date: plus or minus one day
            lo, hi = day - timedelta(days=1), day + timedelta(days=2)
        events.append(Event(row["date_utc"], row["time_utc"], row["type"], row["delta_v_m_s"],
                            np.datetime64(lo, "us"), np.datetime64(hi, "us")))
    return events


def load_truth(paths: list[Path]) -> list[Event]:
    """Events from one or more truth files. Raises when files list the same event twice.

    Two events from different files are the same event when their windows overlap within
    ``TOLERANCE_DAYS``: a timed row's point, or a date-only row's date plus or minus one day.
    shortcut: two genuinely different burns within that window in different files would be
    refused too; add an explicit allow-list if that ever happens.
    """
    per_file = [load_events(p) for p in paths]
    for i in range(len(per_file)):
        for j in range(i + 1, len(per_file)):
            for a in per_file[i]:
                for b in per_file[j]:
                    if _overlaps(a, b.lo, b.hi, TOLERANCE_DAYS):
                        raise ValueError(f"same event in {paths[i]} and {paths[j]}: "
                                         f"{a.date_utc} {a.time_utc} {a.type!r} / {b.date_utc} {b.time_utc} {b.type!r}")
    return [e for evs in per_file for e in evs]


def _sign_ok(ev, d: Detection) -> bool:
    """``ev`` is any event with ``expected_sign`` (+1, -1, or 0 for either)."""
    return ev.expected_sign == 0 or ev.expected_sign * d.step_m > 0


def _overlaps(ev: Event, start: np.datetime64, end: np.datetime64, tol_days: float) -> bool:
    tol = np.timedelta64(int(tol_days * 86_400e6), "us")
    return ev.lo <= end + tol and ev.hi >= start - tol


def match(events: list[Event], detections: list[Detection], tol_days: float = TOLERANCE_DAYS) -> dict[int, int]:
    """One-to-one event index -> detection index, closest centres first."""
    pairs = []
    for ei, ev in enumerate(events):
        ec = ev.lo + (ev.hi - ev.lo) / 2
        for di, d in enumerate(detections):
            if _overlaps(ev, d.start, d.end, tol_days) and _sign_ok(ev, d):
                dc = d.start + (d.end - d.start) / 2
                pairs.append((abs((ec - dc).astype("int64")), ei, di))
    out: dict[int, int] = {}
    used: set[int] = set()
    for _, ei, di in sorted(pairs):
        if ei not in out and di not in used:
            out[ei] = di
            used.add(di)
    return out


def covered(events: list[Event], scores: GapScores) -> list[bool]:
    v = scores.valid
    starts, ends = scores.start[v], scores.end[v]
    return [any(_overlaps(ev, s, e, TOLERANCE_DAYS) for s, e in zip(starts, ends)) for ev in events]


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def evaluate(events, cover, detections, in_period_ev, in_period_det):
    """Scores for one period. Main events exclude the unplanned attitude events."""
    main = [i for i, e in enumerate(events) if e.category != UNPLANNED]
    unpl = [i for i, e in enumerate(events) if e.category == UNPLANNED]
    m_main = match([events[i] for i in main], detections)
    m_main = {main[k]: v for k, v in m_main.items()}
    rest = [d for d in range(len(detections)) if d not in set(m_main.values())]
    m_unpl = match([events[i] for i in unpl], [detections[d] for d in rest])
    m_unpl = {unpl[k]: rest[v] for k, v in m_unpl.items()}

    dets = [d for d in range(len(detections)) if in_period_det[d]]
    unpl_dets = {d for d in m_unpl.values()}
    tp_dets = {d for d in m_main.values()}
    scored = [d for d in dets if d not in unpl_dets]
    tp = sum(d in tp_dets for d in scored)
    res = {
        "detections": len(dets),
        "detections_matching_unplanned_events": len([d for d in dets if d in unpl_dets]),
        "true_positives": tp,
        "false_positives": len(scored) - tp,
        "precision": _ratio(tp, len(scored)),
        "by_type": {},
    }
    cats = sorted({events[i].category for i in main})
    for cat in [None, *cats]:
        idx = [i for i in main if in_period_ev[i] and (cat is None or events[i].category == cat)]
        cov = [i for i in idx if cover[i]]
        hit = [i for i in cov if i in m_main]
        row = {"events": len(idx), "covered": len(cov), "matched": len(hit), "recall": _ratio(len(hit), len(cov))}
        if cat is None:
            res.update(row)
        else:
            res["by_type"][cat] = row
    res["unplanned_attitude_events"] = [
        {"date_utc": events[i].date_utc, "covered": cover[i], "matched": i in m_unpl}
        for i in unpl if in_period_ev[i]
    ]
    return res, m_main, m_unpl


def _f1(res) -> float:
    p, r = res["precision"] or 0.0, res["recall"] or 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def _iso(t: np.datetime64) -> str:
    return str(t.astype("datetime64[s]")) + "Z"


def choose_setting(events, scores_by_k, ev_in, det_in):
    """Sweep the grid scored on one period; ``det_in(dets)`` gives that period's detection mask.

    Only the period's events and detections are matched, so a detection outside the period can
    never take an event inside it, nor an event outside it (a label the choice must not see)
    a detection inside it.

    Returns the setting with the highest F1 (ties to the stricter setting) and the whole sweep.
    """
    events = [e for e, keep in zip(events, ev_in) if keep]
    sweep = []
    for k, sc in scores_by_k.items():
        cover = covered(events, sc)
        for z in Z_GRID:
            for s in STEP_GRID_M:
                dets = pick(sc, z, s)
                dets = [d for d, keep in zip(dets, det_in(dets)) if keep]
                # All-true masks: events and dets were already filtered to the period above.
                res, _, _ = evaluate(events, cover, dets, [True] * len(events), [True] * len(dets))
                sweep.append({"k": k, "z_min": z, "step_min_m": s, "f1": round(_f1(res), 4),
                              "precision": res["precision"], "recall": res["recall"]})
    best = max(sweep, key=lambda r: (r["f1"], r["z_min"], r["step_min_m"], -r["k"]))
    return best, sweep


DETECTION_HEADER = ["start_utc", "end_utc", "period", "step_m", "z", "sign", "matched_event_date",
                    "matched_event_type"]
EVENT_HEADER = ["date_utc", "time_utc", "type", "category", "delta_v_m_s", "period", "covered",
                "matched", "det_start_utc", "det_end_utc", "det_step_m", "det_z"]


def detection_rows(events, dets, det_period, m_main, m_unpl):
    det_event = {d: events[e] for e, d in {**m_main, **m_unpl}.items()}
    for i, d in enumerate(dets):
        ev = det_event.get(i)
        yield [_iso(d.start), _iso(d.end), det_period[i], round(d.step_m, 1), round(d.z, 2), d.sign,
               ev.date_utc if ev else "", ev.type if ev else ""]


def event_rows(events, ev_period, cover, dets, m_main, m_unpl):
    for i, e in enumerate(events):
        d = dets[m_main.get(i, m_unpl.get(i))] if (i in m_main or i in m_unpl) else None
        yield [e.date_utc, e.time_utc, e.type, e.category, e.delta_v_m_s, ev_period[i], cover[i],
               d is not None, _iso(d.start) if d else "", _iso(d.end) if d else "",
               round(d.step_m, 1) if d else "", round(d.z, 2) if d else ""]


def write_csv(path: Path, header, rows) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def run(tle: Path, truth: list[Path], out: Path, frozen: bool = False) -> dict:
    series = to_series(parse_tle(tle.read_text(encoding="utf-8")))[ISS]
    first, last = series.epochs[0], series.epochs[-1]
    all_events = load_truth(truth)
    events = [e for e in all_events if e.hi >= first and e.lo <= last]
    ev_hold = [e.date_utc >= "2023-01-01" for e in events]

    def det_hold(dets):
        return [d.start >= HOLDOUT_START for d in dets]

    # Tuning: 2021-2022 only, unless the frozen setting is scored as it stands.
    scores_by_k = {k: score_gaps(series, k=k) for k in K_GRID}
    if frozen:
        best, sweep = FROZEN, []
    else:
        best, sweep = choose_setting(events, scores_by_k, [not x for x in ev_hold],
                                     lambda dets: [not x for x in det_hold(dets)])
    k, z_min, step_min = best["k"], best["z_min"], best["step_min_m"]

    # Frozen setting on both periods.
    sc = scores_by_k[k]
    cover = covered(events, sc)
    dets = pick(sc, z_min, step_min)
    h = det_hold(dets)
    tune, m_main, m_unpl = evaluate(events, cover, dets, [not x for x in ev_hold], [not x for x in h])
    hold, _, _ = evaluate(events, cover, dets, ev_hold, h)

    out.mkdir(parents=True, exist_ok=True)
    write_csv(out / "detections.csv", DETECTION_HEADER,
              detection_rows(events, dets, ["2023" if x else "2021-2022" for x in h], m_main, m_unpl))
    write_csv(out / "events_scored.csv", EVENT_HEADER,
              event_rows(events, ["2023" if x else "2021-2022" for x in ev_hold], cover, dets, m_main, m_unpl))

    matched = set(m_main.values()) | set(m_unpl.values())
    report = {
        "tle_file": str(tle),
        "tle_count": len(series),
        "tle_first_epoch": _iso(first),
        "tle_last_epoch": _iso(last),
        "truth_files": [str(p) for p in truth],
        "truth_rows": len(all_events),
        "truth_rows_inside_tle_history": len(events),
        "tolerance_days": TOLERANCE_DAYS,
        "grid": {"k": K_GRID, "z_min": Z_GRID, "step_min_m": STEP_GRID_M},
        "frozen_thresholds": {"k": k, "z_min": z_min, "step_min_m": step_min, "nms_days": 1.0,
                              "chosen_by": "frozen (--frozen): not re-chosen" if frozen
                              else "max F1 on 2021-2022, ties to the stricter setting"},
        "noise_sigma_m_median": round(float(np.nanmedian(sc.sigma_m)), 1),
        "tuning_2021_2022": tune,
        "holdout_2023": hold,
        "excluded_for_coverage": [
            {"date_utc": e.date_utc, "type": e.type} for i, e in enumerate(events) if not cover[i]
        ],
        "unmatched_detections": [
            {"start_utc": _iso(d.start), "end_utc": _iso(d.end), "step_m": round(d.step_m, 1),
             "z": round(d.z, 2), "period": "2023" if h[i] else "2021-2022"}
            for i, d in enumerate(dets) if i not in matched
        ],
        "sweep_top10": sorted(sweep, key=lambda r: -r["f1"])[:10],
    }
    (out / "calibration.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    plot(series, events, cover, m_main, m_unpl, dets, out / "iss_sma.png")
    return report


def plot(series, events, cover, m_main, m_unpl, dets, path: Path, years=(2021, 2022, 2023)) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    t = series.epochs.astype("datetime64[s]").astype(datetime)
    a = series.semi_major_axis_km
    matched = set(m_main.values()) | set(m_unpl.values())
    fig, axes = plt.subplots(len(years), 1, figsize=(18, 13 * len(years) / 3))
    for ax, yr in zip(axes, years):
        sel = np.array([x.year == yr for x in t])
        ax.plot(np.array(t)[sel], a[sel], ".", ms=2, color="0.3", label="TLE mean semi-major axis")
        for i, e in enumerate(events):
            lo = e.lo.astype("datetime64[s]").astype(datetime)
            if lo.year != yr and (e.hi.astype("datetime64[s]").astype(datetime)).year != yr:
                continue
            hi = e.hi.astype("datetime64[s]").astype(datetime)
            colour = "tab:green" if (i in m_main or i in m_unpl) else ("tab:red" if cover[i] else "0.7")
            if e.category == UNPLANNED:
                colour = "tab:purple"
            ax.axvspan(lo, hi + timedelta(hours=2), color=colour, alpha=0.3, lw=0)
        for i, d in enumerate(dets):
            dc = (d.start + (d.end - d.start) / 2).astype("datetime64[s]").astype(datetime)
            if dc.year != yr:
                continue
            j = np.searchsorted(series.epochs, d.end)
            ax.plot([dc], [a[min(j, len(a) - 1)] + 0.4], "v", ms=7,
                    color="tab:blue" if i in matched else "tab:orange")
        ax.set_ylabel(f"{yr}: a (km)")
        ax.grid(alpha=0.3)
    axes[0].set_title("ISS mean semi-major axis. Bands: event matched (green), missed (red), "
                      "no coverage (grey), unplanned attitude (purple). Markers: detection matched "
                      "(blue), unmatched (orange)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--tle", type=Path, required=True)
    p.add_argument("--truth", type=Path, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--frozen", action="store_true", help="score FROZEN instead of choosing on 2021-2022")
    args = p.parse_args()
    r = run(args.tle, args.truth, args.out, args.frozen)
    summary = {key: r[key] for key in ("frozen_thresholds", "tuning_2021_2022", "holdout_2023",
                                         "excluded_for_coverage", "unmatched_detections")}
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
