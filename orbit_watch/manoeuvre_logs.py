"""Build ground-truth manoeuvre lists from published logs (IDS, QZSS and the Fengyun set).

    python -m orbit_watch.manoeuvre_logs --ids-dir data/sources/ids \\
        --qzss-dir data/sources/qzss --fengyun-dir data/sources/fengyun --out groundtruth

Every output row comes from one source row (or, for IDS, one row holding several burns) and
carries the source file name, the file's revision date and its URL. The raw files are not
committed; fetch them from the URLs in ``SOURCES`` and rerun this to reproduce the CSVs.

IDS (``*man.txt``, format in ``man.readme`` in the same directory): one fixed-width row per
manoeuvre with start and end to the minute and, for each burn, its median time and Delta-v per
axis. The along-track axis is DV(2) for every parameter type (005: T, R, L with R along-track;
006: radial, along, cross; 007: Q, S, W with S along-track). Burn Delta-v is summed per row.
The time scale is not stated in the readme; it is read as UTC (at TLE cadence a few tens of
seconds do not matter). The last row of a file is first published before the burn and later
restated with executed values (seen in every archive revision checked), so rows starting on or
after the file's revision date are dropped as predictions. Rows repeated verbatim are kept once.

QZSS (``ohi-qzs*.txt``, Cabinet Office "Operational History Information"): CSV sections; only
the ``#+SATELLITE/MANEUVER`` section is read. The GEO files (QZS-3, QZS-6) have an ``NS/EW``
column; the inclined (IGSO) files (QZS-1, QZS-1R, QZS-2, QZS-4) have none, so their ``ns_ew`` is
empty and ``kind`` is ``unspecified``. Times are UTC to the second. The Delta-v is the planned value (the source's own footnote) and
the frame of DVX/DVY/DVZ is not documented; EW burns load DVX, NS burns DVY. An ``NS-1`` row and
the ``NS-2`` row after it share an ``event_group``, because they are one pair of burns an hour
apart that no TLE cadence separates.

Fengyun (``manFY*.txt.fy`` in the dpshorten/TLE_observation_benchmark_dataset repository, the
data set of Shorten et al., "Wide-scale Monitoring of Satellite Lifetimes: Pitfalls and a
Benchmark Dataset"): one line per manoeuvre, ``TYPE COSPAR "start CST" "end CST"``, with no
Delta-v. The repository does not say where the lines come from, and the time zone is ambiguous:
the lines say ``CST`` (China Standard Time is UTC+8), while the repository's README calls its
processed timestamps UTC and its YAML files keep the same clock times. Neither reading is
assumed: ``start_utc`` is the start read as UTC+8 and ``end_utc`` the end read as UTC, a window
that holds the manoeuvre under either reading. The clock times are kept verbatim in
``source_start`` and ``source_end``. ``delta_a_est_m`` is empty.

``delta_a_est_m`` is an estimate, not a source value: the Gauss relation for a circular orbit,
2 * Delta-v_along / n, with n from the satellite's nominal semi-major axis in ``SOURCES``. For
QZSS it assumes DVX is the along-track component, which the source does not confirm.
"""

# shortcut: nominal semi-major axes are medians of each object's Space-Track TLEs over its log
# span (2021-2025 only for the objects added with splits.json; one constant per satellite); SWOT
# changed orbit by ~35 km in 2023, a 2% error in its early estimates, and the IGSO orbits are
# eccentric (e ~ 0.075). Use the TLE nearest each burn if estimates are ever compared tightly.

from __future__ import annotations

import argparse
import csv
import math
import shlex
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

MU_KM3_S2 = 398600.4418
IDS_URL = "ftp://ftp.ids-doris.org/pub/ids/satellites/"
QZSS_URL = "https://qzss.go.jp/en/technical/qzssinfo/khp0mf0000000wuf-att/"
FENGYUN_COMMIT = "4cf0b15600658a486eff9e6a967ebd520e2354d1"  # last commit touching manFY*.txt.fy
FENGYUN_URL = ("https://github.com/dpshorten/TLE_observation_benchmark_dataset/blob/"
               f"{FENGYUN_COMMIT}/raw_data/manoeuvres/")


@dataclass(frozen=True)
class Source:
    file: str
    satellite: str
    norad_id: int
    revision: date  # IDS: file date in the listing; QZSS: date on the index page; Fengyun: commit
    nominal_a_km: float  # median Space-Track TLE semi-major axis over the log span (0: no Delta-v)
    cospar_id: str = ""  # Fengyun only: the international designator the source lines carry

    @property
    def url(self) -> str:
        if self.file.startswith("ohi-"):
            return QZSS_URL + self.file
        if self.file.startswith("manFY"):
            return FENGYUN_URL + self.file
        return IDS_URL + self.file


IDS_SOURCES = (
    Source("cs2man.txt", "CryoSat-2", 36508, date(2026, 11, 6), 7094.4),
    Source("ja3man.txt", "Jason-3", 41240, date(2026, 11, 14), 7714.4),
    Source("swoman.txt", "SWOT", 54754, date(2026, 11, 14), 7268.7),
    Source("sp5man.txt", "SPOT-5", 27421, date(2015, 12, 10), 7200.5),
    # Added with groundtruth/splits.json; nominal a is the median over 2021-2025 TLEs.
    Source("s3aman.txt", "Sentinel-3A", 41335, date(2026, 11, 10), 7177.9),
    Source("s3bman.txt", "Sentinel-3B", 43437, date(2026, 11, 12), 7177.9),
    Source("s6aman.txt", "Sentinel-6A", 46984, date(2026, 8, 26), 7714.4),
    Source("s6bman.txt", "Sentinel-6B", 66514, date(2026, 8, 26), 7694.6),
    Source("srlman.txt", "SARAL", 39086, date(2026, 7, 4), 7159.6),
    Source("h2cman.txt", "HY-2C", 46469, date(2026, 8, 4), 7328.6),
    Source("h2dman.txt", "HY-2D", 48621, date(2026, 9, 30), 7328.6),
)
QZSS_SOURCES = (
    Source("ohi-qzs3.txt", "QZS-3", 42917, date(2026, 11, 4), 42165.9),
    Source("ohi-qzs6.txt", "QZS-6", 62876, date(2026, 11, 4), 42165.9),
    # IGSO, added with groundtruth/splits.json; nominal a is the median over the log span within
    # 2021-2025 (QZS-1 up to 2022-02-28, its last logged burn).
    Source("ohi-qzs1.txt", "QZS-1", 37158, date(2026, 11, 4), 42164.8),
    Source("ohi-qzs1r.txt", "QZS-1R", 49336, date(2026, 11, 4), 42165.1),
    Source("ohi-qzs2.txt", "QZS-2", 42738, date(2026, 11, 4), 42165.7),
    Source("ohi-qzs4.txt", "QZS-4", 42965, date(2026, 11, 4), 42165.0),
)
FENGYUN_SOURCES = (  # only the satellites with lines in 2021-2025
    Source("manFY2F.txt.fy", "Fengyun-2F", 38049, date(2022, 11, 22), 0.0, "2012-002A"),
    Source("manFY2H.txt.fy", "Fengyun-2H", 43491, date(2022, 11, 22), 0.0, "2018-050A"),
    Source("manFY4A.txt.fy", "Fengyun-4A", 41882, date(2022, 11, 22), 0.0, "2016-077A"),
)

IDS_FIELDS = ["event_id", "satellite", "norad_id", "start_utc", "end_utc", "n_burns",
              "burn_times_utc", "dv_radial_m_s", "dv_along_m_s", "dv_cross_m_s", "kind",
              "delta_a_est_m", "source_file", "source_revision", "source_url"]
QZSS_FIELDS = ["event_id", "event_group", "satellite", "norad_id", "start_utc", "end_utc",
               "duration", "ns_ew", "dvx_m_s", "dvy_m_s", "dvz_m_s", "kind", "delta_a_est_m",
               "source_file", "source_revision", "source_url"]
FENGYUN_FIELDS = ["event_id", "satellite", "norad_id", "cospar_id", "start_utc", "end_utc",
                  "source_start", "source_end", "source_time_zone", "source_type", "kind",
                  "delta_a_est_m", "source_file", "source_revision", "source_url"]
QZSS_GEO_HEADER = "#DATE TIME START(UTC),END(UTC),DURATION,NS/EW,DVX(m/s),DVY(m/s),DVZ(m/s)"
QZSS_IGSO_HEADER = "#DATE TIME START(UTC),END(UTC),DURATION,DVX(m/s),DVY(m/s),DVZ(m/s)"
FENGYUN_KINDS = {"GEO-EW-STATION-KEEPING": "EW", "GEO-NS-STATION-KEEPING": "NS",
                 "GEO-ATTITUDE-CONTROL": "attitude"}
CHINA_STANDARD_TIME = timedelta(hours=8)


def delta_a_m(dv_along_m_s: float, a_km: float) -> float:
    """Gauss estimate of the semi-major-axis change (m) from an along-track Delta-v (m/s)."""
    n = math.sqrt(MU_KM3_S2 / a_km**3)  # rad/s
    return 2.0 * dv_along_m_s / n


def _doy(year: str, doy: str, hh: str, mm: str, ss: str = "0") -> datetime:
    sec = float(ss)
    return datetime(int(year), 1, 1) + timedelta(days=int(doy) - 1, hours=int(hh), minutes=int(mm),
                                                  seconds=sec)


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds") + "Z" if t.microsecond == 0 else \
        t.isoformat(timespec="milliseconds") + "Z"


@dataclass(frozen=True)
class IdsRow:
    satellite_code: str
    start: datetime
    end: datetime
    burn_times: tuple[datetime, ...]
    dv_radial: float
    dv_along: float
    dv_cross: float


def parse_ids_line(line: str) -> IdsRow:
    """One IDS manoeuvre row. Header columns are fixed width (readme), burn fields whitespace-split."""
    if len(line) < 46 or not line[44].isdigit():
        raise ValueError(f"not an IDS manoeuvre row: {line[:60]!r}")
    start = _doy(line[6:10], line[11:14], line[15:17], line[18:20])
    end = _doy(line[21:25], line[26:29], line[30:32], line[33:35])
    ptype, n = line[40:43], int(line[44])
    if ptype not in ("005", "006", "007"):
        raise ValueError(f"unknown parameter type {ptype!r}")
    fields = line[45:].split()
    if len(fields) != 15 * n:
        raise ValueError(f"expected {15 * n} burn fields for {n} burns, got {len(fields)}")
    times, radial, along, cross = [], 0.0, 0.0, 0.0
    for b in range(n):
        f = fields[15 * b:15 * b + 15]
        times.append(_doy(*f[0:5]))
        dv = [float(x) for x in f[6:9]]
        along += dv[1]
        if ptype == "005":  # T (cross-track), R (along-track), L (radial)
            cross, radial = cross + dv[0], radial + dv[2]
        else:  # 006: radial, along, cross; 007: Q (radial), S (along), W (cross)
            radial, cross = radial + dv[0], cross + dv[2]
    return IdsRow(line[0:5], start, end, tuple(times), radial, along, cross)


def parse_ids(text: str, src: Source) -> tuple[list[dict], dict]:
    """Rows of one IDS file as output dicts, plus counts of what was dropped and why."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    seen, rows, dropped = set(), [], {"duplicate_rows": 0, "on_or_after_revision": 0}
    revision = datetime.combine(src.revision, datetime.min.time())
    for ln in lines:
        key = ln.rstrip()
        if key in seen:
            dropped["duplicate_rows"] += 1
            continue
        seen.add(key)
        r = parse_ids_line(ln)
        if r.start >= revision:
            dropped["on_or_after_revision"] += 1
            continue
        rows.append({
            "satellite": src.satellite, "norad_id": src.norad_id,
            "start_utc": _iso(r.start), "end_utc": _iso(r.end), "n_burns": len(r.burn_times),
            "burn_times_utc": ";".join(_iso(t) for t in r.burn_times),
            "dv_radial_m_s": f"{r.dv_radial:.6g}", "dv_along_m_s": f"{r.dv_along:.6g}",
            "dv_cross_m_s": f"{r.dv_cross:.6g}",
            "kind": "along-track" if abs(r.dv_along) >= abs(r.dv_cross) else "cross-track",
            "delta_a_est_m": round(delta_a_m(r.dv_along, src.nominal_a_km), 1),
            "source_file": src.file, "source_revision": src.revision.isoformat(),
            "source_url": src.url,
        })
    dropped["kept"] = len(rows)
    dropped["source_rows"] = len(lines)
    return rows, dropped


def parse_qzss(text: str, src: Source) -> tuple[list[dict], dict]:
    """The MANEUVER section of one OHI file (GEO or IGSO layout) as output dicts, plus drop counts."""
    lines = text.splitlines()
    try:
        i = lines.index("#+SATELLITE/MANEUVER")
        j = lines.index("#-SATELLITE/MANEUVER", i)
    except ValueError as exc:
        raise ValueError(f"{src.file}: no MANEUVER section") from exc
    header = lines[i + 1].strip()
    if header not in (QZSS_GEO_HEADER, QZSS_IGSO_HEADER):
        raise ValueError(f"{src.file}: unknown maneuver layout: {header!r}")
    geo = header == QZSS_GEO_HEADER
    revision = datetime.combine(src.revision, datetime.min.time())
    rows, dropped = [], {"on_or_after_revision": 0}
    body = [ln for ln in lines[i + 2:j] if ln.strip()]
    for ln in body:
        f = ln.strip().split(",")
        if not geo:
            f.insert(3, "")  # IGSO rows have no NS/EW column
        if len(f) != 7:
            raise ValueError(f"{src.file}: expected {7 if geo else 6} fields: {ln!r}")
        start = datetime.strptime(f[0], "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(f[1], "%Y-%m-%d %H:%M:%S")
        if geo and f[3] not in ("EW", "NS", "NS-1", "NS-2"):
            raise ValueError(f"{src.file}: unknown NS/EW value {f[3]!r}")
        if start >= revision:
            dropped["on_or_after_revision"] += 1
            continue
        dvx, dvy, dvz = (float(x) for x in f[4:7])
        rows.append({
            "satellite": src.satellite, "norad_id": src.norad_id,
            "start_utc": _iso(start), "end_utc": _iso(end), "duration": f[2], "ns_ew": f[3],
            "dvx_m_s": f[4], "dvy_m_s": f[5], "dvz_m_s": f[6],
            "kind": ("EW" if f[3] == "EW" else "NS") if geo else "unspecified",
            "delta_a_est_m": round(delta_a_m(dvx, src.nominal_a_km), 1),
            "source_file": src.file, "source_revision": src.revision.isoformat(),
            "source_url": src.url,
        })
    group = None
    for k, r in enumerate(rows):
        r["event_id"] = f"{r['satellite']}-{k + 1:03d}"
        if r["ns_ew"] == "NS-2" and group and rows[k - 1]["ns_ew"] == "NS-1":
            r["event_group"] = group
        else:
            r["event_group"] = r["event_id"]
        group = r["event_group"]
    dropped["kept"] = len(rows)
    dropped["source_rows"] = len(body)
    return rows, dropped


def parse_fengyun(text: str, src: Source) -> tuple[list[dict], dict]:
    """One Fengyun file as output dicts in time order, plus drop counts."""
    seen, parsed, dropped = set(), [], {"duplicate_rows": 0}
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for ln in lines:
        if ln in seen:
            dropped["duplicate_rows"] += 1
            continue
        seen.add(ln)
        f = shlex.split(ln)
        if len(f) != 4 or f[0] not in FENGYUN_KINDS or f[1] != src.cospar_id:
            raise ValueError(f"{src.file}: unexpected line {ln!r}")
        clock = []
        for value in f[2:]:
            stamp, zone = value.split()
            if zone != "CST":
                raise ValueError(f"{src.file}: unexpected time zone {zone!r}")
            clock.append(datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%S"))
        parsed.append((clock[0], clock[1], f))
    rows = []
    for k, (start, end, f) in enumerate(sorted(parsed, key=lambda p: p[0])):
        rows.append({
            "event_id": f"{src.satellite}-{k + 1:03d}", "satellite": src.satellite,
            "norad_id": src.norad_id, "cospar_id": f[1],
            "start_utc": _iso(start - CHINA_STANDARD_TIME), "end_utc": _iso(end),
            "source_start": f[2], "source_end": f[3], "source_time_zone": "CST (undocumented)",
            "source_type": f[0], "kind": FENGYUN_KINDS[f[0]], "delta_a_est_m": "",
            "source_file": src.file, "source_revision": src.revision.isoformat(),
            "source_url": src.url,
        })
    dropped["kept"] = len(rows)
    dropped["source_rows"] = len(lines)
    return rows, dropped


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def build(ids_dir: Path, qzss_dir: Path, fengyun_dir: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    counts, ids_rows = {}, []
    for src in IDS_SOURCES:
        rows, c = parse_ids((ids_dir / src.file).read_text(encoding="ascii"), src)
        for k, r in enumerate(rows):
            r["event_id"] = f"{src.satellite}-{k + 1:03d}"
        ids_rows += rows
        counts[src.file] = c
    qz_rows = []
    for src in QZSS_SOURCES:
        rows, c = parse_qzss((qzss_dir / src.file).read_text(encoding="utf-8"), src)
        qz_rows += rows
        counts[src.file] = c
    fy_rows = []
    for src in FENGYUN_SOURCES:
        rows, c = parse_fengyun((fengyun_dir / src.file).read_text(encoding="ascii"), src)
        fy_rows += rows
        counts[src.file] = c
    _write(out / "ids_manoeuvres.csv", IDS_FIELDS, ids_rows)
    _write(out / "fengyun_manoeuvres.csv", FENGYUN_FIELDS, fy_rows)
    _write(out / "qzss_manoeuvres.csv", QZSS_FIELDS, qz_rows)
    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--ids-dir", type=Path, required=True)
    p.add_argument("--qzss-dir", type=Path, required=True)
    p.add_argument("--fengyun-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    for name, c in build(args.ids_dir, args.qzss_dir, args.fengyun_dir, args.out).items():
        print(name, c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
