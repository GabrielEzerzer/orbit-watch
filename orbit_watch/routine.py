# Routine score of GEO-region objects from their dated state changes and held spans: each departure's surprise in
# bits against the object's own record of stays and moves (causal), a per-object irregularity rank, and a proximity
# flag on arrivals that end beside another owner's satellite.

from __future__ import annotations

import math
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

DEPARTURES = ("relocation_start", "graveyard", "keeping_stop")
ARRIVAL = "relocation_end"
YEAR_DAYS = 365.25
WINDOW_DAYS = 30.0
MIN_STAYS = 3
SD_FLOOR = 0.15
P_FLOOR = 1e-4
OFF_ROUTINE_BITS = 5.0
OVERRUN_P = 0.01
Z_OVERRUN = 2.3263478740408408
COMMISSIONING_DAYS = 180.0
MIN_HELD_YEARS = 2.0
PRIOR_STEP_DAYS = 30.0
PRIOR_MIN_HELD_YEARS = 0.25
NEAR_DEG = 0.1
AFTER_DAYS = 10
BEFORE_DAYS = (30, 40)
STAYED_DEG = 0.3
SMA_KM = 10.0


@dataclass(frozen=True)
class Prior:
    day: float
    rate: float
    alpha: float
    beta: float
    objects: int
    held_years: float
    departures: int


@dataclass(frozen=True)
class Scored:
    norad_id: int
    event_type: str
    day: float
    scored: bool
    model: str
    past_stays: int
    past_departures: int
    held_years: float
    stay_days: float | None
    p: float | None
    bits: float | None

    @property
    def off_routine(self) -> bool:
        return self.scored and self.bits is not None and self.bits >= OFF_ROUTINE_BITS


@dataclass(frozen=True)
class Overrun:
    norad_id: int
    day: float
    arrival_day: float
    p99_days: float
    past_stays: int


@dataclass(frozen=True)
class Standing:
    norad_id: int
    held_years: float
    years: float
    bits: float
    departures: int
    off_routine: int
    overruns: int

    @property
    def rated(self) -> bool:
        return self.held_years >= MIN_HELD_YEARS

    @property
    def bits_per_year(self) -> float:
        return self.bits / self.years if self.years > 0 else 0.0

    @property
    def departures_per_held_year(self) -> float:
        return self.departures / self.held_years if self.held_years > 0 else 0.0


@dataclass(frozen=True)
class Flag:
    norad_id: int
    day: int
    other: int
    sep_deg: float
    sma_gap_km: float
    neighbours: int


def held_years(holds: Sequence[tuple[float, float]], until: float, since: float = -math.inf) -> float:
    return sum(max(0.0, min(e, until) - max(s, since)) for s, e in holds) / YEAR_DAYS


def belt_priors(holds: dict[int, Sequence[tuple[float, float]]], departures: dict[int, Sequence[float]],
                end_day: float) -> list[Prior]:
    out = []
    norads = sorted(holds)
    for t in np.arange(PRIOR_STEP_DAYS, end_day + PRIOR_STEP_DAYS, PRIOR_STEP_DAYS):
        h = np.array([held_years(holds[n], float(t)) for n in norads])
        k = np.array([sum(d < t for d in departures.get(n, ())) for n in norads], dtype=float)
        if h.sum() <= 0:
            continue
        m = float(k.sum() / h.sum())
        sel = h >= PRIOR_MIN_HELD_YEARS
        v = float(np.var(k[sel] / h[sel]) - m * np.mean(1.0 / h[sel])) if sel.sum() > 1 else 0.0
        beta = m / v if v > 0 and m > 0 else math.inf
        out.append(Prior(float(t), m, m * beta if math.isfinite(beta) else math.inf, beta, int(sel.sum()),
                         float(h.sum()), int(k.sum())))
    return out


def prior_lookup(priors: Sequence[Prior]) -> Callable[[float], Prior | None]:
    days = np.array([p.day for p in priors])

    def at(day: float) -> Prior | None:
        i = int(np.searchsorted(days, day, side="right")) - 1
        return priors[i] if i >= 0 else None
    return at


def lognormal(stays: Sequence[float]) -> tuple[float, float]:
    x = np.log(np.asarray(stays, dtype=float))
    return float(x.mean()), max(float(x.std(ddof=1)), SD_FLOOR)


def stay_window_p(stays: Sequence[float], t: float) -> float:
    mu, sd = lognormal(stays)

    def cdf(v: float) -> float:
        return 0.0 if v <= 0 else 0.5 * (1.0 + math.erf((math.log(v) - mu) / (sd * math.sqrt(2.0))))
    return cdf(t + WINDOW_DAYS / 2) - cdf(t - WINDOW_DAYS / 2)


def rate_window_p(past: int, years: float, prior: Prior) -> float:
    w = WINDOW_DAYS / YEAR_DAYS
    if not math.isfinite(prior.beta):
        return 1.0 - math.exp(-prior.rate * w)
    return 1.0 - math.exp(-(prior.alpha + past) * math.log1p(w / (prior.beta + years)))


def bits(p: float) -> float:
    return -math.log2(max(p, P_FLOOR))


def score_object(norad: int, events: Sequence[tuple[float, str]], holds: Sequence[tuple[float, float]],
                 first_day: float, end_day: float, prior_at: Callable[[float], Prior | None]
                 ) -> tuple[list[Scored], list[Overrun]]:
    rows: list[Scored] = []
    overruns: list[Overrun] = []
    stays: list[float] = []
    arrival: float | None = None
    armed: tuple[float, int] | None = None
    past = 0
    start = first_day + COMMISSIONING_DAYS

    def close(until: float) -> None:
        if arrival is not None and armed is not None and until - arrival > armed[0] and arrival + armed[0] >= start:
            overruns.append(Overrun(norad, arrival + armed[0], arrival, armed[0], armed[1]))

    for day, kind in sorted(events):
        if kind == ARRIVAL:
            close(day)
            arrival = day
            armed = None
            if len(stays) >= MIN_STAYS:
                mu, sd = lognormal(stays)
                armed = (math.exp(mu + Z_OVERRUN * sd), len(stays))
            continue
        if kind not in DEPARTURES:
            continue
        close(day)
        stay = day - arrival if arrival is not None else None
        years = held_years(holds, day)
        prior = prior_at(day)
        scored = day >= start and prior is not None
        if stay is not None and len(stays) >= MIN_STAYS:
            model, p = "stays", stay_window_p(stays, max(stay, 1.0))
        elif prior is not None:
            model, p = "rate", rate_window_p(past, years, prior)
        else:
            model, p = "rate", None
        rows.append(Scored(norad, kind, day, scored, model, len(stays), past, round(years, 4), stay,
                           None if p is None else p, None if p is None else bits(p)))
        if stay is not None:
            stays.append(max(stay, 1.0))
        past += 1
        arrival, armed = None, None
    close(end_day)
    return rows, overruns


def standing(norad: int, rows: Sequence[Scored], overruns: Sequence[Overrun], holds: Sequence[tuple[float, float]],
             last_day: float, lo: float = -math.inf, hi: float = math.inf) -> Standing:
    end = min(last_day, hi)
    inside = [r for r in rows if r.scored and lo <= r.day < hi]
    first = min((s for s, e in holds if e > lo and s < end), default=None)
    years = max(0.0, end - max(first, lo)) / YEAR_DAYS if first is not None else 0.0
    return Standing(norad, held_years(holds, end, lo), years, float(sum(r.bits for r in inside)), len(inside),
                    sum(r.off_routine for r in inside), sum(lo <= o.day < hi for o in overruns))


def ranked(standings: Sequence[Standing]) -> list[Standing]:
    return sorted((s for s in standings if s.rated),
                  key=lambda s: (-s.bits_per_year, -s.departures_per_held_year, s.norad_id))


def circular_mean(block: np.ndarray) -> np.ndarray:
    z = np.exp(1j * np.radians(block))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        return np.degrees(np.angle(np.nanmean(z, axis=1)))


def separation(a: np.ndarray | float, b: np.ndarray | float) -> np.ndarray:
    return np.abs((np.asarray(a) - b + 180.0) % 360.0 - 180.0)


def proximity(k: int, day: int, lon: np.ndarray, sma: np.ndarray, norads: Sequence[int],
              owners: Sequence[str | None], launches: Sequence[str | None]) -> Flag | None:
    n_days = lon.shape[1]
    w = slice(max(day, 0), min(day + AFTER_DAYS, n_days))
    pre = slice(max(day - BEFORE_DAYS[1], 0), max(day - BEFORE_DAYS[0], 0))
    if w.start >= w.stop:
        return None
    now = circular_mean(lon[:, w])
    before = circular_mean(lon[:, pre]) if pre.start < pre.stop else np.full(len(norads), np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        a_now = np.nanmedian(sma[:, w], axis=1)
    sep = separation(now, now[k])
    hits = []
    for j in np.flatnonzero(sep <= NEAR_DEG):
        if j == k or not np.isfinite(before[j]) or separation(before[j], now[j]) > STAYED_DEG:
            continue
        gap = float(a_now[j] - a_now[k])
        if not abs(gap) <= SMA_KM:
            continue
        if owners[j] == owners[k] or (launches[j] is not None and launches[j] == launches[k]):
            continue
        hits.append((float(sep[j]), gap, int(j)))
    if not hits:
        return None
    s, gap, j = min(hits)
    return Flag(int(norads[k]), int(day), int(norads[j]), round(s, 4), round(gap, 2), len(hits))


def top_share(values: dict[int, float], picks: Sequence[int], share: float) -> tuple[int, int]:
    rateable = [n for n in picks if n in values]
    cut = float(np.quantile(list(values.values()), 1.0 - share))
    return sum(values[n] >= cut and values[n] > 0 for n in rateable), len(rateable)


def lower_half(values: dict[int, float], picks: Sequence[int]) -> tuple[int, int]:
    rateable = [n for n in picks if n in values]
    median = float(np.median(list(values.values())))
    return sum(values[n] <= median for n in rateable), len(rateable)


def overlap(first: Sequence[int], second: Sequence[int], top: int, wide: int) -> tuple[int, int]:
    a = list(first[:top])
    return len(set(a) & set(second[:wide])), len(a)


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) < 3:
        return None
    rx = _ranks(np.asarray(x, dtype=float))
    ry = _ranks(np.asarray(y, dtype=float))
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


def _ranks(x: np.ndarray) -> np.ndarray:
    order = np.argsort(x, kind="mergesort")
    r = np.empty(len(x))
    r[order] = np.arange(len(x), dtype=float)
    for v in np.unique(x):
        tie = x == v
        r[tie] = r[tie].mean()
    return r
