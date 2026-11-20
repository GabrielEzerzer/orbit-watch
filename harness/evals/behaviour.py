# Checks of the behaviour score (issue 105): cited irregular objects outside, cited steady keepers outside, rocket
# bodies and debris outside, and the cited irregular count against two plain rankings cut at the outside set's size.

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from harness.evals.mode_events import _commit
from harness.evals.routine import IRREGULAR, STEADY, _shown, read_cited
from orbit_watch.jobs.routine import DEAD_TYPES

OUT = Path("findings/behaviour")
IRREGULAR_SHARE = 0.75
DEAD_SHARE = 0.01
PLAIN = ("relocation_starts_per_year", "burns_per_year")


def plain_order(rows: Sequence[dict], feature: str) -> list[int]:
    return [int(r["norad_id"]) for r in sorted(rows, key=lambda r: (-float(r[feature]), int(r["norad_id"])))]


def cited_rows(rows: Sequence[dict], ids: Sequence[int], positions: dict[str, dict[int, int]]) -> list[dict]:
    by = {int(r["norad_id"]): r for r in rows}
    return [{"norad_id": n, "name": by[n]["name"] if n in by else "", "rank": int(by[n]["rank"]) if n in by else None,
             "score": float(by[n]["score"]) if n in by else None, "outside": int(by[n]["outside"]) if n in by else 0,
             **{f"rank_{f}": positions[f].get(n) for f in PLAIN}} for n in ids]


def count_checks(rows: Sequence[dict], irregular: Sequence[int], steady: Sequence[int]) -> dict:
    outside = {int(r["norad_id"]) for r in rows if int(r["outside"])}
    scored = {int(r["norad_id"]) for r in rows}
    hit = sum(n in outside for n in irregular)
    calm = sum(n in outside for n in steady)
    dead = [r for r in rows if r["object_type"] in DEAD_TYPES]
    dead_out = sum(int(r["outside"]) for r in dead)
    orders = {f: plain_order(rows, f) for f in PLAIN}
    plain = {f: sum(n in set(orders[f][:len(outside)]) for n in irregular) for f in PLAIN}
    checks = {
        "1_cited_irregular_outside": {"listed": len(irregular), "scored": sum(n in scored for n in irregular),
                                      "outside": hit, "target": f"at least {IRREGULAR_SHARE:.0%} of {len(irregular)}",
                                      "pass": hit >= IRREGULAR_SHARE * len(irregular)},
        "2_cited_steady_outside": {"listed": len(steady), "scored": sum(n in scored for n in steady), "outside": calm,
                                   "target": "0", "pass": calm == 0},
        "3_rocket_bodies_and_debris_outside": {"objects": len(dead), "outside": dead_out,
                                               "share": round(dead_out / len(dead), 4) if dead else None,
                                               "target": f"at most {DEAD_SHARE:.0%}",
                                               "pass": dead_out <= DEAD_SHARE * len(dead)},
        "4_against_plain_rankings": {"cut_objects": len(outside), "outlier_score": hit,
                                     **{f: plain[f] for f in PLAIN}, "target": "outlier score higher than both",
                                     "pass": all(hit > v for v in plain.values())},
    }
    positions = {f: {n: i for i, n in enumerate(orders[f], 1)} for f in PLAIN}
    return {"checks": checks, "verdict": "pass" if all(c["pass"] for c in checks.values()) else "fail",
            "irregular_objects": cited_rows(rows, irregular, positions),
            "steady_objects": cited_rows(rows, steady, positions)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Checks of the behaviour score against the cited lists (issue 105).")
    p.add_argument("--out", type=Path, default=OUT, help="results folder of the behaviour job (default %(default)s)")
    p.add_argument("--irregular", type=Path, default=IRREGULAR, help="cited irregular objects (default %(default)s)")
    p.add_argument("--steady", type=Path, default=STEADY, help="cited steady keepers (default %(default)s)")
    a = p.parse_args(argv)
    with open(a.out / "features.csv", newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    result = {**_commit(), "irregular_file": _shown(a.irregular), "steady_file": _shown(a.steady),
              **count_checks(rows, [n for n, _ in read_cited(a.irregular)], [n for n, _ in read_cited(a.steady)])}
    path = a.out / "checks.json"
    path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({k: result[k] for k in ("checks", "verdict")}, indent=1))
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
