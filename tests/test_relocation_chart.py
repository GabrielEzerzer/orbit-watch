import importlib.util
from datetime import date
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "tools" / "relocation_chart.py"
_spec = importlib.util.spec_from_file_location("relocation_chart", _PATH)
chart = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chart)


def row(norad, kind, day, lon_before, lon_after):
    return {"norad_id": norad, "event_type": kind, "date": day, "lon_before": lon_before, "lon_after": lon_after}


def test_a_move_inside_the_chart_is_one_line():
    assert chart.pieces(date(2022, 1, 1), 10.0, date(2022, 1, 11), 20.0) == [
        ((date(2022, 1, 1), date(2022, 1, 11)), (10.0, 20.0))]


def test_a_move_across_180_is_split_at_the_edge_and_goes_the_short_way():
    (first, second) = chart.pieces(date(2022, 1, 1), 170.0, date(2022, 1, 21), -170.0)
    assert first == ((date(2022, 1, 1), date(2022, 1, 11)), (170.0, 180.0))
    assert second == ((date(2022, 1, 11), date(2022, 1, 21)), (-180.0, -170.0))
    (first, second) = chart.pieces(date(2022, 1, 1), -175.0, date(2022, 1, 11), 175.0)
    assert first[1] == (-175.0, -180.0) and second[1] == (180.0, 175.0)


def test_moves_pair_starts_with_ends_and_keep_unpaired_starts_and_arrivals():
    rows = [
        row("1", "relocation_start", "2022-01-01", "10.0", "30.0"),
        row("1", "relocation_end", "2022-01-21", "28.0", "30.0"),
        row("2", "relocation_end", "2023-05-01", "", "-60.0"),
        row("3", "relocation_start", "2022-06-01", "100.0", "140.0"),
        row("3", "graveyard", "2022-09-01", "120.0", "140.0"),
        row("4", "relocation_start", "2025-12-01", "-20.0", "-25.0"),
    ]
    segments, arrivals, graveyards = chart.moves(rows)
    assert segments == [
        ((date(2022, 1, 1), date(2022, 1, 21)), (10.0, 30.0)),
        ((date(2022, 6, 1), date(2022, 9, 1)), (100.0, 120.0)),
        ((date(2025, 12, 1), chart.DATA_END), (-20.0, -25.0)),
    ]
    assert arrivals == [(date(2023, 5, 1), -60.0)]
    assert graveyards == [(date(2022, 9, 1), 120.0)]
