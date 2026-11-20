# Features

Every command in the repo: what it does, how to run it, what it reads and what it writes. Generated from `features.json` by `python tools/features_doc.py`; do not edit by hand.

Upper-case words in a command are placeholders. `$ORBIT_WATCH_DATA` is the data folder (see [orbit_watch/README.md](../orbit_watch/README.md#data-and-downloads)).

- [Data jobs](#data-jobs)
- [Analyses](#analyses)
- [Evaluations](#evaluations)
- [Tools](#tools)

## Data jobs

### Extract TLE history from the tle-archive git history

Pulls the TLE history of chosen objects out of the OndroNR/tle-archive git history, 2021-2023.

```
python -m orbit_watch.jobs.extract_tle_archive --out DIR --norad ID [--norad ID ...] [--name-regex REGEX]
```

Reads:

- the OndroNR/tle-archive GitHub repository, cloned by the job
- NORAD ids or an object-name regex

Writes:

- DIR/<norad>.tle per object
- DIR/manifest.json

### Build the GEO-region TLE set

Picks every object in the GEO region from yearly full-catalogue TLE bundles and writes its TLE history.

```
python -m orbit_watch.jobs.geo_belt build --source URL --bundle PATH_OR_GLOB [--bundle ...] --out DIR_OR_ZIP [--also ID ...]
```

Reads:

- TLE bundles as .txt files or inside .zip files
- the bundles' source URL, recorded in the manifest

Writes:

- <norad>.tle per object
- manifest.json
- both in a directory or in one .zip

### Add SATCAT entries to the GEO-region set

Adds each object's Space-Track SATCAT entry (type, launch, decay) to the GEO-region manifest.

```
python -m orbit_watch.jobs.geo_belt satcat --out DIR
```

Reads:

- DIR/manifest.json from the build command
- Space-Track login in SPACETRACK_USER and SPACETRACK_PASSWORD

Writes:

- DIR/manifest.json with SATCAT entries
- the SATCAT query cached under spacetrack/ beside DIR

### Label GEO operating modes

Labels the operating mode of every GEO-region object in 30-day windows, 2021-2025.

```
python -m orbit_watch.jobs.geo_modes --geo-dir DIR --out DIR [--summary-dir DIR]
```

Reads:

- GEO-DIR/manifest.json and GEO-DIR/<norad>.tle from the GEO-region set
- groundtruth/splits.json, to skip holdout objects

Writes:

- OUT/segments.csv
- SUMMARY-DIR/year_end_counts.csv, transitions_per_object.csv, transition_types.csv and summary.json

### List GEO station-keeping state changes

Writes one row per dated state change (relocation start and end, graveyard move, end of keeping, end of north-south keeping, burn while free) for every GEO-region object, 2021-2025.

```
python -m orbit_watch.jobs.state_changes [--geo-dir DIR] [--out DIR] [--summary-dir DIR]
```

Reads:

- GEO-DIR/manifest.json and GEO-DIR/<norad>.tle from the GEO-region set (default $ORBIT_WATCH_DATA/geo)
- groundtruth/splits.json, to skip holdout objects

Writes:

- OUT/events.csv (default $ORBIT_WATCH_DATA/state_changes)
- SUMMARY-DIR/summary.json with counts per type and year (default findings/state_changes)
- SUMMARY-DIR/events.csv when it is under 2 MB

### Rank GEO objects by how far they break their own routine

belt reads every GEO-region object's element sets once and caches its held spans, daily longitude and semi-major axis and steps outside holds (with --as-of, also the state changes and holds rebuilt on data cut at the end of 2021-2024); score turns the cache and the state-change list into each relocation start's surprise in bits against the object's own stays and moves (end-of-life departures listed, not scored), a per-object rank, stay overruns, proximity flags on arrivals and the unrated list.

```
python -m orbit_watch.jobs.routine belt|score [--as-of] [--events CSV] [--out DIR] [--geo-dir DIR] [--cache PATH]
```

Reads:

- GEO-DIR/manifest.json and GEO-DIR/<norad>.tle from the GEO-region set (default $ORBIT_WATCH_DATA/geo)
- groundtruth/splits.json, to skip holdout objects
- for score: the state-change list (default findings/state_changes/events.csv)

Writes:

- belt: the cache (default $ORBIT_WATCH_DATA/routine/belt.pkl)
- score: OUT/rank.csv, unrated.csv, departures.csv, off_routine.csv, overruns.csv, flagged_arrivals.csv, belt_prior.csv and summary.json (default findings/routine)

### Write the published dataset

Writes dataset/: the state-change events with object names, owners, types and departure scores, one row per object with its rank or why it is unrated, the data card, and the evidence page for the top 30 of the rank; with --charts also one longitude chart per evidence object.

```
python -m orbit_watch.jobs.dataset [--out DIR] [--catalogue MANIFEST] [--charts] [--geo-dir DIR] [--cache PATH]
```

Reads:

- findings/state_changes, findings/state_injection, findings/state_audit_fresh and findings/routine result files
- names, owners and types from OUT/objects.csv, or from a GEO-region manifest.json with SATCAT entries given as --catalogue
- for --charts: GEO-DIR/<norad>.tle (default $ORBIT_WATCH_DATA/geo) and the belt cache (default $ORBIT_WATCH_DATA/routine/belt.pkl)

Writes:

- OUT/events.csv, OUT/objects.csv and OUT/README.md (default dataset)
- OUT/evidence/README.md
- with --charts: OUT/evidence/<norad>.png for the top 30

## Analyses

### Calibrate the detector on the ISS

Picks the detector thresholds on 2021-2022 ISS burns and scores 2023 once with them.

```
python -m orbit_watch.calibrate --tle PATH --truth CSV [CSV ...] --out DIR [--frozen]
```

Reads:

- ISS TLE history
- ISS manoeuvre lists from groundtruth/

Writes:

- OUT/detections.csv
- OUT/events_scored.csv
- OUT/calibration.json
- OUT/iss_sma.png

### Score the ISS holdout and cross-validate

Scores the frozen detector on Space-Track ISS history for 2024-2025, then runs leave-one-year-out cross-validation.

```
python -m orbit_watch.holdout --gp PATH --archive PATH --truth CSV [CSV ...] --out DIR
```

Reads:

- Space-Track gp_history for the ISS
- the archive ISS TLE history
- ISS manoeuvre lists from groundtruth/

Writes:

- OUT/holdout_2024_2025/: detections.csv, events_scored.csv, report.json and a plot
- OUT/cv_2021_2025/: detections.csv, events_scored.csv, report.json and cv_scores.png

### Injection-recovery test on the ISS

Adds synthetic steps to the real ISS series in memory and measures recall by step size and false alarms on quiet stretches.

```
python -m orbit_watch.inject --spacetrack PATH --truth CSV [CSV ...] --out DIR
```

Reads:

- Space-Track gp_history for the ISS
- ISS manoeuvre lists from groundtruth/

Writes:

- OUT/synthetic_injection_recall.csv
- OUT/synthetic_injection_report.json
- OUT/synthetic_injection_recall.png

### Score the detector on operator logs

Scores the ISS-tuned detector, and a GEO tune, against the QZS-3 and QZS-6 (GEO) manoeuvre logs.

```
python -m orbit_watch.generalise --truth-dir DIR --tle-dir DIR --out DIR [--final]
```

Reads:

- manoeuvre logs in groundtruth/
- Space-Track gp_history files, or GEO-region TLEs

Writes:

- OUT/<satellite>_events_scored.csv and <satellite>_detections.csv
- OUT/<regime>_recall.png
- OUT/report.json

### Build ground truth from operator logs

Turns the published QZSS and Fengyun manoeuvre logs into the ground-truth CSVs, one row per source row.

```
python -m orbit_watch.manoeuvre_logs --qzss-dir DIR --fengyun-dir DIR --out DIR
```

Reads:

- QZSS manoeuvre logs
- Fengyun manoeuvre logs

Writes:

- OUT/qzss_manoeuvres.csv
- OUT/fengyun_manoeuvres.csv

### Write the train and holdout split

Prints the train/holdout split of the labelled objects from its fixed rule, and writes it with --write.

```
python -m orbit_watch.truth [--write]
```

Reads:

- the labelled objects and the split rule in orbit_watch/truth.py

Writes:

- the split JSON on stdout
- groundtruth/splits.json with --write

## Evaluations

### Detector evaluation

Scores the step detector per regime (GEO, IGSO, ISS) against fixed periods and objects, with the GEO east-west and ISS recall guardrails.

```
python -m harness.evals.detector --split SPLIT [--final] [--data-dir DIR] [--settings JSON] [--truth-dir DIR] [--out JSON]
```

Reads:

- harness/evals/split.json
- a settings JSON (default harness/evals/settings/frozen.json)
- element sets under DATA-DIR (default $ORBIT_WATCH_DATA)
- ground truth under TRUTH-DIR

Writes:

- a results JSON (default harness/evals/results/<split>-<settings>.json)
- a score table on stdout

### GEO mode events evaluation

Scores the GEO mode layer against a cited list of real GEO events: whether each event's mode change appears within 45 days, and how many days off it is.

```
python -m harness.evals.mode_events [--events CSV] [--geo-dir DIR] [--out DIR]
```

Reads:

- an events CSV (default groundtruth/geo_events.csv)
- GEO-DIR/<norad>.tle from the GEO-region set (default $ORBIT_WATCH_DATA/geo)
- groundtruth/splits.json, to skip holdout objects

Writes:

- OUT/summary.json (default findings/geo_events)
- OUT/events.csv
- a score table on stdout

### GEO state changes evaluation

Scores dated state changes against the cited list of real GEO events (recall and date error per split and type) and counts false events on QZS-3, QZS-6 and Fengyun-2H while their logs show them on station; --final adds the holdout Fengyun-2F and Fengyun-4A, run once.

```
python -m harness.evals.state_changes [--split dev|all] [--final] [--events CSV] [--geo-dir DIR] [--out DIR]
```

Reads:

- an events CSV (default groundtruth/geo_events.csv)
- GEO-DIR/<norad>.tle from the GEO-region set (default $ORBIT_WATCH_DATA/geo)
- groundtruth/qzss_manoeuvres.csv and groundtruth/fengyun_manoeuvres.csv for the on-station spans
- groundtruth/splits.json, to skip holdout objects outside --final

Writes:

- OUT/eval_<split>.json (default findings/state_changes)
- OUT/eval_<split>.csv
- OUT/false_events_final.json with --final
- a score table on stdout

### GEO state changes planted-change test

Plants relocations, keeping stops, graveyard climbs and free burns into the element sets of held GEO satellites with a fixed seed, and reports recall, date error and extra events per kind and drift rate on dev and test hosts, plus false events on the untouched stretches.

```
python -m harness.evals.state_injection [--geo-dir DIR] [--out DIR] [--split dev|all] [--freeze]
```

Reads:

- GEO-DIR/manifest.json and GEO-DIR/<norad>.tle from the GEO-region set (default $ORBIT_WATCH_DATA/geo)
- harness/evals/state_injection_hosts.json, the frozen host stretches (rebuilt by --freeze from groundtruth/splits.json, groundtruth/geo_events.csv and the current code)

Writes:

- OUT/summary.json (default findings/state_injection)
- OUT/trials.csv
- a score table on stdout

### Hand audit of belt state changes

Draws the fixed 50-event audit sample from the belt's state changes, charts each sampled event, or checks and summarises the hand verdicts.

```
python -m harness.evals.state_audit sample|chart|summary [--out DIR]
```

Reads:

- findings/state_audit/events.csv, the belt list as audited (from #55)
- groundtruth/splits.json and groundtruth/geo_events.csv, to leave out holdout and test-event objects
- for chart: $ORBIT_WATCH_DATA/geo/<norad>.tle, manifest.json and $ORBIT_WATCH_DATA/geo_modes/segments.csv
- for summary: OUT/audit.csv with the hand verdicts

Writes:

- sample: the sample as CSV on stdout
- chart: one PNG per event, with neighbouring events from the audited list, and digests.json in OUT (default $ORBIT_WATCH_DATA/state_audit)
- summary: OUT/summary.json (default findings/state_audit)

### Routine score checks

checks: off-routine rows on dead objects and on QZS-3, QZS-6 and Fengyun-2H while on station, cited relocation starts flagged and cited end-of-life moves typed, stability of the top of the rank across 2021 to mid-2023 and the rest, as-of reruns on cut data, and the cited irregular and steady lists when present; planted: three or four relocations planted on a fixed rhythm in a held satellite's element sets, then one more on or off rhythm, scored in bits; audit: the blind hand-audit sample of the top 30 and 20 from the middle, with one chart per object.

```
python -m harness.evals.routine checks|planted|audit [--split dev|all] [--events CSV] [--out DIR] [--geo-dir DIR] [--cache PATH] [--irregular CSV] [--steady CSV] [--charts DIR] [--share F]
```

Reads:

- OUT/rank.csv, departures.csv, overruns.csv and belt_prior.csv from the routine job (default findings/routine)
- the belt cache from the routine job, built with --as-of for the causality check
- GEO-DIR/<norad>.tle and manifest.json (default $ORBIT_WATCH_DATA/geo)
- groundtruth/geo_events.csv, groundtruth/qzss_manoeuvres.csv, groundtruth/fengyun_manoeuvres.csv and harness/evals/state_injection_hosts.json
- groundtruth/irregular_objects.csv and groundtruth/steady_objects.csv when present

Writes:

- checks: OUT/checks_<split>.json
- planted: OUT/planted_<split>.json and OUT/planted_<split>.csv
- audit: OUT/audit_sample.csv, OUT/audit_key.csv and one PNG per sampled object (default $ORBIT_WATCH_DATA/routine/audit_charts)

### Independent cross-check

sample: fixes the objects to research before any search, the top 30 of the routine rank and 20 drawn with a fixed seed from the other objects on the state-change list; fetch: saves a copy of each source page; verify: checks every quote in the claims file word for word against its saved copy; score: matches the dated claims to the state-change list with the cited-event rule and reports coverage, agreement and every disagreement, with analyses built on public element sets kept apart.

```
python -m harness.evals.cross_check sample|fetch|verify|score [URLS]
```

Reads:

- findings/routine/rank.csv and unrated.csv, and findings/state_changes/events.csv
- groundtruth/geo_events.csv, irregular_objects.csv and steady_objects.csv, to mark objects already cited
- groundtruth/cross_check_sample.csv and groundtruth/cross_check.csv
- for verify: the saved page copies and index.csv in $ORBIT_WATCH_DATA/sources/cross_check

Writes:

- sample: groundtruth/cross_check_sample.csv
- fetch: one page copy per URL and a row in index.csv in $ORBIT_WATCH_DATA/sources/cross_check
- verify: each quote not found on its page, on stdout
- score: findings/cross_check/summary.json and claims.csv

## Tools

### Compare GEO modes with ESA's classification

Prints, per ESA 2019 class, how many objects have the matching mode in early 2021.

```
python tools/esa_classification.py ESA_TEXT SEGMENTS_CSV [--manifest PATH]
```

Reads:

- pdftotext output of ESA's Classification of Geosynchronous Objects, Issue 21
- segments.csv from the GEO modes job
- $ORBIT_WATCH_DATA/geo/manifest.json with SATCAT entries

Writes:

- a Markdown table on stdout

### Fetch element sets for the labelled objects

Fetches Space-Track gp_history for 2021-2025 for each object added in groundtruth/splits.json.

```
python tools/fetch_truth_tles.py [--cache-dir DIR]
```

Reads:

- Space-Track login in SPACETRACK_USER and SPACETRACK_PASSWORD
- groundtruth/splits.json

Writes:

- CACHE-DIR/gp_history-<norad>-2021-01-01--2026-01-01.json
- counts and file sizes on stdout

### Write the labelled-objects table

Writes groundtruth/objects.md, one row per labelled object with its burn and element-set counts.

```
python tools/truth_table.py [--tle-dir DIR]
```

Reads:

- groundtruth/splits.json and the ground-truth CSVs
- cached Space-Track gp_history files in TLE-DIR

Writes:

- groundtruth/objects.md
- the same table on stdout

### Draw the belt relocation chart

Draws every relocation and graveyard move in the belt's state-change list as date against longitude, one line per move from its start to its end.

```
python tools/relocation_chart.py [--events CSV] [--out PNG]
```

Reads:

- an events CSV from the state changes job (default findings/state_changes/events.csv)

Writes:

- a PNG (default docs/belt_relocations.png)
- the counts drawn on stdout

### Draw the LUCH stops chart

Draws where LUCH (OLYMP) and LUCH (OLYMP) 2 were parked, 2021-2025, one panel each: a bar per stop from arrival to departure, labelled with the other owner's satellite when the arrival was flagged.

```
python tools/stops_chart.py [--events CSV] [--flags CSV] [--out PNG]
```

Reads:

- an events CSV from the state changes job (default findings/state_changes/events.csv)
- a flagged arrivals CSV from the routine job (default findings/routine/flagged_arrivals.csv)

Writes:

- a PNG (default docs/luch_stops.png)
- the counts drawn on stdout

### Write the feature map

Writes docs/features.md from features.json, grouped into data jobs, analyses, evaluations and tools.

```
python tools/features_doc.py
```

Reads:

- features.json

Writes:

- docs/features.md
