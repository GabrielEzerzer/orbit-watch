# Pull per-object TLE history out of the OndroNR/tle-archive git history of CelesTrak's active.txt.
# Run it on Kaggle: the bare clone is about 2 GB.

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from orbit_watch.elements import parse_tle

REPO_URL = "https://github.com/OndroNR/tle-archive.git"
PATH = "TLEs/active.txt"
COMMIT_MARK = "\x1e"
GAP = timedelta(days=3)


@dataclass
class ObjectHistory:
    lines: dict[datetime, tuple[str, str]] = field(default_factory=dict)
    invalid: int = 0
    conflicts: int = 0


@dataclass
class Extract:
    commits: int = 0
    last_commit: str | None = None
    objects: dict[int, ObjectHistory] = field(default_factory=dict)


def _catnr(tle_line: str) -> int | None:
    field_ = tle_line[2:7]
    return int(field_) if field_.strip().isdigit() else None


def extract(diff_lines: Iterable[str], wanted: set[int]) -> Extract:
    result = Extract(objects={n: ObjectHistory() for n in wanted})
    current: dict[int, list[str | None]] = {n: [None, None] for n in wanted}
    touched: set[int] = set()

    def close_commit() -> None:
        for norad in touched:
            line1, line2 = current[norad]
            if line1 is None or line2 is None:
                continue
            history = result.objects[norad]
            try:
                (record,) = parse_tle(f"{line1}\n{line2}\n")
            except ValueError:
                history.invalid += 1
                continue
            held = history.lines.get(record.epoch)
            if held is None:
                history.lines[record.epoch] = (line1, line2)
            elif held != (line1, line2):
                history.conflicts += 1
        touched.clear()

    for raw in diff_lines:
        line = raw.rstrip("\r\n")
        if line.startswith(COMMIT_MARK):
            close_commit()
            result.commits += 1
            result.last_commit = line[1:].split()[0]
            continue
        if not (line.startswith("+1 ") or line.startswith("+2 ")):
            continue
        tle_line = line[1:]
        norad = _catnr(tle_line)
        if norad in current:
            current[norad][int(tle_line[0]) - 1] = tle_line
            touched.add(norad)
    close_commit()
    return result


def names_matching(text: str, pattern: re.Pattern[str]) -> dict[int, str]:
    lines = [ln.rstrip("\r\n") for ln in text.splitlines()]
    found: dict[int, str] = {}
    for name, line1 in zip(lines, lines[1:]):
        if not name.startswith(("1 ", "2 ")) and line1.startswith("1 ") and pattern.search(name):
            norad = _catnr(line1)
            if norad is not None:
                found[norad] = name.strip()
    return found


def gaps(epochs: list[datetime], longer_than: timedelta = GAP) -> list[tuple[datetime, datetime]]:
    return [(a, b) for a, b in zip(epochs, epochs[1:]) if b - a > longer_than]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    ).stdout


def _all_names(repo: Path) -> dict[int, list[str]]:
    log = _git(repo, "log", "--first-parent", "--reverse", "--format=%H %cI", "--", PATH)
    samples: dict[str, str] = {}
    commits = [row.split() for row in log.splitlines() if row.strip()]
    for sha, date in commits:
        samples.setdefault(date[:7], sha)
    found: dict[int, list[str]] = {}
    for sha in [*samples.values(), commits[-1][0]]:
        for norad, name in names_matching(_git(repo, "show", f"{sha}:{PATH}"), re.compile("")).items():
            if name not in found.setdefault(norad, []):
                found[norad].append(name)
    return found


def _iso(epoch: datetime) -> str:
    return epoch.isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pull per-object TLE history out of the OndroNR/tle-archive git history.")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--norad", type=int, action="append", default=[])
    parser.add_argument("--name-regex", type=re.compile)
    args = parser.parse_args(argv)
    if not args.norad and args.name_regex is None:
        parser.error("give at least one --norad or a --name-regex")
    args.out.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp) / "tle-archive.git"
        print(f"cloning {REPO_URL}", flush=True)
        subprocess.run(["git", "clone", "--bare", "--single-branch", "-q", REPO_URL, str(repo)], check=True)
        head = _git(repo, "rev-parse", "HEAD").strip()

        names = _all_names(repo)
        pattern = args.name_regex
        wanted = set(args.norad) | {
            n for n, seen in names.items() if pattern and any(pattern.search(name) for name in seen)
        }
        print(f"walking {PATH} for {len(wanted)} objects", flush=True)
        proc = subprocess.Popen(
            ["git", "-C", str(repo), "log", "--first-parent", "--reverse", "-p", "-U0", "--no-renames",
             "--no-color", "--no-ext-diff", f"--format={COMMIT_MARK}%H %cI", "--", PATH],
            stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
        )
        result = extract(proc.stdout, wanted)
        if proc.wait() != 0:
            raise RuntimeError(f"git log exited {proc.returncode}")

    objects = {}
    for norad in sorted(wanted):
        history = result.objects[norad]
        epochs = sorted(history.lines)
        (args.out / f"{norad}.tle").write_text(
            "".join(f"{a}\n{b}\n" for a, b in (history.lines[e] for e in epochs)), encoding="ascii"
        )
        objects[str(norad)] = {
            "names": names.get(norad, []),
            "tle_count": len(epochs),
            "first_epoch": _iso(epochs[0]) if epochs else None,
            "last_epoch": _iso(epochs[-1]) if epochs else None,
            "invalid_pairs": history.invalid,
            "epoch_conflicts": history.conflicts,
            "gaps_over_3_days": [[_iso(a), _iso(b)] for a, b in gaps(epochs)],
        }
    manifest = {
        "repo_url": REPO_URL,
        "path": PATH,
        "archive_head": head,
        "last_commit_touching_path": result.last_commit,
        "commits_walked": result.commits,
        "name_regex": args.name_regex.pattern if args.name_regex else None,
        "objects": objects,
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
