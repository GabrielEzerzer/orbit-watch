"""Score the frozen ISS detector on Space-Track gp_history, then retune it with every label.

    python -m orbit_watch.holdout \\
        --gp data/spacetrack/gp_history-25544-2021-01-01--2026-01-01.json \\
        --archive data/archive/25544.tle --truth groundtruth/iss_manoeuvres.csv --out findings

Three runs, all with calibrate.py's matching, coverage and precision rules (``match``,
``covered``, ``evaluate``) and its grid and choice rule (``choose_setting``):

1. Holdout. The setting calibrate.py froze on the archive's 2021-2022 (k=4, |z|>=12,
   |step|>=200 m, NMS 1 day) scores Space-Track 2024-2025 once. Nothing was tuned on 2024-2025.
2. Source check. The same setting on Space-Track 2021-2022 and 2023, next to the archive.
3. Leave-one-year-out cross-validation over 2021-2025 on Space-Track: choose the setting on four
   years, score the fifth. Then the setting chosen on all five years, which is in-sample.

As in calibrate.py, the detector runs once over the whole series of a source and each period is
scored through masks: an event belongs to the year of its ``date_utc``, a detection to the year of
the epoch before its step. The noise floor (half the median sigma) is therefore taken over the
whole 2021-2025 Space-Track series; it uses no labels.

Space-Track restates element sets. Records whose epochs lie within ``SAME_EPOCH_S`` of each other
are one element set, and the latest issued (highest ``GP_ID``) is kept. Exact repeats of an epoch
and reissues whose epoch differs by a few milliseconds both occur; the closest distinct epochs are
over 10 s apart.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from orbit_watch.calibrate import (
    DETECTION_HEADER,
    EVENT_HEADER,
    ISS,
    K_GRID,
    STEP_GRID_M,
    Z_GRID,
    _iso,
    choose_setting,
    covered,
    detection_rows,
    evaluate,
    event_rows,
    load_events,
    plot,
    write_csv,
)
from orbit_watch.detect import pick, score_gaps
from orbit_watch.elements import _omm_epoch, parse_omm_json, parse_tle
from orbit_watch.series import to_series

FROZEN = {"k": 4, "z_min": 12, "step_min_m": 200}  # calibrate.py's choice on the archive, 2021-2022
YEARS = (2021, 2022, 2023, 2024, 2025)
HOLDOUT_YEARS = (2024, 2025)
SAME_EPOCH_S = 1.0


def dedupe_gp_rows(rows: list[dict]) -> tuple[list[dict], dict]:
    """One row per element set: epochs within ``SAME_EPOCH_S`` collapse to the highest ``GP_ID``."""
    for r in rows:
        if not isinstance(r, dict) or not str(r.get("GP_ID", "")).isdigit() or not r.get("EPOCH"):
            raise ValueError(f"GP record without a numeric GP_ID and an EPOCH: {r!r:.200}")
    timed = sorted(((_omm_epoch(str(r["EPOCH"])), int(r["GP_ID"]), r) for r in rows),
                   key=lambda x: (x[0], x[1]))
    groups: list[list] = []
    for item in timed:
        if groups and (item[0] - groups[-1][-1][0]).total_seconds() < SAME_EPOCH_S:
            groups[-1].append(item)
        else:
            groups.append([item])
    kept = [max(g, key=lambda x: x[1])[2] for g in groups]
    exact = sum(len(g) - len({x[0] for x in g}) for g in groups)
    stats = {"rows": len(rows), "exact_epoch_repeats_dropped": exact,
             "near_epoch_reissues_dropped": len(rows) - len(kept) - exact, "element_sets_kept": len(kept)}
    return kept, stats


def load_gp_history(path: Path):
    text = path.read_text(encoding="utf-8")
    rows = json.loads(text, parse_float=str, parse_int=str)
    if not isinstance(rows, list):
        raise ValueError(f"{path}: gp_history JSON must be a list of records")
    kept, stats = dedupe_gp_rows(rows)
    series = to_series(parse_omm_json(json.dumps(kept)))[ISS]
    assert len(series) == len(kept)
    return series, stats


def year_of(t: np.datetime64) -> int:
    return int(t.astype("datetime64[Y]").astype(int)) + 1970


def period_masks(events, dets, years):
    """calibrate.py's period rule: event by ``date_utc``, detection by the epoch before the step."""
    ys = set(years)
    return [int(e.date_utc[:4]) in ys for e in events], [year_of(d.start) in ys for d in dets]


def loyo_folds(years):
    """Leave-one-year-out: (training years, held-out year) for each year."""
    return [(tuple(y for y in years if y != test), test) for test in years]


def per_year_counts(series, years):
    ys = [year_of(t) for t in series.epochs]
    return {str(y): ys.count(y) for y in years}


def _counts(res):
    """The numbers that pool across folds: true positives, scored detections, matched, covered."""
    return {"tp": res["true_positives"], "scored_detections": res["true_positives"] + res["false_positives"],
            "matched": res["matched"], "covered": res["covered"], "events": res["events"]}


def _pool(rows):
    tot = {k: sum(r[k] for r in rows) for k in rows[0]}
    tot["precision"] = round(tot["tp"] / tot["scored_detections"], 3) if tot["scored_detections"] else None
    tot["recall"] = round(tot["matched"] / tot["covered"], 3) if tot["covered"] else None
    return tot


class Scored:
    """One source: the series, its events and the per-k gap scores, scored by setting and period."""

    def __init__(self, series, all_events):
        self.series = series
        first, last = series.epochs[0], series.epochs[-1]
        self.events = [e for e in all_events if e.hi >= first and e.lo <= last]
        self.scores_by_k = {k: score_gaps(series, k=k) for k in K_GRID}

    def score(self, setting, years):
        sc = self.scores_by_k[setting["k"]]
        cover = covered(self.events, sc)
        dets = pick(sc, setting["z_min"], setting["step_min_m"])
        ev_in, det_in = period_masks(self.events, dets, years)
        res, m_main, m_unpl = evaluate(self.events, cover, dets, ev_in, det_in)
        return res, dict(cover=cover, dets=dets, ev_in=ev_in, det_in=det_in, m_main=m_main, m_unpl=m_unpl)

    def choose(self, years):
        best, _ = choose_setting(self.events, self.scores_by_k, period_masks(self.events, [], years)[0],
                                 lambda dets: period_masks(self.events, dets, years)[1])
        return {"k": best["k"], "z_min": best["z_min"], "step_min_m": best["step_min_m"], "f1": best["f1"]}

    def sigma_median(self, k, years=None):
        sc = self.scores_by_k[k]
        sel = np.ones(len(sc.sigma_m), bool) if years is None else np.isin([year_of(t) for t in sc.start], years)
        return round(float(np.nanmedian(sc.sigma_m[sel])), 1)

    def excluded(self, d):
        return [{"date_utc": e.date_utc, "type": e.type}
                for i, e in enumerate(self.events) if d["ev_in"][i] and not d["cover"][i]]

    def unmatched(self, d):
        matched = set(d["m_main"].values()) | set(d["m_unpl"].values())
        return [{"start_utc": _iso(x.start), "end_utc": _iso(x.end), "step_m": round(x.step_m, 1), "z": round(x.z, 2)}
                for i, x in enumerate(d["dets"]) if d["det_in"][i] and i not in matched]


def _label(years):
    return str(years[0]) if len(years) == 1 else f"{years[0]}-{years[-1]}"


def run(gp: Path, archive: Path, truth: Path, out: Path) -> dict:
    all_events = load_events(truth)
    st_series, dedupe = load_gp_history(gp)
    st = Scored(st_series, all_events)
    ar = Scored(to_series(parse_tle(archive.read_text(encoding="utf-8")))[ISS], all_events)
    k = FROZEN["k"]

    # 1. Holdout, scored once.
    hold, hd = st.score(FROZEN, HOLDOUT_YEARS)
    # The frozen setting over every year, for the committed tables and the source check.
    periods = ((2021, 2022), (2023,), (2024,), (2025,))
    labels = {y: _label(p) for p in periods for y in p}
    _, alld = st.score(FROZEN, YEARS)
    ev_label = [labels[int(e.date_utc[:4])] for e in st.events]
    det_label = [labels[year_of(x.start)] for x in alld["dets"]]
    hout = out / "holdout_2024_2025"
    hout.mkdir(parents=True, exist_ok=True)
    write_csv(hout / "detections.csv", DETECTION_HEADER,
              detection_rows(st.events, alld["dets"], det_label, alld["m_main"], alld["m_unpl"]))
    write_csv(hout / "events_scored.csv", EVENT_HEADER,
              event_rows(st.events, ev_label, alld["cover"], alld["dets"], alld["m_main"], alld["m_unpl"]))
    plot(st.series, st.events, alld["cover"], alld["m_main"], alld["m_unpl"], alld["dets"],
         hout / "iss_sma_2024_2025.png", years=HOLDOUT_YEARS)

    # 2. Source check: the frozen setting on both sources, 2021-2022 and 2023.
    def source(sc: Scored, name, path, extra):
        row = {"file": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), **extra,
               "element_sets_used": len(sc.series), "first_epoch": _iso(sc.series.epochs[0]),
               "last_epoch": _iso(sc.series.epochs[-1]), "per_year": per_year_counts(sc.series, YEARS),
               "noise_sigma_m_median_whole_series": sc.sigma_median(k),
               "noise_sigma_m_median_2021_2023": sc.sigma_median(k, [2021, 2022, 2023])}
        for p in periods[:2]:
            res, d = sc.score(FROZEN, p)
            row[_label(p)] = {**res, "excluded_for_coverage": sc.excluded(d), "unmatched_detections": sc.unmatched(d)}
        return name, row

    source_check = dict([
        source(ar, "archive", archive, {"duplicates": "none: no two records share an epoch"}),
        source(st, "spacetrack", gp, {"duplicates": dedupe}),
    ])

    holdout_report = {
        "source": {key: v for key, v in source_check["spacetrack"].items() if key not in ("2021-2022", "2023")},
        "truth_rows": len(all_events),
        "frozen_thresholds": {**FROZEN, "nms_days": 1.0,
                              "chosen_by": "calibrate.py: max F1 on archive 2021-2022, ties to the stricter setting"},
        "same_epoch_rule": f"epochs within {SAME_EPOCH_S} s are one element set; highest GP_ID kept",
        "holdout_2024_2025": hold,
        "holdout_by_year": {str(y): st.score(FROZEN, (y,))[0] for y in HOLDOUT_YEARS},
        "excluded_for_coverage": st.excluded(hd),
        "unmatched_detections": st.unmatched(hd),
        "source_check": source_check,
    }
    (hout / "report.json").write_text(json.dumps(holdout_report, indent=2) + "\n", encoding="utf-8")

    # 3. Leave-one-year-out CV, then the in-sample choice on all five years.
    folds, rows, ev_rows_all, det_rows_all = [], [], [], []
    for train, test in loyo_folds(YEARS):
        setting = st.choose(train)
        res, d = st.score(setting, (test,))
        folds.append({"held_out": test, "trained_on": list(train), "setting": setting, "scores": res,
                      "excluded_for_coverage": st.excluded(d), "unmatched_detections": st.unmatched(d)})
        rows.append(_counts(res))
        prefix = [test, setting["k"], setting["z_min"], setting["step_min_m"]]
        lab = [str(test)] * len(d["dets"])
        det_rows_all += [prefix + r for r, keep in zip(
            detection_rows(st.events, d["dets"], lab, d["m_main"], d["m_unpl"]), d["det_in"]) if keep]
        ev_rows_all += [prefix + r for r, keep in zip(
            event_rows(st.events, [str(test)] * len(st.events), d["cover"], d["dets"], d["m_main"], d["m_unpl"]),
            d["ev_in"]) if keep]
    insample_setting = st.choose(YEARS)
    insample, _ = st.score(insample_setting, YEARS)
    cv_report = {
        "source": {"file": str(gp), "sha256": source_check["spacetrack"]["sha256"],
                   "element_sets_used": len(st.series)},
        "grid": {"k": K_GRID, "z_min": Z_GRID, "step_min_m": STEP_GRID_M},
        "rule": "max F1 on the training years, ties to the stricter setting (calibrate.choose_setting)",
        "folds": folds,
        "pooled_cv": _pool(rows),
        "in_sample_all_five_years": {"setting": insample_setting, "scores": insample,
                                     "note": "chosen and scored on the same labels: in-sample, not a test"},
    }
    cout = out / "cv_2021_2025"
    cout.mkdir(parents=True, exist_ok=True)
    fold_cols = ["held_out_year", "k", "z_min", "step_min_m"]
    write_csv(cout / "detections.csv", fold_cols + DETECTION_HEADER, det_rows_all)
    write_csv(cout / "events_scored.csv", fold_cols + EVENT_HEADER, ev_rows_all)
    (cout / "report.json").write_text(json.dumps(cv_report, indent=2) + "\n", encoding="utf-8")
    plot_cv(folds, cv_report["pooled_cv"], insample, cout / "cv_scores.png")
    return {"holdout": holdout_report, "cv": cv_report}


def plot_cv(folds, pooled, insample, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [str(f["held_out"]) for f in folds] + ["pooled CV", "in-sample"]
    prec = [f["scores"]["precision"] or 0 for f in folds] + [pooled["precision"], insample["precision"]]
    rec = [f["scores"]["recall"] or 0 for f in folds] + [pooled["recall"], insample["recall"]]
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(x - 0.2, prec, 0.4, label="precision", color="tab:blue")
    ax.bar(x + 0.2, rec, 0.4, label="recall", color="tab:green")
    for i, f in enumerate(folds):
        s = f["setting"]
        ax.text(i, 1.02, f"k={s['k']} z>={s['z_min']}\n|step|>={s['step_min_m']} m", ha="center", fontsize=8)
    ax.set_xticks(x, names)
    ax.set_ylim(0, 1.15)
    ax.set_ylabel("score on the held-out year")
    ax.set_title("ISS, Space-Track 2021-2025: leave-one-year-out CV (setting chosen on the other four years)")
    ax.legend(loc="lower right")
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--gp", type=Path, required=True)
    p.add_argument("--archive", type=Path, required=True)
    p.add_argument("--truth", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    r = run(args.gp, args.archive, args.truth, args.out)
    h, c = r["holdout"], r["cv"]
    print(json.dumps({"holdout_2024_2025": h["holdout_2024_2025"], "pooled_cv": c["pooled_cv"],
                      "folds": [(f["held_out"], f["setting"]) for f in c["folds"]],
                      "in_sample": c["in_sample_all_five_years"]["setting"]}, indent=2))


if __name__ == "__main__":
    main()
