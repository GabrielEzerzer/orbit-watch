# The frozen evaluation of the step detector per regime, with the GEO east-west and ISS recall guardrails.
# Coverage, exposure, matching and counting live here so no detector or setting change can move them.

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from collections import namedtuple
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from orbit_watch import calibrate, holdout
from orbit_watch.detect import Detection, Setting, pick_setting, score_gaps
from orbit_watch.generalise import (LATE_DAYS, MAX_GAP_DAYS, MAX_SPAN_DAYS, TOLERANCE_DAYS, covered,
                                    load_log_events, load_series, log_coverage)
from orbit_watch.sources import data_dir as default_data_dir
from orbit_watch.truth import GROUNDTRUTH, HoldoutError, load_splits, require_allowed

HERE = Path(__file__).resolve().parent
SPLIT_PATH = HERE / "split.json"
DEFAULT_SETTINGS = HERE / "settings" / "frozen.json"
RESULTS = HERE / "results"
YEAR_DAYS = 365.25
Z95 = 1.959963984540054
GROUP_ORDER = ("GEO", "IGSO", "ISS", "GEO-Fengyun")
SETTING_KEY = {"GEO": "GEO", "IGSO": "IGSO", "ISS": "ISS", "GEO-Fengyun": "GEO"}
RECALL_TARGETS = {("GEO", "EW"): 0.9, ("ISS", "all"): 0.95}
INC_ONLY_SUBSETS = ("NS",)
REF_K = 4
REF_MAX_SPAN_DAYS = 3.0
REF_MAX_GAP_DAYS = 2.0
_DAY = np.timedelta64(86_400_000_000, "us")
_Gaps = namedtuple("_Gaps", "start end valid")


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, centre - half), min(1.0, centre + half)


def recall(matched: int, covered_n: int, events: int, matched_all: int | None = None) -> dict:
    matched_all = matched if matched_all is None else matched_all
    ci = wilson(matched, covered_n)
    return {"events": events, "covered": covered_n, "matched": matched, "matched_all": matched_all,
            "recall": round(matched / covered_n, 4) if covered_n else None,
            "recall_all_events": round(matched_all / events, 4) if events else None,
            "ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
            "ci95_width": round(ci[1] - ci[0], 4) if ci else None}


def fa_rate(false_alarms: int, object_years: float) -> float | None:
    return round(false_alarms / object_years, 4) if object_years > 0 else None


def subtract(span: tuple, zones: list[tuple]) -> list[tuple]:
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


def reference_scored(epochs: np.ndarray) -> np.ndarray:
    n, k = len(epochs), REF_K
    out = np.zeros(max(n - 1, 0), dtype=bool)
    if n < 2 * k:
        return out
    t = (epochs - epochs[0]).astype("int64") / 86_400e6
    i = np.arange(k - 1, n - k)
    out[i] = ((t[i + 1] - t[i] <= REF_MAX_GAP_DAYS)
              & (t[i] - t[i - k + 1] <= REF_MAX_SPAN_DAYS)
              & (t[i + k] - t[i + 1] <= REF_MAX_SPAN_DAYS))
    return out


def _us(t) -> np.ndarray:
    return np.asarray(t, dtype="datetime64[us]").astype("int64")


def match(events, dets: list[Detection], tol_days: float = TOLERANCE_DAYS,
          late_days: float | None = None) -> dict[int, int]:
    if not events or not dets:
        return {}
    tol = int(tol_days * 86_400e6)
    late = int((tol_days if late_days is None else late_days) * 86_400e6)
    elo, ehi = _us([e.lo for e in events]), _us([e.hi for e in events])
    esign = np.array([e.expected_sign for e in events])
    ec = elo + (ehi - elo) // 2
    choices = []
    for di, d in enumerate(dets):
        ps, pe = int(_us(d.peak_start)), int(_us(d.peak_end))
        ok = (elo <= pe + tol) & (ehi >= ps - late) & ((esign == 0) | (esign * d.step_m > 0))
        if ok.any():
            dist = np.abs(ec - (ps + (pe - ps) // 2))
            ei = min(np.flatnonzero(ok), key=lambda j: (dist[j], elo[j], j))
            choices.append((int(dist[ei]), ps, di, int(ei)))
    out: dict[int, int] = {}
    for _, _, di, ei in sorted(choices):
        out.setdefault(ei, di)
    return out


@dataclass
class Obj:
    norad: int
    name: str
    group: str
    source: str
    series: object
    events: list
    excluded: list
    coverage: tuple
    late_days: float | None
    _scores: dict = field(default_factory=dict)

    def scores(self, k: int, channel: str = "a"):
        if (k, channel) not in self._scores:
            self._scores[k, channel] = score_gaps(self.series, k=k, max_span_days=MAX_SPAN_DAYS,
                                                  max_gap_days=MAX_GAP_DAYS, channel=channel)
        return self._scores[k, channel]

    def reference(self) -> np.ndarray:
        if "ref" not in self._scores:
            self._scores["ref"] = reference_scored(self.series.epochs)
        return self._scores["ref"]

    def detections(self, s: Setting) -> list[Detection]:
        return pick_setting(self.scores(s.k), self.scores(s.k, "i") if s.inc_channel else None, s)


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
    if obj.group in ("GEO", "GEO-Fengyun"):
        return [e.kind] if e.kind in ("EW", "NS", "EW+NS") else []
    return []


def counts_as_hit(obj: Obj, e, d: Detection) -> bool:
    return "i" in d.channel.split("+") or not set(subset_of(obj, e)) & set(INC_ONLY_SUBSETS)


def _check_peaks(obj: Obj, dets: list[Detection]) -> None:
    ep = obj.series.epochs
    for d in dets:
        i = int(np.searchsorted(ep, d.peak_start))
        if not (i + 1 < len(ep) and ep[i] == d.peak_start and ep[i + 1] == d.peak_end):
            raise ValueError(f"{obj.name}: detection {d} does not name one gap of the series as its peak")


def score_object(obj: Obj, s: Setting, lo: np.datetime64, hi: np.datetime64) -> dict:
    in_p = lambda t: lo <= t < hi
    ev = [e for e in obj.events if in_p(_mid(e))]
    exc = [e for e in obj.excluded if in_p(_mid(e))]
    dets: list[Detection] = [d for d in obj.detections(s) if in_p(d.peak_start)]
    _check_peaks(obj, dets)
    ref = _Gaps(obj.series.epochs[:-1], obj.series.epochs[1:], obj.reference())
    cover = covered(ev, ref, TOLERANCE_DAYS, obj.late_days)
    m = match(ev, dets, TOLERANCE_DAYS, obj.late_days)
    rest = [i for i in range(len(dets)) if i not in set(m.values())]
    m_exc = match(exc, [dets[i] for i in rest], TOLERANCE_DAYS, obj.late_days)
    unmatched = [i for j, i in enumerate(rest) if j not in set(m_exc.values())]
    hit = {ei for ei, di in m.items() if counts_as_hit(obj, ev[ei], dets[di])}

    tol, late = _tol(TOLERANCE_DAYS), _tol(TOLERANCE_DAYS if obj.late_days is None else obj.late_days)
    span = (max(lo, obj.coverage[0]), min(hi, obj.coverage[1]))
    zones = [(e.lo - tol, e.hi + late) for e in obj.events + obj.excluded]
    scored = ref.valid | obj.scores(s.k).valid
    if span[0] < span[1]:
        no_burn = subtract(span, zones)
        unscored = subtract(span, list(zip(ref.start[scored], ref.end[scored])))
        stretches = subtract(span, zones + unscored)
    else:
        no_burn, stretches = [], []
    fa = [i for i in unmatched
          if any(a <= dets[i].peak_start and dets[i].peak_end <= b for a, b in stretches)]
    burn_zones = [(e.lo - tol, e.hi + late) for e in obj.events]
    dup = [i for i in unmatched if i not in fa
           and any(dets[i].peak_start <= zh and dets[i].peak_end >= zl for zl, zh in burn_zones)]

    def det_row(d: Detection) -> dict:
        return {"start_utc": calibrate._iso(d.peak_start), "end_utc": calibrate._iso(d.peak_end),
                "step_m": round(d.step_m, 1), "z": round(d.z, 2), "channel": d.channel}

    subsets: dict[str, dict] = {}
    for name in ["all"] + sorted({x for e in ev for x in subset_of(obj, e)}):
        idx = [i for i, e in enumerate(ev) if name == "all" or name in subset_of(obj, e)]
        cov = [i for i in idx if cover[i]]
        subsets[name] = {"events": len(idx), "covered": len(cov), "matched": sum(i in hit for i in cov),
                         "matched_all": sum(i in hit for i in idx)}
    return {
        "subsets": subsets,
        "detections": len(dets), "matched_detections": len(m),
        "dropped_attitude_or_unplanned": len(m_exc),
        "false_alarms": len(fa), "duplicates": len(dup), "wrong_channel": len(m) - len(hit),
        "object_years": years(stretches), "no_burn_years": years(no_burn),
        "_detail": {
            "missed": [{"event_id": getattr(e, "event_id", None) or f"{e.date_utc} {e.time_utc}".strip(),
                        "start_utc": calibrate._iso(e.lo), "kind": getattr(e, "kind", None) or e.category,
                        "delta_a_est_m": getattr(e, "delta_a_est_m", None)}
                       for i, e in enumerate(ev) if cover[i] and i not in hit],
            "wrong_channel_list": [{"event_id": e.event_id, "start_utc": calibrate._iso(e.lo),
                                    "detection": det_row(dets[m[i]])}
                                   for i, e in enumerate(ev) if i in m and i not in hit],
            "false_alarm_list": [det_row(dets[i]) for i in fa],
            "duplicate_list": [det_row(dets[i]) for i in dup],
        },
    }


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
        raise HoldoutError(f"--split {split} scores the holdout objects; it needs --final, and has "
                           "been scored once, at FROZEN (docs/results.md, 'Detector evaluation')")
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
                             "object_years": round(r["object_years"], 4),
                             "no_burn_years": round(r["no_burn_years"], 4)}
        if not final:
            per_obj[obj.name].update(detail)
        g = pooled.setdefault(obj.group, {"objects": [], "subsets": {}, "false_alarms": 0, "duplicates": 0,
                                          "wrong_channel": 0, "object_years": 0.0, "no_burn_years": 0.0})
        g["objects"].append(obj.name)
        for key in ("false_alarms", "duplicates", "wrong_channel", "object_years", "no_burn_years"):
            g[key] += r[key]
        for sub, c in r["subsets"].items():
            acc = g["subsets"].setdefault(sub, {"events": 0, "covered": 0, "matched": 0, "matched_all": 0})
            for k in acc:
                acc[k] += c[k]

    groups = {}
    for gname in GROUP_ORDER:
        if gname not in pooled:
            continue
        g = pooled[gname]
        groups[gname] = {
            "objects": g["objects"], "setting": settings[SETTING_KEY[gname]].__dict__,
            "subsets": {sub: recall(c["matched"], c["covered"], c["events"], c["matched_all"])
                        for sub, c in g["subsets"].items()},
            "false_alarms": g["false_alarms"], "duplicates": g["duplicates"], "wrong_channel": g["wrong_channel"],
            "object_years": round(g["object_years"], 3), "no_burn_years": round(g["no_burn_years"], 3),
            "scored_fraction": round(g["object_years"] / g["no_burn_years"], 3) if g["no_burn_years"] else None,
            "fa_per_object_year": fa_rate(g["false_alarms"], g["object_years"]),
        }
    return {"split": split, "period": period, "settings": name, **_commit(),
            "tolerance_days": {"before": TOLERANCE_DAYS, "after": LATE_DAYS, "after_iss": TOLERANCE_DAYS},
            "coverage_reference": {"k": REF_K, "max_span_days": REF_MAX_SPAN_DAYS, "max_gap_days": REF_MAX_GAP_DAYS},
            "targets": targets(groups), "groups": groups, "objects": per_obj}


def targets(groups: dict) -> list[dict]:
    out = []
    for (g, sub), want in RECALL_TARGETS.items():
        r = groups.get(g, {}).get("subsets", {}).get(sub)
        val = r["recall"] if r else None
        out.append({"check": f"{g} recall {sub}", "target": f">= {want}", "value": val,
                    "ci95": r["ci95"] if r else None,
                    "status": "no events" if val is None else ("PASS" if val >= want else "MISS")})
    return out


def table(res: dict) -> str:
    def f(x, nd=3):
        return "-" if x is None else f"{x:.{nd}f}"
    head = (f"{'group':<12} {'subset':<7} {'events':>6} {'cov':>4} {'hit':>4} {'recall':>6} "
            f"{'95% CI':>13} {'width':>5} {'hit/ev':>6} {'FA':>4} {'obj-yr':>7} {'FA/yr':>6} "
            f"{'scored':>6} {'dup':>4} {'wch':>4}")
    lines = [f"split={res['split']} ({res['period']['from']} to {res['period']['to']}, "
             f"{res['period']['objects']} objects)  settings={res['settings']}  "
             f"commit={res['commit'][:7]}{' (dirty)' if res['dirty'] else ''}", head, "-" * len(head)]
    for gname, g in res["groups"].items():
        for j, (sub, r) in enumerate(g["subsets"].items()):
            ci = f"[{r['ci95'][0]:.2f}, {r['ci95'][1]:.2f}]" if r["ci95"] else "-"
            fa = (f"{g['false_alarms']:>4} {g['object_years']:>7.2f} {f(g['fa_per_object_year'], 2):>6} "
                  f"{f(g['scored_fraction'], 2):>6} {g['duplicates']:>4} {g['wrong_channel']:>4}" if j == 0 else "")
            lines.append(f"{gname if j == 0 else '':<12} {sub:<7} {r['events']:>6} {r['covered']:>4} "
                         f"{r['matched']:>4} {f(r['recall']):>6} {ci:>13} {f(r['ci95_width'], 2):>5} "
                         f"{f(r['recall_all_events']):>6} {fa}".rstrip())
    lines.append("cov: covered by the k=4 reference. hit/ev: every matched event / events. scored: exposure / "
                 "no-burn log-covered time. dup: unmatched detections in a burn's match zone. wch: NS events "
                 "matched by a semi-major-axis detection only (misses).")
    lines.append("ISS false alarms are against lower-bound lists and not checked; GEO-Fengyun is exploratory.")
    lines.append("targets: " + " | ".join(
        f"{t['check']} {f(t['value'])} ({t['target']}) {t['status']}" for t in res["targets"]))
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="The frozen evaluation of the step detector, per regime, with the GEO east-west and ISS recall guardrails.")
    p.add_argument("--split", choices=("train", "dev", "test"), default="dev")
    p.add_argument("--final", action="store_true", help="required for --split test (holdout objects)")
    p.add_argument("--settings", type=Path, default=DEFAULT_SETTINGS)
    p.add_argument("--data-dir", type=Path,
                   help="folder holding spacetrack/ (gp_history) and geo/ (<norad>.tle); default $ORBIT_WATCH_DATA")
    p.add_argument("--truth-dir", type=Path, default=GROUNDTRUTH)
    p.add_argument("--out", type=Path, help="JSON path (default results/<split>-<settings name>.json)")
    a = p.parse_args(argv)
    res = evaluate(a.split, a.settings, a.data_dir or default_data_dir(), a.truth_dir, final=a.final)
    out = a.out or RESULTS / f"{a.split}-{res['settings']}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(table(res))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
