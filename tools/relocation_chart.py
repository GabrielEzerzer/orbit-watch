# Draw every relocation and graveyard move in the belt's state-change list as date against longitude.
# A move is a line from its start to its end, drawn the way its start's drift rate points when that
# rate covers more than half the belt over the move, otherwise the short way; split at the chart edge.

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "findings" / "state_changes" / "events.csv"
OUT = ROOT / "docs" / "belt_relocations.png"
DATA_END = date(2025, 12, 31)
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
MOVE, GRAVEYARD = "#2a78d6", "#eb6834"
DRIFT_DEG_PER_DAY_PER_KM = 1.5 * 360.9856 / 42164.17


def wrap180(x: float) -> float:
    return (x + 180.0) % 360.0 - 180.0


def arc(lon0: float, lon1: float, size_km: float, days: int) -> float:
    short = wrap180(lon1 - lon0)
    drift = -DRIFT_DEG_PER_DAY_PER_KM * size_km
    if drift * short < 0 and abs(drift) * days > 180.0:
        return short - 360.0 if short > 0 else short + 360.0
    return short


def pieces(d0: date, lon0: float, d1: date, delta: float) -> list[tuple[tuple[date, date], tuple[float, float]]]:
    end = lon0 + delta
    if -180.0 <= end <= 180.0:
        return [((d0, d1), (lon0, end))]
    edge = 180.0 if end > 180.0 else -180.0
    cut = d0 + (d1 - d0) * ((edge - lon0) / delta)
    return [((d0, cut), (lon0, edge)), ((cut, d1), (-edge, end - 2 * edge))]


def moves(rows: list[dict]) -> tuple[list, list, list]:
    by_object: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_object[r["norad_id"]].append(r)
    lines, arrivals, graveyards = [], [], []
    for events in by_object.values():
        events.sort(key=lambda r: r["date"])
        start = None
        for r in events:
            kind, day = r["event_type"], date.fromisoformat(r["date"])
            if kind == "relocation_start":
                if start is not None:
                    lines.append((start, None))
                start = r
            elif kind == "relocation_end":
                if start is not None:
                    lines.append((start, r))
                    start = None
                else:
                    arrivals.append((day, float(r["lon_after"])))
            elif kind == "graveyard":
                if start is not None:
                    lines.append((start, r))
                    start = None
                if r["lon_before"]:
                    graveyards.append((day, float(r["lon_before"])))
        if start is not None:
            lines.append((start, None))
    segments = []
    for start, end in lines:
        d0, lon0 = date.fromisoformat(start["date"]), float(start["lon_before"])
        if end is None:
            d1, lon1 = DATA_END, float(start["lon_after"])
        else:
            d1 = date.fromisoformat(end["date"])
            lon1 = float(end["lon_after"] if end["event_type"] == "relocation_end" else end["lon_before"])
        segments.extend(pieces(d0, lon0, d1, arc(lon0, lon1, float(start["size"]), (d1 - d0).days)))
    return segments, arrivals, graveyards


def draw(rows: list[dict], out: Path) -> tuple[int, int, int]:
    segments, arrivals, graveyards = moves(rows)
    starts = sum(r["event_type"] == "relocation_start" for r in rows)
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, ax = plt.subplots(figsize=(12, 6.4), dpi=110)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    for (d0, d1), (y0, y1) in segments:
        ax.plot([d0, d1], [y0, y1], color=MOVE, linewidth=1.4, alpha=0.75, solid_capstyle="round")
    if arrivals:
        ax.scatter(*zip(*arrivals), s=16, facecolors="none", edgecolors=MOVE, linewidths=1.0, zorder=3)
    if graveyards:
        ax.scatter(*zip(*graveyards), s=46, marker="X", color=GRAVEYARD, edgecolors=SURFACE, linewidths=0.8, zorder=4)
    ax.set_ylim(-180, 180)
    ax.set_yticks(range(-180, 181, 60))
    ax.set_yticklabels(["180°", "120°W", "60°W", "0°", "60°E", "120°E", "180°"])
    ax.set_xlim(date(2021, 1, 1), date(2026, 1, 1))
    ax.xaxis.set_major_locator(mdates.YearLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax.grid(color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelcolor=INK)
    ax.set_ylabel("Longitude", color=INK)
    handles = [
        plt.Line2D([], [], color=MOVE, linewidth=2, label=f"Relocation, start to end ({starts} starts)"),
        plt.Line2D([], [], color=MOVE, marker="o", markerfacecolor="none", linestyle="none", markersize=6,
                   label=f"Arrival with no start in the data ({len(arrivals)})"),
        plt.Line2D([], [], color=GRAVEYARD, marker="X", linestyle="none", markersize=8,
                   label=f"Graveyard move, where the climb starts ({len(graveyards)})"),
    ]
    ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.07), ncol=3, frameon=False,
              labelcolor=INK)
    fig.suptitle("Relocations and graveyard moves in the GEO belt, 2021-2025", x=0.07, ha="left",
                 color=INK, fontsize=13, fontweight="bold")
    ax.set_title("Each line runs from a move's start to its end, the way its drift points, or the short way "
                 "when the drift is too slow to tell.", loc="left", color=MUTED, fontsize=9.5)
    fig.subplots_adjust(left=0.07, right=0.98, top=0.88, bottom=0.14)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    return starts, len(arrivals), len(graveyards)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Draw every relocation and graveyard move in the belt's state-change "
                                            "list as date against longitude.")
    p.add_argument("--events", type=Path, default=EVENTS, help=f"default: {EVENTS.relative_to(ROOT).as_posix()}")
    p.add_argument("--out", type=Path, default=OUT, help=f"default: {OUT.relative_to(ROOT).as_posix()}")
    args = p.parse_args(argv)
    with open(args.events, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    starts, arrivals, graveyards = draw(rows, args.out)
    print(f"{args.out}: {starts} relocation starts, {arrivals} arrivals with no start, {graveyards} graveyard moves")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
