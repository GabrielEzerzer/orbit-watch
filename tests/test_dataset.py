from collections import Counter
from pathlib import Path

import numpy as np

from orbit_watch.charts import label_rows, lon_range, recentre
from orbit_watch.jobs import dataset as ds
from orbit_watch.truth import read_event_rows

ROOT = Path(__file__).resolve().parents[1]
FINDINGS = ROOT / "findings"
OUT = ROOT / "dataset"


def built():
    return ds.build(FINDINGS, ds.catalogue_from_objects(OUT / "objects.csv"))


def committed(name: str) -> str:
    return (OUT / name).read_text(encoding="utf-8")


def test_committed_dataset_matches_what_the_job_writes_from_findings():
    events, objects = built()
    hint = "dataset/ is out of date with findings/; run python -m orbit_watch.jobs.dataset"
    assert committed("events.csv") == ds.csv_text(ds.EVENT_FIELDS, events), hint
    assert committed("objects.csv") == ds.csv_text(ds.OBJECT_FIELDS, objects), hint
    assert committed("README.md") == ds.card(FINDINGS, events, objects), hint
    assert committed("evidence/README.md") == ds.evidence(FINDINGS, events, objects), hint


def test_every_state_change_appears_once_and_every_departure_finds_its_score():
    events, objects = built()
    source = read_event_rows(FINDINGS / "state_changes" / "events.csv")[1]
    departures = read_event_rows(FINDINGS / "routine" / "departures.csv")[1]
    flagged = read_event_rows(FINDINGS / "routine" / "flagged_arrivals.csv")[1]
    rank = read_event_rows(FINDINGS / "routine" / "rank.csv")[1]
    unrated = read_event_rows(FINDINGS / "routine" / "unrated.csv")[1]
    keys = Counter(ds.key(e) for e in events)
    assert len(events) == len(source)
    assert keys == Counter(ds.key(e) for e in source)
    assert max(keys.values()) == 1
    scored = {ds.key(e): e for e in events if e["scored"] != ""}
    assert len(scored) == len(departures)
    for d in departures:
        assert all(scored[ds.key(d)][k] == d[k] for k in ds.SCORE_FIELDS)
    assert sum(e["proximity_flag"] == "1" for e in events) == len(flagged)
    assert len(objects) == len(rank) + len(unrated)
    assert [o["norad_id"] for o in objects if o["rated"] == 1] == [int(r["norad_id"]) for r in rank]
    assert sum(o["state_changes"] for o in objects) == len(source)


def test_longitude_axis_covers_holds_and_listed_longitudes_but_not_the_transfer():
    days = np.arange(10.0)
    lon = np.array([100.0, 60.0, 20.0, 10.0, 10.1, 10.0, 9.9, 9.5, 9.4, 9.5])
    lo, hi = lon_range(days, lon, [{"lon_before": "10.0", "lon_after": "9.45"}], [(3.0, 6.0), (7.0, 10.0)])
    assert lo == 9.4 - 0.25 and hi == 10.1 + 0.25
    lo, hi = lon_range(days, np.array([175.0] * 5 + [-178.0] * 5), [], [(0.0, 10.0)])
    assert np.allclose([lo, hi], [175.0 - 0.56, 182.0 + 0.56])
    assert np.allclose(recentre(np.array([175.0, -178.0, -10.0]), lo, hi), [175.0, 182.0, 350.0])
    spread = np.array([-170.0, -60.0, 50.0, 160.0] * 2 + [0.0, 0.0])
    assert lon_range(days, spread, [], [(0.0, 10.0)]) == (-180.0, 180.0)


def test_close_event_labels_move_to_a_new_row():
    assert label_rows([0.0, 10.0, 20.0, 100.0, 105.0]) == [0, 1, 2, 0, 1]
