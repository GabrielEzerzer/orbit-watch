import importlib.util
import json
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "tools" / "truth_table.py"
_spec = importlib.util.spec_from_file_location("truth_table", _PATH)
truth_table = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(truth_table)


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def test_burns_count_only_this_object_in_2021_2025(monkeypatch, tmp_path):
    monkeypatch.setattr(truth_table, "GROUNDTRUTH", tmp_path)
    write(tmp_path / "shared.csv", "norad_id,start_utc\n"
          "100,2020-12-31T23:00\n100,2021-01-01T00:00\n100,2025-12-31T23:59\n100,2026-01-01T00:00\n200,2022-05-01T00:00\n")
    write(tmp_path / "own.csv", "date_utc\n2023-03-03\n2019-01-01\n")
    assert truth_table.burns_2021_2025(100, ["shared.csv"]) == 2
    assert truth_table.burns_2021_2025(200, ["shared.csv"]) == 1
    assert truth_table.burns_2021_2025(100, ["shared.csv", "own.csv"]) == 3


def test_table_rows_are_sorted_and_count_cached_element_sets(monkeypatch, tmp_path):
    monkeypatch.setattr(truth_table, "GROUNDTRUTH", tmp_path)
    write(tmp_path / "log.csv", "norad_id,start_utc\n1,2022-01-01\n2,2022-01-01\n2,2023-01-01\n")
    monkeypatch.setattr(truth_table, "load_splits", lambda: {
        2: {"name": "B", "regime": "GEO", "split": "train", "truth_files": ["log.csv"]},
        1: {"name": "A", "regime": "LEO", "split": "holdout", "truth_files": ["log.csv"]},
        3: {"name": "C", "regime": "GEO", "split": "holdout", "truth_files": []},
    })
    tle_dir = tmp_path / "tles"
    tle_dir.mkdir()
    write(tle_dir / f"gp_history-3-{truth_table.SPAN}.json", json.dumps([{}, {}, {}]))
    rows = [line for line in truth_table.table(tle_dir).splitlines() if line.startswith("| ") and line[2].isdigit()]
    assert rows == [
        "| 3 | C | GEO | holdout | 0 | 3 |",
        "| 1 | A | LEO | holdout | 1 | not cached |",
        "| 2 | B | GEO | train | 2 | not cached |",
    ]
