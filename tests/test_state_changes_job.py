import csv
from datetime import datetime, timezone

from orbit_watch.events import ROW_FIELDS, Event
from orbit_watch.jobs import state_changes as job


def event(kind, year, norad=1):
    t = datetime(year, 6, 1, tzinfo=timezone.utc)
    return Event(norad, kind, t, "rate_exit", 1.0, 10.0, 20.0, "controlled_lon", "drifting", t)


def test_counts_cover_every_type_and_year():
    c = job.counts([event("graveyard", 2022), event("graveyard", 2022), event("free_burn", 2025)])
    assert c["graveyard"]["2022"] == 2 and c["free_burn"]["2025"] == 1 and c["relocation_end"]["2021"] == 0
    assert set(c) == set(job.EVENT_TYPES) and all(len(v) == 5 for v in c.values())


def test_events_csv_has_one_row_per_event(tmp_path):
    size = job.write_events([event("keeping_stop", 2023), event("relocation_start", 2024, 2)], tmp_path / "e.csv")
    with open(tmp_path / "e.csv", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert size > 0 and list(rows[0]) == ROW_FIELDS
    assert [(r["norad_id"], r["event_type"], r["date"]) for r in rows] == [
        ("1", "keeping_stop", "2023-06-01"), ("2", "relocation_start", "2024-06-01")]
