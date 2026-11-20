import importlib.util
from datetime import date
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "tools" / "stops_chart.py"
_spec = importlib.util.spec_from_file_location("stops_chart", _PATH)
chart = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(chart)


def row(norad, kind, day, lon_before, lon_after):
    return {"norad_id": norad, "event_type": kind, "date": day, "lon_before": lon_before, "lon_after": lon_after}


def test_stops_run_from_arrival_to_departure_with_flags_moves_and_graveyards():
    a, b = chart.OBJECTS
    events = [
        row(a, "relocation_end", "2021-03-01", "-3.0", "-8.0"),
        row(a, "relocation_start", "2021-04-01", "-8.0", "45.0"),
        row(a, "relocation_end", "2021-05-01", "41.0", "45.0"),
        row(a, "ns_keeping_stop", "2021-06-01", "45.0", "45.0"),
        row(a, "graveyard", "2021-08-01", "45.0", "119.0"),
        row(b, "relocation_start", "2023-05-02", "58.0", "8.9"),
        row(b, "relocation_end", "2023-05-22", "12.3", "8.9"),
        row("1", "relocation_end", "2022-01-01", "0.0", "1.0"),
    ]
    flags = [{"norad_id": a, "date": "2021-03-01", "other_name": "SAT X", "other_owner": "ABC"}]
    found, moves, graveyards = chart.stops(events, flags)
    assert found == [
        {"norad_id": a, "start": date(2021, 3, 1), "end": date(2021, 4, 1), "lon": -8.0, "neighbour": "SAT X (ABC)"},
        {"norad_id": a, "start": date(2021, 5, 1), "end": date(2021, 8, 1), "lon": 45.0, "neighbour": None},
        {"norad_id": b, "start": chart.CHART_START, "end": date(2023, 5, 2), "lon": 58.0, "neighbour": None},
        {"norad_id": b, "start": date(2023, 5, 22), "end": chart.CHART_END, "lon": 8.9, "neighbour": None},
    ]
    assert moves == [(a, date(2021, 4, 1), -8.0, date(2021, 5, 1), 45.0),
                     (b, date(2023, 5, 2), 58.0, date(2023, 5, 22), 8.9)]
    assert graveyards == [(a, date(2021, 8, 1), 45.0)]
