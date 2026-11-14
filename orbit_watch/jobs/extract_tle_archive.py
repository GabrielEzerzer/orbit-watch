"""Pull per-object TLE history out of the OndroNR/tle-archive git history.

    python -m orbit_watch.jobs.extract_tle_archive --out <dir> --norad 25544 [--norad ...]
        [--name-regex 'LUCH|OLYMP']

The archive is a GitHub repo whose hourly job committed CelesTrak's ``TLEs/active.txt`` (3LE)
from 2021-01-01 until 2023-12-28: about 19k commits and 1.94 GB. This job makes a bare clone,
streams ``git log -p -U0`` of that one file oldest first, and keeps only the added TLE lines of
the wanted catalog numbers. Every line 1 / line 2 pair is checked with our own TLE parser and
de-duplicated by epoch. It writes ``<norad>.tle`` (2-line TLEs, epoch order) per object and a
``manifest.json``. Run it on Kaggle (see the README); the clone is too big for the laptop.
"""

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
COMMIT_MARK = "\x1e"  # starts each commit header line in our `git log --format`
GAP = timedelta(days=3)


@dataclass
class ObjectHistory:
    lines: dict[datetime, tuple[str, str]] = field(default_factory=dict)  # epoch -> (line 1, line 2)
    invalid: int = 0  # pairs our parser rejected
    conflicts: int = 0  # pairs whose epoch was already held with different lines (first one kept)


@dataclass
class Extract:
    commits: int = 0
    last_commit: str | None = None
    objects: dict[int, ObjectHistory] = field(default_factory=dict)


def _catnr(tle_line: str) -> int | None:
    field_ = tle_line[2:7]
    return int(field_) if field_.strip().isdigit() else None


def extract(diff_lines: Iterable[str], wanted: set[int]) -> Extract:
    """Collect the wanted objects' element sets from ``git log -p -U0 --reverse`` output.

    Commit headers are lines starting with ``COMMIT_MARK`` followed by the SHA. The current
    line 1 and line 2 of each wanted object are carried from commit to commit, so a commit that
    changes only one of the two lines still yields a whole pair. Pairs are validated after each
    commit, once every hunk of that commit has been read.
    """
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
        # Added TLE lines only; '+++ b/...' file headers never match '+1 ' or '+2 '.
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
    """Catalog number -> name for the 3LE entries in ``text`` whose name line matches ``pattern``."""
    lines = [ln.rstrip("\r\n") for ln in text.splitlines()]
    found: dict[int, str] = {}
    for name, line1 in zip(lines, lines[1:]):
        if not name.startswith(("1 ", "2 ")) and line1.startswith("1 ") and pattern.search(name):
            norad = _catnr(line1)
            if norad is not None:
                found[norad] = name.strip()
    return found


def gaps(epochs: list[datetime], longer_than: timedelta = GAP) -> list[tuple[datetime, datetime]]:
    """Consecutive (earlier, later) epoch pairs further apart than ``longer_than``; epochs sorted."""
    return [(a, b) for a, b in zip(epochs, epochs[1:]) if b - a > longer_than]


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    ).stdout


def _resolve_names(repo: Path, pattern: re.Pattern[str]) -> dict[int, str]:
    """Names from the first version of the file in each month and the last version."""
    # shortcut: monthly samples can miss an object that was in active.txt for under a month;
    # scan every version if a short-lived object ever matters.
    log = _git(repo, "log", "--first-parent", "--reverse", "--format=%H %cI", "--", PATH)
    samples: dict[str, str] = {}
    commits = [row.split() for row in log.splitlines() if row.strip()]
    for sha, date in commits:
        samples.setdefault(date[:7], sha)
    found: dict[int, str] = {}
    for sha in [*samples.values(), commits[-1][0]]:
        found.update(names_matching(_git(repo, "show", f"{sha}:{PATH}"), pattern))
    return found


def _iso(epoch: datetime) -> str:
    return epoch.isoformat().replace("+00:00", "Z")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
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

        names = _resolve_names(repo, args.name_regex) if args.name_regex else {}
        wanted = set(args.norad) | set(names)
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
            "name": names.get(norad),
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
