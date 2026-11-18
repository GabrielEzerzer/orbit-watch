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
| GEO state changes (2 to 18 min; measured runs took 145 to 1,083 s) | `python -m orbit_watch.jobs.state_changes` | `$ORBIT_WATCH_DATA/state_changes/events.csv`, `findings/state_changes/` |
| GEO state changes evaluation | `python -m harness.evals.state_changes [--split dev\|all]`; `--final` adds the holdout Fengyun false-event check, run once | `findings/state_changes/eval_<split>.json` and `.csv`, `false_events_final.json` |
| GEO state changes planted-change test (about 7 min) | `python -m harness.evals.state_injection` | `findings/state_injection/summary.json` and `trials.csv` |
| Hand audit of belt state changes | `python -m harness.evals.state_audit sample\|chart\|summary [--out DIR]` | the sample on stdout; charts and `digests.json` in `--out` (default `$ORBIT_WATCH_DATA/state_audit/`); `summary.json` in `--out` (default `findings/state_audit/`) |

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
| At most 0.2 false events per object-year, counted on state-change events | met on QZS-3, QZS-6 and Fengyun-2H, the train objects with burn logs (the snap-back filter was tuned on the two QZSS satellites): 0 events over 6.459 object-years while their logs show them on station. They keep station throughout, so the check sees false departures, arrivals and keeping stops on a held object; it does not see extra or mistyped events around a real change, or false free burns on objects that are not held |
| The same count on the holdout Fengyun-2F and Fengyun-4A (`--final`, run once) | measured, not yet gated: 0 events over 2.15 object-years (Fengyun-2F 0 in 1.01, Fengyun-4A 0 in 1.14), from the first log row in 2021 to the last in January and February 2022; `findings/state_changes/false_events_final.json` |
| Planted changes in held satellites (`harness/evals/state_injection.py`) | measured, not yet gated: relocations at 0.1-3 deg/day caught at both ends in 0.99 (dev) and 0.98 (test) of trials, median date error 0 days (0.84 in both before steps 6-11); at 0.02-0.1 deg/day 0.86 (dev) and 0.87 (test) (0.71 and 0.69 before); graveyard climbs 1.00; keeping stops 0.78-0.85, median error 7-8 days; free burns after a stop 0.60-0.61. Events on untouched host stretches: 15 in 1,412.5 trial-object-years (dev), 12 in 1,315.9 (test), mostly real moves on shared hosts; inside all 594 candidate held stretches before any plant: 54 in 2,131.9 object-years (0.025 per object-year), real moves and re-dated north-south stops (see the planted-change test below). Extra events after a planted stop come mostly from hosts with noisy held-era element sets, so the free-burn threshold must not be tuned on them |
| Recall and dating error on a cited list of known GEO events | dated state changes: dev 13/13, median date error 2 days; test 18/20, median 5 days (scored only at the end of each set of steps, never to choose a rule; see the cited table). The mode layer alone: 26/33, median 11.5 days |
| A hand audit of about 50 events from across the belt | done: 42 of 50 real with the right type. In-sample, since steps 6-18 were written after reading these verdicts: 46 of 50 rows right after steps 6-11 and 49 of 50 after steps 12-18 (a real row within 5 days with the right type, or an artefact or duplicate gone); see "Hand audit of belt state changes" |

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
mode-layer boundary the event came from). On an arrival from a stretch that is not held,
`lon_before` is the median longitude of the 10 days before it; for a departure with no later
hold, `lon_after` is the median longitude of the last 10 days of the data. Either is empty when
those 10 days hold no element set (six arrivals and one graveyard move in the belt list). The
event types are:

| type | what it is | dated by (`signal`) | `size` |
|---|---|---|---|
| `relocation_start` | a held object leaves its slot and is held again later, is still moving at relocation speed when the data end, or moves at relocation speed until a graveyard climb (step 14) | `rate_exit`: the first set that leaves the held drift band or longitude box and stays out 5 days (inside a gap, see step 7); `a_step` when that exit is slow drift and a burn starts the move later (step 16); `burn_gap` when the exit is slow and the burns stop first (steps 4 and 15) | median semi-major axis of the moving sets (drift at least 0.05 deg/day away from the hold's) from the start to the next held mode segment, the end of the data or the climb, minus the hold's median, km: usually negative for an eastward move, but a later drift inside the same span can outweigh a short move (#75). All sets in that span are used when none moves that fast; 0 when the next mode segment is already held |
| `relocation_end` | a moving object starts to hold a slot | `rate_entry`: the first set that stays inside the new slot's band (inside a gap, see step 7) | 0 |
| `graveyard` | a held object leaves and its semi-major axis rises at least 150 km, with no later hold | `rate_exit`; `a_step` when the climb starts with a burn after a slow drift or a stall (steps 14 and 16) | highest semi-major axis from the end of the held mode segment to the end of the data, minus the hold's median, km |
| `keeping_stop` | a held object leaves with no climb, no later hold and no move under way at the end of the data, or drifts slowly for more than 90 days before a climb (step 14) | `burn_gap`: the last east-west burn plus half the burn interval (step 4, or step 15 on a slow cycle); `rate_exit` when the burns give no date | highest semi-major axis from the end of the held mode segment to the end of the data (to the climb under step 14), minus the hold's median, km; 0 when a move or climb follows it (step 4) |
| `ns_keeping_stop` | `controlled_lon_inc` to `controlled_lon` at the same slot, with at least 2 inclination corrections found | `ns_gap`: the last correction plus half the median interval between corrections (step 8) | largest inclination in the `controlled_lon` segment after it, deg |
| `free_burn` | a semi-major-axis step of at least 1 km by an object that is never held again (steps 10 and 18) | `a_step`: the step detector's peak | the step detector's step, m: the change in median semi-major axis across the detection once the local linear trend of the 6 sets on each side is removed. On a steady climb it can have the opposite sign to the net change: 29155 on 2024-07-16 is listed at -1179 m while its semi-major axis climbs about 11 km between 8 and 20 July |

Any type except `ns_keeping_stop` and `free_burn` can carry `mode_change` instead: no sustained
exit from the hold or entry into it was found within 45 days of the mode-layer boundary, so the
boundary's date is used (three rows in the belt list). Burns after a graveyard move are listed as
free burns when they are not part of the climb (step 10): an object in a graveyard orbit can keep
manoeuvring, as 28790 and 29155 do in 2024.

The steps behind it. Step 1 was measured on the detector evaluation's QZS-3 and QZS-6 false
alarms; the others on the dev split of `groundtruth/geo_events.csv`:

1. **Snap-back blocks** (`orbit_watch.clean`). Runs of up to 10 days where the semi-major axis or
   the inclination vector jumps away and comes back while the mean longitude carries on are
   alternate orbit solutions, not burns. They are about 1.6% of sets on a 100-object sample, and
   on QZS-3 and QZS-6 they caused 6 of the 7 detector dev false alarms that were not near a logged
   burn. They are dropped before anything else, with none of the logged QZS burns lost. When the
   sets on either side of a block are fewer than 3 or span less than a day, only the inclination
   vector is judged, so a block that is the start of a new orbit is kept.
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
5. **One slot.** Two holds whose longitude ranges come within 0.5 deg of each other are the same
   slot, so a re-centred box or a hold split by a short drift is not a relocation. Across a
   stretch that is not held, this applies only when nothing in the stretch drifts at 0.05
   deg/day or more for 5 days; a move out and back to the same slot is a start and an end. An
   arrival is dated no earlier than the departure it follows.

Steps 6 to 11 came from the hand audit and the planted-change test below; each was kept only if
the dev cited events, the kept satellites and the dev planted trials did not get worse:

6. **Moves the windows hide.** A quick move across a 30-day window boundary can leave every
   window inside the held box, so the mode layer reads one held segment over both slots. Inside a
   held segment, a run of sets outside the held drift band, with at least 3 calm sets on each
   side within 10 days, that shifts the longitude at least 0.5 deg in the direction of the drift
   splits it into hold, drift and hold. Two holds whose ranges touch are also a move when the
   10-day median longitudes at the end of one and the start of the next differ by 0.5 deg or more.
   Where the whole-hold box finds no departure or arrival, the box of the hold's 30 days at that
   edge is tried before the window boundary; using it first trips on ordinary box excursions
   weeks before a move.
7. **Changes inside gaps.** When the first set out of the hold, or back in it, comes after a gap
   of more than 2 days, the change is placed inside the gap by running that set back at its drift
   rate relative to the hold, as if the burn were instant: the latest start the sets allow.
8. **End of north-south keeping.** Corrections are steps in the inclination vector (i cos RAAN,
   i sin RAAN) once its free drift, fitted on the 60 days after the window boundary, is removed. A
   correction is a step between 3-set medians across a gap of at least 5 times the set-to-set
   scatter and at least 0.006 deg, in the 180 days before. The stop is the last correction plus
   half the median interval. With fewer than 2 corrections nothing is listed, which drops stops on
   objects that never kept inclination.
9. **Moves still under way at the end of the data.** A departure with no later hold and no climb
   is a `relocation_start`, not a `keeping_stop`, when the data end within 90 days of it and the
   drift goes from under 0.025 to a sustained 0.05 deg/day or more relative to the hold within 5
   days, or between consecutive sets. That takes a burn: natural drift needs 15 days or more to
   change that much.
10. **Free burns.** A burn is listed only with at least 10 days of data after it (a hold takes 10
    days to show, so a burn in the last 10 days can be a new slot's first trim); not after a
    relocation start still under way at the end of the data, whose burns are part of the move;
    and not as part of a graveyard climb, where each burn follows the departure or the previous
    climb burn within 30 days.
11. **Inclined orbits.** Above 25 deg inclination (IGSO and QZO objects) the mode layer's hold
    test does not apply: a single held window between inclined stretches read as an arrival and a
    departure, and every later keeping burn as a free burn. Inclined stretches are skipped, like
    undetermined ones.

Steps 12 to 18 came from a second hand reading of the belt list after steps 6 to 11; each was
kept under the same rule:

12. **One move, one pair.** An out-of-band run inside a held segment that starts before the
    previous inner move has arrived is part of that move, not a second one (JCSAT 12, 35755, and
    37237 each lost a duplicate start).
13. **A hold to the last set.** A short hold that lasts to the last element set is not followed
    by an empty stretch, so it gives no departure at the end of the data.
14. **Burns after the departure.** A departure followed within 15 days by a burn of at least
    1 km, with the data ending within 90 days of it, is a move under way (`relocation_start`), not
    a keeping stop. A climb that stalls for more than 90 days and then rises again to 150 km
    above the hold is a graveyard move dated at the burn that resumes the climb. The departure
    before it is a `relocation_start` when the drift jumps to 0.05 deg/day or more relative to the
    hold within 5 days, as in step 9, and the median drift until the climb is at least that fast:
    the object was moved and then retired, as 26719 was in December 2022. Otherwise the departure
    is a keeping stop. The stall is measured on a 3-set median of the semi-major axis that only
    counts gains, so an orbit lowered for a move reads as a stall.
15. **Slow burn cycles.** When fewer than 3 burns fall in the 60 days before a slow exit, the last
    two burns inside the hold within 180 days give the stop (the last burn plus half their
    interval), if the exit comes between half and one and a half intervals after the last burn.
16. **Slow drift before the burn.** A relocation or graveyard departure whose first sets out of
    the hold drift slowly, with fast drift within 45 days, is dated at the burn of at least 1 km
    in the 5 days before the first fast set.
17. **Free drift read as a hold.** A short hold with no detected burn between its start and the
    departure gives no keeping stop: free drift after an arrival can be slow enough to read as
    one.
18. **One free burn per step.** Detections within 2 days of each other are one burn: only the
    largest that passes step 10 is listed, and only when the median semi-major axis of up to 3
    sets on each side of the group differs by at least 1 km.

| split | events | caught | median \|error\| (days) | 90th percentile (days) | same type |
|---|---|---|---|---|---|
| dev, mode layer (baseline) | 13 | 11 | 10 | 33 | 9 |
| dev, state changes | 13 | 13 | 2 | 13 | 13 |
| test, mode layer (baseline) | 20 | 15 | 14 | 30.8 | 14 |
| test, state changes, before steps 6-11 (scored once) | 20 | 17 | 3 | 12.2 | 16 |
| test, state changes after steps 6-11 (scored once) | 20 | 17 | 5 | 13.4 | 16 |
| test, state changes after steps 12-18 (scored once) | 20 | 18 | 5 | 14 | 17 |

The test median moved from 3 to 5 days with the gap rule (step 7) alone: four test graveyard moves
start in a gap and are now dated 2 to 10 days earlier, inside it. Each new date is the latest the
sets allow. ASTRA 1D (23331) is 46 deg away moving at -4.77 deg/day at the first set after an
11-day gap, so it left by 7 November 2021; three of the four cited dates give only the month,
scored as the 15th, and the fourth is the day GSAT-12's disposal was completed. On dev, Astra 2D
(26638) moves the same way, to 13 days before its cited decommissioning date, which matches the
hand audit's estimate from the sets.

The test split is scored once per set of steps, after the steps were kept on dev and the hand
audit. The extra test catch after steps 12-18 is the graveyard move of 28707, now dated 17 days
before its cited date by step 14. 28707's belt row was looked at while building step 14, and its
date moved by one day as a result (from 18 to 17 days early). Its departure on 2021-11-09, a burn
that lowers the orbit by about 50 km and starts an eastward drift of 0.5 to 0.7 deg/day, was then
listed as a keeping stop; it is now a `relocation_start`, and its graveyard row is unchanged.

Matching is rung 1's (one event per change, closest first, within 45 days; a departure of any
kind matches a relocation start, graveyard move or end of keeping). False events are counted on
QZS-3, QZS-6 and Fengyun-2H while their logs show them on station: 0 over 6.459 object-years
(target at most 0.2 per object-year). A satellite counts as on station from its first log row to
its last, clipped to its element sets and to 2021-2025; a gap between east-west burns longer
than twice that log's median east-west gap would mean the log shows it away, so that span is
dropped and named in the output. No span is dropped in 2021-2025: Fengyun-2H's east-west burns
come every 106 days at the median and at most 162 days apart. The Fengyun logs end in January and
February 2022, so Fengyun-2H adds 1.047 object-years, and they have no stated provenance (see
`groundtruth/README.md`), so the count on them supports the QZSS count rather than standing
alone. `--final` runs the same count on the holdout Fengyun-2F and Fengyun-4A; it was run once,
after everything else was fixed, and its result is in `findings/state_changes/false_events_final.json`.
`events.state_changes` builds its series without `final=True`, so the eval runs a copy of
`events.burns` that passes it; a test checks that the copy gives the same events on mock data. Graveyard moves are still the worst dated (dev median 9 days, mostly early), because
sources variously date the start of the climb, its end or the decommissioning; three of the 13 dev
events are dated only to the month and scored as the 15th.

The belt run (`findings/state_changes/summary.json` records its commit) covers 1,799 objects and
finds 764 events on 301 of them; the full list is `findings/state_changes/events.csv`:

| type | 2021 | 2022 | 2023 | 2024 | 2025 | total | after steps 6-11 | before steps 6-11 |
|---|---|---|---|---|---|---|---|---|
| relocation_start | 41 | 40 | 56 | 48 | 57 | 242 | 240 | 214 |
| relocation_end | 65 | 59 | 84 | 63 | 68 | 339 | 341 | 325 |
| graveyard | 16 | 11 | 21 | 15 | 20 | 83 | 83 | 83 |
| keeping_stop | 2 | 7 | 2 | 2 | 4 | 17 | 22 | 31 |
| ns_keeping_stop | 9 | 7 | 14 | 14 | 15 | 59 | 59 | 76 |
| free_burn | 0 | 0 | 5 | 10 | 9 | 24 | 32 | 96 |

Known limits. Arrivals outnumber relocation starts because 108 objects' first relocation event
is an arrival: mostly objects launched in 2021-2025 or already moving at the start of 2021. A
slow keeping stop followed by a move gives two departures for one physical move, a
`keeping_stop` and then a `relocation_start`, and the scorer matches only one of them: on dev
event 28884 the keeping stop is matched by exact type and the relocation start, 48 days later,
is left over. A move made entirely inside one gap is still dated to the end of the gap at both
ends, as Meteosat-11 (40732) is in April 2023. A keeping stop whose last burn is the one that
starts the drift is dated when the longitude leaves the box: 32478 is dated 2022-09-11 against
an estimate of 2022-08-17 (25 days). A climb that has risen less than 150 km when the data end
reads as a move under way: SJ-17 (41838) is listed as a `relocation_start` in November 2025,
115 km above its slot at the end, which may be either. A climb by an object that was never held
in the data is still listed as free burns. A move whose drift pauses can be split into several
start and end pairs (JCSAT 12, 35755, gives two pairs for one 4.5 deg move in March 2022). A move
made in a gap after a short burn can be dated a few days early by step 15: 58990 is dated
2024-06-13, and its sets show the change between 06-14 and 06-18.

### Hand audit of belt state changes (`harness/evals/state_audit.py`, `findings/state_audit/`)

The scored lists above are small and lean on well-documented events, so 50 events from the belt
list were judged by hand. The verdicts are judgments read from each object's element sets, not
cited ground truth: an event is `real` if the change it describes shows in the sets (whatever its
date error), `artefact` if nothing changed at that date (bad sets, free drift read as a hold, or a
routine keeping burn), `wrong_type` if a real change has another type, and `duplicate` if another
event already covers it.

The sample is fixed by `SEED` in `harness/evals/state_audit.py` and drawn from the belt list as it
was audited, kept in `findings/state_audit/events.csv`, so later changes to the list do not move
it. It leaves out the holdout objects
and every object with a test-split event in `groundtruth/geo_events.csv` (5 holdout objects and 17
with test-split events, 75 belt events in all), takes at least 5 events of each type and shares the rest in proportion to each type's count, then
draws within each type with a seeded generator. Each event was charted over 60 days either side
(mean longitude, drift rate, semi-major axis and the inclination vector, with the raw and
filtered sets, neighbouring events and mode segments) and judged on the same checklist: did the
change happen, of this type, and when. `findings/state_audit/audit.csv` holds one row per event
with the estimated true date, `date_error_days` (event date minus estimated date) and one line of
evidence; `summary.json` holds the counts.

| type | sampled | real | artefact | duplicate | wrong type |
|---|---|---|---|---|---|
| relocation_start | 10 | 10 | 0 | 0 | 0 |
| relocation_end | 13 | 13 | 0 | 0 | 0 |
| graveyard | 7 | 7 | 0 | 0 | 0 |
| keeping_stop | 6 | 5 | 1 | 0 | 0 |
| ns_keeping_stop | 7 | 5 | 2 | 0 | 0 |
| free_burn | 7 | 2 | 3 | 2 | 0 |
| all | 50 | 42 | 6 | 2 | 0 |

Of the 42 real events, 41 could be dated from the sets. Leaving out north-south stops, the median
error is 1 day and 27 of 36 are within 3 days. Of the 9 dated more than 3 days off, 8 are late,
mostly where the change falls in a gap in the sets (dated at the gap's end, 4 to 15 days)
or where keeping stops on a burn cycle slower than the burn-gap rule needs (25 and 46 days). For a
change inside a gap, the estimate runs the first set after the gap back at its drift rate as if
the burn were instant, so it is the latest plausible start and those errors are lower bounds. The
5 real north-south stops are dated 82 to 114 days late (median 108): a stop is dated at the start
of the first 30-day window whose median inclination is above 0.3 deg, which can be up to about 15
days either side of the crossing, and the inclination takes about 100 days to grow from the kept
value to 0.3 deg. Free burns are the weakest type. Two are steps inside a graveyard climb already
listed: a burn is left out only within 15 days of a listed event (`CLIMB_DAYS`), and these come 22
days (Spaceway 2) and 21 days (Optus D2) after it. One is a run of bad sets over about 1.5 days
that relaxes back, which a one-set outlier filter would not remove. Two are routine east-west
burns of kept inclined satellites (BeiDou 7, IRNSS 1D), whose free burns all follow a false
earlier departure.

After steps 6 to 11 the same 50 rows were checked against the new belt list (a real row counts
when an event of the right type is within 5 days of the estimated date, an artefact or duplicate
when it is gone): 46 of 50, against 30 of 50 before. This and the next count are in-sample:
the steps were written after reading these verdicts. The 7 changes inside gaps and the 5 real
north-south stops are now within 0 to 5 days of the estimates; the 2 north-south stops on objects
that never kept inclination, the 2 climb burns listed as free burns, the bad-set run on 27854 and
the free burns of the 2 inclined satellites are gone. After steps 12 to 18, 49 of 50 are
right: 25258's stop is dated 2022-04-09 against an estimate of 04-08 (step 15), 41103's move
2022-09-10, on the estimated day (step 16), and 56372's keeping stop is gone (step 17). Still
wrong: 32478's keeping stop, 25 days late.

Public sources. Four sampled rows are corroborated by public pages, listed with quotes in
`summary.json` under `public_sources`:

- Intelsat 33E (41748), keeping_stop 2024-10-29: "broke into at least 57 pieces on 19 October
  2024" (https://en.wikipedia.org/wiki/Intelsat_33e). This matches the estimate of 2024-10-19.
- COMS 1 (36744), ns_keeping_stop 2021-07-26: "COMS concluded operations in April 2021"
  (https://www.eoportal.org/satellite-missions/coms-1). This matches the estimate of 2021-04-03.
- Astra 2D (26638), graveyard 2023-01-24: "In early January 2023, Astra 2D was put into a
  graveyard orbit" (https://space.skyrocket.de/doc_sdat/astra-2d.htm), while Wikipedia gives
  decommissioning on 27 January 2023 (https://en.wikipedia.org/wiki/Astra_2D). The estimate of
  2023-01-14 sits between the two.
- Astra 5B (39617), relocation_end 2023-07-19: "the satellite had moved to 23.5"
  (https://en.wikipedia.org/wiki/Astra_5B), in July 2023. This matches the estimate to the month.

#### Out-of-sample audit (`findings/state_audit_fresh/`)

After steps 6 to 18 were written, 50 more events were drawn from the new belt list and judged on
the same checklist, from the element sets only. This sample was never used to choose a rule. The
list as audited is frozen in `findings/state_audit_fresh/events.csv`, and `state_audit sample
--fresh` redraws the sample from it with its own seed, leaving out the holdout objects, the
objects with test-split events and every object in the first audit. `audit.csv` and
`summary.json` hold the verdicts; like the first audit's, they are judgments from the sets, not
cited ground truth.

| type | sampled | real | artefact | duplicate | wrong type |
|---|---|---|---|---|---|
| relocation_start | 11 | 11 | 0 | 0 | 0 |
| relocation_end | 14 | 14 | 0 | 0 | 0 |
| graveyard | 7 | 6 | 1 | 0 | 0 |
| keeping_stop | 5 | 3 | 0 | 1 | 1 |
| ns_keeping_stop | 7 | 7 | 0 | 0 | 0 |
| free_burn | 6 | 6 | 0 | 0 | 0 |
| all | 50 | 47 | 1 | 1 | 1 |

47 of 50 are real with the right type. 45 of them could be dated from the sets: median error 0
days, 90th percentile 3, maximum 50; 42 are within 3 days and 43 within 7. The misses: Express 80
(45986) is held to its last set, and one bad set at the end of its data reads as a graveyard move
(#71); GOES 16's (41866) keeping stop is a pause in keeping before a move that is already listed
(#72); SJ-23's (55131) keeping stop is a move with no later hold (#72). The largest error is
EUTE 113 West A's (29162) keeping stop, 50 days late because a small burn after keeping ended
anchors it (#73). The other two over 3 days are DSN-3's (61733) arrival, dated at a trim inside
its new slot 9 days after it settled (#74), and a north-south stop 4 days late. The 2 real events
left undated are arrivals after a transfer orbit, which the sets bound only to a window across a
gap (#70). Issues #69 to #74 hold the failure patterns this audit found. Since the audit, the
`size` of the 11 sampled relocation starts has changed with the fix to that column; no sampled
row changed its type or date.

#### Planted-change test (`harness/evals/state_injection.py`, `findings/state_injection/`)

The cited events are few, so this test plants changes into real element sets, in memory, and
checks what `orbit_watch.events` finds. A candidate is the longest held mode segment of at least
120 days of a GEO-region object; holdout objects and objects with a test-split event in
`groundtruth/geo_events.csv` are left out. A candidate hosts plants only if it held no
state-change event when the host set was frozen. The 594 candidates, which 491 of them are
quiet, each object's last element set and its held-era scatter are frozen in
`harness/evals/state_injection_hosts.json` (`--freeze` rebuilds it, recording its commit), so a
change to the event code changes neither the hosts nor the plants, and a host that the changed
code finds noisy stays in. Hosts go to dev or test by the parity of the last hex digit of the
SHA-256 of their NORAD number: 261 dev and 230 test. Every plant starts at least 60 days into
the stretch and is drawn with a fixed seed; trials alternate between dev and test hosts.

How a plant edits the element sets. Each edited set keeps its eccentricity, inclination, node
and argument of perigee; it gets a new mean motion n from the planted drift rate, a semi-major
axis scaled by (n_old/n)^(2/3), and a mean anomaly shifted by the planted change in mean
longitude, so the three agree.

- **Relocation**: a burn-free drift at constant rate (a straight line in longitude, with no
  longitude acceleration) for D days from the host's local longitude to its slot
  longitude D days later plus r*D, then the host's own sets shifted by r*D. |r| is
  log-uniform within five bins from 0.02 to 3 deg/day (100 trials each); the distance is
  log-uniform from 1 to 20 deg, so D = distance/|r|, clipped to 2-120 days. Truth: a start on
  the first day and an end on the last.
- **Keeping stop**: after the stop day the longitude follows a free path, integrated with the
  longitude acceleration from `orbit_watch.modes`, starting from the host's local longitude and
  drift. Truth: a keeping stop. 160 trials.
- **Graveyard climb**: a stop followed by 1 to 3 burns 0.5-3 days apart that raise the
  semi-major axis 200-400 km in total. Truth: a graveyard move at the first burn. 160 trials.
- **Free burn**: a stop, then one burn of 1.5-20 km (log-uniform, either sign) 45-120 days
  later. Truth: a keeping stop and a free burn. 160 trials.

During a drift and on a free path, each set's longitude and drift rate keep the host's own
scatter but none of its keeping burns: the host's residuals from a local line through 9 sets
(cut at detected burns and at jumps over 10 sigma, with residuals within 2 days of a cut taken
from elsewhere), differenced so they stay white. Manoeuvre structure that neither cut catches is
carried along (see below). Scoring uses the state-change eval's
`score` (type families, 45 days, one-to-one, closest first). Extra events are the unmatched ones
within 45 days of the planted change (near) and, for the kinds that leave the object free, any
after it (later). False events on untouched stretches count the unmatched events on the host
stretch before the plant (and after a relocation); that exposure adds up over trials, so a
stretch used by several trials counts once per trial. The belt-wide figure is taken before any
plant: every event inside the 594 candidate held stretches with 45 days trimmed from each end.

| split | kind | drift rate (deg/day) | truth | trials | recall | all truths caught | median \|error\| (days) | p90 (days) | mistyped | extra per trial (near / later / median) |
|---|---|---|---|---|---|---|---|---|---|---|
| dev | relocation | slow, 0.02-0.1 | relocation_start | 100 | 0.89 | 86/100 = 0.86 | 1 | 7.2 | 6 | 0.14 / 0 / 0 |
| dev | relocation | slow, 0.02-0.1 | relocation_end | 100 | 0.89 | 86/100 = 0.86 | 0 | 4.2 | 0 | 0.14 / 0 / 0 |
| dev | relocation | normal, 0.1-3 | relocation_start | 150 | 0.99 | 148/150 = 0.99 | 0 | 1 | 1 | 0.007 / 0 / 0 |
| dev | relocation | normal, 0.1-3 | relocation_end | 150 | 0.99 | 148/150 = 0.99 | 0 | 1 | 0 | 0.007 / 0 / 0 |
| dev | relocation | 0.02-0.05 | relocation_start | 50 | 0.82 | 38/50 = 0.76 | 2 | 14 | 4 | 0.24 / 0 / 0 |
| dev | relocation | 0.02-0.05 | relocation_end | 50 | 0.82 | 38/50 = 0.76 | 0 | 9 | 0 | 0.24 / 0 / 0 |
| dev | relocation | 0.05-0.1 | relocation_start | 50 | 0.96 | 48/50 = 0.96 | 0 | 1.6 | 2 | 0.04 / 0 / 0 |
| dev | relocation | 0.05-0.1 | relocation_end | 50 | 0.96 | 48/50 = 0.96 | 0 | 2 | 0 | 0.04 / 0 / 0 |
| dev | relocation | 0.1-0.3 | relocation_start | 50 | 1.00 | 49/50 = 0.98 | 0 | 1 | 1 | 0.02 / 0 / 0 |
| dev | relocation | 0.1-0.3 | relocation_end | 50 | 0.98 | 49/50 = 0.98 | 0 | 1.2 | 0 | 0.02 / 0 / 0 |
| dev | relocation | 0.3-1 | relocation_start | 50 | 0.98 | 49/50 = 0.98 | 0 | 1 | 0 | 0 / 0 / 0 |
| dev | relocation | 0.3-1 | relocation_end | 50 | 1.00 | 49/50 = 0.98 | 0 | 1 | 0 | 0 / 0 / 0 |
| dev | relocation | 1-3 | relocation_start | 50 | 1.00 | 50/50 = 1.00 | 0 | 1 | 0 | 0 / 0 / 0 |
| dev | relocation | 1-3 | relocation_end | 50 | 1.00 | 50/50 = 1.00 | 0 | 1.2 | 0 | 0 / 0 / 0 |
| dev | keeping_stop |  | keeping_stop | 80 | 0.85 | - | 8 | 30.3 | 0 | 0 / 0.338 / 0 |
| dev | graveyard |  | graveyard | 80 | 1.00 | - | 0 | 1 | 0 | 0.037 / 0.25 / 0 |
| dev | free_burn |  | keeping_stop | 80 | 0.80 | 46/80 = 0.57 | 12 | 30 | 4 | 0.3 / 0.362 / 0 |
| dev | free_burn |  | free_burn | 80 | 0.60 | 46/80 = 0.57 | 0 | 1 | 0 | 0.3 / 0.362 / 0 |
| test | relocation | slow, 0.02-0.1 | relocation_start | 100 | 0.92 | 87/100 = 0.87 | 1 | 8 | 0 | 0.07 / 0 / 0 |
| test | relocation | slow, 0.02-0.1 | relocation_end | 100 | 0.89 | 87/100 = 0.87 | 0 | 8 | 0 | 0.07 / 0 / 0 |
| test | relocation | normal, 0.1-3 | relocation_start | 150 | 0.98 | 147/150 = 0.98 | 0 | 1 | 0 | 0 / 0 / 0 |
| test | relocation | normal, 0.1-3 | relocation_end | 150 | 0.99 | 147/150 = 0.98 | 0 | 1 | 0 | 0 / 0 / 0 |
| test | relocation | 0.02-0.05 | relocation_start | 50 | 0.88 | 39/50 = 0.78 | 2 | 9.7 | 0 | 0.14 / 0 / 0 |
| test | relocation | 0.02-0.05 | relocation_end | 50 | 0.82 | 39/50 = 0.78 | 1 | 30 | 0 | 0.14 / 0 / 0 |
| test | relocation | 0.05-0.1 | relocation_start | 50 | 0.96 | 48/50 = 0.96 | 0 | 2 | 0 | 0 / 0 / 0 |
| test | relocation | 0.05-0.1 | relocation_end | 50 | 0.96 | 48/50 = 0.96 | 0 | 1 | 0 | 0 / 0 / 0 |
| test | relocation | 0.1-0.3 | relocation_start | 50 | 0.98 | 49/50 = 0.98 | 0 | 1 | 0 | 0 / 0 / 0 |
| test | relocation | 0.1-0.3 | relocation_end | 50 | 0.98 | 49/50 = 0.98 | 0 | 1 | 0 | 0 / 0 / 0 |
| test | relocation | 0.3-1 | relocation_start | 50 | 0.96 | 48/50 = 0.96 | 0 | 1 | 0 | 0 / 0 / 0 |
| test | relocation | 0.3-1 | relocation_end | 50 | 1.00 | 48/50 = 0.96 | 0 | 1 | 0 | 0 / 0 / 0 |
| test | relocation | 1-3 | relocation_start | 50 | 1.00 | 50/50 = 1.00 | 0 | 1 | 0 | 0 / 0 / 0 |
| test | relocation | 1-3 | relocation_end | 50 | 1.00 | 50/50 = 1.00 | 0 | 1 | 0 | 0 / 0 / 0 |
| test | keeping_stop |  | keeping_stop | 80 | 0.78 | - | 7 | 25.8 | 0 | 0 / 0.338 / 0 |
| test | graveyard |  | graveyard | 80 | 1.00 | - | 0 | 1 | 0 | 0.037 / 0.163 / 0 |
| test | free_burn |  | keeping_stop | 80 | 0.75 | 45/80 = 0.56 | 8 | 30 | 1 | 0.25 / 0.212 / 0 |
| test | free_burn |  | free_burn | 80 | 0.61 | 45/80 = 0.56 | 0 | 1 | 0 | 0.25 / 0.212 / 0 |

"All truths caught" counts trials where every planted truth is matched: both ends of a
relocation, or the stop and the burn. The table is for the code with steps 6 to 18; before steps 6 to 11,
relocations at 0.1-3 deg/day were caught at both ends in 0.84 of trials in both splits and at
0.02-0.1 deg/day in 0.71 (dev) and 0.69 (test), and per drift-rate bin from slowest to fastest in
0.62 / 0.80 / 0.76 / 0.82 / 0.94 (dev) and 0.62 / 0.76 / 0.86 / 0.80 / 0.86 (test).

False events on untouched host stretches: dev 15 over 1,412.5 trial-object-years, test 12 over
1,315.9 (1 each before steps 6 to 11). They are counted once per trial on a shared host, and most
are real: 10 of the dev ones are one 1.1 deg move of 23553 in April 2021, 2 a 0.65 deg shift of
34713 in January 2021, both with burns, and 2 the keeping stop of 25258 on 2022-04-09 that the
hand audit dates to 04-08; the last is a keeping stop of 48808 on 2024-06-16, not checked by
hand. On test, 33750 and 55912 make real moves of 14 and 1.5 deg, and 26638's graveyard move is
dated inside a gap. Two are not: a 0.1 deg keeping excursion of 26880 on 2025-03-31, and a 10
deg jump in a day on 52903 on 2022-11-17, a mix-up between element sets.

Inside all 594 candidate held stretches, before any plant: 54 events over 2,131.9 object-years
(0.025 per object-year; 0 before steps 6 to 11). The 10 relocation pairs are 6 real moves of 0.57
to 14 deg with burns that the window boundaries hid (step 6: 23553, 27168, 28626, 28885, 55912,
58204), one 4.5 deg move of JCSAT 12 (35755) split into 2 pairs, one move of 37237 in November
2023, and the element-set mix-up on 52903. The 34 north-south stops were listed before as well,
about 100 days later and outside the held stretch; step 8 dates them inside it.

Extra events after a planted stop, by the host's held-era scatter (median absolute change of the
semi-major axis between consecutive sets in the host stretch, in `trials.csv`):

| split | kind | host held-era SMA scatter | trials | hosts | extra events | of which free burns | extras per trial (mean / median) |
|---|---|---|---|---|---|---|---|
| dev | keeping_stop | < 0.1 km | 68 | 60 | 16 | 0 | 0.235 / 0 |
| dev | keeping_stop | >= 0.1 km | 12 | 10 | 11 | 5 | 0.917 / 0 |
| dev | graveyard | < 0.1 km | 68 | 58 | 3 | 3 | 0.044 / 0 |
| dev | graveyard | >= 0.1 km | 12 | 11 | 20 | 20 | 1.667 / 0.5 |
| dev | free_burn | < 0.1 km | 68 | 58 | 41 | 0 | 0.603 / 0 |
| dev | free_burn | >= 0.1 km | 12 | 11 | 12 | 10 | 1 / 0.5 |
| test | keeping_stop | < 0.1 km | 69 | 56 | 23 | 0 | 0.333 / 0 |
| test | keeping_stop | >= 0.1 km | 11 | 10 | 4 | 4 | 0.364 / 0 |
| test | graveyard | < 0.1 km | 67 | 61 | 3 | 3 | 0.045 / 0 |
| test | graveyard | >= 0.1 km | 13 | 12 | 13 | 13 | 1 / 1 |
| test | free_burn | < 0.1 km | 64 | 57 | 26 | 1 | 0.406 / 0 |
| test | free_burn | >= 0.1 km | 16 | 12 | 11 | 8 | 0.688 / 1 |

What the trials show (the dates and hosts are in `trials.csv`):

- **Short moves.** Relocations of under 1.5 deg are caught at both ends in 40 of 46 trials (1 of
  46 before step 6). Starts caught: 1.5-3 deg 115 of 128, 3-6 deg 155 of 158, 6 deg and more 167
  of 168. A 1.3 deg move over 10 days by Sky Muster 2 (41794, 2023-02-23) and a 1.5 deg move over
  42 days by ARSAT 2 (40941, 2021-05-18), missed before, are now dated within a day at both ends.
- **The slowest moves.** At 0.02-0.03 deg/day most starts are dated within a week, but the
  drift stays inside the held band, so some are dated when the longitude leaves the box, about
  40 days late (62374 from 2025-04-29 at 38 days, 42662 from 2024-11-27 at 42 days), and 9 of
  35 starts and 11 of 35 arrivals are missed (for example 44186 from 2024-09-28 gives no event;
  54026 from 2024-05-14, missed before, is now dated within 2 days).
- **Keeping stops near a stable longitude.** Near 105 W and 75 E a free object barely drifts, so
  its stop is dated months late or not at all: GOES 17 (43226) stopped on 2024-03-20 is dated
  more than 45 days later; MUOS 5 (41622) stopped on 2024-02-13 gives no event. Its slow libration can also
  read as holds: EWS-G3 (35491) stopped on 2021-04-19 gives three relocation pairs from
  2022-05-07 to 2024-11-27; GSAT 11 (43824) and DirecTV 10 (31862) do the same.
- **Extra free burns after a stop are mostly a planting artefact.** 76 trials on hosts with
  held-era scatter of at least 0.1 km give 60 extra free burns; the other 404 give 7 (931 and
  160 before step 18). The free path carries the host's held-era structure:
  manoeuvre-like excursions that no detected burn explains, which the 2-day guard around detected
  burns does not remove. For example, Inmarsat 5-F1 (39476) has a +4 km semi-major-axis excursion
  between days 1517.8 and 1519.4 (2025-02-26 to 2025-02-27) with no detected burn within 6 days;
  carried onto its free path after a stop planted on 2021-07-02 (trial 545), it reads as a 6 km
  `free_burn` on 2025-02-27. Real free objects are mostly tracked more cleanly: all 94
  objects with a keeping stop or graveyard move in `findings/state_changes/events.csv` and at
  least 10 sets from 10 days after the first one have a median set-to-set change of the
  semi-major axis under 0.1 km (median 0.034 km). These extras say little about the belt, and **the free-burn threshold must not be tuned on these
  trials**. 3 planted free burns count as caught 4-29 days off, most likely through such noise
  rather than the planted burn (trials 829, 868, 919; for example trial 919 on 61503 at 29 days).
  Step 18 dropped two such matches (trials 846 and 852, 39 and 24 days off), which is why dev
  free-burn recall went from 0.61 to 0.60.
- **Stop then burn.** A free burn soon after a stop near the slot sometimes splits the stop with
  a short hold, so the stop is typed `relocation_start` (5 trials: 834, 861, 906, 928, 930).

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
