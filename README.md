# Orbit watch

Change-point detection on public satellite orbital-element history (TLE/GP data) to find
unannounced manoeuvres. It parses element sets, propagates them with SGP4, detects steps in the
mean semi-major axis and the inclination vector, scores the detector against cited manoeuvre
logs, and labels the operating mode of every object in the GEO region. Built out of interest.

**Goal.** A dataset of off-routine GEO manoeuvres in 2021-2025 for the whole belt, and a ranking
of the objects that have no real routine. The unit of the dataset is a change of station-keeping
state: a relocation, the start or end of station keeping, the end of north-south keeping, or a
burn by an object that otherwise drifts. Changes come from the per-window operating modes of
`orbit_watch.modes`, and the step detector dates each one to the day. This is not built yet;
"Detector state and gates" says what the detector does now and what it must pass. Objects outside
the GEO region are out of scope, apart from the ISS, which stays as a regression bench.

Results and leads are in `FINDINGS.md` and `findings/`. Ground-truth sources, caveats and the
train/holdout split are in `groundtruth/README.md`. This file says what exists, how to run it and
where the numbers are; "Method notes" at the end gives the rules, thresholds and sources the code
does not state.

## Setup and tests

```
python -m venv .venv
.venv/Scripts/python -m pip install -e .[dev]   # .venv/bin/python on Linux/macOS
.venv/Scripts/python -m pytest -q
```

Tests never touch the network: every loader takes its fetch function or HTTP session as an
argument, and the tests pass fakes. Fixtures live in `mock/`; `mock/README.md` says where each came
from.

## Modules

| Module | What it does |
|---|---|
| `orbit_watch.elements` | Parses TLEs (2- and 3-line, checksums checked) and GP records (JSON, CSV) into one `ElementSet` |
| `orbit_watch.series` | `to_series`: an epoch-sorted `ElementSeries` per object; epochs under 60 s apart collapse to the later one; refuses holdout objects unless `final=True` |
| `orbit_watch.propagate` | TEME position and velocity through `sgp4`; raises `PropagationError` on SGP4 error codes |
| `orbit_watch.sources`, `celestrak`, `spacetrack` | `ElementSource` implementations: a local directory, CelesTrak current GP, Space-Track `gp_history` |
| `orbit_watch.detect` | The step detector: Theil-Sen detrend per side, median step, robust `z`, optional inclination-vector channel |
| `orbit_watch.calibrate` | Chooses and scores the ISS setting against the NASA (and Roscosmos) lists |
| `orbit_watch.holdout` | Scores the frozen setting on Space-Track ISS history, plus leave-one-year-out CV |
| `orbit_watch.inject` | Synthetic injection-recovery on the real ISS series |
| `orbit_watch.manoeuvre_logs`, `truth` | Build the QZSS and Fengyun label CSVs; the only reader of label files, with the holdout guard |
| `orbit_watch.generalise` | Scores the ISS setting and a GEO tune on the QZSS (GEO) logs |
| `orbit_watch.geo` | Sub-satellite longitude |
| `orbit_watch.modes` | ESA operating mode of a GEO-region object per 30-day window |
| `orbit_watch.clean` | Drops snap-back blocks: runs of element sets whose semi-major axis or inclination vector jumps away and returns while the longitude does not |
| `orbit_watch.events` | Dated station-keeping state changes of a GEO-region object, one per change, with the signal that dated it |
| `orbit_watch.jobs.*` | Long jobs: `extract_tle_archive`, `geo_belt`, `geo_modes`, `state_changes` |
| `harness.evals.detector` | The frozen per-regime evaluation; nothing in `orbit_watch` imports `harness` |

## Data

Data lives outside the repo, in the folder named by the `ORBIT_WATCH_DATA` environment variable
(written `$ORBIT_WATCH_DATA` below). The fetchers, the tools and the eval read it from there and stop
with a message naming the variable when it is unset; the jobs take their folders as arguments. The
tests need no data.

| Path | Contents | Made by |
|---|---|---|
| `$ORBIT_WATCH_DATA/archive/<norad>.tle` | OndroNR/tle-archive history, 2021-01-01 to 2023-12-28 | `jobs.extract_tle_archive` |
| `$ORBIT_WATCH_DATA/spacetrack/` | Space-Track `gp_history` and SATCAT answers, kept for good | `SpaceTrackSource`, `tools/fetch_truth_tles.py`, `geo_belt satcat` |
| `$ORBIT_WATCH_DATA/geo/` | `<norad>.tle` and `manifest.json` for every GEO-region object, 2021-2025 | `jobs.geo_belt` |
| `$ORBIT_WATCH_DATA/geo_modes/segments.csv` | One row per mode segment | `jobs.geo_modes` |
| `$ORBIT_WATCH_DATA/state_changes/events.csv` | One row per dated state change | `jobs.state_changes` |
| `$ORBIT_WATCH_DATA/sources/{qzss,fengyun}/` | Operator manoeuvre logs as published (QZSS, Fengyun) | downloaded by hand |
| `$ORBIT_WATCH_DATA/celestrak/<UTC date>/` | CelesTrak downloads, cached per UTC day | `celestrak` |

Download rules:

- **CelesTrak** blocks clients that download the same data again and again. A query already
  cached today is read from disk; a response is cached only after it parses, and any non-200
  answer raises. Requests send the User-Agent `orbit-watch/0.1 (research prototype)`.
- **Space-Track** is off unless the environment variables `SPACETRACK_USER` and
  `SPACETRACK_PASSWORD` hold a Space-Track account's login; set them before running anything that
  uses it. It keeps under 30 requests a minute and 300 an hour. Space-Track allows each object's `gp_history`
  to be downloaded once, so every answer under `$ORBIT_WATCH_DATA/spacetrack/` is kept with no expiry and never
  fetched again. Keep that folder. SATCAT is one full-catalogue query (Space-Track allows it once a
  day and asks for combined queries, not one per object), kept the same way; delete
  `$ORBIT_WATCH_DATA/spacetrack/satcat-<fields>.json` to fetch a newer one.

## Running each job and tool

| Job | Command | Output |
|---|---|---|
| ISS calibration (tune on 2021-2022, score 2023) | `python -m orbit_watch.calibrate --tle $ORBIT_WATCH_DATA/archive/25544.tle --truth groundtruth/iss_manoeuvres.csv --out <dir>` | `calibration.json`, `detections.csv`, `events_scored.csv`, `iss_sma.png` |
| ISS, frozen setting, both truth lists | `python -m orbit_watch.calibrate --frozen --tle $ORBIT_WATCH_DATA/archive/25544.tle --truth groundtruth/iss_manoeuvres.csv groundtruth/iss_roscosmos_manoeuvres.csv --out findings/combined_truth` | `findings/combined_truth/` |
| ISS holdout 2024-2025 and CV | `python -m orbit_watch.holdout --gp $ORBIT_WATCH_DATA/spacetrack/gp_history-25544-2021-01-01--2026-01-01.json --archive $ORBIT_WATCH_DATA/archive/25544.tle --truth groundtruth/iss_manoeuvres.csv --out findings` | `findings/holdout_2024_2025/`, `findings/cv_2021_2025/` |
| ISS holdout, both truth lists | the same with `--truth groundtruth/iss_manoeuvres.csv groundtruth/iss_roscosmos_manoeuvres.csv --out findings/combined_truth_holdout` | `findings/combined_truth_holdout/` |
| Injection-recovery | `python -m orbit_watch.inject --spacetrack $ORBIT_WATCH_DATA/spacetrack/gp_history-25544-2021-01-01--2026-01-01.json --truth groundtruth/iss_manoeuvres.csv groundtruth/iss_roscosmos_manoeuvres.csv --out findings/injection` | `findings/injection/` |
| Label CSVs from operator logs | `python -m orbit_watch.manoeuvre_logs --qzss-dir $ORBIT_WATCH_DATA/sources/qzss --fengyun-dir $ORBIT_WATCH_DATA/sources/fengyun --out groundtruth` | `groundtruth/*_manoeuvres.csv` |
| Generalisation (QZSS GEO) | `python -m orbit_watch.generalise --truth-dir groundtruth --tle-dir $ORBIT_WATCH_DATA/spacetrack --out findings/generalise` | `findings/generalise/` |
| Frozen per-regime eval | `python -m harness.evals.detector --split dev [--settings harness/evals/settings/inc-vector.json]` | `harness/evals/results/<split>-<settings>.json` |
| TLE archive extraction (about 5 min, a 2 GB clone) | `python -m orbit_watch.jobs.extract_tle_archive --out $ORBIT_WATCH_DATA/archive --norad 25544` | `<norad>.tle`, `manifest.json` |
| GEO-region history (about 16 min) | see "Every object in the GEO region" | `$ORBIT_WATCH_DATA/geo/` |
| GEO operating modes (about 2 min) | `python -m orbit_watch.jobs.geo_modes --geo-dir $ORBIT_WATCH_DATA/geo --out $ORBIT_WATCH_DATA/geo_modes` | `$ORBIT_WATCH_DATA/geo_modes/segments.csv`, `findings/geo_modes/` |
| GEO state changes (about 4 min) | `python -m orbit_watch.jobs.state_changes` | `$ORBIT_WATCH_DATA/state_changes/events.csv`, `findings/state_changes/` |
| GEO state changes evaluation | `python -m harness.evals.state_changes [--split dev\|all]` | `findings/state_changes/eval_<split>.json` and `.csv` |

Tools:

- `python tools/fetch_truth_tles.py` (needs the Space-Track variables): Space-Track history for the objects added with `groundtruth/splits.json`, holdout objects included: fetching their element sets is allowed, running the detector on them is not.
- `python tools/truth_table.py`: regenerates `groundtruth/objects.md`.
- `pdftotext -layout -enc UTF-8 Classification_of_Geosynchronous_Objects_I21R0.pdf i21.txt`, then `python tools/esa_classification.py i21.txt $ORBIT_WATCH_DATA/geo_modes/segments.csv`: ESA's 2019 per-object classes beside our first 2021 mode, as a Markdown table.

## Results

### ISS regression bench (`FINDINGS.md`, `findings/`)

The ISS is the regression bench: every detector change must keep these numbers, and the ISS
setting is not tuned further. Frozen setting: `k = 4`, `|z| >= 12`, `|step| >= 200 m`, non-maximum suppression over 1 day,
chosen by F1 on 2021-2022 only. An event matches a detection when its time overlaps the
detection's interval widened by 0.5 day, one to one. Both burn lists are lower bounds, so an
unmatched detection is a lead, not a false alarm proven.

| Source, period | NASA list: precision | recall | NASA + Roscosmos: precision | recall |
|---|---|---|---|---|
| Archive 2021-2022 (tuning) | 24/27 | 24/25 | 26/27 | 26/27 |
| Archive 2023 | 16/21 | 16/17 | 20/21 | 20/21 |
| Space-Track 2021-2022 | 23/26 | 23/25 | 25/26 | 25/27 |
| Space-Track 2023 | 16/22 | 16/17 | 20/22 | 20/21 |
| **Space-Track 2024-2025 (clean holdout)** | 27/42 | 27/27 | **35/42 = 0.83** | **35/35 = 1.00** |

- 2023 is unseen by the thresholds but not by the method: an earlier detector (least-squares
  lines, sign-blind matching) was scored on it once, precision 16/23 and recall 16/17, before it
  was replaced. 2024-2025 is the clean holdout.
- Space-Track loses one archive event in 2021-2022, the 2021-12-03 retrograde debris avoidance:
  two transitional element sets that the archive lacks pull the measured step from −461 m to
  about −210 m, and `z` below 12.
- Leave-one-year-out CV over 2021-2025 on Space-Track (NASA list): precision 64/86 = 0.74,
  recall 64/69 = 0.93 (`findings/cv_2021_2025/`). It was not rerun with the Roscosmos list,
  because it re-chooses the setting.
- Unmatched detections, with the Roscosmos match for each, are listed in `FINDINGS.md`.

**Sensitivity** (`findings/injection/`, synthetic steps in quiet stretches, 600 trials per size):

| Recall at step size | 100 m | 150 m | 200 m | 300 m | 500 m | 1 km |
|---|---|---|---|---|---|---|
| native cadence (about 5.6 TLEs a day), frozen | 0.01 | 0.01 | 0.52 | 0.98 | 1.00 | 1.00 |
| native, `|z| >= 6`, `|step| >= 50 m` | 0.95 | 0.98 | 0.98 | 1.00 | 1.00 | 1.00 |
| thinned to about 1 a day, frozen | 0.01 | 0.06 | 0.48 | 0.92 | 0.97 | 1.00 |
| thinned to about 1 every 2 days, frozen | 0.02 | 0.07 | 0.34 | 0.72 | 0.89 | 0.98 |

The 200 m floor, not `z`, sets what the frozen setting sees. The looser setting gives about 19 to
21 false alarms a year against at most 0.9 for the frozen one. A clean step leaves out a real
burn's transitional TLEs, so these recalls are upper bounds.

### Beyond the ISS: QZSS (GEO)

`findings/generalise/`, on QZS-3 and QZS-6; chance recall comes from the logs shifted by 7, 13 and
19 days either way.

| Setting | Precision | Recall |
|---|---|---|
| Frozen ISS setting, whole history | 179/253 = 0.71 | 179/232 = 0.77 (chance about 0.10) |
| GEO tune (k=4, z>=3, step>=1000 m), later part (not blind) | 70/92 | 70/93 |

The ISS setting carries over to GEO east-west burns (about 3 km in `a`). The tuned later part is
not a blind holdout: four method changes (the 2-day late tolerance, the 60 s epoch collapse,
merging burns under 12 h apart and the `|z|` grid beyond 30) came after it was first scored
(`test_part_not_blind` in `report.json`). The unmatched QZS-3 and QZS-6 detections have not been
checked against anything else.

### Detector evaluation (`harness/evals/`)

`harness/evals/split.json` fixes `train` (train objects of `groundtruth/splits.json`, 2021-2023),
`dev` (the same objects, 2024-2025) and `test` (holdout objects, 2021-2025, refused without
`--final`). The settings JSON gives the detector setting per regime (ISS, GEO, IGSO). Its
coverage, matching and counting rules are fixed in `harness/evals/detector.py`, so no detector
change can move them. Label files are read only through `orbit_watch.truth.read_label_rows` and
series built only through `to_series`, both of which refuse holdout objects unless
`final=True`; that is a code-path guard against tuning on the holdout by accident, not a wall.

#### Detector state and gates

The kept setting is `harness/evals/settings/inc-vector.json`: the ISS setting in every regime,
plus the inclination channel on GEO, which scores the step of the inclination vector
(i cos RAAN, i sin RAAN) with `inc_z_min` 30 and `inc_step_min_deg` 0.02.

The detector is no longer tuned burn by burn against these scores. The evaluation's GEO labels are the logs of
two QZSS satellites (QZS-3 and QZS-6), which are kept far more cleanly than most of the belt, so a
better score here says little about the belt the dataset covers. A detector change now has to pass
these gates instead:

| Gate | Status |
|---|---|
| Guardrail: GEO east-west recall >= 0.9 | met: train 36/39 = 0.923, dev 33/34 = 0.971 |
| Guardrail: ISS recall >= 0.95 | dev 35/35 = 1.000 met; train 45/48 = 0.938 not met |
| At most 0.2 false events per object-year, counted on state-change events | met: 0 events over 5.412 object-years of QZS-3 and QZS-6 log coverage |
| Recall and dating error on a cited list of known GEO events | dated state changes: dev 13/13, median date error 2 days; test 17/20, median 3 days (scored once). The mode layer alone: 26/33, median 11.5 days |
| A hand audit of about 50 events from across the belt | not done |

GEO north-south recall is reported, not gated: train 6/17 = 0.353, dev 4/14 = 0.286. The
inclination vector's job is to date when north-south keeping stops, not to catch each burn. Scores are in `harness/evals/results/` (`<split>-inc-vector.json`, with
`<split>-frozen.json` as the baseline). At the detection level, GEO has 4 false alarms
(unmatched detections away from any logged burn) over 2.388 object-years on train (1.67 a year)
and 7 over 1.956 on dev (3.58 a year). Another 15 on train and 12 on dev fall in a burn's match
zone and count as duplicates.

The test split has been scored once, at the FROZEN setting (`results/test-frozen.json`), and the
kept setting has never been scored on it.

##### GEO mode events (`harness/evals/mode_events.py`)

Scores the mode layer, not the detector, against `groundtruth/geo_events.csv`: real relocations,
graveyard moves and ends of station keeping, each with a source. For every event it recomputes the
object's segments from `<geo-dir>/<norad>.tle` with the current `orbit_watch.modes`, drops
`undetermined` segments, and looks for a matching mode change (held to free for the end of keeping,
`controlled_lon_inc` to `controlled_lon` for the end of north-south keeping, held to held with
disjoint longitudes as a relocation) within 45 days of the event. Each change matches one event,
closest first, and the date error is the change's date minus the event's. Events on holdout
objects, outside 2021-2025 or on objects missing from the GEO-region set are listed, not scored.
Events are split into `dev` and `test` by the last hex digit of the sha256 of their `event_id`.

```
python -m harness.evals.mode_events [--events groundtruth/geo_events.csv] [--geo-dir DIR] [--out findings/geo_events]
```

It writes `summary.json` (recall and the median and 90th percentile of the absolute date error,
per split and event type) and `events.csv` (one row per event with the matched change and the
object's mode timeline 90 days either side).

Baseline (`findings/geo_events/`, which records the commit it was run at), 33 events on 24 objects:

| split | events | caught | recall | median \|error\| (days) | 90th percentile (days) |
|---|---|---|---|---|---|
| dev | 13 | 11 | 0.85 | 10 | 33 |
| test | 20 | 15 | 0.75 | 14 | 30.8 |
| all | 33 | 26 | 0.79 | 11.5 | 33.5 |

By type over both splits: relocation starts 7 of 8, relocation ends 5 of 8, graveyard moves 12 of
15, ends of keeping 2 of 2. Caught graveyard moves are dated early (median error 22 days, 10 of 12
before the source date), partly because several sources date the end of disposal or the
decommissioning, and partly because a change is dated at the start of its 30-day window. Of the 7
misses, five are on objects the layer reads as drifting on both sides of the event: Luch (Olymp)
in four of its five rows (its short moves in 2021 and its last months in 2025 never hold a 30-day
window), and Express-AM3, already free before its graveyard move, whose climb the layer cannot see
because it does not use the semi-major axis. Astra 3A's keeping ended 58 days before the month its
source gives for disposal, and Express-AM33 has no determined segment after its arrival. The test
split was scored once here; later changes are judged on dev.

### Every object in the GEO region, 2021-2025

`orbit_watch.jobs.geo_belt` collects every element set from 2021 to 2025 of every object that was
in the GEO region (ESA's definition: mean motion 0.9-1.1 rev/day, eccentricity at most 0.2,
inclination at most 70 deg) at any epoch in the period. Space-Track's own yearly bundles are
behind an end-to-end encrypted share, so it reads the yearly bundles of the CC0 Kaggle dataset
`vaibhavpandey12382/historical-tle-datasets`, whose orbital fields match Space-Track's
latest-issued sets on the two objects compared (Fengyun-2H, QZS-4). It reads any local `.txt` or
`.zip` bundle, so Space-Track's zips also work.

```
python -m orbit_watch.jobs.geo_belt build --source https://www.kaggle.com/datasets/vaibhavpandey12382/historical-tle-datasets --bundle '<bundles>/**/tle2021.txt' --bundle '<bundles>/**/tle2022.txt' --bundle '<bundles>/**/tle2023.txt' --bundle '<bundles>/**/tle2024.txt' --bundle '<bundles>/**/tle2025.txt' --out $ORBIT_WATCH_DATA/geo
python -I -m orbit_watch.jobs.geo_belt satcat --out $ORBIT_WATCH_DATA/geo
```

The `satcat` step needs the Space-Track variables. The manifest records the rule, each bundle's
sha256 and per-object counts.

The full run (commit 74a831f, about 16 minutes) read 177,075,602 lines (88,220,159 pairs) and
kept 1,808 objects with 4,957,896 TLEs, 1,804 of them by the rule. The other four were LEO objects
added with `--also` and have since been deleted, so the set holds 1,804 objects and 4,940,529 TLEs. 136
objects have sets outside the region, such as a transfer orbit before arrival. 635,284 lines were
rejected (the ones looked at are 68-character lines of analyst objects, 8xxxx), 785,425 pairs
restated an epoch already held with different lines, and 8 pairs failed `parse_tle`.

**Restated epochs.** The mirror's element set numbers and line 1 checksums differ from
Space-Track's, but the orbital fields match. Against the `gp_history` files of Fengyun-2H (43491)
and QZS-4 (42965), every epoch the mirror holds matches Space-Track's latest-issued set (highest
`GP_ID`) on those fields: 4,220 and 1,851 epochs, including all 390 and 718 epochs Space-Track
issued more than once. So keeping the later record, as `geo_belt` and `series.to_series` do,
matches Space-Track's latest issue. The mirror lacks 2 of 43491's 4,222 epochs.

### Operating modes of GEO-region objects

`orbit_watch.modes` labels each object's mode per 30-day window with ESA's classes (*Classification
of Geosynchronous Objects*, Issue 21.0, 2019): `controlled_lon_inc` (C1), `controlled_lon` (C2),
`drifting` (D), `librating_75E` (L1), `librating_105W` (L2), `librating_both` (L3), `inclined`
(I), `undetermined` (Ind) and `out_of_region`. The thresholds and their sources are in "Method
notes". The job skips objects outside the rule and the 5 holdout objects, so 1,799 objects are
classified. Year-end counts, transitions and the summary are in `findings/geo_modes/`; 1,477
objects keep one mode for the whole period. Known limits are tracked in issues #21, #28, #29,
#30 and #32.

**Against ESA.** No ESA issue for 2021-2025 could be reached, so there is no same-date check. The
table puts ESA's counts for 1 January 2019 (each class's opening sentence in section 4, page
given; the totals match p. 3 and p. 216) beside ours at the end of 2021. It is context, and
nothing was tuned to it.

| class | ESA, 1 Jan 2019 | source | ours, 31 Dec 2021 |
|---|---|---|---|
| C1 | 372 | 4.1, p. 51 | 347 |
| C2 | 150 | 4.2, p. 83 | 146 |
| C4 | 7 | 4.3, p. 96 | (in drifting or librating) |
| D | 831 | 4.4, p. 97 | 876 |
| L1 | 127 | 4.5, p. 167 | 113 |
| L2 | 46 | 4.6, p. 178 | 41 |
| L3 | 22 | 4.7, p. 182 | 18 |
| I | 21 | 4.8, p. 191 | 21 |
| Ind | 2 | 4.9, p. 193 | 35 |
| total | 1,578 | p. 3, p. 216 | 1,597 (1,799 less 190 with no data and 12 out of region) |

The populations differ because ESA classifies everything in DISCOS, including 206 objects from
JSC Vimpel data and 9 from KIAM (p. 216), many of which have no public TLEs; three years of
launches, retirements and re-orbits separate the dates; ESA classifies each object from its whole
history and corrects some by hand (section 4, p. 50), while we label 30-day windows, so a keeper
between cycles or a librator at a turning point can be undetermined; and ESA's C4 objects land in
our drifting or librating classes.

**Per-object check.** A one-off run of `tools/esa_classification.py` on section 3 of the same
report (pp. 10-49) keeps the 1,342 rows that sit on one line with a page reference inside their
class's chapter. Matched by COSPAR id to our first determined mode before 1 July 2021, 1,272
objects have a mode:

| ESA 2019 | objects | same mode in early 2021 | main other modes |
|---|---|---|---|
| C1 | 332 | 279 (84%) | controlled_lon 25, drifting 24 |
| C2 | 117 | 88 (75%) | drifting 22, controlled_lon_inc 4 |
| C4 | 1 | 0 (0%) | controlled_lon_inc 1 |
| D | 675 | 663 (98%) | librating_75E 5, librating_both 2 |
| L1 | 88 | 83 (94%) | drifting 2, controlled_lon_inc 2 |
| L2 | 29 | 28 (97%) | drifting 1 |
| L3 | 14 | 10 (71%) | librating_75E 2, drifting 2 |
| I | 14 | 14 (100%) | |
| Ind | 2 | 0 (0%) | librating_105W 1, drifting 1 |

Controlled satellites that now read as drifting were not checked one by one; retirements and
relocations between the dates would explain them. Seven dead satellites hold still for months
within about half a degree of a stable point and read librating, because one free path fits all
five years of their longitudes: ATS 3 (3029), NATO 2B (4902), SATCOM C5 (13631), GStar 1
(15677), GStar 3 (19483) and ACTS (22796) at 105 deg W, and SIRIO (10294) at 75 deg E, with
swings of 0.2-1.8 deg. ESA lists all seven as L2 or L1; the comparison table counts neither
GStar 1, whose row cites a page outside the L2 chapter, nor ACTS, whose status row has no
class. The two L3 objects we call drifting, Intelsat 804 (25110) and Cosmos 2479 (38101), pass
over the high barrier in 2021-2025.

### Dated state changes (`orbit_watch.events`, `findings/state_changes/`)

The event unit is one change of an object's station-keeping state, dated to the day, with the
signal that dated it and its size. `jobs.state_changes` writes one row per event for every
GEO-region object except the 5 holdout objects: `norad_id`, `event_type`, `date`, `signal`,
`size`, `lon_before`, `lon_after`, `mode_before`, `mode_after` and `mode_change` (the date of the
mode-layer boundary the event came from). The event types are:

| type | what it is | dated by (`signal`) | `size` |
|---|---|---|---|
| `relocation_start` | a held object leaves its slot and is held again later | `rate_exit`: the first set that leaves the held drift band or longitude box and stays out 5 days | rise of the semi-major axis, km (0 when the next mode segment is already held) |
| `relocation_end` | a moving object starts to hold a slot | `rate_entry`: the first set that stays inside the new slot's band | 0 |
| `graveyard` | a held object leaves and its semi-major axis rises at least 150 km, with no later hold | `rate_exit` | rise, km |
| `keeping_stop` | a held object leaves with no climb and no later hold | `burn_gap`: the last east-west burn plus half the burn interval; `rate_exit` when fewer than 3 burns are seen | rise, km |
| `ns_keeping_stop` | `controlled_lon_inc` to `controlled_lon` at the same slot | `mode_change`: the 30-day window boundary | largest inclination after, deg |
| `free_burn` | a semi-major-axis step of at least 1 km by an object that is never held again | `a_step`: the step detector's peak | step, m |

The steps behind it, each measured on the dev split of `groundtruth/geo_events.csv`:

1. **Snap-back blocks** (`orbit_watch.clean`). Runs of up to 10 days where the semi-major axis or
   the inclination vector jumps away and comes back while the mean longitude carries on are
   alternate orbit solutions, not burns. They are about 1.6% of sets on a 100-object sample, and
   on QZS-3 and QZS-6 they caused 6 of the 7 dev false alarms that were not near a logged burn.
   They are dropped before anything else.
2. **Dating from the drift rate.** The mode layer dates a change at a 30-day window boundary; the
   per-set drift rate leaves the held band within a day of a real departure (dev median error 10
   to 6 days).
3. **Short holds.** Inside stretches that are not held, a run of sets with drift at most 0.02
   deg/day inside a 0.3 deg box for at least 10 days, entered by a set moving at 0.05 deg/day or
   more within 5 days, is a hold. This catches stops the windows cannot see, such as SJ-17's
   13-day move in November 2024 and Luch (Olymp)'s stops in 2021 and 2025. The entry burn keeps
   librating objects out (dev recall 11 to 13 of 13, median 6 to 3 days).
4. **Burn gap.** When keeping simply stops, the longitude leaves the box weeks after the last
   burn; the midpoint between the last burn and the one that never came dates it (one dev event,
   14 to 0 days). If the object climbs later, the climb is a second event.

| split | events | caught | median \|error\| (days) | 90th percentile (days) | same type |
|---|---|---|---|---|---|
| dev, mode layer (baseline) | 13 | 11 | 10 | 33 | 9 |
| dev, state changes | 13 | 13 | 2 | 12.4 | 13 |
| test, mode layer (baseline) | 20 | 15 | 14 | 30.8 | 14 |
| test, state changes (scored once) | 20 | 17 | 3 | 12.2 | 16 |

Matching is rung 1's (one event per change, closest first, within 45 days; a departure of any
kind matches a relocation start, graveyard move or end of keeping). False events are counted on
QZS-3 and QZS-6 over the span their logs cover: 0 over 5.412 object-years (target at most 0.2 per
object-year). Graveyard moves are still the worst dated (dev median 6 days, mostly early), because
sources variously date the start of the climb, its end or the decommissioning; three of the 13 dev
events are dated only to the month and scored as the 15th.

The belt run (`findings/state_changes/summary.json` records its commit) covers 1,799 objects and
finds 863 events on 308 of them; the full list is `findings/state_changes/events.csv`:

| type | 2021 | 2022 | 2023 | 2024 | 2025 | total |
|---|---|---|---|---|---|---|
| relocation_start | 42 | 38 | 57 | 45 | 49 | 231 |
| relocation_end | 66 | 60 | 86 | 60 | 70 | 342 |
| graveyard | 17 | 12 | 20 | 15 | 19 | 83 |
| keeping_stop | 4 | 7 | 2 | 4 | 17 | 34 |
| ns_keeping_stop | 10 | 9 | 16 | 18 | 23 | 76 |
| free_burn | 11 | 4 | 18 | 26 | 38 | 97 |

Known limits. Arrivals outnumber departures because a newly launched satellite's first arrival
has no departure. A departure in the last weeks of 2025 has no arrival inside the data, so it is
typed `keeping_stop`: 11 of the 17 in 2025 fall in November and December. A satellite that
arrives in the last 10 days of the data is not seen as held, so its first trim burn can read as a
`free_burn`. A climb by an object that was already free is a `free_burn`, not a `graveyard` move.
North-south keeping stops are still dated at the window boundary. No hand audit of belt events
has been done.

## Method notes

Rules, thresholds and sources that the code does not state, per module.

### `elements`

- A blank TLE eccentricity field is refused, not read as 0.
- CelesTrak and Space-Track print the GP `EPOCH` with no offset; it is read as UTC.
- OMM numbers are kept as their text until parsed, so a JSON value and the same CSV value give
  the same float.

### `series`

- When two records share an epoch, the later input record wins, so a later source restates an
  earlier one. A chain of epochs each under 60 s after the previous one collapses to its last
  epoch.

### `detect`

- The step's standard error is `se = sigma * sqrt(pi/2) * sqrt(2/k)`, the standard error of a
  difference of two medians; `sigma` is 1.4826 times the pooled median absolute deviation, floored
  at half the series' median `sigma` so a run of near-identical TLEs does not inflate `z`.
- `z` ranks steps but is not a calibrated probability: consecutive ISS TLEs come from overlapping,
  correlated orbit-determination arcs, so the minimum `|step|` does most of the work.
- `merge_channels` keeps every semi-major-axis detection and drops an inclination detection within
  `nms_days` of one. Semi-major axis goes first because `z` is not comparable across channels.

### `calibrate`

- Ties in the F1 choice go to the stricter setting: higher `|z|`, then higher `|step|`, then
  smaller `k`.
- A row with no time is a US-local date and is widened by one day either side.
- Step sign: up for reboosts (test burns included), down for deboosts and burns the source calls
  retrograde, either for the rest.

### `holdout`

- An event's year is its `date_utc`; a detection's year is that of the epoch before its step. The
  detector runs once per source, so the noise floor (half the median `sigma`) spans all of
  2021-2025 and uses no labels.

### `inject`

- 300 trials per size and sign. A quiet gap has no truth window and no frozen detection within a
  margin equal to the scoring window `max_span_days` (3 days at native cadence, wider on thinned
  series).
- A thinned series is re-thinned with a random grid phase in every realisation, so the trials
  spread over many thinned series.
- `chance_recovery` is the share of quiet gaps that a detection already present with nothing
  injected would "recover": the floor under small-step recall at a loose setting.
- The looser settings are a measurement, not a tuning; none of them is chosen.

### `generalise`

- Each satellite's tune/test split falls on the first day of the month holding its
  60th-percentile logged event, fixed from the log before any scoring.
- `lag_days` uses only events with `|delta_a|` of at least 500 m whose step reaches 30% of the
  estimate.
- A burn/counter-burn pair takes either sign, because its net sign is within the estimate's error.

### `harness.evals.detector`

- An event is covered when the coverage reference scores a gap near it: `score_gaps`' gap rule at
  `REF_K` = 4 with the 3-day span and 2-day gap limits of `generalise` at 3ca08ab, copied, so no
  detector change moves it.
- A detection is assigned to a period, matched and counted by its peak gap (the gap its step and
  `z` come from), never by its interval.
- Duplicates are unmatched detections whose peak gap overlaps a logged burn's match zone: neither
  hits nor false alarms, counted so that lowering `nms_days` or `z_min` near burns does not look
  free.
- Exposure is the union of the no-burn time the reference scores and the time the setting scores,
  so marking noisy gaps unscored cannot lower the false-alarm rate. QZS-4 (about one element set a
  day, none for 3-5 days after a burn) has only 0.415 (train) and 0.235 (dev) of its no-burn time
  scored.
- With `--final` there is no per-event detail: the test score is a count, not a guide.

### `modes`

- Classes and region: ESA Space Debris Office, *Classification of Geosynchronous Objects*, Issue
  21.0, 19 July 2019, GEN-DB-LOG-00270-OPS-SD, status at 1 January 2019, section 2 and table 1
  (p. 6). ESA does not host it publicly; the copy read is at
  <https://astronomer.ru/data/0128/Classification_of_Geosynchronous_Objects_I21R0.pdf>.
- `out_of_region`: median semi-major axis outside 37,948-46,380 km or eccentricity above 0.25
  (ESA's GEO, IGO and EGO classes together).
- Longitude is the mean longitude (node + argument of perigee + mean anomaly - GMST), the quantity
  ESA tabulates. The sub-satellite longitude adds an inclined orbit's daily figure-eight, about
  ±1 deg at 15 deg inclination.
- Held: the 5th-95th percentile longitude spread is at most 0.3 deg. ITU Radio Regulations
  No. 22.6 sets ±0.1 deg east-west for geostationary stations; 0.3 leaves room for TLE noise and
  sits in the gap of the spread histogram (150 sampled objects: 2,627 windows below 0.15 deg, 147
  between 0.15 and 0.5 deg). A held window counts as control only if a 90-day run of three windows
  that includes it is held too, or it is stiller than a free object could be.
- `BOX_DEG` 1.5: among 90-day runs with a burn in 250 sampled objects, 933 spread under 1 deg, 10
  spread 1-3 deg and the rest 3 deg or more.
- `FREE_RESIDUAL_DEG` 0.02: in a seeded sample of 400 objects the two-window fit leaves 0.42% of
  2,153 free-librator windows above it, and 99.5% of keeper windows and every relocation above it.
- The 30-day windows are laid back from 2026-01-01 so every object shares the grid; the first
  window is 26 days.

### `jobs.extract_tle_archive` and `jobs.geo_belt`

- `extract_tle_archive` carries each object's line 1 and line 2 across commits, so a commit that
  changes one line still yields a whole pair. On an epoch conflict it keeps the first pair;
  `geo_belt` keeps the later one, as `series` does.
- The Kaggle dataset's 2021, 2022 and 2024 files end every line 1 with a backslash, which
  `geo_belt` drops.
- `geo_belt` writes one zip when `--out` ends in `.zip`, for hosts that should not write thousands
  of files.

### `spacetrack`

- A Space-Track login answered with `"Login":"Failed"` in the body counts as refused even with
  HTTP 200, as in the open-source `spacetrack` client.
