"""Synthetic injection-recovery test of the ISS step detector.

    python -m orbit_watch.inject \\
        --spacetrack data/spacetrack/gp_history-25544-2021-01-01--2026-01-01.json \\
        --truth groundtruth/iss_manoeuvres.csv --out findings/injection

Everything this module adds to the data is a synthetic injection: a step of known size added
to the real ISS series in memory to see whether the detector finds it. Nothing injected is
written to ``groundtruth/`` or to any event list; real events come only from ``groundtruth/``.

What it measures, all on Space-Track gp_history for the ISS:

1. Recall against injected step size, at the frozen setting and at a few looser ones.
2. Detections per year on quiet stretches with nothing injected, for the same settings.
3. Recall at the frozen setting with the series thinned to about one TLE a day and about one
   every two days.

Where the step goes. ``detect.score_gaps`` reads one array, ``series.semi_major_axis_km`` (the
mean semi-major axis ``to_series`` derives from each TLE's mean motion), and nothing else. A
synthetic injection at gap ``i`` adds the step to that array for every epoch after gap ``i``.
That is exactly what the detector consumes, so the test measures the detector and not the
element parsing.

What that leaves out. A real burn reaches the TLEs through orbit determination: the first one or
two TLEs after a burn are often fitted across it and sit between the two levels, and scatter can
stay high for a few TLEs. A synthetic injection is a clean, instantaneous step, so its recall is an
upper bound for a real burn of the same size. The detector's medians ignore up to ``k/2 - 1 = 1``
such transitional TLE per side at ``k = 4``, so the gap should be small, but it is not measured
here. The thinned series keep the ISS's per-TLE scatter; an object tracked less often usually has
noisier TLEs too, so the thinned recall is also optimistic.

Quiet stretches. A gap is quiet when no ground-truth event window and no detection at the frozen
setting (on the full series) lies within ``margin`` days of it; ``margin`` is the scoring window
``max_span_days``: 3 days at the native cadence, wider on thinned series so a quiet gap's scoring
window never reaches a real burn. Only gaps the detector scores are used. Injections in one
realisation are at least ``SPACING_DAYS`` apart (wider on thinned series), so no scoring window
holds two injected steps.

A trial is recovered when a detection with the injected step's sign overlaps the injected gap,
widened by ``calibrate.TOLERANCE_DAYS`` (the same rule ``calibrate.match`` uses for real events).

False alarms. The frozen detections define the quiet stretches, so the frozen setting has no
detections there by construction. Two rates are reported: detections per year where only
ground-truth events are excluded (an upper bound on false alarms, because unannounced burns,
Roscosmos ones in particular, count), and detections per year in the fully quiet stretches, which
is zero for the frozen setting and shows what each looser setting adds. Those extra detections
may still include small real burns, so they too are an upper bound. ``chance_recovery`` is the
share of quiet gaps that one of those detections would "recover" with nothing injected: the floor
under the small-step recall at a loose setting.

The looser settings are a measurement, not a tuning: none of them is chosen here.
"""

from __future__ import annotations

import argparse
import csv
import json
from dataclasses import dataclass, replace
from pathlib import Path

import numpy as np

from orbit_watch.calibrate import TOLERANCE_DAYS, _iso, _overlaps, load_events
from orbit_watch.detect import Detection, pick, score_gaps
from orbit_watch.elements import parse_omm_json
from orbit_watch.series import ElementSeries, to_series

ISS = 25544
# Frozen setting: calibrate.run chooses k=4, |z|>=12, |step|>=200 m, NMS 1 day on the 2021-2022
# archive TLEs (rerun with the current groundtruth/ gives the same). It is not stored in code, so
# it is restated here.
K = 4
FROZEN = (12.0, 200.0)
NMS_DAYS = 1.0
LOOSER = tuple((z, s) for z in (6.0, 8.0) for s in (0.0, 50.0, 100.0))
SIZES_M = (25, 50, 100, 150, 200, 300, 500, 1000, 2000)
QUIET_DAYS = 3.0
SPACING_DAYS = 10.0
TRIALS_PER_CELL = 300  # per size and sign; 600 per size with both signs pooled
SEED = 20261114
# Thinning factor in days; None is the native series. Scoring guards scale with it (see _guards).
CADENCES = {"native": None, "about 1 per day": 1.0, "about 1 per 2 days": 2.0}
_DAY_US = 86_400e6


@dataclass(frozen=True)
class Window:
    """A time interval, shaped like calibrate.Event for calibrate._overlaps."""

    lo: np.datetime64
    hi: np.datetime64


def load_series(path: Path) -> ElementSeries:
    return to_series(parse_omm_json(path.read_text(encoding="utf-8")))[ISS]


def inject(series: ElementSeries, gaps, steps_m) -> ElementSeries:
    """A copy of ``series`` with each synthetic injection step added after its gap."""
    a_m = series.semi_major_axis_km * 1000.0
    for g, s in zip(gaps, steps_m):
        a_m[g + 1:] += s
    return replace(series, semi_major_axis_km=a_m / 1000.0)


def thin(series: ElementSeries, every_days: float, phase_days: float = 0.0) -> ElementSeries:
    """Keep the epoch nearest each point of a grid ``every_days`` apart, starting at ``phase_days``."""
    t = (series.epochs - series.epochs[0]).astype("int64") / _DAY_US
    grid = np.arange(phase_days, t[-1], every_days)
    j = np.clip(np.searchsorted(t, grid), 1, len(t) - 1)
    keep = np.unique(np.where(np.abs(t[j - 1] - grid) <= np.abs(t[j] - grid), j - 1, j))
    return replace(series, **{f: getattr(series, f)[keep] for f in (
        "epochs", "semi_major_axis_km", "inclination", "eccentricity", "raan", "mean_motion", "bstar")})


def _guards(every_days: float | None) -> dict:
    """score_gaps outage guards. Native keeps detect.py's defaults; a thinned series scales them.

    shortcut: 3.5x and 2x the thinning step are chosen so k=4 epochs on a jittered grid still
    fit; a per-object cadence model would be better if this is used beyond the ISS.
    """
    if every_days is None:
        return {"max_span_days": 3.0, "max_gap_days": 2.0}
    return {"max_span_days": 3.5 * every_days, "max_gap_days": 2.0 * every_days}


def quiet_gaps(series: ElementSeries, windows: list[Window], margin_days: float) -> np.ndarray:
    """Per gap: True when no window lies within ``margin_days`` of it."""
    m = np.timedelta64(int(margin_days * _DAY_US), "us")
    start, end = series.epochs[:-1], series.epochs[1:]
    if not windows:
        return np.ones(len(start), bool)
    lo = np.array([w.lo for w in windows])
    hi = np.array([w.hi for w in windows])
    clash = (lo[None, :] <= end[:, None] + m) & (hi[None, :] >= start[:, None] - m)
    return ~clash.any(axis=1)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (float("nan"), float("nan"))
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def recovered(dets: list[Detection], gap: Window, step_m: float) -> bool:
    return any(np.sign(d.step_m) == np.sign(step_m) and _overlaps(gap, d.start, d.end, TOLERANCE_DAYS)
               for d in dets)


def _spread(candidates: np.ndarray, centre: np.ndarray, spacing: float, rng) -> list[int]:
    """Random candidate gaps, greedily kept when at least ``spacing`` days from every kept one."""
    kept: list[int] = []
    for g in rng.permutation(candidates):
        if all(abs(centre[g] - centre[h]) >= spacing for h in kept):
            kept.append(int(g))
    return sorted(kept)


def recall_trials(full: ElementSeries, avoid: list[Window], every_days, settings, rng) -> dict:
    """Synthetic injection trials. Returns per-setting counts and what the series looked like.

    A thinned series is re-thinned with a random grid phase in every realisation, so its trials
    are spread over many different thinned series rather than repeating one series' few quiet gaps.
    """
    guards = _guards(every_days)
    margin = max(QUIET_DAYS, guards["max_span_days"])
    spacing = max(SPACING_DAYS, 2 * guards["max_span_days"] + guards["max_gap_days"])
    cells = [(s, sign) for s in SIZES_M for sign in (1, -1)]
    queue = [cells[i] for i in rng.permutation(np.repeat(np.arange(len(cells)), TRIALS_PER_CELL))]
    counts = {st: {c: [0, 0] for c in cells} for st in settings}  # [recovered, trials]
    seen = {"epochs": [], "scored_gaps": [], "quiet_scored_gaps": [], "sigma": []}
    sites: set = set()
    while queue:
        series = full if every_days is None else thin(full, every_days, rng.uniform(0, every_days))
        base = score_gaps(series, k=K, **guards)
        candidates = np.flatnonzero(base.valid & quiet_gaps(series, avoid, margin))
        t = (series.epochs - series.epochs[0]).astype("int64") / _DAY_US
        gaps = _spread(candidates, 0.5 * (t[:-1] + t[1:]), spacing, rng)
        if not gaps:
            raise ValueError("no quiet scored gaps to inject into")
        assign, queue = list(zip(gaps, queue)), queue[len(gaps):]
        sc = score_gaps(inject(series, [g for g, _ in assign], [s * sg for _, (s, sg) in assign]), k=K, **guards)
        for st in settings:
            dets = pick(sc, st[0], st[1], NMS_DAYS)
            for g, (s, sg) in assign:
                hit = recovered(dets, Window(series.epochs[g], series.epochs[g + 1]), s * sg)
                counts[st][(s, sg)][0] += hit
                counts[st][(s, sg)][1] += 1
        sites.update(series.epochs[g] for g, _ in assign)
        for key, v in (("epochs", len(series)), ("scored_gaps", base.valid.sum()),
                       ("quiet_scored_gaps", len(candidates)),
                       ("sigma", np.nanmedian(np.where(base.valid, base.sigma_m, np.nan)))):
            seen[key].append(float(v))
    return {
        "counts": counts,
        "realisations": len(seen["epochs"]),
        "distinct_injection_gaps": len(sites),
        "epochs_mean": round(float(np.mean(seen["epochs"])), 1),
        "scored_gaps_mean": round(float(np.mean(seen["scored_gaps"])), 1),
        "quiet_scored_gaps_mean": round(float(np.mean(seen["quiet_scored_gaps"])), 1),
        "quiet_margin_days": margin,
        "spacing_days": spacing,
        "guards": guards,
        "noise_sigma_m_median": round(float(np.median(seen["sigma"])), 2),
    }


def false_alarms(series: ElementSeries, events: list[Window], frozen: list[Window], settings) -> dict:
    """Detections per year on quiet gaps of the native series, nothing injected."""
    sc = score_gaps(series, k=K)
    dur = (series.epochs[1:] - series.epochs[:-1]).astype("int64") / _DAY_US / 365.25
    out = {}
    for name, avoid in (("truth_quiet", events), ("fully_quiet", events + frozen)):
        mask = sc.valid & quiet_gaps(series, avoid, QUIET_DAYS)
        years = float(dur[mask].sum())
        rows = {}
        tol = np.timedelta64(int(TOLERANCE_DAYS * _DAY_US), "us")
        for st in settings:
            dets = pick(sc, st[0], st[1], NMS_DAYS)
            gaps = np.searchsorted(sc.start, [d.start for d in dets])
            n = int(mask[gaps].sum()) if len(gaps) else 0
            rows[_label(st)] = {"detections": n, "per_year": round(n / years, 2)}
            if name == "fully_quiet":
                # Chance recovery: the share of injection candidates (quiet scored gaps) that a
                # detection already present without any injection would "recover", averaged over
                # both signs. It is the floor under the small-step recall at each setting.
                ds = np.array([d.start for d in dets], dtype="datetime64[us]")
                de = np.array([d.end for d in dets], dtype="datetime64[us]")
                sg = np.sign([d.step_m for d in dets])
                gs, ge = sc.start[mask][:, None], sc.end[mask][:, None]
                near = (ds[None, :] <= ge + tol) & (de[None, :] + tol >= gs)
                hit = [(near & (sg[None, :] == s)).any(axis=1).mean() for s in (1, -1)]
                rows[_label(st)]["chance_recovery"] = round(float(np.mean(hit)), 4) if len(dets) else 0.0
        out[name] = {"exposure_years": round(years, 3), "by_setting": rows}
    return out


def _label(st) -> str:
    tag = " (frozen)" if tuple(st) == FROZEN else ""
    return f"|z|>={st[0]:g}, |step|>={st[1]:g} m{tag}"


def _rows(cadence: str, st, counts) -> list[dict]:
    rows = []
    for s in SIZES_M:
        for sign_name, signs in (("+", (1,)), ("-", (-1,)), ("both", (1, -1))):
            k = sum(counts[(s, sg)][0] for sg in signs)
            n = sum(counts[(s, sg)][1] for sg in signs)
            lo, hi = wilson(k, n)
            rows.append({"cadence": cadence, "setting": _label(st), "z_min": st[0], "step_min_m": st[1],
                         "injected_step_m": s, "sign": sign_name, "trials": n, "recovered": k,
                         "recall": round(k / n, 4) if n else None,
                         "wilson95_lo": round(lo, 4), "wilson95_hi": round(hi, 4)})
    return rows


def run(spacetrack: Path, truth: Path, out: Path) -> dict:
    series = load_series(spacetrack)
    events = [Window(e.lo, e.hi) for e in load_events(truth)]
    frozen_dets = pick(score_gaps(series, k=K), *FROZEN, NMS_DAYS)
    frozen = [Window(d.start, d.end) for d in frozen_dets]
    settings = [FROZEN, *LOOSER]

    rows, cadence_info = [], {}
    for ci, (name, every) in enumerate(CADENCES.items()):
        sts = settings if every is None else [FROZEN]
        res = recall_trials(series, events + frozen, every, sts, np.random.default_rng([SEED, ci]))
        for st in sts:
            rows += _rows(name, st, res["counts"][st])
        cadence_info[name] = {k: v for k, v in res.items() if k != "counts"}

    out.mkdir(parents=True, exist_ok=True)
    with open(out / "synthetic_injection_recall.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    recall: dict[str, dict] = {}
    for r in rows:
        if r["sign"] == "both":
            recall.setdefault(f"{r['cadence']} / {r['setting']}", {})[str(r["injected_step_m"])] = {
                "recall": r["recall"], "wilson95": [r["wilson95_lo"], r["wilson95_hi"]], "trials": r["trials"]}
    element_sets = len(json.loads(spacetrack.read_text(encoding="utf-8")))
    report = {
        "what": "Synthetic injection-recovery test of the ISS step detector. Every step counted "
                "under recall was injected in memory; none is a real event.",
        "input": {"file": spacetrack.name, "element_sets": element_sets, "distinct_epochs": len(series),
                  "first_epoch": _iso(series.epochs[0]), "last_epoch": _iso(series.epochs[-1])},
        "frozen_setting": {"k": K, "z_min": FROZEN[0], "step_min_m": FROZEN[1], "nms_days": NMS_DAYS},
        "looser_settings": [_label(st) for st in LOOSER],
        "frozen_detections_on_full_series": len(frozen_dets),
        "groundtruth_events": len(events),
        "injected_step_sizes_m": SIZES_M,
        "trials_per_size_and_sign": TRIALS_PER_CELL,
        "seed": SEED,
        "recovery_tolerance_days": TOLERANCE_DAYS,
        "cadences": cadence_info,
        "false_alarms": false_alarms(series, events, frozen, settings),
        "recall_both_signs": recall,
        "limits": [
            "A synthetic injection is a clean step; a real burn's transitional TLEs are not modelled, "
            "so recall is an upper bound for a real burn of the same size.",
            "Thinned series keep the ISS's per-TLE scatter, so thinned recall is optimistic for "
            "objects that are tracked less often and fitted from fewer observations.",
            "False-alarm rates are upper bounds: unannounced real burns count as detections.",
            "Wilson intervals treat trials as independent. Trials of different sizes can share a "
            "gap (distinct_injection_gaps per cadence), so intervals are somewhat optimistic where "
            "that count is small next to the trial count.",
        ],
    }
    (out / "synthetic_injection_report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    plot(rows, out / "synthetic_injection_recall.png")
    return report


# Categorical slots 1-8 of the dataviz reference palette, in fixed order.
_COLOURS = ("#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948")


def plot(rows: list[dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    both = [r for r in rows if r["sign"] == "both"]
    fig, axes = plt.subplots(1, 2, figsize=(15, 6), sharey=True)
    panels = (
        (axes[0], "native", "setting", "Native cadence (~5.6 TLEs/day), by setting"),
        (axes[1], None, "cadence", "Frozen setting, by cadence"),
    )
    for ax, cadence, key, title in panels:
        sel = [r for r in both if (r["cadence"] == cadence if cadence else r["setting"].endswith("(frozen)"))]
        for i, name in enumerate(dict.fromkeys(r[key] for r in sel)):
            rs = [r for r in sel if r[key] == name]
            x = [r["injected_step_m"] for r in rs]
            y = [r["recall"] for r in rs]
            lo = [r["recall"] - r["wilson95_lo"] for r in rs]
            hi = [r["wilson95_hi"] - r["recall"] for r in rs]
            ax.errorbar(x, y, yerr=[lo, hi], color=_COLOURS[i], lw=2, marker="o", ms=5, capsize=2, label=name)
        ax.set_xscale("log")
        ax.set_xticks(SIZES_M, [str(s) for s in SIZES_M])
        ax.minorticks_off()
        ax.set_xlabel("synthetic injection step in semi-major axis (m, both signs pooled)")
        ax.set_title(title, fontsize=10)
        ax.grid(alpha=0.25)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(fontsize=8, frameon=False, loc="lower right")
    axes[0].set_ylabel("recall (Wilson 95% interval)")
    axes[0].set_ylim(-0.02, 1.02)
    fig.suptitle("Synthetic injection-recovery: ISS step detector recall against injected step size "
                 "(Space-Track gp_history 2021-2025)", fontsize=11)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--spacetrack", type=Path, required=True)
    p.add_argument("--truth", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args()
    r = run(args.spacetrack, args.truth, args.out)
    print(json.dumps({k: r[k] for k in ("cadences", "false_alarms", "recall_both_signs")}, indent=2))


if __name__ == "__main__":
    main()
