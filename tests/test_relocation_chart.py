import importlib.util
from datetime import date
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "tools" / "relocation_chart.py"
_spec = importlib.util.spec_from_file_location("relocation_chart", _PATH)
chart = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chart)


def row(norad, kind, day, lon_before, lon_after, size="0.0"):
    return {"norad_id": norad, "event_type": kind, "date": day, "lon_before": lon_before, "lon_after": lon_after,
            "size": size}


def test_a_move_inside_the_chart_is_one_line():
    assert chart.pieces(date(2022, 1, 1), 10.0, date(2022, 1, 11), 10.0) == [
        ((date(2022, 1, 1), date(2022, 1, 11)), (10.0, 20.0))]


def test_a_move_across_180_is_split_at_the_edge():
    (first, second) = chart.pieces(date(2022, 1, 1), 170.0, date(2022, 1, 21), 20.0)
    assert first == ((date(2022, 1, 1), date(2022, 1, 11)), (170.0, 180.0))
    assert second == ((date(2022, 1, 11), date(2022, 1, 21)), (-180.0, -170.0))
    (first, second) = chart.pieces(date(2022, 1, 1), -175.0, date(2022, 1, 11), -10.0)
    assert first[1] == (-175.0, -180.0) and second[1] == (180.0, 175.0)
    (first, second) = chart.pieces(date(2022, 1, 1), -100.0, date(2022, 8, 29), -240.0)
    assert first == ((date(2022, 1, 1), date(2022, 3, 22)), (-100.0, -180.0))
    assert second == ((date(2022, 3, 22), date(2022, 8, 29)), (180.0, 20.0))


def test_a_move_goes_the_way_its_drift_points_when_the_drift_covers_more_than_half_the_belt():
    assert round(chart.arc(89.5, -109.2, 73.6, 215), 6) == -198.7
    assert round(chart.arc(-91.1, 89.5, -591.0, 34), 6) == 180.6
    assert round(chart.arc(-102.6, 20.9, 79.7, 239), 6) == -236.5


def test_a_drift_too_slow_to_reach_the_long_way_keeps_the_short_way():
    assert round(chart.arc(119.4, 127.5, 4.5, 87), 6) == 8.1
    assert chart.arc(10.0, 30.0, 0.0, 20) == 20.0
    assert round(chart.arc(89.5, -109.2, -73.6, 215), 6) == 161.3


def test_moves_pair_starts_with_ends_and_keep_unpaired_starts_and_arrivals():
    rows = [
        row("1", "relocation_start", "2022-01-01", "10.0", "30.0", "-80.0"),
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


def test_moves_draw_a_westward_drift_the_long_way():
    rows = [
        row("5", "relocation_start", "2021-08-05", "90.0", "-110.0", "73.6"),
        row("5", "relocation_end", "2022-03-08", "-108.0", "-110.0"),
    ]
    segments, _, _ = chart.moves(rows)
    assert segments == [((date(2021, 8, 5), date(2022, 3, 8)), (90.0, -110.0))]
