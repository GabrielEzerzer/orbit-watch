# ESA's per-object classes for 1 January 2019 beside our first mode of 2021, read from pdftotext -layout
# output of ESA's Classification of Geosynchronous Objects, issue 21.

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

CHAPTERS = {"C1": (51, 83), "C2": (83, 96), "C4": (96, 97), "D": (97, 167), "L1": (167, 178),
            "L2": (178, 182), "L3": (182, 191), "I": (191, 193), "Ind": (193, 194)}
OURS = {"C1": "controlled_lon_inc", "C2": "controlled_lon", "C4": "drifting", "D": "drifting",
        "L1": "librating_75E", "L2": "librating_105W", "L3": "librating_both", "I": "inclined",
        "Ind": "undetermined"}
_ROW = re.compile(r"^(\d{4}-\d{3}[A-Z]{1,3}) .*\s(C1|C2|C4|D|L1|L2|L3|I|Ind)\s+\d+\.\s+p\.\s*(\d+)$")


def esa_classes(text: str) -> dict[str, str]:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("COSPAR Name") and "Status" in line)
    end = next(i for i in range(start, len(lines)) if re.match(r"^\s*4\s+OBJECTS WITH EPHEMERIS", lines[i]))
    out = {}
    for line in lines[start:end]:
        m = _ROW.match(line.strip())
        if m and CHAPTERS[m[2]][0] <= int(m[3]) < CHAPTERS[m[2]][1]:
            out[m[1]] = m[2]
    return out


def first_modes(segments_csv: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    with open(segments_csv, encoding="utf-8") as f:
        for r in csv.DictReader(f):
            n = int(r["norad_id"])
            if n not in out and r["mode"] != "undetermined" and r["start"] < "2021-07-01":
                out[n] = r["mode"]
    return out


def agreement(esa: dict[str, str], cospar_to_norad: dict[str, int], ours: dict[int, str]) -> dict[str, Counter]:
    by_class: dict[str, Counter] = defaultdict(Counter)
    for cospar, cls in esa.items():
        mode = ours.get(cospar_to_norad.get(cospar, -1))
        if mode is not None:
            by_class[cls][mode] += 1
    return by_class


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="ESA's per-object classes for 1 January 2019 beside our first mode of 2021.")
    p.add_argument("esa_text", type=Path, help="pdftotext -layout -enc UTF-8 output of the Issue 21 PDF")
    p.add_argument("segments", type=Path, help="segments.csv from orbit_watch.jobs.geo_modes")
    p.add_argument("--manifest", type=Path, default=Path("data/geo/manifest.json"))
    args = p.parse_args(argv)
    esa = esa_classes(args.esa_text.read_text(encoding="utf-8"))
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    cospar_to_norad = {o["satcat"]["INTLDES"]: int(n) for n, o in manifest["objects"].items() if o.get("satcat")}
    by_class = agreement(esa, cospar_to_norad, first_modes(args.segments))
    print(f"{len(esa)} ESA rows kept, {sum(sum(c.values()) for c in by_class.values())} matched to a mode\n")
    print("| ESA 2019 | objects | same mode in early 2021 | main other modes |")
    print("|---|---|---|---|")
    for cls in CHAPTERS:
        c = by_class.get(cls)
        if not c:
            continue
        total, same = sum(c.values()), c[OURS[cls]]
        others = [f"{m} {k}" for m, k in c.most_common() if m != OURS[cls]][:2]
        print(f"| {cls} | {total} | {same} ({same / total:.0%}) | {', '.join(others)} |")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
