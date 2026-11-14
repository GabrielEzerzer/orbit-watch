"""TLE history of every object in the GEO region, from yearly full-catalogue TLE bundles.

    python -m orbit_watch.jobs.geo_belt build --source TEXT --bundle PATH_OR_GLOB [...] --out DIR_OR_ZIP
    hush run -- python -m orbit_watch.jobs.geo_belt satcat --out DIR

``build`` streams the bundles (TLE text, 2-line or 3-line, as ``.txt`` files or inside ``.zip``
files) twice, never holding a whole bundle in memory. The first pass picks the objects that meet
``RULE`` in the period; the second keeps every element set those objects have in the period,
including ones outside the region (a transfer orbit before arrival, a graveyard orbit after it).
Each pair is checked with ``elements.parse_tle`` and de-duplicated by epoch the way
``series.to_series`` does it (a later record with the same epoch wins). It writes ``<norad>.tle``
per object (2-line TLEs in epoch order) and ``manifest.json``, into a directory, or into one zip
when ``--out`` ends in ``.zip`` (a Kaggle kernel should not write thousands of output files).

``satcat`` adds each object's Space-Track SATCAT entry (type, launch, decay) to an existing
``manifest.json`` in a directory, with one full-catalogue SATCAT query cached under
``data/spacetrack`` beside the output directory.
"""

from __future__ import annotations

import argparse
import glob
import hashlib
import io
import json
import sys
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from orbit_watch.elements import parse_tle
from orbit_watch.jobs.extract_tle_archive import _catnr, _iso

START = datetime(2021, 1, 1, tzinfo=timezone.utc)
END = datetime(2026, 1, 1, tzinfo=timezone.utc)  # exclusive
RULE = {
    "text": (
        "An object is in the GEO region if any of its element sets with an epoch in the period has "
        "mean motion 0.9 to 1.1 rev/day, eccentricity at most 0.2 and inclination at most 70 deg "
        "(ESA's GEO-region definition). All of its element sets in the period are kept, including "
        "ones outside those bounds."
    ),
    "mean_motion_rev_per_day": [0.9, 1.1],
    "eccentricity_max": 0.2,
    "inclination_deg_max": 70.0,
}
SATCAT_FIELDS = ("OBJECT_NAME", "OBJECT_TYPE", "INTLDES", "COUNTRY", "LAUNCH", "DECAY")


def in_geo_region(mean_motion: float, eccentricity: float, inclination: float) -> bool:
    """``RULE`` for one element set (rev/day, dimensionless, degrees)."""
    low, high = RULE["mean_motion_rev_per_day"]
    return (
        low <= mean_motion <= high
        and eccentricity <= RULE["eccentricity_max"]
        and inclination <= RULE["inclination_deg_max"]
    )


def bundle_paths(patterns: Iterable[str]) -> list[Path]:
    """Files named by paths or recursive globs, in the order given; each must match something."""
    paths: list[Path] = []
    for pattern in patterns:
        if glob.has_magic(pattern):
            found = sorted(Path(p) for p in glob.glob(pattern, recursive=True) if Path(p).is_file())
        else:
            found = [Path(pattern)] if Path(pattern).is_file() else []
        if not found:
            raise FileNotFoundError(f"no bundle file matches {pattern!r}")
        paths.extend(p for p in found if p not in paths)
    return paths


def bundle_lines(path: Path) -> Iterator[str]:
    """The text lines of a ``.txt`` bundle, or of every ``.txt`` member of a ``.zip``, streamed."""
    if path.suffix.lower() != ".zip":
        with open(path, encoding="ascii", errors="replace") as f:
            yield from f
        return
    with zipfile.ZipFile(path) as zf:
        members = sorted(n for n in zf.namelist() if n.lower().endswith(".txt"))
        if not members:
            raise ValueError(f"{path}: no .txt member")
        for member in members:
            with zf.open(member) as raw:
                yield from io.TextIOWrapper(raw, encoding="ascii", errors="replace")


@dataclass
class LineCount:
    lines: int = 0  # non-blank lines read
    pairs: int = 0  # line 1 / line 2 pairs found by layout (not yet checked by the parser)
    rejected_lines: int = 0  # non-blank lines that are not part of a pair or a name line before one


def tle_pairs(lines: Iterable[str], count: LineCount) -> Iterator[tuple[str | None, str, str]]:
    """(name or None, line 1, line 2) for each pair laid out as in ``parse_tle``; counts the rest.

    A line 1 and line 2 are 69 characters starting ``1 `` and ``2 ``. A line directly before a
    line 1 that does not start with ``1 `` or ``2 `` is its name (a leading ``0 `` removed). Every
    other non-blank line is rejected, such as the 68-character analyst-object lines (catalog
    numbers 8xxxx) in the Kaggle mirror's 2025 file.
    """
    name: str | None = None  # a candidate name line, not yet followed by a line 1
    line1: str | None = None
    for raw in lines:
        line = raw.rstrip()
        if not line:
            continue
        count.lines += 1
        is_line1 = line.startswith("1 ") and len(line) == 69
        is_line2 = line.startswith("2 ") and len(line) == 69
        if line1 is not None:
            if is_line2:
                count.pairs += 1
                yield name, line1, line
                name, line1 = None, None
                continue
            count.rejected_lines += 1 + (name is not None)  # the orphan line 1 and its name
            name, line1 = None, None
        if is_line1:
            line1 = line
        elif line.startswith(("1 ", "2 ")):  # a stray or malformed element line is never a name
            count.rejected_lines += 1 + (name is not None)
            name = None
        else:
            count.rejected_lines += name is not None
            name = line[2:].strip() if line.startswith("0 ") else line.strip()
    count.rejected_lines += (line1 is not None) + (name is not None)


def select(paths: Iterable[Path], start: datetime = START, end: datetime = END) -> tuple[set[int], dict[Path, LineCount]]:
    """Pass 1: the catalog numbers with at least one valid element set in the period inside ``RULE``."""
    selected: set[int] = set()
    counts: dict[Path, LineCount] = {}
    for path in paths:
        count = counts[path] = LineCount()
        for _name, line1, line2 in tle_pairs(bundle_lines(path), count):
            # Same columns parse_tle reads, so this pre-check never drops a set the parser keeps.
            try:
                inside = in_geo_region(float(line2[52:63]), float("0." + line2[26:33]), float(line2[8:16]))
            except ValueError:
                continue
            norad = _catnr(line1)
            if not inside or norad is None or norad in selected:
                continue
            try:
                (rec,) = parse_tle(f"{line1}\n{line2}\n")
            except ValueError:
                continue
            if start <= rec.epoch < end and in_geo_region(rec.mean_motion, rec.eccentricity, rec.inclination):
                selected.add(norad)
    return selected, counts


@dataclass
class ObjectHistory:
    lines: dict[datetime, tuple[str, str]] = field(default_factory=dict)  # epoch -> (line 1, line 2)
    names: list[str] = field(default_factory=list)  # distinct name lines, first seen first
    in_region: set[datetime] = field(default_factory=set)  # epochs whose kept set meets RULE
    invalid: int = 0  # pairs the parser rejected
    conflicts: int = 0  # pairs restating a held epoch with different lines (the later one kept)


def collect(
    paths: Iterable[Path], selected: set[int], start: datetime = START, end: datetime = END
) -> dict[int, ObjectHistory]:
    """Pass 2: every valid element set of the selected objects with an epoch in the period."""
    histories = {norad: ObjectHistory() for norad in selected}
    for path in paths:
        for name, line1, line2 in tle_pairs(bundle_lines(path), LineCount()):
            history = histories.get(_catnr(line1))
            if history is None:
                continue
            try:
                (rec,) = parse_tle(f"{line1}\n{line2}\n")
            except ValueError:
                history.invalid += 1
                continue
            if not start <= rec.epoch < end:
                continue
            held = history.lines.get(rec.epoch)
            if held is not None and held != (line1, line2):
                history.conflicts += 1
            history.lines[rec.epoch] = (line1, line2)
            if in_geo_region(rec.mean_motion, rec.eccentricity, rec.inclination):
                history.in_region.add(rec.epoch)
            else:
                history.in_region.discard(rec.epoch)
            if name and name not in history.names:
                history.names.append(name)
    return histories


def _sha256(path: Path) -> str:
    with open(path, "rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def build(
    source: str, paths: list[Path], start: datetime = START, end: datetime = END, also: Iterable[int] = ()
) -> dict[str, str]:
    """Output file name -> contents: ``<norad>.tle`` per selected object and ``manifest.json``.

    ``also`` adds objects outside the rule (e.g. LEO calibration satellites); each object's
    ``by_rule`` says whether the rule selected it.
    """
    by_rule, counts = select(paths, start, end)
    selected = by_rule | set(also)
    histories = collect(paths, selected, start, end)
    files: dict[str, str] = {}
    objects = {}
    for norad in sorted(histories):
        history = histories[norad]
        if not history.lines:
            continue
        epochs = sorted(history.lines)
        files[f"{norad}.tle"] = "".join(f"{a}\n{b}\n" for a, b in (history.lines[e] for e in epochs))
        objects[str(norad)] = {
            "by_rule": norad in by_rule,
            "names": history.names,
            "tle_count": len(epochs),
            "in_region_count": len(history.in_region),
            "first_epoch": _iso(epochs[0]),
            "last_epoch": _iso(epochs[-1]),
            "invalid_pairs": history.invalid,
            "epoch_conflicts": history.conflicts,
        }
    manifest = {
        "job": "orbit_watch.jobs.geo_belt",
        "created": _iso(datetime.now(timezone.utc).replace(microsecond=0)),
        "source": source,
        "period": {"start": _iso(start), "end_exclusive": _iso(end)},
        "rule": RULE,
        "also": sorted(set(also)),
        "bundles": [
            {
                "name": path.name,
                "path": path.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
                "lines": counts[path].lines,
                "pairs": counts[path].pairs,
                "rejected_lines": counts[path].rejected_lines,
            }
            for path in paths
        ],
        "object_count": len(objects),
        "tle_count": sum(o["tle_count"] for o in objects.values()),
        "objects": objects,
    }
    files["manifest.json"] = json.dumps(manifest, indent=2) + "\n"
    return files


def write(files: dict[str, str], out: Path) -> None:
    """Into directory ``out``, or into the zip ``out`` when it ends in ``.zip``."""
    if out.suffix.lower() == ".zip":
        out.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, text in files.items():
                zf.writestr(name, text)
        return
    out.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out / name).write_text(text, encoding="ascii", newline="\n")


def add_satcat(manifest: dict, rows: Iterable[dict], query: str) -> dict:
    """``manifest`` with each object's SATCAT fields under ``satcat`` (None if the catalogue lacks it)."""
    by_norad = {str(int(r["NORAD_CAT_ID"])): r for r in rows}
    missing = 0
    for norad, entry in manifest["objects"].items():
        row = by_norad.get(norad)
        missing += row is None
        entry["satcat"] = None if row is None else {k: row.get(k) for k in SATCAT_FIELDS}
    manifest["satcat"] = {"query": query, "objects_missing": missing}
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    build_cmd = commands.add_parser("build", help="select GEO-region objects from bundles and write their TLEs")
    build_cmd.add_argument("--source", required=True, help="where the bundles came from (a URL), for the manifest")
    build_cmd.add_argument("--bundle", required=True, action="append", help="a bundle file or recursive glob (repeatable)")
    build_cmd.add_argument("--out", required=True, type=Path, help="output directory, or a .zip file")
    build_cmd.add_argument("--also", type=int, action="append", default=[], help="NORAD id to add outside the rule (repeatable)")
    satcat_cmd = commands.add_parser("satcat", help="add SATCAT entries to an output directory's manifest")
    satcat_cmd.add_argument("--out", required=True, type=Path, help="the output directory of build")
    args = parser.parse_args(argv)

    if args.command == "build":
        paths = bundle_paths(args.bundle)
        for path in paths:
            print(f"bundle {path} ({path.stat().st_size} bytes)", flush=True)
        files = build(args.source, paths, also=args.also)
        write(files, args.out)
        manifest = json.loads(files["manifest.json"])
        print(json.dumps({k: v for k, v in manifest.items() if k != "objects"}, indent=2))
        return 0

    from orbit_watch.spacetrack import SpaceTrackSource

    path = args.out / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    st = SpaceTrackSource.from_env(START.date(), END.date(), cache_dir=args.out.resolve().parent / "spacetrack")
    if st is None:
        sys.exit("SPACETRACK_USER and SPACETRACK_PASSWORD are not set; run it as `hush run -- ...`")
    rows, query = st.satcat(("NORAD_CAT_ID", *SATCAT_FIELDS))
    path.write_text(json.dumps(add_satcat(manifest, rows, query), indent=2) + "\n", encoding="utf-8")
    print(f"SATCAT added to {path}; objects missing from the catalogue: {manifest['satcat']['objects_missing']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
