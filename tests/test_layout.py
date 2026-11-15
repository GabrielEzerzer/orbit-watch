import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TOP_LEVEL_DIRS = {".github", "findings", "groundtruth", "harness", "mock", "orbit_watch", "setup", "tests", "tools"}
TOP_LEVEL_FILES = {".gitignore", ".lint-baseline.json", "FINDINGS.md", "README.md", "features.json", "hush.toml", "pyproject.toml"}


def placed(path):
    top, _, rest = path.partition("/")
    return top in TOP_LEVEL_DIRS if rest else path in TOP_LEVEL_FILES


def misplaced(paths):
    return sorted(p for p in paths if not placed(p))


def test_every_tracked_file_sits_under_a_known_top_level_folder():
    proc = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True)
    if proc.returncode != 0:
        pytest.skip("not a git checkout, so there is no tracked file list to check")
    stray = misplaced(filter(None, proc.stdout.decode("utf-8").split("\0")))
    assert not stray, (
        f"{stray} sit outside the repo's known top-level folders and files. Put code in orbit_watch/, jobs in "
        "orbit_watch/jobs/, evaluations in harness/, one-off scripts in tools/, tests in tests/, fixtures in mock/, "
        "labels in groundtruth/ and committed results in findings/. Add a new top-level folder to TOP_LEVEL_DIRS, "
        "or a new top-level file to TOP_LEVEL_FILES, in tests/test_layout.py only when none of these fits."
    )


def test_misplaced_names_files_outside_the_known_folders():
    assert misplaced(["orbit_watch/detect.py", "README.md", "scripts/run.py", "notes.txt", "mock/x.tle"]) == [
        "notes.txt", "scripts/run.py"]
