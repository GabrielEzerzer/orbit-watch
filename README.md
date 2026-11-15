# Orbit watch

Change-point detection on public satellite orbital-element history (TLE/GP data) to find
unannounced manoeuvres. It parses element sets, propagates them with SGP4, detects steps in the
mean semi-major axis (and optionally inclination), scores the detector against cited manoeuvre
logs, and labels the operating mode of every object in the GEO region. Built out of interest.

Results and leads are in `FINDINGS.md` and `findings/`. Ground-truth sources, caveats and the
train/holdout split are in `groundtruth/README.md`. Each module's docstring gives its rules in
full; this file says what exists, how to run it and where the numbers are.

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
| `orbit_watch.spaceweather` | `load_space_weather()`: CelesTrak `SW-All.csv` (Kp, Ap, F10.7) as numpy arrays |
| `orbit_watch.detect` | The step detector: Theil-Sen detrend per side, median step, robust `z`, optional inclination channel |
| `orbit_watch.calibrate` | Chooses and scores the ISS setting against the NASA (and Roscosmos) lists |
| `orbit_watch.holdout` | Scores the frozen setting on Space-Track ISS history, plus leave-one-year-out CV |
| `orbit_watch.inject` | Synthetic injection-recovery on the real ISS series |
| `orbit_watch.manoeuvre_logs`, `truth` | Build the IDS, QZSS and Fengyun label CSVs; the only reader of label files, with the holdout guard |
| `orbit_watch.generalise` | Scores the detector on IDS (LEO) and QZSS (GEO) logs |
| `orbit_watch.geo`, `geo_hunt` | Sub-satellite longitude; the first uncalibrated GEO step hunt |
| `orbit_watch.modes` | ESA operating mode of a GEO-region object per 30-day window |
| `orbit_watch.jobs.*` | Long jobs: `extract_tle_archive`, `geo_belt`, `geo_modes` |
| `harness.evals.detector` | The frozen per-regime evaluation; nothing in `orbit_watch` imports `harness` |

## Data

`data/` is git-ignored. Inputs live there:

| Path | Contents | Made by |
|---|---|---|
| `data/archive/<norad>.tle` | OndroNR/tle-archive history, 2021-01-01 to 2023-12-28 | `jobs.extract_tle_archive` |
| `data/spacetrack/` | Space-Track `gp_history` and SATCAT answers, kept for good | `SpaceTrackSource`, `tools/fetch_*_tles.py`, `geo_belt satcat` |
| `data/geo/` | `<norad>.tle` and `manifest.json` for every GEO-region object, 2021-2025 | `jobs.geo_belt` |
| `data/geo_modes/segments.csv` | One row per mode segment | `jobs.geo_modes` |
| `data/celestrak/<UTC date>/` | CelesTrak downloads, cached per UTC day | `celestrak`, `spaceweather` |
| `data/kaggle/<slug>/` | Kaggle kernel pushes and outputs | `tools/kaggle_run.py` |

Download rules:

- **CelesTrak** blocks clients that download the same data again and again. A query already
  cached today is read from disk; a response is cached only after it parses, and any non-200
  answer raises. Requests send the User-Agent `orbit-watch/0.1 (research prototype)`.
- **Space-Track** is off unless `SPACETRACK_USER` and `SPACETRACK_PASSWORD` are set; the
  credentials live in the hush vault, so run anything that uses it as `hush run -- <command>`. It
  keeps under 30 requests a minute and 300 an hour. Space-Track allows each object's `gp_history`
  to be downloaded once, so every answer under `data/spacetrack/` is kept with no expiry and never
  fetched again. Keep that folder.

## Running each job and tool

Commands that need the ISS TLE file on Kaggle attach it (`--attach`); see "Running on Kaggle CPU".

| Job | Command | Output |
|---|---|---|
| ISS calibration (tune on 2021-2022, score 2023) | `python -m orbit_watch.calibrate --tle data/archive/25544.tle --truth groundtruth/iss_manoeuvres.csv --out <dir>` | `calibration.json`, `detections.csv`, `events_scored.csv`, `iss_sma.png` |
| ISS, frozen setting, both truth lists | `python -m orbit_watch.calibrate --frozen --tle data/archive/25544.tle --truth groundtruth/iss_manoeuvres.csv groundtruth/iss_roscosmos_manoeuvres.csv --out findings/combined_truth` | `findings/combined_truth/` |
| ISS holdout 2024-2025 and CV | `python -m orbit_watch.holdout --gp data/spacetrack/gp_history-25544-2021-01-01--2026-01-01.json --archive data/archive/25544.tle --truth groundtruth/iss_manoeuvres.csv --out findings` | `findings/holdout_2024_2025/`, `findings/cv_2021_2025/` |
| ISS holdout, both truth lists | the same with `--truth groundtruth/iss_manoeuvres.csv groundtruth/iss_roscosmos_manoeuvres.csv --out findings/combined_truth_holdout` | `findings/combined_truth_holdout/` |
| Injection-recovery | `python -m orbit_watch.inject --spacetrack data/spacetrack/gp_history-25544-2021-01-01--2026-01-01.json --truth groundtruth/iss_manoeuvres.csv groundtruth/iss_roscosmos_manoeuvres.csv --out findings/injection` | `findings/injection/` |
| Label CSVs from operator logs | `python -m orbit_watch.manoeuvre_logs --ids-dir data/sources/ids --qzss-dir data/sources/qzss --fengyun-dir data/sources/fengyun --out groundtruth` | `groundtruth/*_manoeuvres.csv` |
| Generalisation (IDS, QZSS) | `python -m orbit_watch.generalise --truth-dir groundtruth --tle-dir data/spacetrack --out findings/generalise` | `findings/generalise/` |
| Frozen per-regime eval | `python -m harness.evals.detector --split dev --data-dir data [--settings harness/evals/settings/inc-channel.json]` | `harness/evals/results/<split>-<settings>.json` |
| GEO hunt (Luch / Olymp-K) | `python -m orbit_watch.geo_hunt --tle-dir data/archive --norad 39727 --out out` | `steps.csv`, `summary.json`, one plot per object |
| TLE archive extraction (Kaggle, about 5 min) | `python -m orbit_watch.jobs.extract_tle_archive --out /kaggle/working/out --norad 25544 --name-regex 'LUCH\|OLYMP'` | `<norad>.tle`, `manifest.json` |
| GEO-region history (Kaggle, about 16 min) | see "Every object in the GEO region" | `data/geo/` |
| GEO operating modes (about 2 min) | `python -m orbit_watch.jobs.geo_modes --geo-dir data/geo --out data/geo_modes` | `data/geo_modes/segments.csv`, `findings/geo_modes/` |

Tools:

- `hush run -- python tools/fetch_generalise_tles.py`: Space-Track history for the six generalisation satellites, once each.
- `hush run -- python tools/fetch_truth_tles.py`: Space-Track history for the other objects in `groundtruth/splits.json`.
- `python tools/truth_table.py`: regenerates `groundtruth/objects.md`.
- `python tools/esa_classification.py i21.txt data/geo_modes/segments.csv`: ESA's 2019 per-object classes beside our first 2021 mode (the docstring gives the `pdftotext` step).
- `python tools/kaggle_run.py`: runs a command on Kaggle CPU (below).

## Results

### ISS (`FINDINGS.md`, `findings/`)

Frozen setting: `k = 4`, `|z| >= 12`, `|step| >= 200 m`, non-maximum suppression over 1 day,
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

- 2023 is unseen by the thresholds but not by the method: an earlier detector was scored on it
  once before it was replaced. 2024-2025 is the clean holdout.
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

### Beyond the ISS: IDS (LEO) and QZSS (GEO)

`findings/generalise/`, on CryoSat-2, Jason-3, SWOT and SPOT-5 (LEO) and QZS-3 and QZS-6 (GEO);
chance recall comes from the logs shifted by 7, 13 and 19 days.

| Regime | Frozen ISS setting, whole history | Per-regime tune, later part (not blind) |
|---|---|---|
| GEO | P 179/253 = 0.71, R 179/232 = 0.77 (chance recall about 0.10) | P 70/92, R 70/93 (k=4, z>=3, step>=1000 m) |
| LEO | P 36/42 = 0.86, R 36/445 = 0.08 | P 162/260, R 162/199 (k=6, z>=40, step>=0) |

The ISS setting carries over to GEO east-west burns (about 3 km in `a`) and misses routine LEO
burns (10-50 m). The tuned later part is not a blind holdout: four method changes came after it
was first scored (`report.json`, `test_part_not_blind`, and the module docstring). The unmatched
QZS-3 and QZS-6 detections have not been checked against anything else.

### Frozen per-regime evaluation (`harness/evals/`)

`harness/evals/split.json` fixes `train` (train objects of `groundtruth/splits.json`, 2021-2023),
`dev` (the same objects, 2024-2025) and `test` (holdout objects, 2021-2025, refused without
`--final`). The settings JSON gives the detector setting per regime (ISS, LEO, GEO, IGSO). Its
coverage, matching and counting rules are fixed in `harness/evals/detector.py`, so no detector
change can move them. Label files are read only through `orbit_watch.truth.read_label_rows` and
series built only through `to_series`, both of which refuse holdout objects unless
`final=True`; that is a code-path guard against tuning on the holdout by accident, not a wall.

#### Where the detector hill-climb stands

Paused (issue #22, which holds the next rounds and the open measurement decisions). The kept
setting is `harness/evals/settings/inc-channel.json`: the ISS setting in every regime plus the
inclination channel on GEO (`inc_z_min` 12, `inc_step_min_deg` 0.011). Scores
(`harness/evals/results/`):

| Target | train | dev |
|---|---|---|
| LEO recall on burns of 50 m or more, >= 0.9 | MISS: 4/18 = 0.222 | MISS: 11/40 = 0.275 |
| LEO false alarms <= 1 per object-year | PASS: 0.15 | PASS: 0.00 |
| GEO recall east-west, >= 0.9 | PASS: 36/39 = 0.923 | PASS: 33/34 = 0.971 |
| GEO recall north-south, >= 0.8 | MISS: 3/17 = 0.176 | MISS: 1/14 = 0.071 |
| GEO false alarms <= 1 per object-year | MISS: 1.67 | MISS: 3.58 |
| IGSO false alarms <= 1 per object-year | PASS: 0.00 (no IGSO event covered) | PASS: 0.00 |
| ISS recall >= 0.95 (guardrail) | MISS: 45/48 = 0.938 | PASS: 35/35 = 1.000 |

A round is kept only if its target improves, no regime's recall drops on train or dev, no
regime's false alarms rise, and the ISS stays at 45/48 on train and 35/35 on dev or better. Failed rounds are reverted with `git revert`. The
test split was scored once, at the FROZEN baseline (`results/test-frozen.json`), and stays
reserved for the end of the climb.

### GEO hunt (Luch / Olymp-K)

Uncalibrated leads for five objects, in `FINDINGS.md` and `findings/geo_*.png`,
`findings/geo_steps.csv`.

### Every object in the GEO region, 2021-2025

`orbit_watch.jobs.geo_belt` collects every element set from 2021 to 2025 of every object that was
in the GEO region (ESA's definition: mean motion 0.9-1.1 rev/day, eccentricity at most 0.2,
inclination at most 70 deg) at any epoch in the period. Space-Track's own yearly bundles are
behind an end-to-end encrypted share, so it runs on Kaggle against the CC0 mirror
`vaibhavpandey12382/historical-tle-datasets`, whose orbital fields match Space-Track's
latest-issued sets on the two objects compared (Fengyun-2H, QZS-4). It reads any local `.txt` or
`.zip` bundle, so Space-Track's zips also work.

```
MSYS_NO_PATHCONV=1 python tools/kaggle_run.py --slug ow-geo-belt --dataset vaibhavpandey12382/historical-tle-datasets -- python -m orbit_watch.jobs.geo_belt build --source https://www.kaggle.com/datasets/vaibhavpandey12382/historical-tle-datasets --bundle '/kaggle/input/**/tle2021.txt' --bundle '/kaggle/input/**/tle2022.txt' --bundle '/kaggle/input/**/tle2023.txt' --bundle '/kaggle/input/**/tle2024.txt' --bundle '/kaggle/input/**/tle2025.txt' --also 36508 --also 41240 --also 54754 --also 27421 --out /kaggle/working/out/geo.zip
python -I -m zipfile -e data/kaggle/ow-geo-belt/out/out/geo.zip data/geo
hush run -- python -I -m orbit_watch.jobs.geo_belt satcat --out data/geo
```

The `--also` objects are the four LEO satellites `generalise` reads from `data/geo/`. The run kept
1,808 objects with 4,957,896 TLEs (1,804 by the rule). The manifest records the rule, each
bundle's sha256 and per-object counts.

### Operating modes of GEO-region objects

`orbit_watch.modes` labels each object's mode per 30-day window with ESA's classes (*Classification
of Geosynchronous Objects*, Issue 21.0, 2019): `controlled_lon_inc` (C1), `controlled_lon` (C2),
`drifting` (D), `librating_75E` (L1), `librating_105W` (L2), `librating_both` (L3), `inclined`
(I), `undetermined` (Ind) and `out_of_region`. The rules and their sources are in the module
docstring. The job skips the four `--also` objects and the 5 holdout objects, so 1,799 objects are
classified. Year-end counts, transitions and the summary are in `findings/geo_modes/`; 1,477
objects keep one mode for the whole period. Against ESA's per-object list for 1 January 2019
(`tools/esa_classification.py`), 84% of ESA's C1 objects and 98% of its D objects read the same
mode in early 2021. Known limits are tracked in issues #21, #28, #29 and #30.

## Running on Kaggle CPU

`tools/kaggle_run.py` runs a command on a private Kaggle CPU kernel against the exact commit at
HEAD (it refuses a dirty working tree):

```
python tools/kaggle_run.py --slug ow-suite -- pytest -q
```

It needs the `kaggle` CLI installed and authenticated. It embeds `git archive HEAD` (without
`findings/`, to stay under Kaggle's limit of about 1 MB) and the commit SHA in a generated script,
pushes it, polls its status every 30 seconds and downloads the outputs to
`data/kaggle/<slug>/out/`: `COMMIT.txt`, `run.log`, `exit_code.txt` and `out/` with anything
written under `/kaggle/working/out`. It checks `COMMIT.txt` against the pushed commit and exits
with the command's exit code.

- `--attach PATH` (repeatable) embeds an uncommitted file, such as git-ignored data, at the same
  relative path; the kernel records each file's sha256 in `ATTACHED.txt`, which is checked
  against the local file. Kaggle rejects a script above about 1 MB, so attach one TLE file per run.
- `--dataset OWNER/SLUG` (repeatable) mounts a Kaggle dataset under `/kaggle/input`.
- From Git Bash, set `MSYS_NO_PATHCONV=1` when the command has an absolute path such as
  `/kaggle/working/out`; otherwise Git Bash rewrites it and `kaggle_run.py` refuses the command.
  `kaggle datasets create` fails from Git Bash on Windows; run it from PowerShell.
