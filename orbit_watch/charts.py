# Chart of one object's cleaned element sets with its held spans and listed state changes: the longitude panel
# alone for the dataset evidence, or with drift rate, semi-major axis and inclination for the hand audit.

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path

import numpy as np

from orbit_watch.clean import drop_snapback_blocks
from orbit_watch.modes import GRID_END, GRID_START, N_DAYS, day_of, track
from orbit_watch.routine import END_OF_LIFE, SCORED

PANELS = {"lon": "mean longitude (deg E)", "rate": "drift rate (deg/day)", "sma": "semi-major axis - 42164 (km)",
          "inc": "inclination (deg)"}
INK, MUTED, HOLD = "#0b0b0b", "#52514e", "#1baf7a"
STYLES = {
    "departure": ("relocation start", {"color": "#eb6834", "lw": 2.6, "ls": "-"}),
    "end_of_life": ("graveyard move or keeping stop", {"color": "#6250d6", "lw": 2.6, "ls": (0, (6, 2, 1.5, 2))}),
    "arrival": ("relocation end", {"color": "#2a78d6", "lw": 1.8, "ls": (0, (4, 2))}),
    "other": ("end of N-S keeping or free burn", {"color": MUTED, "lw": 1.6, "ls": (0, (1, 1.5))}),
}
OFF_ROUTINE = "#e34948"
LABEL_GAP_DAYS = 40.0
LON_PAD_DEG = 0.25
WHOLE_BELT_DEG = 180.0
LEGEND_COLUMNS = 4
ZORDER = {"other": 1.0, "arrival": 1.1, "end_of_life": 1.2, "departure": 1.3}


def kind_of(event_type: str) -> str:
    if event_type in SCORED:
        return "departure"
    if event_type in END_OF_LIFE:
        return "end_of_life"
    return "arrival" if event_type == "relocation_end" else "other"


def wrap(lon) -> np.ndarray:
    return (np.asarray(lon, dtype=float) + 180.0) % 360.0 - 180.0


def lon_range(days: np.ndarray, lon: np.ndarray, events: Sequence[dict],
              holds: Sequence[tuple[float, float]]) -> tuple[float, float]:
    inside = np.zeros(len(days), dtype=bool)
    if holds:
        inside = (days >= min(s for s, _ in holds)) & (days < max(e for _, e in holds))
    values = list(lon[inside]) + [float(ev[k]) for ev in events for k in ("lon_before", "lon_after") if ev.get(k)]
    if not values:
        values = list(lon)
    lo, hi = float(np.min(values)), float(np.max(values))
    if hi - lo > WHOLE_BELT_DEG:
        centre = float(np.degrees(np.angle(np.exp(1j * np.radians(values)).mean())))
        shifted = centre + wrap(np.array(values) - centre)
        lo, hi = float(np.min(shifted)), float(np.max(shifted))
    if hi - lo > WHOLE_BELT_DEG:
        return -180.0, 180.0
    pad = max(LON_PAD_DEG, 0.08 * (hi - lo))
    return lo - pad, hi + pad


def recentre(lon: np.ndarray, lo: float, hi: float) -> np.ndarray:
    centre = (lo + hi) / 2
    return centre + wrap(lon - centre)


def tick_label(v: float, _pos=None) -> str:
    w = float(wrap(v))
    return f"{180.0 if w == -180.0 else w:g}"


def label_rows(days: Sequence[float]) -> list[int]:
    last: list[float] = []
    rows = []
    for d in days:
        row = next((k for k, x in enumerate(last) if d - x >= LABEL_GAP_DAYS), len(last))
        if row == len(last):
            last.append(d)
        last[row] = d
        rows.append(row)
    return rows


def chart(path: Path, title: str, records, events: Sequence[dict], holds: Sequence[tuple[float, float]],
          panels: Sequence[str] = tuple(PANELS), numbered: bool = False, size: tuple[float, float] = (12, 10),
          dpi: int = 80) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch
    from matplotlib.ticker import FuncFormatter

    kept, _ = drop_snapback_blocks(records)
    tk = track(kept)
    series = {"lon": tk.lon, "rate": tk.rate, "sma": tk.semi_major_axis_km - 42164.0, "inc": tk.inclination}
    events = sorted(events, key=lambda ev: ev["date"])
    xs = [day_of(date.fromisoformat(ev["date"])) for ev in events]
    fig, axes = plt.subplots(len(panels), 1, figsize=size, sharex=True, squeeze=False)
    axes = axes[:, 0]
    hidden = 0
    for ax, name in zip(axes, panels):
        y = series[name]
        if name == "lon":
            lo, hi = lon_range(tk.days, tk.lon, events, holds)
            if lo < -180.0 or hi > 180.0:
                y = recentre(y, lo, hi)
                ax.yaxis.set_major_formatter(FuncFormatter(tick_label))
            hidden = int(((y < lo) | (y > hi)).sum())
            ax.set_ylim(lo, hi)
        for s, e in holds:
            ax.axvspan(s, e, color=HOLD, alpha=0.14, lw=0, zorder=0)
        for x, ev in zip(xs, events):
            kind = kind_of(ev["event_type"])
            ax.axvline(x, zorder=ZORDER[kind], **STYLES[kind][1])
        ax.plot(tk.days, y, ".", color=INK, ms=2.2, zorder=2.0)
        ax.set_ylabel(PANELS[name], fontsize=9, color=MUTED)
        ax.tick_params(labelsize=8, colors=MUTED)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.grid(axis="y", color="#e4e3df", lw=0.6, zorder=0)
    top = axes[0]
    if numbered:
        for k, (x, row) in enumerate(zip(xs, label_rows(xs)), 1):
            off = events[k - 1].get("off_routine") == "1"
            top.text(x, 1.015 + 0.075 * row, str(k), transform=top.get_xaxis_transform(), ha="center", va="bottom",
                     fontsize=8, color="white" if off else INK, fontweight="bold" if off else "normal",
                     bbox={"boxstyle": "round,pad=0.15", "fc": OFF_ROUTINE if off else "white", "ec": "none"})
    if hidden:
        fig.text(0.99, 0.985, f"{hidden} element sets outside the longitude axis are not drawn", ha="right",
                 va="top", fontsize=8, color=MUTED)
    ticks = [day_of(date(y, 1, 1)) for y in range(GRID_START.year, GRID_END.year + 1)]
    axes[-1].set_xticks(ticks, [str(y) for y in range(GRID_START.year, GRID_END.year + 1)])
    axes[-1].set_xlim(0, N_DAYS)
    present = {kind_of(ev["event_type"]) for ev in events}
    handles = [Line2D([], [], ls="", marker=".", color=INK, ms=6, label="element set (cleaned)"),
               Patch(color=HOLD, alpha=0.3, lw=0, label="held")]
    handles += [Line2D([], [], label=label, **style) for kind, (label, style) in STYLES.items() if kind in present]
    if numbered and any(ev.get("off_routine") == "1" for ev in events):
        handles.append(Patch(color=OFF_ROUTINE, label="off-routine departure (number)"))
    ncol = min(len(handles), LEGEND_COLUMNS)
    fig.legend(handles=handles, loc="lower center", ncol=ncol, fontsize=8, frameon=False)
    fig.suptitle(title, x=0.01, ha="left", fontsize=11, color=INK)
    lines = -(-len(handles) // ncol)
    fig.tight_layout(rect=(0, (0.06 if len(panels) == 1 else 0.025) * lines, 1, 1))
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=dpi)
    plt.close(fig)
