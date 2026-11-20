# Draw where LUCH (OLYMP) and LUCH (OLYMP) 2 were parked, 2021-2025, one panel each, from the committed
# state-change list and proximity flags. A stop runs from an arrival to the next departure; a flagged stop
# is labelled with the other owner's satellite it arrived beside.

from __future__ import annotations

import argparse
import csv
from datetime import date
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from matplotlib.transforms import Bbox

ROOT = Path(__file__).resolve().parents[1]
EVENTS = ROOT / "findings" / "state_changes" / "events.csv"
FLAGS = ROOT / "findings" / "routine" / "flagged_arrivals.csv"
OUT = ROOT / "docs" / "luch_stops.png"
OBJECTS = ("40258", "55841")
CHART_START, CHART_END = date(2021, 1, 1), date(2026, 1, 1)
SURFACE, INK, MUTED, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
MOVE, GRAVEYARD, UNFLAGGED = "#2a78d6", "#eb6834", "#d6e4f7"
BAR = 9
DEPARTURES = ("relocation_start", "graveyard")


def stops(events: list[dict], flags: list[dict]) -> tuple[list[dict], list[tuple], list[tuple]]:
    flag_at = {(f["norad_id"], f["date"]): f for f in flags}
    found, moves, graveyards = [], [], []
    for norad in OBJECTS:
        rows = sorted((r for r in events if r["norad_id"] == norad), key=lambda r: r["date"])
        held, last = None, None
        for r in rows:
            kind, day = r["event_type"], date.fromisoformat(r["date"])
            if kind == "relocation_end":
                if last is not None:
                    moves.append((norad, last[0], last[1], day, float(r["lon_after"])))
                    last = None
                flag = flag_at.get((norad, r["date"]))
                held = {"norad_id": norad, "start": day, "lon": float(r["lon_after"]),
                        "neighbour": f"{flag['other_name']} ({flag['other_owner']})" if flag else None}
            elif kind in DEPARTURES:
                if held is None:
                    held = {"norad_id": norad, "start": CHART_START, "lon": float(r["lon_before"]),
                            "neighbour": None}
                held["end"] = day
                found.append(held)
                if kind == "graveyard":
                    graveyards.append((norad, day, held["lon"]))
                else:
                    last = (day, held["lon"])
                held = None
        if held is not None:
            held["end"] = CHART_END
            found.append(held)
    return found, moves, graveyards


def place_label(ax, placed: list[Bbox], text: str, x0: date, x1: date, y: float, renderer) -> None:
    tiers = (8, -8, 22, -22, 36, -36, 50, 64)
    to_px = ax.transData.transform
    bounds = ax.get_window_extent()
    for x, pad in ((x0, 0), (x1, 4)):
        for dy in tiers:
            t = ax.annotate(text, (mdates.date2num(x), y), xytext=(pad, dy), textcoords="offset points",
                            ha="left", va="bottom" if dy > 0 else "top", color=INK, fontsize=9.5)
            box = t.get_window_extent(renderer).padded(2)
            inside = (box.x0 >= bounds.x0 and box.x1 <= bounds.x1 and box.y0 >= bounds.y0
                      and box.y1 <= bounds.y1)
            if inside and not any(box.overlaps(b) for b in placed):
                placed.append(box)
                if abs(dy) > tiers[0]:
                    edge = box.y0 if dy > 0 else box.y1
                    px = to_px((mdates.date2num(x), y))
                    lx = px[0] + (pad + 6) * ax.figure.dpi / 72
                    ax.plot(*ax.transData.inverted().transform([(lx, px[1]), (lx, edge)]).T, color=MUTED,
                            linewidth=0.7, zorder=2)
                return
            t.remove()
    raise RuntimeError(f"no room to label {text!r}")


def draw(events: list[dict], flags: list[dict], out: Path) -> tuple[int, int]:
    found, moves, graveyards = stops(events, flags)
    names = {f["norad_id"]: f["name"] for f in flags}
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
    fig, axes = plt.subplots(len(OBJECTS), 1, figsize=(10, 8.2), dpi=100, sharex=True, sharey=True)
    fig.patch.set_facecolor(SURFACE)
    lons = [s["lon"] for s in found]
    for ax, norad in zip(axes, OBJECTS):
        ax.set_facecolor(SURFACE)
        for _, d0, y0, d1, y1 in (m for m in moves if m[0] == norad):
            ax.plot([d0, d1], [y0, y1], color=MOVE, linewidth=1.0, alpha=0.6, zorder=2)
        mine = [s for s in found if s["norad_id"] == norad]
        for s in mine:
            ax.plot([s["start"], s["end"]], [s["lon"]] * 2, color=MOVE, linewidth=BAR, solid_capstyle="butt",
                    zorder=3)
            if s["neighbour"] is None:
                ax.plot([s["start"], s["end"]], [s["lon"]] * 2, color=UNFLAGGED, linewidth=BAR - 3,
                        solid_capstyle="butt", zorder=3)
        for _, day, lon in (g for g in graveyards if g[0] == norad):
            ax.scatter([day], [lon], s=70, marker="X", color=GRAVEYARD, edgecolors=SURFACE, linewidths=0.8,
                       zorder=4)
        ax.set_title(f"{names.get(norad, norad)}, NORAD {norad}", loc="left", color=INK, fontsize=11,
                     fontweight="bold")
        ax.grid(color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(MUTED)
        ax.tick_params(colors=MUTED, labelcolor=INK)
        ax.set_ylabel("Longitude", color=INK)
    lo, hi = min(lons), max(lons)
    step = 20
    y0, y1 = int(step * (lo // step - 1)), int(step * (hi // step + 3))
    axes[0].set_ylim(y0, y1)
    ticks = range(y0, y1 + 1, step)
    axes[0].set_yticks(list(ticks))
    axes[0].set_yticklabels([f"{abs(t)}°{'E' if t > 0 else 'W' if t < 0 else ''}" for t in ticks])
    axes[0].set_xlim(CHART_START, CHART_END)
    axes[-1].xaxis.set_major_locator(mdates.YearLocator())
    axes[-1].xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    handles = [
        Patch(facecolor=MOVE, edgecolor=MOVE,
              label="Stop, flagged: arrived within 0.1° of another owner's satellite, named beside the bar"),
        Patch(facecolor=UNFLAGGED, edgecolor=MOVE, linewidth=1.5, label="Stop, not flagged"),
        plt.Line2D([], [], color=MOVE, linewidth=1.0, alpha=0.6, label="Move between stops"),
        plt.Line2D([], [], color=GRAVEYARD, marker="X", linestyle="none", markersize=9,
                   label="Move to the graveyard orbit"),
    ]
    fig.suptitle(f"Where {' and '.join(names.get(n, n) for n in OBJECTS)} parked, "
                 f"{CHART_START.year}-{CHART_END.year - 1}", x=0.08, ha="left", color=INK,
                 fontsize=13, fontweight="bold")
    fig.text(0.08, 0.915, "Each bar is one stop, from the day the satellite arrived to the day it left.",
             color=MUTED, fontsize=9.5)
    fig.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.08, 0.0), ncol=2, frameon=False,
               labelcolor=INK, fontsize=9.5)
    fig.subplots_adjust(left=0.08, right=0.98, top=0.86, bottom=0.13, hspace=0.22)
    renderer = fig.canvas.get_renderer()
    for ax, norad in zip(axes, OBJECTS):
        placed: list[Bbox] = []
        mine = [s for s in found if s["norad_id"] == norad]
        for s in mine:
            a, b = ax.transData.transform([(mdates.date2num(s["start"]), s["lon"]),
                                           (mdates.date2num(s["end"]), s["lon"])])
            half = BAR * fig.dpi / 144 + 1
            placed.append(Bbox([[a[0], a[1] - half], [b[0], b[1] + half]]))
        for _, d0, y0, d1, y1 in (m for m in moves if m[0] == norad):
            placed.append(Bbox(ax.transData.transform([(mdates.date2num(d0), min(y0, y1)),
                                                       (mdates.date2num(d1), max(y0, y1))])))
        for s in mine:
            if s["neighbour"]:
                place_label(ax, placed, s["neighbour"], s["start"], s["end"], s["lon"], renderer)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, facecolor=SURFACE)
    plt.close(fig)
    return len(found), sum(s["neighbour"] is not None for s in found)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Draw where LUCH (OLYMP) and LUCH (OLYMP) 2 were parked, 2021-2025, "
                                            "and which other owner's satellite each flagged stop was beside.")
    p.add_argument("--events", type=Path, default=EVENTS, help=f"default: {EVENTS.relative_to(ROOT).as_posix()}")
    p.add_argument("--flags", type=Path, default=FLAGS, help=f"default: {FLAGS.relative_to(ROOT).as_posix()}")
    p.add_argument("--out", type=Path, default=OUT, help=f"default: {OUT.relative_to(ROOT).as_posix()}")
    args = p.parse_args(argv)
    with open(args.events, encoding="utf-8", newline="") as f:
        events = list(csv.DictReader(f))
    with open(args.flags, encoding="utf-8", newline="") as f:
        flags = list(csv.DictReader(f))
    count, labelled = draw(events, flags, args.out)
    print(f"{args.out}: {count} stops, {labelled} labelled with a neighbour")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
