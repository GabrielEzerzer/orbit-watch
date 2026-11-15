# Daily space-weather indices (Kp, Ap, F10.7) from CelesTrak's SW-All.csv, fetched at most once per UTC day.
# kp and ap: 8 three-hour columns from 00-03 UT; kp is NaN on prediction rows.
# F10.7 is in solar flux units, the adjusted value scaled to 1 AU. Dst is not loaded.

from __future__ import annotations

import csv
import io
import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from orbit_watch.celestrak import CACHE_DIR, Fetch, cached_fetch, http_get, utc_today

SW_URL = "https://celestrak.org/SpaceData/SW-All.csv"
_KP = [f"KP{i}" for i in range(1, 9)]
_AP = [f"AP{i}" for i in range(1, 9)]
_REQUIRED = ["DATE", *_KP, *_AP, "AP_AVG", "F10.7_OBS", "F10.7_ADJ", "F10.7_DATA_TYPE"]


@dataclass(frozen=True)
class SpaceWeather:
    day: np.ndarray
    kp: np.ndarray
    ap: np.ndarray
    ap_daily: np.ndarray
    f107_obs: np.ndarray
    f107_adj: np.ndarray
    data_type: np.ndarray


def _num(row: dict[str, str], key: str, low: float, high: float) -> float:
    text = (row.get(key) or "").strip()
    if not text:
        return math.nan
    value = float(text)
    if not low <= value <= high:
        raise ValueError(f"{key}={text!r} out of [{low}, {high}]")
    return value


def parse_sw_all(body: bytes) -> SpaceWeather:
    reader = csv.DictReader(io.StringIO(body.decode("utf-8")))
    missing = [k for k in _REQUIRED if k not in (reader.fieldnames or [])]
    if missing:
        raise ValueError(f"SW-All.csv lacks columns {missing}")
    days, kp, ap, ap_daily, f_obs, f_adj, kinds = [], [], [], [], [], [], []
    try:
        for row in reader:
            days.append(date.fromisoformat(row["DATE"]))
            kp.append([_num(row, k, 0, 90) / 10 for k in _KP])
            ap.append([_num(row, k, 0, 400) for k in _AP])
            ap_daily.append(_num(row, "AP_AVG", 0, 400))
            f_obs.append(_num(row, "F10.7_OBS", 0, 1000))
            f_adj.append(_num(row, "F10.7_ADJ", 0, 1000))
            kinds.append(row["F10.7_DATA_TYPE"].strip())
    except (ValueError, TypeError) as exc:
        raise ValueError(f"SW-All.csv line {reader.line_num}: {exc}") from exc
    if not days:
        raise ValueError("SW-All.csv has no rows")
    if any(b <= a for a, b in zip(days, days[1:])):
        raise ValueError("SW-All.csv dates are not strictly increasing")
    return SpaceWeather(
        day=np.array(days, dtype="datetime64[D]"),
        kp=np.array(kp, dtype=float),
        ap=np.array(ap, dtype=float),
        ap_daily=np.array(ap_daily, dtype=float),
        f107_obs=np.array(f_obs, dtype=float),
        f107_adj=np.array(f_adj, dtype=float),
        data_type=np.array(kinds, dtype=str),
    )


def load_space_weather(
    cache_dir: Path = CACHE_DIR,
    fetch: Fetch = http_get,
    today: Callable[[], date] = utc_today,
) -> SpaceWeather:
    return cached_fetch(SW_URL, "SW-All.csv", parse_sw_all, cache_dir=cache_dir, fetch=fetch, today=today)
