"""Build ground-truth manoeuvre lists from published operator logs (IDS and QZSS).

    python -m orbit_watch.manoeuvre_logs --ids-dir data/sources/ids \\
        --qzss-dir data/sources/qzss --out groundtruth

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
the ``#+SATELLITE/MANEUVER`` section is read, and only the GEO layout with an ``NS/EW`` column.
Times are UTC to the second. The Delta-v is the planned value (the source's own footnote) and
the frame of DVX/DVY/DVZ is not documented; EW burns load DVX, NS burns DVY. An ``NS-1`` row and
the ``NS-2`` row after it share an ``event_group``, because they are one pair of burns an hour
apart that no TLE cadence separates.

``delta_a_est_m`` is an estimate, not a source value: the Gauss relation for a circular orbit,
2 * Delta-v_along / n, with n from the satellite's nominal semi-major axis in ``SOURCES``. For
QZSS it assumes DVX is the along-track component, which the source does not confirm.
"""

# shortcut: nominal semi-major axes are medians of each object's Space-Track TLEs over its log
# span (one constant per satellite); SWOT changed orbit by ~35 km in 2023, a 2% error in its
# early estimates. Use the TLE nearest each burn if estimates are ever compared tightly.

from __future__ import annotations

import argparse
import csv
import math
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

MU_KM3_S2 = 398600.4418
IDS_URL = "ftp://ftp.ids-doris.org/pub/ids/satellites/"
QZSS_URL = "https://qzss.go.jp/en/technical/qzssinfo/khp0mf0000000wuf-att/"


@dataclass(frozen=True)
class Source:
    file: str
    satellite: str
    norad_id: int
    revision: date  # IDS: file date in the directory listing; QZSS: date on the index page
    nominal_a_km: float  # median Space-Track TLE semi-major axis over the log span

    @property
    def url(self) -> str:
        return (QZSS_URL if self.file.startswith("ohi-") else IDS_URL) + self.file


IDS_SOURCES = (
    Source("cs2man.txt", "CryoSat-2", 36508, date(2026, 11, 6), 7094.4),
    Source("ja3man.txt", "Jason-3", 41240, date(2026, 11, 14), 7714.4),
    Source("swoman.txt", "SWOT", 54754, date(2026, 11, 14), 7268.7),
    Source("sp5man.txt", "SPOT-5", 27421, date(2015, 12, 10), 7200.5),
)
QZSS_SOURCES = (
    Source("ohi-qzs3.txt", "QZS-3", 42917, date(2026, 11, 4), 42165.9),
    Source("ohi-qzs6.txt", "QZS-6", 62876, date(2026, 11, 4), 42165.9),
)

IDS_FIELDS = ["event_id", "satellite", "norad_id", "start_utc", "end_utc", "n_burns",
              "burn_times_utc", "dv_radial_m_s", "dv_along_m_s", "dv_cross_m_s", "kind",
              "delta_a_est_m", "source_file", "source_revision", "source_url"]
QZSS_FIELDS = ["event_id", "event_group", "satellite", "norad_id", "start_utc", "end_utc",
               "duration", "ns_ew", "dvx_m_s", "dvy_m_s", "dvz_m_s", "kind", "delta_a_est_m",
               "source_file", "source_revision", "source_url"]
QZSS_GEO_HEADER = "#DATE TIME START(UTC),END(UTC),DURATION,NS/EW,DVX(m/s),DVY(m/s),DVZ(m/s)"


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
    """The MANEUVER section of one GEO OHI file as output dicts, plus drop counts."""
    lines = text.splitlines()
    try:
        i = lines.index("#+SATELLITE/MANEUVER")
        j = lines.index("#-SATELLITE/MANEUVER", i)
    except ValueError as exc:
        raise ValueError(f"{src.file}: no MANEUVER section") from exc
    if lines[i + 1].strip() != QZSS_GEO_HEADER:
        raise ValueError(f"{src.file}: not the GEO maneuver layout: {lines[i + 1]!r}")
    revision = datetime.combine(src.revision, datetime.min.time())
    rows, dropped = [], {"on_or_after_revision": 0}
    body = [ln for ln in lines[i + 2:j] if ln.strip()]
    for ln in body:
        f = ln.split(",")
        if len(f) != 7:
            raise ValueError(f"{src.file}: expected 7 fields: {ln!r}")
        start = datetime.strptime(f[0], "%Y-%m-%d %H:%M:%S")
        end = datetime.strptime(f[1], "%Y-%m-%d %H:%M:%S")
        if f[3] not in ("EW", "NS", "NS-1", "NS-2"):
            raise ValueError(f"{src.file}: unknown NS/EW value {f[3]!r}")
        if start >= revision:
            dropped["on_or_after_revision"] += 1
            continue
        dvx, dvy, dvz = (float(x) for x in f[4:7])
        rows.append({
            "satellite": src.satellite, "norad_id": src.norad_id,
            "start_utc": _iso(start), "end_utc": _iso(end), "duration": f[2], "ns_ew": f[3],
            "dvx_m_s": f[4], "dvy_m_s": f[5], "dvz_m_s": f[6],
            "kind": "EW" if f[3] == "EW" else "NS",
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


def _write(path: Path, fields: list[str], rows: list[dict]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def build(ids_dir: Path, qzss_dir: Path, out: Path) -> dict:
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
    _write(out / "ids_manoeuvres.csv", IDS_FIELDS, ids_rows)
    _write(out / "qzss_manoeuvres.csv", QZSS_FIELDS, qz_rows)
    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--ids-dir", type=Path, required=True)
    p.add_argument("--qzss-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    for name, c in build(args.ids_dir, args.qzss_dir, args.out).items():
        print(name, c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
