# Which labelled objects may be used for tuning, and a loader that keeps the holdout blind.
# groundtruth/splits.json is written from OBJECTS and SPLIT_RULE, and a test checks it still follows the rule.

from __future__ import annotations

import argparse
import csv
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path

GROUNDTRUTH = Path(__file__).resolve().parents[1] / "groundtruth"
SPLITS_PATH = GROUNDTRUTH / "splits.json"
SEED = "orbit-watch truth-sets 2026-11-14"
HOLDOUT_SHARE = {"LEO": 1 / 3, "GEO": 2 / 3, "IGSO": 2 / 3}
SPLIT_RULE = (
    "The rule, fixed before any detector output for the new objects existed: * Every object "
    "that had been scored before this split (the ISS, CryoSat-2, Jason-3, SWOT, SPOT-5, "
    "QZS-3, QZS-6) is ``train``: none of them is blind any more. * The objects added with the "
    "split are grouped by regime (LEO, GEO, IGSO). Each group is sorted by NORAD id and "
    "shuffled with ``random.Random(SEED)``; the first ``ceil(n / 3)`` LEO objects and the "
    "first ``ceil(2 n / 3)`` GEO and IGSO objects are ``holdout``, the rest ``train``."
)


@dataclass(frozen=True)
class TruthObject:
    norad_id: int
    name: str
    regime: str
    truth_files: tuple[str, ...]
    previously_scored: bool


OBJECTS = (
    TruthObject(25544, "ISS", "ISS", ("iss_manoeuvres.csv", "iss_roscosmos_manoeuvres.csv"), True),
    TruthObject(36508, "CryoSat-2", "LEO", ("ids_manoeuvres.csv",), True),
    TruthObject(41240, "Jason-3", "LEO", ("ids_manoeuvres.csv",), True),
    TruthObject(54754, "SWOT", "LEO", ("ids_manoeuvres.csv",), True),
    TruthObject(27421, "SPOT-5", "LEO", ("ids_manoeuvres.csv",), True),
    TruthObject(42917, "QZS-3", "GEO", ("qzss_manoeuvres.csv",), True),
    TruthObject(62876, "QZS-6", "GEO", ("qzss_manoeuvres.csv",), True),
    TruthObject(41335, "Sentinel-3A", "LEO", ("ids_manoeuvres.csv",), False),
    TruthObject(43437, "Sentinel-3B", "LEO", ("ids_manoeuvres.csv",), False),
    TruthObject(46984, "Sentinel-6A", "LEO", ("ids_manoeuvres.csv",), False),
    TruthObject(66514, "Sentinel-6B", "LEO", ("ids_manoeuvres.csv",), False),
    TruthObject(39086, "SARAL", "LEO", ("ids_manoeuvres.csv",), False),
    TruthObject(46469, "HY-2C", "LEO", ("ids_manoeuvres.csv",), False),
    TruthObject(48621, "HY-2D", "LEO", ("ids_manoeuvres.csv",), False),
    TruthObject(37158, "QZS-1", "IGSO", ("qzss_manoeuvres.csv",), False),
    TruthObject(49336, "QZS-1R", "IGSO", ("qzss_manoeuvres.csv",), False),
    TruthObject(42738, "QZS-2", "IGSO", ("qzss_manoeuvres.csv",), False),
    TruthObject(42965, "QZS-4", "IGSO", ("qzss_manoeuvres.csv",), False),
    TruthObject(38049, "Fengyun-2F", "GEO", ("fengyun_manoeuvres.csv",), False),
    TruthObject(43491, "Fengyun-2H", "GEO", ("fengyun_manoeuvres.csv",), False),
    TruthObject(41882, "Fengyun-4A", "GEO", ("fengyun_manoeuvres.csv",), False),
)


class HoldoutError(PermissionError):
    pass
def make_splits(objects=OBJECTS) -> dict:
    split = {o.norad_id: "train" for o in objects if o.previously_scored}
    for regime, share in HOLDOUT_SHARE.items():
        new = sorted(o.norad_id for o in objects if not o.previously_scored and o.regime == regime)
        random.Random(SEED).shuffle(new)
        n_holdout = math.ceil(share * len(new))
        split.update({norad: "holdout" if k < n_holdout else "train" for k, norad in enumerate(new)})
    return {
        "rule": SPLIT_RULE,
        "seed": SEED,
        "objects": [
            {"norad_id": o.norad_id, "name": o.name, "regime": o.regime,
             "split": split[o.norad_id], "previously_scored": o.previously_scored,
             "truth_files": list(o.truth_files)}
            for o in objects
        ],
    }


def load_splits(path: Path = SPLITS_PATH) -> dict[int, dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {int(o["norad_id"]): o for o in data["objects"]}


def require_not_holdout(norad_id: int, *, final: bool = False,
                        splits: dict[int, dict] | None = None) -> dict | None:
    splits = load_splits() if splits is None else splits
    entry = splits.get(int(norad_id))
    if entry is not None and entry["split"] == "holdout" and not final:
        raise HoldoutError(
            f"NORAD {norad_id} ({entry['name']}) is in the holdout; only a final scoring run "
            "(final=True) may read its labels or element sets"
        )
    return entry


def require_allowed(norad_id: int, *, final: bool = False, splits: dict[int, dict] | None = None) -> dict:
    entry = require_not_holdout(norad_id, final=final, splits=splits)
    if entry is None:
        raise HoldoutError(f"NORAD {norad_id} is not in splits.json; assign it before scoring")
    return entry


def read_label_rows(path: Path, norad_id: int, *, final: bool = False) -> list[dict]:
    require_allowed(norad_id, final=final)
    with open(path, encoding="utf-8", newline="") as f:
        return [r for r in csv.DictReader(f)
                if "norad_id" not in r or int(r["norad_id"]) == int(norad_id)]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Write or check groundtruth/splits.json.")
    p.add_argument("--write", action="store_true", help="write splits.json from the rule")
    args = p.parse_args(argv)
    text = json.dumps(make_splits(), indent=2) + "\n"
    if args.write:
        SPLITS_PATH.write_text(text, encoding="utf-8", newline="\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
