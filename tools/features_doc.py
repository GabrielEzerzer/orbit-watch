# Write docs/features.md, the public feature map, from features.json, grouped by kind.

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FEATURES = ROOT / "features.json"
OUT = ROOT / "docs" / "features.md"
GROUPS = (("job", "Data jobs"), ("analysis", "Analyses"), ("eval", "Evaluations"), ("tool", "Tools"))


def render(features: list[dict]) -> str:
    kinds = {k for k, _ in GROUPS}
    unknown = sorted({f["kind"] for f in features} - kinds)
    if unknown:
        raise ValueError(f"features.json has kinds with no group in tools/features_doc.py: {unknown}")
    lines = ["# Features", "",
             "Every command in the repo: what it does, how to run it, what it reads and what it writes. "
             "Generated from `features.json` by `python tools/features_doc.py`; do not edit by hand.", "",
             "Upper-case words in a command are placeholders. `$ORBIT_WATCH_DATA` is the data folder "
             "(see [method.md](method.md#data-and-downloads)).", ""]
    lines += [f"- [{title}](#{title.lower().replace(' ', '-')})" for _, title in GROUPS]
    for kind, title in GROUPS:
        lines += ["", f"## {title}"]
        for f in (f for f in features if f["kind"] == kind):
            lines += ["", f"### {f['name']}", "", f["description"], "", "```", f["command"], "```", "", "Reads:", ""]
            lines += [f"- {x}" for x in f["inputs"]]
            lines += ["", "Writes:", ""]
            lines += [f"- {x}" for x in f["outputs"]]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Write docs/features.md from features.json.")
    p.parse_args(argv)
    features = json.loads(FEATURES.read_text(encoding="utf-8"))["features"]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(features), encoding="utf-8", newline="\n")
    print(f"{OUT.relative_to(ROOT).as_posix()}: {len(features)} features")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
