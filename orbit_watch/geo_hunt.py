"""First GEO manoeuvre hunt: semi-major-axis steps and longitude for a few objects.

    python -m orbit_watch.geo_hunt --tle-dir data/archive --norad 37951 38977 --out out

For each object it reads ``<tle-dir>/<norad>.tle``, computes the sub-satellite longitude at every
TLE epoch (``orbit_watch.geo``), runs the existing step detector (``orbit_watch.detect``) on
semi-major axis and writes

* ``steps.csv``: one row per detected step, with the longitude and the longitude drift rate
  (least-squares over the ``K`` epochs on each side) before and after it;
* ``<norad>.png``: longitude and semi-major axis against time, steps marked;
* ``summary.json``: per object, the epoch count, the scatter and the thresholds used.

The thresholds are NOT calibrated. There is no GEO ground truth, so they are set from each object's
own TLE scatter: ``|z| >= Z_MIN`` and ``|step| >= STEP_SIGMAS`` x the median per-gap scatter of
that object's semi-major axis. A flagged step is a lead to look at, not a confirmed burn.
"""

# shortcut: thresholds are per-object multiples of scatter, not calibrated against known GEO
# manoeuvres; calibrate once a GEO ground-truth list (operator notices) exists.

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

from orbit_watch.detect import _days, pick, score_gaps
from orbit_watch.elements import parse_tle
from orbit_watch.geo import drift_rate, longitudes
from orbit_watch.series import distinct_epochs, to_series

K = 4  # epochs each side of a gap; GEO TLEs come about twice a day
MAX_SPAN_DAYS = 4.0
MAX_GAP_DAYS = 3.0
NMS_DAYS = 2.0
Z_MIN = 8.0
STEP_SIGMAS = 10.0


def hunt(path: Path) -> dict:
    (recs,) = distinct_epochs(parse_tle(path.read_text(encoding="utf-8"))).values()
    (series,) = to_series(recs).values()  # the same records, so lon lines up with series
    lon = longitudes(recs)
    t = _days(series.epochs)
    scores = score_gaps(series, k=K, max_span_days=MAX_SPAN_DAYS, max_gap_days=MAX_GAP_DAYS)
    sigma = float(np.nanmedian(np.where(scores.valid, scores.sigma_m, np.nan)))
    step_min = STEP_SIGMAS * sigma
    steps = pick(scores, Z_MIN, step_min, nms_days=NMS_DAYS)
    index = {e: i for i, e in enumerate(series.epochs)}
    rows = []
    for d in steps:
        i = index[d.start]
        b, a = slice(max(i - K + 1, 0), i + 1), slice(i + 1, i + 1 + K)
        rows.append({
            "norad": series.norad_id,
            "start": str(d.start)[:16], "end": str(d.end)[:16],
            "step_m": round(d.step_m), "z": round(d.z, 1),
            "lon_before_deg": round(float(lon[i]), 3), "lon_after_deg": round(float(lon[i + 1]), 3),
            "drift_before_deg_per_day": round(drift_rate(t[b], lon[b]), 4),
            "drift_after_deg_per_day": round(drift_rate(t[a], lon[a]), 4),
        })
    names = sorted({r.name for r in recs if r.name})
    return {
        "series": series, "lon": lon, "rows": rows,
        "summary": {
            "norad": series.norad_id, "names": names, "epochs": len(series),
            "first": str(series.epochs[0])[:16], "last": str(series.epochs[-1])[:16],
            "gaps_scored": int(scores.valid.sum()), "median_sigma_m": round(sigma, 1),
            "z_min": Z_MIN, "step_min_m": round(step_min, 1), "steps": len(rows),
            "lon_min_deg": round(float(lon.min()), 3), "lon_max_deg": round(float(lon.max()), 3),
        },
    }


def plot(result: dict, path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    s, lon, rows = result["series"], result["lon"], result["rows"]
    summ = result["summary"]
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 9), sharex=True)
    ax1.plot(s.epochs, lon, ".", ms=2, color="#1f5fa8")
    ax1.set_ylabel("sub-satellite longitude (deg E)")
    ax2.plot(s.epochs, s.semi_major_axis_km, ".", ms=2, color="#333333")
    ax2.set_ylabel("mean semi-major axis (km)")
    for r in rows:
        t = np.datetime64(r["end"])
        colour = "#d95f02" if r["step_m"] > 0 else "#7570b3"
        for ax in (ax1, ax2):
            ax.axvline(t, color=colour, lw=0.6, alpha=0.6)
    title = f"NORAD {summ['norad']} ({', '.join(summ['names'])}): {summ['steps']} steps flagged"
    ax1.set_title(title + f"  (uncalibrated: |z| >= {Z_MIN:g}, |step| >= {summ['step_min_m']:g} m)")
    ax2.set_xlabel("TLE epoch (UTC); orange = step up in a, purple = step down")
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--tle-dir", type=Path, required=True)
    p.add_argument("--norad", type=int, nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    rows, summaries = [], []
    for norad in args.norad:
        result = hunt(args.tle_dir / f"{norad}.tle")
        plot(result, args.out / f"{norad}.png")
        rows += result["rows"]
        summaries.append(result["summary"])
        print(json.dumps(result["summary"]))
    fields = ["norad", "start", "end", "step_m", "z", "lon_before_deg", "lon_after_deg",
              "drift_before_deg_per_day", "drift_after_deg_per_day"]
    with open(args.out / "steps.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    (args.out / "summary.json").write_text(json.dumps(summaries, indent=2), encoding="utf-8")
    print(f"{len(rows)} steps written to {args.out / 'steps.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
