import importlib.util
from pathlib import Path

import pytest

_PATH = Path(__file__).resolve().parents[1] / "tools" / "fetch_truth_tles.py"
_spec = importlib.util.spec_from_file_location("fetch_truth_tles", _PATH)
fetch = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fetch)


class FakeSource:
    made: list

    def __init__(self, start, end, cache_dir):
        self.start, self.end, self.cache_dir, self.calls = start, end, cache_dir, []

    @classmethod
    def from_env(cls, start, end, cache_dir=None, limiter=None):
        cls.made.append(cls(start, end, cache_dir))
        return cls.made[-1]

    def history(self, norad):
        self.calls.append(norad)
        (self.cache_dir / f"gp_history-{norad}-{self.start}--{self.end}.json").write_text("[]", encoding="utf-8")
        return []


@pytest.fixture
def made(monkeypatch):
    monkeypatch.setattr(FakeSource, "made", [], raising=False)
    monkeypatch.setattr(fetch, "SpaceTrackSource", FakeSource)
    return FakeSource.made


def test_fetches_only_objects_not_previously_scored_over_2021_2025(made, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(fetch, "load_splits", lambda: {
        1: {"name": "old", "previously_scored": True},
        2: {"name": "new", "previously_scored": False},
        3: {"name": "newer", "previously_scored": False},
    })
    assert fetch.main(["--cache-dir", str(tmp_path)]) == 0
    (source,) = made
    assert source.calls == [2, 3]
    assert [str(d) for d in (source.start, source.end)] == ["2021-01-01", "2026-01-01"]
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "gp_history-2-2021-01-01--2026-01-01.json", "gp_history-3-2021-01-01--2026-01-01.json"]
    assert "2 new: 0 element sets" in capsys.readouterr().out


def test_stops_without_credentials(monkeypatch, tmp_path):
    monkeypatch.delenv("SPACETRACK_USER", raising=False)
    monkeypatch.delenv("SPACETRACK_PASSWORD", raising=False)
    assert fetch.main(["--cache-dir", str(tmp_path)]) == 2
