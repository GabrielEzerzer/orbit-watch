# features.json lists every command a user can run: each job, tool, harness eval and module entry point.
# Each mapped command must exist and answer --help, and each mapped test file must exist.

import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FEATURES = json.loads((ROOT / "features.json").read_text(encoding="utf-8"))["features"]
FIELDS = ("name", "kind", "description", "command", "inputs", "outputs", "test")
_spec = importlib.util.spec_from_file_location("features_doc", ROOT / "tools" / "features_doc.py")
features_doc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(features_doc)


def target(command: str) -> tuple[str, list[str]]:
    words = command.split()
    assert words[0] == "python", command
    if words[1] == "-m":
        name, rest, run = words[2], words[3:], ["-m", words[2]]
    else:
        name, rest, run = words[1], words[2:], [words[1]]
    while rest and re.fullmatch(r"[a-z][a-z_]*", rest[0]):
        run.append(rest.pop(0))
    return name, run + ["--help"]


def entry_points() -> set[str]:
    found = {f"orbit_watch.jobs.{p.stem}" for p in (ROOT / "orbit_watch" / "jobs").glob("*.py")}
    found |= {f"harness.evals.{p.stem}" for p in (ROOT / "harness" / "evals").glob("*.py")}
    found |= {f"tools/{p.name}" for p in (ROOT / "tools").glob("*.py")}
    found |= {f"orbit_watch.{p.stem}" for p in (ROOT / "orbit_watch").glob("*.py")
              if 'if __name__ == "__main__":' in p.read_text(encoding="utf-8")}
    return {f for f in found if not f.endswith("__init__")}


def test_every_entry_has_every_field_and_a_unique_name():
    assert all(all(f.get(k) for k in FIELDS) for f in FEATURES), [f.get("name") for f in FEATURES]
    names = [f["name"] for f in FEATURES]
    assert len(names) == len(set(names))


def test_docs_features_md_matches_features_json():
    committed = (ROOT / "docs" / "features.md").read_text(encoding="utf-8")
    assert committed == features_doc.render(FEATURES), (
        "docs/features.md is out of date with features.json; run python tools/features_doc.py")


def test_every_job_tool_eval_and_entry_point_is_mapped():
    mapped = {target(f["command"])[0] for f in FEATURES}
    assert entry_points() - mapped == set()


@pytest.mark.parametrize("feature", FEATURES, ids=[f["name"] for f in FEATURES])
def test_mapped_command_exists_and_answers_help(feature):
    name, run = target(feature["command"])
    if name.endswith(".py"):
        assert (ROOT / name).is_file(), name
    else:
        assert importlib.util.find_spec(name) is not None, name
    env = {k: v for k, v in os.environ.items() if not k.startswith("SPACETRACK_")}
    env.update(PYTHONPATH=str(ROOT), HTTP_PROXY="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9",
               NO_PROXY="", http_proxy="http://127.0.0.1:9", https_proxy="http://127.0.0.1:9", no_proxy="")
    done = subprocess.run([sys.executable, *run], cwd=ROOT, env=env, capture_output=True, text=True,
                          timeout=60)
    assert done.returncode == 0, done.stderr[-2000:]
    assert "usage:" in done.stdout


@pytest.mark.parametrize("feature", FEATURES, ids=[f["name"] for f in FEATURES])
def test_mapped_test_file_exists(feature):
    assert (ROOT / feature["test"]).is_file(), feature["test"]
