# Rejects blocks of element sets that jump away from an object's track and snap back to it, judged on
# the semi-major axis, the inclination vector and the mean longitude together. A real move does not return.

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from orbit_watch.elements import ElementSet
from orbit_watch.modes import SIDEREAL_REV_PER_DAY, mean_longitude
from orbit_watch.geo import wrap180

MAX_BLOCK_DAYS = 10.0
END_TRIES = 3
SIDE_SETS = 6
SIDE_DAYS = 5.0
SOLID_SIDE_SETS = 3
SOLID_SIDE_DAYS = 1.0
JUMP_Z = 6.0
EXCURSION_Z = 12.0
RETURN_SHARE = 0.4
LOOSE_RETURN_SHARE = 0.75
LON_RETURN_DEG = 0.05
MIN_EXCURSION = {"a": 0.2, "i": 0.01}
LONE_REACH_DAYS = 3.0
LONE_MIN_KM = 10.0
LONE_SHARE = 0.25
NOISE_FLOOR = {"a": 0.005, "ix": 0.0005, "iy": 0.0005, "lon": 0.0005}


@dataclass(frozen=True)
class Block:
    start: datetime
    end: datetime
    n_sets: int
    excursion: float
    gap: float
    channel: str


def _unwrapped_longitude(days: np.ndarray, lon: np.ndarray, rate: np.ndarray) -> np.ndarray:
    u = np.empty_like(lon)
    u[0] = lon[0]
    for i in range(1, len(lon)):
        guess = u[i - 1] + rate[i - 1] * (days[i] - days[i - 1])
        u[i] = guess + wrap180(lon[i] - guess)
    return u


def channels(records: Sequence[ElementSet]) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    t0 = records[0].epoch
    days = np.array([(r.epoch - t0).total_seconds() / 86400.0 for r in records])
    inc = np.array([r.inclination for r in records])
    node = np.radians([r.raan for r in records])
    rate = np.array([360.0 * (r.mean_motion - SIDEREAL_REV_PER_DAY) for r in records])
    lon = np.array([mean_longitude(r) for r in records])
    return days, {
        "a": np.array([r.semi_major_axis_km for r in records]),
        "ix": inc * np.cos(node),
        "iy": inc * np.sin(node),
        "lon": _unwrapped_longitude(days, lon, rate),
    }


def noise(days: np.ndarray, y: np.ndarray, floor: float) -> float:
    if len(y) < 3:
        return floor
    dt = np.diff(days)
    slope = np.diff(y) / np.where(dt > 0, dt, np.nan)
    d2 = np.diff(slope) * dt[1:]
    d2 = d2[np.isfinite(d2)]
    return max(float(1.4826 * np.median(np.abs(d2)) / np.sqrt(2.0)) if len(d2) else floor, floor)


def _sides(days: np.ndarray, jumps: np.ndarray, s: int, e: int) -> tuple[np.ndarray, np.ndarray, bool] | None:
    left: list[int] = []
    for i in range(s - 1, max(s - 1 - SIDE_SETS, -1), -1):
        if days[s] - days[i] > SIDE_DAYS or (left and jumps[i]):
            break
        left.append(i)
    right: list[int] = []
    for i in range(e + 1, min(e + 1 + SIDE_SETS, len(days))):
        if days[i] - days[e] > SIDE_DAYS or (right and jumps[i - 1]):
            break
        right.append(i)
    if not left or not right:
        return None
    solid = all(len(x) >= SOLID_SIDE_SETS and abs(days[x[-1]] - days[x[0]]) >= SOLID_SIDE_DAYS for x in (left, right))
    return np.array(left[::-1]), np.array(right), solid


def block_scores(days: np.ndarray, ys: dict[str, np.ndarray], jumps: np.ndarray, s: int, e: int
                 ) -> tuple[dict[str, float], dict[str, float], float, bool] | None:
    sides = _sides(days, jumps, s, e)
    if sides is None:
        return None
    left, right, solid = sides
    block = np.arange(s, e + 1)
    both = np.concatenate([left, right])
    mid = 0.5 * (days[s] + days[e])
    design = np.column_stack([days[both] - mid, np.isin(both, left), np.isin(both, right)]).astype(float)
    off, gap = {}, {}
    for k, y in ys.items():
        slope, c_left, c_right = np.linalg.lstsq(design, y[both], rcond=None)[0]
        off[k] = float(np.median(y[block] - slope * (days[block] - mid))) - 0.5 * (c_left + c_right)
        gap[k] = float(c_left - c_right)
    exc = {"a": abs(off["a"]), "i": float(np.hypot(off["ix"], off["iy"]))}
    ret = {"a": abs(gap["a"]), "i": float(np.hypot(gap["ix"], gap["iy"]))}
    return exc, ret, abs(gap["lon"]), solid


def is_snapback(exc: dict[str, float], ret: dict[str, float], lon_gap: float, solid: bool,
                sigma: dict[str, float]) -> bool:
    share = {c: ret[c] / max(exc[c], MIN_EXCURSION[c]) for c in exc}
    judged = exc if solid else ("i",)
    evidence = any(exc[c] >= max(EXCURSION_Z * sigma[c], MIN_EXCURSION[c]) and share[c] <= RETURN_SHARE for c in judged)
    return evidence and max(share.values()) <= LOOSE_RETURN_SHARE and lon_gap <= LON_RETURN_DEG


def snapback_blocks(records: Sequence[ElementSet]) -> list[tuple[int, int, Block]]:
    if len(records) < 3:
        return []
    days, ys = channels(records)
    sig = {k: noise(days, y, NOISE_FLOOR[k]) for k, y in ys.items()}
    sigma = {"a": sig["a"], "i": float(np.hypot(sig["ix"], sig["iy"]))}
    step = {"a": np.abs(np.diff(ys["a"])), "i": np.hypot(np.diff(ys["ix"]), np.diff(ys["iy"]))}
    jump = np.max([step[c] / max(sigma[c], MIN_EXCURSION[c] / JUMP_Z) for c in step], axis=0)
    jumps = jump >= JUMP_Z
    cand = np.flatnonzero(jumps)
    out: list[tuple[int, int, Block]] = []
    after = -1
    for ci, g1 in enumerate(cand):
        s = int(g1) + 1
        if s <= after:
            continue
        for g2 in cand[ci + 1:ci + 1 + END_TRIES]:
            e = int(g2)
            if days[e] - days[s] > MAX_BLOCK_DAYS:
                break
            sc = block_scores(days, ys, jumps, s, e)
            if sc is None or not is_snapback(*sc, sigma):
                continue
            exc, ret, _, _ = sc
            worst = max(exc, key=lambda c: exc[c] / max(sigma[c], MIN_EXCURSION[c] / EXCURSION_Z))
            out.append((s, e, Block(records[s].epoch, records[e].epoch, e - s + 1, round(exc[worst], 4),
                                    round(ret[worst], 4), worst)))
            after = e
            break
    return out


def lone_sets(records: Sequence[ElementSet]) -> list[int]:
    days = np.array([(r.epoch - records[0].epoch).total_seconds() / 86400.0 for r in records])
    a = np.array([r.semi_major_axis_km for r in records])
    lon = np.array([mean_longitude(r) for r in records])
    rate = np.array([360.0 * (r.mean_motion - SIDEREAL_REV_PER_DAY) for r in records])
    out = []
    for i in range(len(records)):
        near = [j for j in (i - 1, i + 1) if 0 <= j < len(records) and abs(days[j] - days[i]) <= LONE_REACH_DAYS]
        if len(near) == 1 and 0 < i < len(records) - 1:
            continue
        if len(near) == 1:
            if abs(a[i] - a[near[0]]) >= LONE_MIN_KM:
                out.append(i)
            continue
        if len(near) < 2:
            continue
        p, n = near
        frac = (days[i] - days[p]) / (days[n] - days[p])
        dev = abs(a[i] - (a[p] + frac * (a[n] - a[p])))
        carried = abs(float(wrap180(lon[n] - lon[p] - 0.5 * (rate[p] + rate[n]) * (days[n] - days[p]))))
        if dev >= LONE_MIN_KM and abs(a[n] - a[p]) <= LONE_SHARE * dev and carried <= LON_RETURN_DEG:
            out.append(i)
    return out


def drop_snapback_blocks(records: Sequence[ElementSet]) -> tuple[list[ElementSet], list[Block]]:
    found = snapback_blocks(records)
    drop = {i for s, e, _ in found for i in range(s, e + 1)}
    kept = [r for i, r in enumerate(records) if i not in drop]
    lone = set(lone_sets(kept)) if len(kept) >= 2 else set()
    blocks = [b for _, _, b in found] + [Block(kept[i].epoch, kept[i].epoch, 1, 0.0, 0.0, "lone") for i in sorted(lone)]
    return [r for i, r in enumerate(kept) if i not in lone], sorted(blocks, key=lambda b: b.start)
