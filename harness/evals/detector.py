"""The frozen evaluation of the step detector, per regime: the score every hill-climb round reports.

    python -m harness.evals.detector --split dev --data-dir <data> [--settings <json>] [--out <json>]
    python -m harness.evals.detector --split test --final --data-dir <data>   # final round only

``split.json`` (beside this file) fixes the periods and objects: ``train`` and ``dev`` are the
train objects of ``groundtruth/splits.json`` in 2021-2023 and 2024-2025, ``test`` is the holdout
objects over 2021-2025 and needs ``--final``, which is passed to the holdout guard
(``orbit_watch.truth``). The detector setting per regime (ISS, LEO, GEO, IGSO) comes from a
settings JSON (``settings/frozen.json`` by default); the Fengyun objects take the GEO setting.

Everything that decides a match is ``orbit_watch.generalise``'s: ``load_log_events`` (12 h merging),
``log_coverage``, ``covered``, ``match_near`` with ``TOLERANCE_DAYS`` before the burn and
``LATE_DAYS`` after it, and its rule that a detection matching an attitude-only line is dropped.
The ISS keeps calibrate.py's rules, which ``match_near`` gives with ``late_days=None``: its events
come from ``calibrate.load_truth`` (NASA and Roscosmos lists), its tolerance is
``TOLERANCE_DAYS`` either side, its unplanned attitude events are dropped like attitude lines, and
its element sets come from ``holdout.load_gp_history`` (latest issued wins), as in every ISS score
so far. The detector runs once on each object's whole 2021-2025 series (``score_gaps`` and its
noise floor use no labels); a period's events and detections are then matched only with each
other, as ``calibrate.choose_setting`` does, so no label outside the period reaches its score.

Per group and period:

* Recall = matched / covered events (an event is covered when a scored gap overlaps its window),
  with a 95% Wilson interval. LEO also reports recall on events whose merged ``|delta_a_est_m|``
  is at least 50 m; an event without an estimate (none in the IDS logs; every Fengyun line) is in
  the all-events recall and left out of that subset. Merged burn/counter-burn pairs use their net
  estimate, which is what a TLE sees.
* False alarms per object-year on log-covered stretches with no logged burn. The covered span is
  the log's coverage (``log_coverage``) clipped to the period. Every logged event, attitude lines
  and other periods' events included, removes the zone in which a detection could match it,
  ``[start - TOLERANCE_DAYS, end + late]``, and so does all time outside the gaps the detector
  scores at that setting's ``k`` (a detection can only sit on a scored gap, so unscored time is no
  exposure; without this an object the detector cannot score, such as QZS-4 at k=4, would show a
  clean false-alarm rate). What is left are the no-burn stretches, and their summed length in
  years of 365.25 days is the exposure. A false alarm is an unmatched detection that lies wholly
  inside one stretch. Pooled over the group: false alarms / object-years.
* ``covered`` depends on ``k`` (a larger window scores fewer gaps), so recall over covered events
  can rise because hard events left the denominator. Each subset therefore also reports
  ``recall_all_events`` (matched / events), which a round should not lower.

The ISS lists are lower bounds, not operator logs, so the ISS false-alarm rate is reported but
not checked against the target. Fengyun is reported and never checked (``groundtruth/README.md``).
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from orbit_watch import calibrate, holdout
from orbit_watch.detect import Detection, pick, score_gaps
from orbit_watch.generalise import (LATE_DAYS, MAX_GAP_DAYS, MAX_SPAN_DAYS, TOLERANCE_DAYS, Setting,
                                    covered, load_log_events, load_series, log_coverage, match_near)
from orbit_watch.truth import GROUNDTRUTH, HoldoutError, load_splits, require_allowed

HERE = Path(__file__).resolve().parent
SPLIT_PATH = HERE / "split.json"
DEFAULT_SETTINGS = HERE / "settings" / "frozen.json"
RESULTS = HERE / "results"
YEAR_DAYS = 365.25
Z95 = 1.959963984540054
LEO_MIN_DELTA_A_M = 50.0
FA_MAX_PER_OBJECT_YEAR = 1.0
GROUP_ORDER = ("LEO", "GEO", "IGSO", "ISS", "GEO-Fengyun")
SETTING_KEY = {"LEO": "LEO", "GEO": "GEO", "IGSO": "IGSO", "ISS": "ISS", "GEO-Fengyun": "GEO"}
# (group, subset) -> minimum recall. FA <= 1 per object-year is checked for every group in FA_CHECKED.
RECALL_TARGETS = {("LEO", ">=50 m"): 0.9, ("GEO", "EW"): 0.9, ("GEO", "NS"): 0.8, ("ISS", "all"): 0.95}
FA_CHECKED = ("LEO", "GEO", "IGSO")
_DAY = np.timedelta64(86_400_000_000, "us")


# ---------------------------------------------------------------- arithmetic

def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    """95% Wilson score interval for k successes in n trials (None when n == 0)."""
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def recall(matched: int, covered_n: int, events: int) -> dict:
    ci = wilson(matched, covered_n)
    return {"events": events, "covered": covered_n, "matched": matched,
            "recall": round(matched / covered_n, 4) if covered_n else None,
            "recall_all_events": round(matched / events, 4) if events else None,
            "ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
            "ci95_width": round(ci[1] - ci[0], 4) if ci else None}


def fa_rate(false_alarms: int, object_years: float) -> float | None:
    return round(false_alarms / object_years, 4) if object_years > 0 else None


def subtract(span: tuple, zones: list[tuple]) -> list[tuple]:
    """``span`` (lo, hi) minus the union of ``zones``, as sorted disjoint (lo, hi) stretches."""
    lo, hi = span
    out, cur = [], lo
    for zl, zh in sorted(zones):
        if zh <= cur:
            continue
        if zl >= hi:
            break
        if zl > cur:
            out.append((cur, zl))
        cur = max(cur, zh)
    if cur < hi:
        out.append((cur, hi))
    return out


def years(stretches: list[tuple]) -> float:
    return sum((b - a) / _DAY for a, b in stretches) / YEAR_DAYS


# ---------------------------------------------------------------- objects

@dataclass
class Obj:
    norad: int
    name: str
    group: str
    source: str
    series: object
    events: list  # scoring targets
    excluded: list  # attitude lines and unplanned ISS events: not targets, their matches dropped
    coverage: tuple
    late_days: float | None
    _scores: dict = field(default_factory=dict)

    def scores(self, k: int):
        if k not in self._scores:
            self._scores[k] = score_gaps(self.series, k=k, max_span_days=MAX_SPAN_DAYS,
                                         max_gap_days=MAX_GAP_DAYS)
        return self._scores[k]


def load_object(entry: dict, truth_dir: Path, tle_dir: Path, geo_dir: Path, group: str,
                final: bool) -> Obj:
    norad = int(entry["norad_id"])
    require_allowed(norad, final=final)
    if group == "ISS":
        (gp,) = sorted(tle_dir.glob(f"gp_history-{norad}-*.json"))
        series, _ = holdout.load_gp_history(gp)
        evs = calibrate.load_truth([truth_dir / f for f in entry["truth_files"]])
        return Obj(norad, entry["name"], group, gp.name, series,
                   [e for e in evs if e.category != calibrate.UNPLANNED],
                   [e for e in evs if e.category == calibrate.UNPLANNED],
                   (np.datetime64("2021-01-01", "us"), np.datetime64("2026-01-01", "us")), None)
    (truth_file,) = entry["truth_files"]
    path = truth_dir / truth_file
    series, source, _ = load_series(norad, tle_dir, geo_dir, final=final)
    evs = load_log_events(path, norad, final=final)
    return Obj(norad, entry["name"], group, source, series,
               [e for e in evs if e.kind != "attitude"], [e for e in evs if e.kind == "attitude"],
               log_coverage(path, norad, final=final), LATE_DAYS)


def _mid(e) -> np.datetime64:
    return e.lo + (e.hi - e.lo) / 2


def _tol(days: float) -> np.timedelta64:
    return np.timedelta64(int(days * 86_400e6), "us")


def subset_of(obj: Obj, e) -> list[str]:
    """The table subsets an event counts in, besides 'all'."""
    if obj.group == "LEO":
        return [">=50 m"] if e.delta_a_est_m is not None and abs(e.delta_a_est_m) >= LEO_MIN_DELTA_A_M else []
    if obj.group in ("GEO", "GEO-Fengyun"):
        return [e.kind] if e.kind in ("EW", "NS", "EW+NS") else []  # EW+NS: merged under 12 h
    return []


def score_object(obj: Obj, s: Setting, lo: np.datetime64, hi: np.datetime64) -> dict:
    """One object in one period [lo, hi)."""
    sc = obj.scores(s.k)
    in_p = lambda t: lo <= t < hi  # noqa: E731
    ev = [e for e in obj.events if in_p(_mid(e))]
    exc = [e for e in obj.excluded if in_p(_mid(e))]
    dets: list[Detection] = [d for d in pick(sc, s.z_min, s.step_min_m, s.nms_days) if in_p(d.start)]
    cover = covered(ev, sc, TOLERANCE_DAYS, obj.late_days)
    m = match_near(ev, dets, TOLERANCE_DAYS, obj.late_days)
    rest = [i for i in range(len(dets)) if i not in set(m.values())]
    m_exc = match_near(exc, [dets[i] for i in rest], TOLERANCE_DAYS, obj.late_days)
    unmatched = [i for j, i in enumerate(rest) if j not in set(m_exc.values())]

    late = _tol(TOLERANCE_DAYS if obj.late_days is None else obj.late_days)
    span = (max(lo, obj.coverage[0]), min(hi, obj.coverage[1]))
    zones = [(e.lo - _tol(TOLERANCE_DAYS), e.hi + late) for e in obj.events + obj.excluded]
    if span[0] < span[1]:
        unscored = subtract(span, list(zip(sc.start[sc.valid], sc.end[sc.valid])))
        stretches = subtract(span, zones + unscored)
    else:
        stretches = []
    fa = [i for i in unmatched
          if any(a <= dets[i].start and dets[i].end <= b for a, b in stretches)]

    subsets: dict[str, dict] = {}
    for name in ["all"] + sorted({x for e in ev for x in subset_of(obj, e)}):
        idx = [i for i, e in enumerate(ev) if name == "all" or name in subset_of(obj, e)]
        cov = [i for i in idx if cover[i]]
        subsets[name] = {"events": len(idx), "covered": len(cov), "matched": sum(i in m for i in cov)}
    return {
        "subsets": subsets,
        "detections": len(dets), "matched_detections": len(m),
        "dropped_attitude_or_unplanned": len(m_exc),
        "false_alarms": len(fa), "object_years": years(stretches),
        "_detail": {
            "missed": [{"event_id": getattr(e, "event_id", None) or f"{e.date_utc} {e.time_utc}".strip(),
                        "start_utc": calibrate._iso(e.lo), "kind": getattr(e, "kind", None) or e.category,
                        "delta_a_est_m": getattr(e, "delta_a_est_m", None)}
                       for i, e in enumerate(ev) if cover[i] and i not in m],
            "false_alarms": [{"start_utc": calibrate._iso(dets[i].start), "end_utc": calibrate._iso(dets[i].end),
                              "step_m": round(dets[i].step_m, 1), "z": round(dets[i].z, 2)} for i in fa],
        },
    }


# ---------------------------------------------------------------- run

def _commit() -> dict:
    def git(*a):
        return subprocess.run(["git", *a], cwd=HERE, capture_output=True, text=True).stdout.strip()
    return {"commit": git("rev-parse", "HEAD"),
            "dirty": bool(git("status", "--porcelain", "--untracked-files=no"))}


def load_settings(path: Path) -> tuple[str, dict[str, Setting]]:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return d["name"], {r: Setting(**v) for r, v in d["regimes"].items()}


def evaluate(split: str, settings_path: Path, data_dir: Path, truth_dir: Path = GROUNDTRUTH,
             final: bool = False) -> dict:
    spec = json.loads(SPLIT_PATH.read_text(encoding="utf-8"))
    period = spec["periods"][split]
    if period.get("requires_final") and not final:
        raise HoldoutError(f"--split {split} scores the holdout objects; it needs --final, and is run "
                           "once at baseline and once at the final round (.agent/journal.md)")
    if final and not period.get("requires_final"):
        raise HoldoutError("--final is only for --split test")
    lo, hi = (np.datetime64(period[k], "us") for k in ("from", "to"))
    name, settings = load_settings(settings_path)
    splits = load_splits()
    tle_dir, geo_dir = data_dir / "spacetrack", data_dir / "geo"

    per_obj, pooled = {}, {}
    for o in spec["objects"][period["objects"]]:
        entry = splits[int(o["norad_id"])]
        assert entry["split"] == period["objects"], f"split.json disagrees with splits.json on {o}"
        obj = load_object(entry, truth_dir, tle_dir, geo_dir, o["group"], final)
        r = score_object(obj, settings[SETTING_KEY[obj.group]], lo, hi)
        detail = r.pop("_detail")
        per_obj[obj.name] = {"norad_id": obj.norad, "group": obj.group, "element_source": obj.source,
                             "element_sets": len(obj.series), **r,
                             "object_years": round(r["object_years"], 4)}
        if not final:  # no per-event detail for the holdout: the test score is a count, not a guide
            per_obj[obj.name].update(detail)
        g = pooled.setdefault(obj.group, {"objects": [], "subsets": {}, "false_alarms": 0, "object_years": 0.0})
        g["objects"].append(obj.name)
        g["false_alarms"] += r["false_alarms"]
        g["object_years"] += r["object_years"]
        for sub, c in r["subsets"].items():
            acc = g["subsets"].setdefault(sub, {"events": 0, "covered": 0, "matched": 0})
            for k in acc:
                acc[k] += c[k]

    groups = {}
    for gname in GROUP_ORDER:
        if gname not in pooled:
            continue
        g = pooled[gname]
        groups[gname] = {
            "objects": g["objects"], "setting": settings[SETTING_KEY[gname]].__dict__,
            "subsets": {sub: recall(c["matched"], c["covered"], c["events"]) for sub, c in g["subsets"].items()},
            "false_alarms": g["false_alarms"], "object_years": round(g["object_years"], 3),
            "fa_per_object_year": fa_rate(g["false_alarms"], g["object_years"]),
        }
    return {"split": split, "period": period, "settings": name, **_commit(),
            "tolerance_days": {"before": TOLERANCE_DAYS, "after": LATE_DAYS, "after_iss": TOLERANCE_DAYS},
            "targets": targets(groups), "groups": groups, "objects": per_obj}


def targets(groups: dict) -> list[dict]:
    out = []
    for (g, sub), want in RECALL_TARGETS.items():
        r = groups.get(g, {}).get("subsets", {}).get(sub)
        val = r["recall"] if r else None
        out.append({"check": f"{g} recall {sub}", "target": f">= {want}", "value": val,
                    "ci95": r["ci95"] if r else None,
                    "status": "no events" if val is None else ("PASS" if val >= want else "MISS")})
    for g in FA_CHECKED:
        v = groups.get(g, {}).get("fa_per_object_year")
        yrs = groups.get(g, {}).get("object_years", 0.0)
        out.append({"check": f"{g} false alarms / object-year ({yrs:.2f} obj-yr)",
                    "target": f"<= {FA_MAX_PER_OBJECT_YEAR}", "value": v, "object_years": yrs,
                    "status": "no exposure" if v is None
                    else ("PASS" if v <= FA_MAX_PER_OBJECT_YEAR else "MISS")})
    return out


def table(res: dict) -> str:
    def f(x, nd=3):
        return "-" if x is None else f"{x:.{nd}f}"
    head = (f"{'group':<12} {'subset':<7} {'events':>6} {'cov':>4} {'hit':>4} {'recall':>6} "
            f"{'95% CI':>13} {'width':>5} {'hit/ev':>6} {'FA':>4} {'obj-yr':>7} {'FA/yr':>6}")
    lines = [f"split={res['split']} ({res['period']['from']} to {res['period']['to']}, "
             f"{res['period']['objects']} objects)  settings={res['settings']}  "
             f"commit={res['commit'][:7]}{' (dirty)' if res['dirty'] else ''}", head, "-" * len(head)]
    for gname, g in res["groups"].items():
        for j, (sub, r) in enumerate(g["subsets"].items()):
            ci = f"[{r['ci95'][0]:.2f}, {r['ci95'][1]:.2f}]" if r["ci95"] else "-"
            fa = (f"{g['false_alarms']:>4} {g['object_years']:>7.2f} {f(g['fa_per_object_year'], 2):>6}"
                  if j == 0 else "")
            lines.append(f"{gname if j == 0 else '':<12} {sub:<7} {r['events']:>6} {r['covered']:>4} "
                         f"{r['matched']:>4} {f(r['recall']):>6} {ci:>13} {f(r['ci95_width'], 2):>5} "
                         f"{f(r['recall_all_events']):>6} {fa}".rstrip())
    lines.append("ISS false alarms are against lower-bound lists and not checked; GEO-Fengyun is exploratory.")
    lines.append("targets: " + " | ".join(
        f"{t['check']} {f(t['value'])} ({t['target']}) {t['status']}" for t in res["targets"]))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--split", choices=("train", "dev", "test"), default="dev")
    p.add_argument("--final", action="store_true", help="required for --split test (holdout objects)")
    p.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    p.add_argument("--data-dir", type=Path, default=Path("data"),
                   help="folder holding spacetrack/ (gp_history) and geo/ (<norad>.tle)")
    p.add_argument("--truth-dir", type=Path, default=GROUNDTRUTH)
    p.add_argument("--out", type=Path, help="JSON path (default results/<split>-<settings name>.json)")
    a = p.parse_args(argv)
    res = evaluate(a.split, a.settings, a.data_dir, a.truth_dir, final=a.final)
    out = a.out or RESULTS / f"{a.split}-{res['settings']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(table(res))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
