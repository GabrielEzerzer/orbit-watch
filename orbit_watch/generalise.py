"""Does the ISS-tuned step detector generalise? Score it against IDS (LEO) and QZSS (GEO) logs.

    python -m orbit_watch.generalise --truth-dir groundtruth --tle-dir data/spacetrack \\
        --out findings/generalise

For each satellite, from its Space-Track gp_history and its operator manoeuvre log
(``orbit_watch.manoeuvre_logs``):

1. The frozen ISS setting as-is (``FROZEN``: k=4, |z|>=12, |step|>=200 m, NMS 1 day, gaps
   scored only when each side spans <=3 days and the gap <=2 days, as in the ISS run).
2. A per-regime tune with a time split. Each satellite's history is split at the first day of
   the month holding its 60th-percentile logged event (fixed from the log alone, before any
   scoring). ``k``, ``|z|`` and ``|step|`` are chosen by F1 pooled over the regime's satellites
   on the earlier part (ties go to the stricter setting, as in calibrate.py); the later part is
   scored once with that setting.

**The test part is not a blind holdout.** The late tolerance, the epoch collapse, burn merging
and the |z| grid beyond 30 (all below) were added after a first scoring of the test part had been
seen, and the lag figures that justify the late tolerance include test-part burns. Measured at
review: with the 0.5-day tolerance instead of 2 days, the tuned test part drops from P 162/260,
R 162/199 to P 138/260, R 138/196 at LEO, and from P 70/92, R 70/93 to P 60/88, R 60/90 at GEO
(the tune re-picks |z|>=7). Without merging, LEO is P 167/266, R 167/211 and GEO precision falls
to 74/110, so merging does not inflate the numbers. ``TEST_PART_NOT_BLIND`` carries this into the
report.

Matching follows calibrate.py: an event's window (start to end of the logged burn) must overlap
the detection's interval widened by ``TOLERANCE_DAYS``, one-to-one, closest centres first.
Changes, and why:

* Late tolerance. A detection may start up to ``LATE_DAYS`` after the burn ends (calibrate.py
  allows 0.5 day either side; 0.5 day before is kept). Space-Track element sets keep showing the
  old orbit for a while after a burn: the epoch before the largest step comes a median 0.9-1.1
  days after the logged burn for SPOT-5 and 0.2 days for QZS-3, with 90th percentiles of 1.2-2.8
  days (``lag_days`` in the report). The ISS archive did not show this lag.
* Input. Element sets less than ``MIN_EPOCH_GAP_S`` apart are collapsed to the later one before
  scoring. Space-Track history restates element sets at almost the same epoch (562 pairs under
  1 s for QZS-3, 25-63 for the others; one in the ISS archive). Two epochs microseconds apart
  give the Theil-Sen slope pairs a near-zero time base, and the detrended values then produce
  steps of thousands of km. ``detect.py`` is unchanged.
* Chance baseline. Every score is reported next to the same score with the logged events shifted
  by ``CHANCE_SHIFTS_DAYS`` (detections unchanged): what matching gives by coincidence.

* Sign. IDS along-track rows must step the way their along-track Delta-v points (the readme
  defines the axis "in the velocity direction"); IDS cross-track rows take either sign. QZSS
  rows take either sign, because the source does not define the DVX frame; the agreement of
  detected steps with the DVX sign is reported instead of assumed.
* Merging. Logged burns that start less than ``MERGE_HOURS`` after the previous one ends are one
  event with their Delta-a summed: at two to three TLEs a day no gap separates them. This covers
  the QZSS NS-1/NS-2 pairs (an hour apart) and the IDS burn/counter-burn pairs (SWOT, Jason-3:
  e.g. +364 m then -346 m four hours later), whose net change is what a TLE can see. A merged
  event whose rows push a in opposite directions takes either sign.
* Nothing is scored apart: every logged burn is an event, so a detection that matches any
  logged burn is a true positive, and every other detection counts against precision (and is
  listed, since a log can miss burns).

The |z| grid extends calibrate.py's to 300: LEO TLE scatter here is about 0.1 m (against 3 m for
the ISS), so z runs into the hundreds and a grid capped at 30 pinned the first tune to its edge.

Recall counts covered events (at least one scored gap overlaps the event window), by the
estimated |Delta-a| bin and by kind. Delta-a is the log parser's Gauss estimate, not measured.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from orbit_watch.calibrate import TOLERANCE_DAYS, Z_GRID, _iso, _ratio
from orbit_watch.detect import Detection, pick, score_gaps
from orbit_watch.elements import parse_omm_json
from orbit_watch.series import ElementSeries, to_series
from orbit_watch.truth import require_allowed


@dataclass(frozen=True)
class Setting:
    k: int
    z_min: float
    step_min_m: float
    nms_days: float = 1.0


FROZEN = Setting(k=4, z_min=12, step_min_m=200)  # FINDINGS.md, calibration run at 508838a
MAX_SPAN_DAYS, MAX_GAP_DAYS = 3.0, 2.0  # score_gaps defaults, used by the ISS run
SPLIT_QUANTILE = 0.6
MERGE_HOURS = 12.0
LATE_DAYS = 2.0
MIN_EPOCH_GAP_S = 60.0
CHANCE_SHIFTS_DAYS = (-19, -13, -7, 7, 13, 19)
K_GRID = (4, 6, 8)
Z_GRID_EXT = Z_GRID + (40, 60, 80, 100, 150, 200, 300)
STEP_GRID_M = {
    "LEO": (0, 10, 20, 30, 50, 100, 150, 200, 300, 400),
    "GEO": (0, 50, 100, 200, 300, 500, 1000, 1500, 2000, 3000),
}
BIN_EDGES_M = (0, 50, 100, 200, 500, 1000, 2000, 5000, float("inf"))
BIN_LABELS = ("<50 m", "50-100 m", "100-200 m", "200-500 m", "500 m-1 km", "1-2 km", "2-5 km",
              ">5 km")
SATELLITES = (  # (name, NORAD id, regime, ground-truth file)
    ("CryoSat-2", 36508, "LEO", "ids_manoeuvres.csv"),
    ("Jason-3", 41240, "LEO", "ids_manoeuvres.csv"),
    ("SWOT", 54754, "LEO", "ids_manoeuvres.csv"),
    ("SPOT-5", 27421, "LEO", "ids_manoeuvres.csv"),
    ("QZS-3", 42917, "GEO", "qzss_manoeuvres.csv"),
    ("QZS-6", 62876, "GEO", "qzss_manoeuvres.csv"),
)


@dataclass(frozen=True)
class LogEvent:
    event_id: str
    kind: str
    delta_a_est_m: float
    expected_sign: int  # +1 up, -1 down, 0 either (same rule as calibrate._sign_ok)
    lo: np.datetime64
    hi: np.datetime64
    n_rows: int = 1

    @property
    def bin(self) -> str:
        a = abs(self.delta_a_est_m)
        for label, top in zip(BIN_LABELS, BIN_EDGES_M[1:]):
            if a < top:
                return label
        return BIN_LABELS[-1]


def _t(s: str) -> np.datetime64:
    return np.datetime64(s.rstrip("Z"), "us")


def load_log_events(path: Path, norad: int, *, final: bool = False) -> list[LogEvent]:
    """Events for one satellite: one per log row, then merged when under ``MERGE_HOURS`` apart.

    Refuses holdout and unassigned objects unless ``final`` (``orbit_watch.truth``)."""
    require_allowed(norad, final=final)
    with open(path, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if int(r["norad_id"]) == norad]
    rows.sort(key=lambda r: r["start_utc"])
    merge_gap = np.timedelta64(int(MERGE_HOURS * 3600e6), "us")
    clusters: list[list[dict]] = []
    for r in rows:
        if clusters and _t(r["start_utc"]) - max(_t(x["end_utc"]) for x in clusters[-1]) < merge_gap:
            clusters[-1].append(r)
        else:
            clusters.append([r])
    events = []
    for rs in clusters:
        das = [float(r["delta_a_est_m"]) for r in rs]
        kinds = sorted({r["kind"] for r in rs})
        if "dvx_m_s" in rs[0] or kinds != ["along-track"]:
            sign = 0  # QZSS: DVX frame undocumented; IDS cross-track: no direction in a
        elif all(d > 0 for d in das) or all(d < 0 for d in das):
            sign = int(np.sign(das[0]))
        else:
            sign = 0  # burn and counter-burn: the net sign is within the estimate's error
        events.append(LogEvent("+".join(r["event_id"] for r in rs), "+".join(kinds),
                               round(sum(das), 1), sign, _t(rs[0]["start_utc"]),
                               max(_t(r["end_utc"]) for r in rs), len(rs)))
    return events


def drop_near_duplicates(series: ElementSeries, min_gap_s: float = MIN_EPOCH_GAP_S) -> ElementSeries:
    """Keep the later of any element sets whose epochs are under ``min_gap_s`` apart."""
    gaps_s = np.diff(series.epochs).astype("int64") / 1e6
    keep = np.append(gaps_s >= min_gap_s, True)
    return replace(series, **{f: getattr(series, f)[keep] for f in (
        "epochs", "semi_major_axis_km", "inclination", "eccentricity", "raan", "mean_motion", "bstar")})


def split_date(events: list[LogEvent]) -> np.datetime64:
    """First day of the month holding the ``SPLIT_QUANTILE`` event (by start time)."""
    lo = sorted(e.lo for e in events)
    t = lo[int(SPLIT_QUANTILE * (len(lo) - 1))]
    return t.astype("datetime64[M]").astype("datetime64[us]")


def _tol(tol_days: float) -> np.timedelta64:
    return np.timedelta64(int(tol_days * 86_400e6), "us")


def covered(events, scores, tol_days: float = TOLERANCE_DAYS,
            late_days: float | None = None) -> list[bool]:
    """``calibrate.covered``, vectorised, with an optional longer tolerance after the burn."""
    v = scores.valid
    starts, ends = scores.start[v], scores.end[v]  # both increasing, gaps are consecutive
    tol, late = _tol(tol_days), _tol(tol_days if late_days is None else late_days)
    out = []
    for ev in events:
        i = np.searchsorted(ends, ev.lo - tol)  # first gap ending at or after the window opens
        out.append(bool(i < len(starts) and starts[i] <= ev.hi + late))
    return out


def match_near(events, dets: list[Detection], tol_days: float = TOLERANCE_DAYS,
               late_days: float | None = None) -> dict[int, int]:
    """``calibrate.match`` with the candidate pairs found by array operations (same result when
    ``late_days`` is None).

    One-to-one event index -> detection index: the detection interval, widened by ``tol_days``
    before and ``late_days`` after the event, overlaps its window; the step sign fits
    ``expected_sign``; closest centres first.
    """
    if not dets or not events:
        return {}
    tol, late = _tol(tol_days), _tol(tol_days if late_days is None else late_days)
    ds = np.array([d.start for d in dets])
    de = np.array([d.end for d in dets])
    step = np.array([d.step_m for d in dets])
    dc = (ds + (de - ds) / 2).astype("int64")
    pairs = []
    for ei, ev in enumerate(events):
        ok = (ev.lo <= de + tol) & (ev.hi >= ds - late)
        if ev.expected_sign:
            ok &= ev.expected_sign * step > 0
        ec = (ev.lo + (ev.hi - ev.lo) / 2).astype("int64")
        pairs += [(abs(int(ec) - int(dc[di])), ei, int(di)) for di in np.flatnonzero(ok)]
    out: dict[int, int] = {}
    used: set[int] = set()
    for _, ei, di in sorted(pairs):
        if ei not in out and di not in used:
            out[ei] = di
            used.add(di)
    return out


def evaluate(events, cover, dets, m, ev_in, det_in) -> dict:
    """Counts for one period: precision over detections, recall over covered events by bin and kind."""
    matched_dets = set(m.values())
    d_idx = [i for i in range(len(dets)) if det_in[i]]
    tp = sum(i in matched_dets for i in d_idx)
    res = {"detections": len(d_idx), "true_positives": tp, "false_positives": len(d_idx) - tp,
           "precision": _ratio(tp, len(d_idx))}

    def recall(idx):
        cov = [i for i in idx if cover[i]]
        hit = [i for i in cov if i in m]
        return {"events": len(idx), "covered": len(cov), "matched": len(hit),
                "recall": _ratio(len(hit), len(cov))}

    e_idx = [i for i in range(len(events)) if ev_in[i]]
    res.update(recall(e_idx))
    res["by_delta_a_bin"] = {b: recall([i for i in e_idx if events[i].bin == b])
                             for b in BIN_LABELS if any(events[i].bin == b for i in e_idx)}
    res["by_kind"] = {k: recall([i for i in e_idx if events[i].kind == k])
                      for k in sorted({events[i].kind for i in e_idx})}
    return res


def _pool(results: list[dict]) -> dict:
    keys = ("detections", "true_positives", "false_positives", "events", "covered", "matched")
    p = {k: sum(r[k] for r in results) for k in keys}
    p["precision"] = _ratio(p["true_positives"], p["detections"])
    p["recall"] = _ratio(p["matched"], p["covered"])
    pr, rc = p["precision"] or 0.0, p["recall"] or 0.0
    p["f1"] = round(2 * pr * rc / (pr + rc), 4) if pr + rc else 0.0
    return p


class Satellite:
    """One object's series, log events, split and cached per-k gap scores."""

    def __init__(self, name: str, norad: int, regime: str, truth: Path, tle_dir: Path,
                 final: bool = False):
        require_allowed(norad, final=final)  # before the element sets are read
        (path,) = sorted(tle_dir.glob(f"gp_history-{norad}-*.json"))
        self.name, self.norad, self.regime, self.tle_file = name, norad, regime, path.name
        raw = to_series(parse_omm_json(path.read_text(encoding="utf-8")))[norad]
        self.series: ElementSeries = drop_near_duplicates(raw)
        self.near_duplicates_dropped = len(raw) - len(self.series)
        first, last = self.series.epochs[0], self.series.epochs[-1]
        self.all_events = load_log_events(truth, norad, final=final)
        self.events = [e for e in self.all_events if e.hi >= first and e.lo <= last]
        self.split = split_date(self.events)
        self.ev_test = [e.lo >= self.split for e in self.events]
        self._scores, self._cover = {}, {}

    def scores(self, k: int):
        if k not in self._scores:
            self._scores[k] = score_gaps(self.series, k=k, max_span_days=MAX_SPAN_DAYS,
                                         max_gap_days=MAX_GAP_DAYS)
            self._cover[k] = covered(self.events, self._scores[k], late_days=LATE_DAYS)
        return self._scores[k], self._cover[k]

    def run(self, s: Setting):
        sc, cover = self.scores(s.k)
        dets = pick(sc, s.z_min, s.step_min_m, s.nms_days)
        m = match_near(self.events, dets, late_days=LATE_DAYS)
        det_test = [d.start >= self.split for d in dets]
        return sc, cover, dets, m, det_test

    def chance(self, s: Setting, which: str) -> dict:
        """Mean recall and precision with the events shifted in time (detections unchanged)."""
        sc, _, dets, _, det_test = self.run(s)
        want = which == "test"
        rec, prec = [], []
        for shift in CHANCE_SHIFTS_DAYS:
            dt = _tol(shift)
            ev = [replace(e, lo=e.lo + dt, hi=e.hi + dt) for e in self.events]
            cover = covered(ev, sc, late_days=LATE_DAYS)
            m = match_near(ev, dets, late_days=LATE_DAYS)
            ev_in = [True] * len(ev) if which == "all" else [x == want for x in self.ev_test]
            det_in = [True] * len(dets) if which == "all" else [x == want for x in det_test]
            r = evaluate(ev, cover, dets, m, ev_in, det_in)
            rec.append(r["recall"] or 0.0)
            prec.append(r["precision"] or 0.0)
        return {"shifts_days": list(CHANCE_SHIFTS_DAYS), "recall_mean": round(float(np.mean(rec)), 3),
                "precision_mean": round(float(np.mean(prec)), 3)}

    def lag_days(self, which: str) -> dict:
        """Burn end to the epoch before the largest same-sign step (k=4 gaps), for events of
        |Delta-a| >= 50 m (LEO) or 500 m (GEO) whose step reaches 30% of the estimate."""
        sc, _ = self.scores(4)
        day = _tol(1.0)
        floor = 50 if self.regime == "LEO" else 500
        lags = []
        for i, e in enumerate(self.events):
            if abs(e.delta_a_est_m) < floor or self.ev_test[i] != (which == "test"):
                continue
            w = (sc.end >= e.lo - day) & (sc.start <= e.hi + 4 * day) & sc.valid
            if e.expected_sign:
                w &= np.sign(np.nan_to_num(sc.step_m)) == e.expected_sign
            if not w.any():
                continue
            j = np.flatnonzero(w)[np.argmax(np.abs(sc.step_m[w]))]
            if abs(sc.step_m[j]) >= 0.3 * abs(e.delta_a_est_m):
                lags.append((sc.start[j] - e.hi) / day)
        if not lags:
            return {"events": 0}
        return {"events": len(lags), "epoch_before_step_minus_burn_end": {
            "median": round(float(np.median(lags)), 2),
            "p10": round(float(np.percentile(lags, 10)), 2),
            "p90": round(float(np.percentile(lags, 90)), 2)}}

    def period(self, s: Setting, which: str) -> dict:
        _, cover, dets, m, det_test = self.run(s)
        if which == "all":
            ev_in, det_in = [True] * len(self.events), [True] * len(dets)
        else:
            want = which == "test"
            ev_in = [x == want for x in self.ev_test]
            det_in = [x == want for x in det_test]
        return evaluate(self.events, cover, dets, m, ev_in, det_in)

    def cadence(self) -> dict:
        t = self.series.epochs
        gaps_h = np.diff(t).astype("int64") / 3600e6
        days = (t[-1] - t[0]).astype("int64") / 86_400e6
        return {"tle_file": self.tle_file, "tle_count": len(t),
                "near_duplicates_dropped": self.near_duplicates_dropped, "first_epoch": _iso(t[0]),
                "last_epoch": _iso(t[-1]), "per_day": round(len(t) / days, 2),
                "median_gap_hours": round(float(np.median(gaps_h)), 1),
                "p90_gap_hours": round(float(np.percentile(gaps_h, 90)), 1),
                "gaps_over_2_days": int((gaps_h > 48).sum())}


def tune(sats: list[Satellite], regime: str) -> tuple[Setting, list[dict]]:
    sweep = []
    for k in K_GRID:
        for z in Z_GRID_EXT:
            for step in STEP_GRID_M[regime]:
                s = Setting(k, z, step)
                p = _pool([sat.period(s, "tune") for sat in sats])
                sweep.append({"k": k, "z_min": z, "step_min_m": step, **p})
    best = max(sweep, key=lambda r: (r["f1"], r["z_min"], r["step_min_m"], -r["k"]))
    return Setting(best["k"], best["z_min"], best["step_min_m"]), sweep


def _sign_and_ratio(sat: Satellite, s: Setting) -> dict:
    """For matched events: does the step sign agree with the estimate, and step / estimate."""
    _, _, dets, m, _ = sat.run(s)
    pairs = [(sat.events[e].delta_a_est_m, dets[d].step_m) for e, d in m.items()
             if abs(sat.events[e].delta_a_est_m) >= 100]
    same = sum(np.sign(a) == np.sign(st) for a, st in pairs)
    ratios = [st / a for a, st in pairs if np.sign(a) == np.sign(st)]
    return {"matched_events_with_estimate_ge_100m": len(pairs), "same_sign": int(same),
            "median_step_over_estimate": round(float(np.median(ratios)), 2) if ratios else None}


def write_csvs(sat: Satellite, settings: dict[str, Setting], out: Path) -> None:
    slug = sat.name.lower().replace("-", "")
    with open(out / f"{slug}_events_scored.csv", "w", newline="", encoding="utf-8") as fe, \
            open(out / f"{slug}_detections.csv", "w", newline="", encoding="utf-8") as fd:
        we, wd = csv.writer(fe), csv.writer(fd)
        we.writerow(["setting", "event_id", "n_rows", "start_utc", "end_utc", "kind", "delta_a_est_m",
                     "delta_a_bin", "period", "covered", "matched", "det_start_utc", "det_end_utc",
                     "det_step_m", "det_z"])
        wd.writerow(["setting", "start_utc", "end_utc", "period", "step_m", "z",
                     "matched_event_id", "matched_event_delta_a_est_m"])
        for name, s in settings.items():
            _, cover, dets, m, det_test = sat.run(s)
            inv = {d: e for e, d in m.items()}
            for i, e in enumerate(sat.events):
                d = dets[m[i]] if i in m else None
                we.writerow([name, e.event_id, e.n_rows, _iso(e.lo), _iso(e.hi), e.kind, e.delta_a_est_m, e.bin,
                             "test" if sat.ev_test[i] else "tune", cover[i], d is not None,
                             _iso(d.start) if d else "", _iso(d.end) if d else "",
                             round(d.step_m, 1) if d else "", round(d.z, 2) if d else ""])
            for j, d in enumerate(dets):
                e = sat.events[inv[j]] if j in inv else None
                wd.writerow([name, _iso(d.start), _iso(d.end), "test" if det_test[j] else "tune",
                             round(d.step_m, 1), round(d.z, 2), e.event_id if e else "",
                             e.delta_a_est_m if e else ""])


def plot(regime: str, sats: list[Satellite], tuned: Setting, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colours = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100")  # dataviz reference slots 1-4
    markers = ("o", "s", "^", "D")
    x = np.arange(len(BIN_LABELS))
    fig, axes = plt.subplots(1, 3, figsize=(18, 5.5))
    panels = ((FROZEN, "all", f"Frozen ISS setting, whole history\n(k={FROZEN.k}, |z|>={FROZEN.z_min:g}, "
                              f"|step|>={FROZEN.step_min_m:g} m)"),
              (tuned, "test", f"{regime} tune, later part only\n(k={tuned.k}, |z|>={tuned.z_min:g}, "
                              f"|step|>={tuned.step_min_m:g} m)"))
    for ax, (s, which, title) in zip(axes[:2], panels):
        for sat, c, mk in zip(sats, colours, markers):
            bins = sat.period(s, which)["by_delta_a_bin"]
            y = [bins[b]["recall"] if b in bins and bins[b]["recall"] is not None else np.nan
                 for b in BIN_LABELS]
            ax.plot(x, y, marker=mk, ms=8, lw=2, color=c, label=sat.name)
        ax.set_xticks(x, BIN_LABELS, rotation=35, ha="right")
        ax.set_ylim(-0.03, 1.03)
        ax.set_ylabel("recall (matched / covered events)")
        ax.set_xlabel("estimated |delta-a| of the logged burn")
        ax.set_title(title, fontsize=10)
        ax.grid(alpha=0.25)
    axes[0].legend(frameon=False)
    ax = axes[2]
    for sat, c, mk in zip(sats, colours, markers):
        _, _, dets, m, _ = sat.run(FROZEN)
        a = [abs(sat.events[e].delta_a_est_m) for e in m]
        st = [abs(dets[d].step_m) for d in m.values()]
        ax.scatter(a, st, s=40, marker=mk, color=c, edgecolors="white", linewidths=1, label=sat.name)
    lim = ax.get_xlim()[0] or 1, max(ax.get_xlim()[1], ax.get_ylim()[1])
    ax.plot([10, lim[1]], [10, lim[1]], color="0.5", lw=1, ls="--", label="detected = estimate")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("estimated |delta-a| from logged delta-v (m)")
    ax.set_ylabel("|detected step| (m)")
    ax.set_title("Matched events, frozen ISS setting", fontsize=10)
    ax.grid(alpha=0.25, which="both")
    ax.legend(frameon=False, fontsize=8)
    fig.suptitle(f"{regime}: step-detector recall against operator manoeuvre logs")
    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


TEST_PART_NOT_BLIND = (
    "Four method changes were made after a first scoring of the test part: the 2-day late "
    "tolerance, the <60 s epoch collapse, merging burns under 12 h apart, and the |z| grid beyond "
    "30. The lag figures behind the late tolerance include test-part burns. With a 0.5-day "
    "tolerance the tuned test part is LEO P 138/260, R 138/196 and GEO P 60/88, R 60/90 (tune "
    "re-picks |z|>=7); without merging, LEO P 167/266, R 167/211 and GEO precision 74/110. The "
    "GEO tune sits at the bottom of the |z| grid (3), so its 1000 m step floor does all the work."
)


def run(truth_dir: Path, tle_dir: Path, out: Path, final: bool = False) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    sats = [Satellite(n, norad, reg, truth_dir / f, tle_dir, final=final)
            for n, norad, reg, f in SATELLITES]
    report = {
        "frozen_iss_setting": {**FROZEN.__dict__, "max_span_days": MAX_SPAN_DAYS,
                               "max_gap_days": MAX_GAP_DAYS,
                               "source": "FINDINGS.md: calibration run at 508838a"},
        "tolerance_days": {"before_burn": TOLERANCE_DAYS, "after_burn": LATE_DAYS},
        "merge_hours": MERGE_HOURS,
        "split_rule": f"per satellite: first day of the month holding its {SPLIT_QUANTILE:.0%} "
                      "quantile logged event; tune before, test from it",
        "test_part_not_blind": TEST_PART_NOT_BLIND,
        "regimes": {}, "satellites": {},
    }
    for regime in ("LEO", "GEO"):
        group = [s for s in sats if s.regime == regime]
        tuned, sweep = tune(group, regime)
        report["regimes"][regime] = {
            "satellites": [s.name for s in group],
            "grid": {"k": K_GRID, "z_min": Z_GRID_EXT, "step_min_m": STEP_GRID_M[regime]},
            "tuned_setting": {**tuned.__dict__,
                              "chosen_by": "max F1 pooled over the regime on the tune part, ties "
                                           "to the stricter setting"},
            "pooled": {
                "frozen_iss_all": _pool([s.period(FROZEN, "all") for s in group]),
                "frozen_iss_test": _pool([s.period(FROZEN, "test") for s in group]),
                "tuned_tune": _pool([s.period(tuned, "tune") for s in group]),
                "tuned_test": _pool([s.period(tuned, "test") for s in group]),
            },
            "sweep_top10": sorted(sweep, key=lambda r: -r["f1"])[:10],
        }
        for sat in group:
            settings = {"frozen_iss": FROZEN, f"tuned_{regime.lower()}": tuned}
            write_csvs(sat, settings, out)
            sigma = {name: round(float(np.nanmedian(sat.scores(s.k)[0].sigma_m)), 1)
                     for name, s in settings.items()}
            _, _, dets, m, det_test = sat.run(FROZEN)
            matched = set(m.values())
            report["satellites"][sat.name] = {
                "norad_id": sat.norad, "regime": regime, "tle": sat.cadence(),
                "log_rows": sum(e.n_rows for e in sat.all_events),
                "log_events_after_merging": len(sat.all_events), "log_events_inside_tle_history": len(sat.events),
                "split_date": str(sat.split.astype("datetime64[D]")),
                "noise_sigma_m_median": sigma,
                "lag_days": {"tune": sat.lag_days("tune"), "test": sat.lag_days("test")},
                "frozen_iss": {"all": sat.period(FROZEN, "all"), "tune": sat.period(FROZEN, "tune"),
                               "test": sat.period(FROZEN, "test"),
                               "chance_all": sat.chance(FROZEN, "all"),
                               "chance_test": sat.chance(FROZEN, "test"),
                               "sign_and_size": _sign_and_ratio(sat, FROZEN)},
                "tuned": {"tune": sat.period(tuned, "tune"), "test": sat.period(tuned, "test"),
                          "chance_test": sat.chance(tuned, "test"),
                          "sign_and_size": _sign_and_ratio(sat, tuned)},
                "frozen_iss_unmatched_detections": [
                    {"start_utc": _iso(d.start), "end_utc": _iso(d.end), "step_m": round(d.step_m, 1),
                     "z": round(d.z, 2), "period": "test" if det_test[i] else "tune"}
                    for i, d in enumerate(dets) if i not in matched],
            }
        plot(regime, group, tuned, out / f"{regime.lower()}_recall.png")
    (out / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--truth-dir", type=Path, required=True)
    p.add_argument("--tle-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--final", action="store_true",
                   help="allow holdout objects (groundtruth/splits.json); only for the final scoring")
    args = p.parse_args(argv)
    r = run(args.truth_dir, args.tle_dir, args.out, final=args.final)
    for regime, v in r["regimes"].items():
        print(regime, json.dumps(v["tuned_setting"]), json.dumps(v["pooled"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
