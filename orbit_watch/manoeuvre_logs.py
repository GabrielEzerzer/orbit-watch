# Build ground-truth manoeuvre lists from published logs (QZSS and the Fengyun set).
# Every output row carries its source file, the file's revision date and its URL.

from __future__ import annotations

import argparse
import csv
import math
import shlex
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

MU_KM3_S2 = 398600.4418
QZSS_URL = "https://qzss.go.jp/en/technical/qzssinfo/khp0mf0000000wuf-att/"
FENGYUN_COMMIT = "4cf0b15600658a486eff9e6a967ebd520e2354d1"
FENGYUN_URL = ("https://github.com/dpshorten/TLE_observation_benchmark_dataset/blob/"
               f"{FENGYUN_COMMIT}/raw_data/manoeuvres/")


@dataclass(frozen=True)
class Source:
    file: str
    satellite: str
    norad_id: int
    revision: date
    nominal_a_km: float
    cospar_id: str = ""

    @property
    def url(self) -> str:
        if self.file.startswith("manFY"):
            return FENGYUN_URL + self.file
        return QZSS_URL + self.file


QZSS_SOURCES = (
    Source("ohi-qzs3.txt", "QZS-3", 42917, date(2026, 11, 4), 42165.9),
    Source("ohi-qzs6.txt", "QZS-6", 62876, date(2026, 11, 4), 42165.9),
    Source("ohi-qzs1.txt", "QZS-1", 37158, date(2026, 11, 4), 42164.8),
    Source("ohi-qzs1r.txt", "QZS-1R", 49336, date(2026, 11, 4), 42165.1),
    Source("ohi-qzs2.txt", "QZS-2", 42738, date(2026, 11, 4), 42165.7),
    Source("ohi-qzs4.txt", "QZS-4", 42965, date(2026, 11, 4), 42165.0),
)
FENGYUN_SOURCES = (
    Source("manFY2F.txt.fy", "Fengyun-2F", 38049, date(2022, 11, 22), 0.0, "2012-002A"),
    Source("manFY2H.txt.fy", "Fengyun-2H", 43491, date(2022, 11, 22), 0.0, "2018-050A"),
    Source("manFY4A.txt.fy", "Fengyun-4A", 41882, date(2022, 11, 22), 0.0, "2016-077A"),
)

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
    n = math.sqrt(MU_KM3_S2 / a_km**3)
    return 2.0 * dv_along_m_s / n


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds") + "Z" if t.microsecond == 0 else \
        t.isoformat(timespec="milliseconds") + "Z"


def parse_qzss(text: str, src: Source) -> tuple[list[dict], dict]:
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
            f.insert(3, "")
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


def build(qzss_dir: Path, fengyun_dir: Path, out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    counts, qz_rows = {}, []
    for src in QZSS_SOURCES:
        rows, c = parse_qzss((qzss_dir / src.file).read_text(encoding="utf-8"), src)
        qz_rows += rows
        counts[src.file] = c
    fy_rows = []
    for src in FENGYUN_SOURCES:
        rows, c = parse_fengyun((fengyun_dir / src.file).read_text(encoding="ascii"), src)
        fy_rows += rows
        counts[src.file] = c
    _write(out / "fengyun_manoeuvres.csv", FENGYUN_FIELDS, fy_rows)
    _write(out / "qzss_manoeuvres.csv", QZSS_FIELDS, qz_rows)
    return counts


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Build ground-truth manoeuvre lists from published logs (QZSS and the Fengyun set).")
    p.add_argument("--qzss-dir", type=Path, required=True)
    p.add_argument("--fengyun-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)
    for name, c in build(args.qzss_dir, args.fengyun_dir, args.out).items():
        print(name, c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
