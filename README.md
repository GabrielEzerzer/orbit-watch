# Orbit watch

The aim is change-point detection on public satellite orbital-element history
(TLE/GP data) to find unannounced manoeuvres, objects that keep approaching
each other, and dead objects that move. Built out of interest.

## What exists now

- `orbit_watch.elements`: parses TLEs (2-line and 3-line, checksums checked)
  and CelesTrak/Space-Track GP records in JSON and CSV into one immutable
  `ElementSet`, with a UTC epoch, the mean elements, B* and a semi-major axis
  derived the way SGP4 derives it (see the `ElementSet` docstring).
- `orbit_watch.series`: `to_series` turns element sets into an epoch-sorted,
  de-duplicated `ElementSeries` of numpy arrays per object. Epochs under 60 s apart collapse to
  the later one, because their near-zero time spacing gives the detector's slope pairs a near-zero
  time base and fake steps (issue #11); every caller gets this.
- `orbit_watch.propagate`: TEME position and velocity at given UTC times through
  the `sgp4` package, raising `PropagationError` on SGP4 error codes.
- `orbit_watch.sources`: the `ElementSource` protocol and `DirectorySource`,
  which reads element files from a local directory.
- `orbit_watch.celestrak`: `CelesTrakSource`, an `ElementSource` for CelesTrak's current GP data
  (`gp.php`, `FORMAT=json`): `load(norad_ids)` makes one `CATNR` query per object and
  `group(name)` one `GROUP` query. CelesTrak only serves the latest element set per object.
- `orbit_watch.spaceweather`: `load_space_weather()` reads CelesTrak's
  [`SW-All.csv`](https://celestrak.org/SpaceData/SW-All.csv) into a `SpaceWeather` of numpy arrays,
  one row per day from 1957-10-01: Kp per 3 hours, Ap per 3 hours, daily Ap, F10.7 observed and
  adjusted, and CelesTrak's data type (`OBS` for observed days; `INT`, `PRD` and `PRM` for
  interpolated, daily-predicted and monthly-predicted ones, which have no Kp or Ap when monthly).
  Dst (Kyoto WDC) is not loaded yet.
- `orbit_watch.spacetrack`: `SpaceTrackSource`, an `ElementSource` for Space-Track's `gp_history`
  class between two dates. It is written from Space-Track's public documentation and has never
  been run against the live API.
- `orbit_watch.modes` and `orbit_watch.jobs.geo_modes`: ESA operating modes (controlled,
  drifting, librating and the rest) of every GEO-region object in 30-day windows, 2021-2025 (below).
- `orbit_watch.jobs.extract_tle_archive`: pulls per-object TLE history out of the
  [OndroNR/tle-archive](https://github.com/OndroNR/tle-archive) git history (below).

## Manoeuvre detection on the ISS (stage 3)

`orbit_watch.detect` looks for steps in the mean semi-major axis `a` of a TLE series. For every
gap between consecutive epochs it takes the `k` epochs on each side, removes the local drag decay
(a Theil-Sen slope from pairs on the same side, so no pair straddles the gap) and takes the step as
the median after the gap minus the median before it. Medians ignore the one or two transitional
TLEs that follow a burn, which made a least-squares version report ghost steps.

The noise model is estimated from the data. At every gap the TLE scatter `sigma` is 1.4826 times
the median absolute deviation of the detrended values about each side's median, floored at half
the series' median `sigma`. The step's `z` is the step divided by the standard error of a
difference of two medians. A gap is flagged when `|z|` and `|step|`
both pass their thresholds, and within one day only the highest `|z|` is kept. Gaps whose
windows span more than 3 days, or that are longer than 2 days themselves, are not scored, so no
detection crosses an outage such as 2022-06-15..19. Only `a` is used; eccentricity and
inclination are not used yet.

`orbit_watch.calibrate` scores the detector against `groundtruth/iss_manoeuvres.csv`:

- `k`, the `|z|` threshold and the minimum `|step|` are picked by F1 on the 2021-2022 events only,
  then frozen, and 2023 is scored once with them. **2023 is the honest number.**
- An event matches a detection when its time (its date plus or minus one day when `time_utc` is
  empty) overlaps the detection's interval widened by 0.5 day, one-to-one, closest first.
- Recall counts only events with a scored gap overlapping them; the others are listed as excluded
  for coverage. Precision counts every detection in the period, and a detection that matches no
  listed event is a false positive. The NASA list is a lower bound (it has no Roscosmos
  announcements; see "With Roscosmos burns" below), so unmatched detections are leads to check,
  not findings.
- The two unplanned attitude events are scored apart from the main numbers.

It writes `calibration.json`, `detections.csv`, `events_scored.csv` and `iss_sma.png` (`a` per
year with events and detections marked). The TLE file is git-ignored, so the Kaggle run attaches
it and records its sha256 in `ATTACHED.txt`:

```
MSYS_NO_PATHCONV=1 python tools/kaggle_run.py --slug ow-calibrate --attach data/archive/25544.tle --     python -m orbit_watch.calibrate --tle data/archive/25544.tle --truth groundtruth/iss_manoeuvres.csv --out /kaggle/working/out
```

Result of the command above on Kaggle at commit `7df96a6`, with the TLE file at sha256
`e102dc92…7c51` (5,076 TLEs). A local rerun after the 60 s collapse (issue #11) and the tuning fix
(issue #10) uses 5,075 of them (one pair is under 60 s apart, and the later is kept) and chooses the
same setting with the same scores. 45 ground-truth rows fall inside the TLE history:

**Caveat on 2023:** the thresholds below were chosen on 2021-2022 only, but an earlier version of the method was scored on 2023 once before the method was changed (last note below). The clean holdout is 2024-2025 on Space-Track data; see the next section.

| | 2021-2022 (tuning) | 2023 (thresholds unseen; method partly seen, see below) |
|---|---|---|
| Precision | 24/27 = 0.89 | 16/21 = 0.76 |
| Recall | 24/25 = 0.96 | 16/17 = 0.94 |
| Reboosts | 20/20 | 12/13 |
| Debris/collision avoidance | 3/3 | 4/4 |
| Deboost | 1/1 | none |
| Test burn (aborted after 5 s) | 0/1 | none |

Frozen setting: `k = 4`, `|z| >= 12`, `|step| >= 200 m`, non-maximum suppression over 1 day. The
median TLE scatter is about 2.4 m, so `z` mostly ranks; the 200 m step threshold carries most of the
decision. Smaller burns (a 0.21 m/s reboost is about 370 m) are near that limit.

Notes on these numbers:
- Excluded for coverage: the 2022-06-16 debris avoidance, which falls in the 2022-06-15..19 outage.
- Neither unplanned attitude event (2021-07-29, 2021-10-15) produced a detection.
- 2023-11-09 (reboost) and 2023-11-10 (debris avoidance) are a day apart and gave one detection,
  which the matcher gave to the debris avoidance. One of the pair counts as missed either way.
- Unmatched detections count as false positives. Most sit on steps that are visible in the plot, so
  they may be burns missing from the list (it has no Roscosmos announcements), but they are leads,
  not findings.
- An earlier version with least-squares lines and sign-blind matching was run once before this one,
  and its 2023 score was seen (precision 16/23, recall 16/17). Its plot showed ghost steps from the
  transitional TLEs after burns, some of them matched to reboosts with the wrong sign. The median
  detector and the sign rule replaced it, and the thresholds were re-chosen on 2021-2022 alone. Even
  so, 2023 is no longer a never-seen holdout for the method, only for the thresholds.

### Clean holdout: Space-Track 2024-2025

`orbit_watch.holdout` scores the frozen setting once on Space-Track `gp_history` for the ISS
(2021-01-01 to 2025-12-31; 9,855 rows, 9,077 element sets: rows whose epochs are under 60 s apart
are one element set, and the latest issued, by `GP_ID`, is kept whatever its epoch), using
calibrate.py's matching, coverage and precision rules unchanged.
Neither the method nor the thresholds had seen 2024-2025.

```
python -m orbit_watch.holdout --gp data/spacetrack/gp_history-25544-2021-01-01--2026-01-01.json \
    --archive data/archive/25544.tle --truth groundtruth/iss_manoeuvres.csv --out findings
```

| Period | Precision | Recall |
|---|---|---|
| **2024-2025 (clean holdout)** | **27/42 = 0.64** | **27/27 = 1.00** |
| 2024 | 16/22 | 16/16 |
| 2025 | 11/20 | 11/11 |

One event (2025-04-30 debris avoidance) falls in a data gap and is excluded for coverage. The 15
unmatched detections are listed in `FINDINGS.md`; most are large steps up with very high `z`, so
the precision is a lower bound until a fuller event list (Roscosmos burns) exists.

Source check, same frozen setting: Space-Track gives 23/26 precision and 23/25 recall for 2021-2022
(archive 24/27, 24/25) and 16/22 and 16/17 for 2023 (archive 16/21, 16/17). The one lost event is
the 2021-12-03 retrograde debris avoidance: two transitional element sets that the archive lacks
pull the measured step from −461 m to about −210 m, and `z` below 12.

Leave-one-year-out cross-validation over 2021-2025 on Space-Track (tune on four years with the same
grid and rule, score the fifth): pooled **64/86 = 0.74 precision, 64/69 = 0.93 recall**. Every fold
chose `k = 4`, `|z| >= 15`; four of five kept `|step| >= 200 m` (the fold leaving out 2021 chose
300 m). Outputs: `findings/holdout_2024_2025/` and `findings/cv_2021_2025/`. Tuning matches only the
training years' events and detections, so a held-out label cannot enter a fold's tuning score
(issue #10); the fix changed no fold's setting or score on this data.

### With Roscosmos burns

`groundtruth/iss_roscosmos_manoeuvres.csv` adds 14 ISS burns from 2021-2025 that Roscosmos reported
and NASA's pages do not list. It was compiled from the Roscosmos Telegram channel and RIA Novosti
without looking at detector output (`groundtruth/README.md`). Both scoring tools take more than
one truth file and refuse an event listed in two of them. The same frozen setting, not re-chosen
(`--frozen` stops calibrate.py's choice on 2021-2022), scores both lists together:

```
python -m orbit_watch.calibrate --frozen --tle data/archive/25544.tle \
    --truth groundtruth/iss_manoeuvres.csv groundtruth/iss_roscosmos_manoeuvres.csv --out findings/combined_truth
python -m orbit_watch.holdout --gp data/spacetrack/gp_history-25544-2021-01-01--2026-01-01.json \
    --archive data/archive/25544.tle \
    --truth groundtruth/iss_manoeuvres.csv groundtruth/iss_roscosmos_manoeuvres.csv --out findings/combined_truth_holdout
```

| Source, period | NASA only: precision | recall | NASA + Roscosmos: precision | recall |
|---|---|---|---|---|
| Archive 2021-2022 | 24/27 | 24/25 | 26/27 = 0.96 | 26/27 = 0.96 |
| Archive 2023 | 16/21 | 16/17 | 20/21 = 0.95 | 20/21 = 0.95 |
| Space-Track 2021-2022 | 23/26 | 23/25 | 25/26 = 0.96 | 25/27 = 0.93 |
| Space-Track 2023 | 16/22 | 16/17 | 20/22 = 0.91 | 20/21 = 0.95 |
| **Space-Track 2024-2025 (holdout)** | 27/42 | 27/27 | **35/42 = 0.83** | **35/35 = 1.00** |

All 14 Roscosmos burns fall in scored data, and the frozen detector finds every one of them with
the right sign: steps from +521 m (2025-06-19, 0.3 m/s) to +4,913 m (2024-11-13), and −1,755 m for
the 2021-12-24 deboost. The detections are the same ones as before; only their labels change. The
misses are the ones already listed above (the aborted test burn, the 2023-11-09 reboost next to
the 2023-11-10 debris avoidance, and on Space-Track the 2021-12-03 retrograde avoidance).

Seven of the 42 holdout detections still match nothing, and two archive detections in 2021-2023
(three on Space-Track). `FINDINGS.md` lists them with the Roscosmos match for the rest. The
Roscosmos list is thinnest for September to December 2025, so the precision is still a lower
bound. The leave-one-year-out cross-validation was not rerun with the new list, because it
re-chooses the setting.

### Sensitivity: synthetic injection-recovery

`orbit_watch.inject` adds known steps in memory to quiet stretches of the real Space-Track series
and counts how many the detector recovers. All of it is synthetic and labelled so; nothing goes into
`groundtruth/`. 600 trials per size, both signs pooled; outputs in `findings/injection/`.

| Recall at step size | 100 m | 150 m | 200 m | 300 m | 500 m | 1 km |
|---|---|---|---|---|---|---|
| native cadence (about 5.6 TLEs a day), frozen | 0.01 | 0.01 | 0.52 | 0.98 | 1.00 | 1.00 |
| native, `|z| >= 6`, `|step| >= 50 m` | 0.95 | 0.98 | 0.98 | 1.00 | 1.00 | 1.00 |
| thinned to about 1 a day, frozen | 0.01 | 0.06 | 0.48 | 0.92 | 0.97 | 1.00 |
| thinned to about 1 every 2 days, frozen | 0.02 | 0.07 | 0.34 | 0.72 | 0.89 | 0.98 |

The median TLE scatter is 3.4 m, so the 200 m step floor, not `z`, sets what the frozen detector
can see. A looser floor reaches 100 m steps but adds false alarms: about 19 to 21 a year at
`|z| >= 6`, `|step| >= 50 m`, against at most 0.9 a year for the frozen setting (3 detections in
3.2 years of stretches with no listed burn within 3 days; an upper bound, since unlisted burns
count). A clean step leaves out the transitional TLEs a real burn produces, so these recalls are
upper bounds for real burns of the same size.

These figures come from the run with both truth lists (NASA and Roscosmos). With the NASA list
alone the frozen setting had 18 such detections, 5.3 a year. The Roscosmos events also remove a few
gaps (two at the native cadence) from the quiet stretches the injections are drawn from, which reshuffles the random draw, so
the pooled recall figures in the table moved by up to 0.02 from the NASA-only run, and each new
95% interval overlaps the old one. Single-sign cells in the CSV moved by up to 0.09.

### Beyond the ISS: IDS (LEO) and QZSS (GEO) manoeuvre logs

`orbit_watch.generalise` scores the detector against real operator logs
(`groundtruth/ids_manoeuvres.csv`, `groundtruth/qzss_manoeuvres.csv`; sources and credits in
`groundtruth/README.md`) on Space-Track TLE history for CryoSat-2, Jason-3, SWOT and SPOT-5 (LEO)
and QZS-3 and QZS-6 (GEO). Each score sits next to a chance baseline: the same scoring with the
logged events shifted by 7, 13 and 19 days.

```
hush run -- python tools/fetch_generalise_tles.py   # one Space-Track request per object, cached
python -m orbit_watch.generalise --truth-dir groundtruth --tle-dir data/spacetrack --out findings/generalise
```

| Regime | Frozen ISS setting, whole history | Per-regime tune, later part (not blind, see below) |
|---|---|---|
| GEO (QZS-3, QZS-6) | P 179/253 = 0.71, R 179/232 = 0.77 (chance recall about 0.10) | P 70/92, R 70/93 (k=4, z>=3, step>=1000 m) |
| LEO (4 satellites) | P 36/42 = 0.86, R 36/445 = 0.08 | P 162/260, R 162/199 (k=6, z>=40, step>=0) |

- **GEO:** the ISS setting carries over. QZS-3 events in the 2-5 km bin (nearly all east-west burns, median about 3 km in a) are
  found 135 times out of 144.
- **LEO:** the ISS setting finds about 80% of burns above 200 m (35 of 44 covered) and none of the routine ones,
  which are mostly 10-50 m. LEO TLE scatter is about 0.1 m, so a tune with no step floor finds
  most of them.
- **Not a blind holdout.** Four method changes (a 2-day late tolerance for element sets that lag
  a burn, collapsing element sets under 60 s apart, merging burns under 12 h apart, and a wider
  |z| grid) came after the test part had been scored once. With the original 0.5-day tolerance
  the tuned test part is LEO P 138/260, R 138/196 and GEO P 60/88, R 60/90. `report.json`
  (`test_part_not_blind`) and the module docstring carry the details.
- **Unmatched detections:** 60 on QZS-3 and 14 on QZS-6 at the frozen setting, listed in
  `findings/generalise/*_detections.csv`. They have not been checked against anything else.

### Labelled objects for per-regime tuning, and a blind holdout

`groundtruth/` now holds operator logs for 20 objects besides the ISS: 11 LEO satellites from
IDS, the QZSS satellites (two GEO, four IGSO) and three Fengyun GEO satellites from a published
benchmark data set. `groundtruth/splits.json` puts each one in `train` or `holdout` by a seeded
rule fixed before any detector output existed for the new objects, and `groundtruth/objects.md`
lists them (generated by `tools/truth_table.py`). Label files are read only through
`orbit_watch.truth.read_label_rows`, and element series are built only through
`orbit_watch.series.to_series`; both refuse holdout objects unless called with `final=True`.
`generalise` tunes, so it refuses `--final`; the final scorer, which scores a frozen setting
chosen on train objects, is not built yet. This is a code-path guard, not a wall: the labels are
in committed CSVs anyone can read, and the guard only stops this package's code from tuning on
the holdout by accident. Sources, caveats, the rule, each log's coverage and the sources that
were checked and not added are in `groundtruth/README.md`.

## First GEO hunt (Luch / Olymp-K)

`orbit_watch.geo` gives the sub-satellite longitude of an element set at its epoch (SGP4 to TEME,
rotated by IAU 1982 GMST, UTC standing in for UT1). `orbit_watch.geo_hunt` runs the ISS step
detector on each object's semi-major axis with thresholds set from that object's own scatter
(`|z| >= 8`, `|step| >= 10 x` median scatter; not calibrated, there is no GEO ground truth) and
writes `steps.csv`, `summary.json` and one plot per object. Kaggle rejects a kernel script above
about 1 MB, so attach one TLE file per run:

```
MSYS_NO_PATHCONV=1 python tools/kaggle_run.py --slug ow-geo-39727 --attach data/archive/39727.tle -- python -m orbit_watch.geo_hunt --tle-dir data/archive --norad 39727 --out /kaggle/working/out
```

The results are leads in `FINDINGS.md`.

## Downloads, caching and politeness

Tests never touch the network: every loader takes the fetch function or HTTP session as an
argument, and the tests pass fakes.

- **CelesTrak** blocks clients that download the same data again and again. Every CelesTrak
  download is cached under `data/celestrak/<UTC date>/` with a key made from the query
  (`gp-CATNR-25544.json`, `gp-GROUP-stations.json`, `SW-All.csv`). A query already cached today is
  read from disk and not fetched again; a new UTC day fetches it once more. A response is cached
  only after it parses, and any non-200 answer raises, so a run stops at the first error.
  Requests send the User-Agent `orbit-watch/0.1 (research prototype)`, with no name or email.
- **Space-Track** is off unless both `SPACETRACK_USER` and `SPACETRACK_PASSWORD` are set;
  `SpaceTrackSource.from_env(start, end)` returns `None` otherwise. The credentials live in the
  hush vault, so run anything that uses it as `hush run -- <command>`. The loader logs in with
  `POST /ajaxauth/login`, then asks for
  `/basicspacedata/query/class/gp_history/NORAD_CAT_ID/<id>/EPOCH/<start>--<end>/orderby/EPOCH asc/format/json`.
  It keeps under Space-Track's limits of 30 requests a minute and 300 an hour by sleeping when
  needed. Space-Track allows each object's `gp_history` to be downloaded once ever, so every
  answer is kept under `data/spacetrack/` with no expiry, and a query already there never goes
  out again. Keep that folder.

`data/` is git-ignored.

## TLE history from the OndroNR/tle-archive repo

The only no-login TLE history we found that overlaps announced ISS reboosts is the
OndroNR/tle-archive GitHub repo. An hourly job there committed CelesTrak's `TLEs/active.txt` (3LE)
from 2021-01-01 to 2023-12-28. Each version is CelesTrak's latest element set at that hour, so the
history has the element sets CelesTrak served, not every element set ever published. The repo is
about 1.94 GB, so the extraction runs on Kaggle:

```
MSYS_NO_PATHCONV=1 python tools/kaggle_run.py --slug ow-archive --     python -m orbit_watch.jobs.extract_tle_archive --out /kaggle/working/out --norad 25544 --name-regex 'LUCH|OLYMP'
```

The job makes a bare clone, streams `git log -p -U0` of `TLEs/active.txt` oldest first, and keeps
the added line 1 and line 2 of the wanted catalog numbers. `--name-regex` adds every object with a
matching name in the first version of the file in each month or in the last version.
Each line pair is checked with `parse_tle` and de-duplicated by epoch; when one epoch appears
with different lines, the first is kept and the manifest counts it under `epoch_conflicts`. It
writes `<norad>.tle` per object (2-line TLEs in epoch order) and `manifest.json` (repo URL, the
archive's head commit, the last commit that touched the file, commits walked, and per object the
names it had, its TLE count, epoch range, rejected pairs, epoch conflicts and gaps longer than 3 days). The
files arrive in `data/kaggle/ow-archive/out/out/`. A run takes about 5 minutes on Kaggle.

## Every object in the GEO region, 2021-2025

`orbit_watch.jobs.geo_belt` collects the TLE history from 2021-01-01 up to 2026-01-01 of every
object in the GEO region (active satellites, dead ones, rocket bodies and debris), one file per
object, so the detector can run on all of them.

**Population rule** (ESA's GEO-region definition): an object is in if **any** of its element sets
with an epoch in the period has mean motion 0.9 to 1.1 rev/day, eccentricity at most 0.2 and
inclination at most 70 deg (all three bounds inclusive). Every element set it has in the period is
kept, including ones outside those bounds, such as a transfer orbit before arrival or a graveyard
orbit after it. An object that was in the region only before 2021 is left out. The manifest
records the rule and the period.

**Source.** Space-Track's documentation says to use its yearly zip bundles of TLEs, not
`gp_history`, for many objects. The logged-in documentation links them to a Sync.com share
(`https://ln5.sync.com/dl/afd354190/c5cd2q72-a5qjzp4q-nbjdiqkr-cenajuqu`). Sync.com encrypts
shared files end to end and decrypts them in the browser, so a script cannot download them
without reimplementing Sync's private client. The job therefore runs on Kaggle against the CC0
mirror `vaibhavpandey12382/historical-tle-datasets`, which describes itself as Space-Track TLE
history and holds one full-catalogue file per year (`tle2021.txt` to `tle2025.txt`, 2.1 to 2.9 GB
each). The job reads any local `.txt` or `.zip` bundle, so Space-Track's own zips also work once
someone downloads them in a browser into `data/bulk/` (run Python on them with `-I`).

```
MSYS_NO_PATHCONV=1 python tools/kaggle_run.py --slug ow-geo-belt --dataset vaibhavpandey12382/historical-tle-datasets -- python -m orbit_watch.jobs.geo_belt build --source https://www.kaggle.com/datasets/vaibhavpandey12382/historical-tle-datasets --bundle '/kaggle/input/**/tle2021.txt' --bundle '/kaggle/input/**/tle2022.txt' --bundle '/kaggle/input/**/tle2023.txt' --bundle '/kaggle/input/**/tle2024.txt' --bundle '/kaggle/input/**/tle2025.txt' --also 36508 --also 41240 --also 54754 --also 27421 --out /kaggle/working/out/geo.zip
python -I -m zipfile -e data/kaggle/ow-geo-belt/out/out/geo.zip data/geo
hush run -- python -I -m orbit_watch.jobs.geo_belt satcat --out data/geo
```

`build` streams the bundles twice and never holds a whole bundle in memory, but it holds the
selected objects' element sets and the output text: about 3 GB at peak for five years (about 5
million element sets), which a Kaggle CPU kernel handles. The first pass reads
the mean motion, eccentricity and inclination columns of each pair and checks the rule; a pair
that passes is checked with `parse_tle`, and its object is selected if the pair is valid and its
epoch is in the period. The second pass parses every pair of the selected objects, keeps those
with epochs in the period, and de-duplicates by epoch as `series.to_series` does: when an epoch
appears again with different lines, the later one is kept and counted under `epoch_conflicts`.
Selection runs before that de-duplication, so an object can be selected by a pair that a later
pair at the same epoch replaces; such an object shows `by_rule: true` with `in_region_count: 0`.
`--bundle` takes paths or recursive globs (the mirror nests some years one folder deeper). `--also <norad>` (repeatable) adds an object
outside the rule; the run above adds the four LEO satellites that `generalise` uses (CryoSat-2, Jason-3,
SWOT, SPOT-5), whose Space-Track files are no longer on this machine. The manifest marks each
object `by_rule` true or false. The
output is `<norad>.tle` per object (2-line TLEs in epoch order) and `manifest.json`: the source,
the period, the rule, each bundle's name, size, sha256, line and pair counts and rejected lines
(non-blank lines that are not part of a line pair or a name line before one), and per object its
name lines (if the bundle has any), TLE count, how many of those meet the rule, epoch range,
pairs the parser rejected and epoch conflicts. On Kaggle it writes one `geo.zip`, not thousands
of files.

The full run (commit 74a831f) took about 16 minutes on Kaggle. It read 177,075,602 lines
(88,220,159 pairs) from the five files and kept 1,808 objects with 4,957,896 TLEs: 1,804 by the
rule and the four added with `--also`. That is a 184 MB `geo.zip` holding 694 MB of TLE text. The
mirror's 2021, 2022 and 2024 files end every line 1 with a backslash, which the job drops. 136
objects have sets outside the region, such as 65588, which moves from a 5 rev/day transfer orbit to
GEO. 635,284 lines were rejected; the ones looked at are 68-character lines of analyst objects
(8xxxx), which `parse_tle` refuses. 785,425 pairs restated an epoch already held with different
lines, and 8 pairs failed `parse_tle`. 1,766 objects have a last set in December 2025.

**Restated epochs.** The mirror's numbering fields differ from Space-Track's: line 1's element set
number and checksum are not the ones `gp_history` serves for the same set. The orbital fields
(line 1 up to column 64 and all of line 2 but the checksum) match. Against the `gp_history` files
of Fengyun-2H (43491) and QZS-4 (42965), every epoch the mirror holds matches the latest-issued set
(highest `GP_ID`) on those fields: 4,220 and 1,851 epochs, including all 390 and 718 epochs that
Space-Track issued more than once with different lines. So keeping the later record matches
Space-Track's latest issue. The mirror lacks 2 of 43491's 4,222 epochs.

`satcat` adds each object's SATCAT entry (`OBJECT_NAME`, `OBJECT_TYPE`, `INTLDES`, `COUNTRY`,
`LAUNCH`, `DECAY`) to `data/geo/manifest.json`, or `null` for an object the catalogue lacks. It is
one Space-Track query for the whole catalogue (Space-Track allows SATCAT once a day and asks for
combined queries), kept for good under `data/spacetrack/` beside the output folder.

## Operating modes of GEO-region objects

`orbit_watch.modes` labels each GEO-region object's operating mode through time from its mean
longitude, drift rate and inclination. It is layer 1 of a routine model for the belt: the mode
changes and their dates matter as much as the labels. `orbit_watch.jobs.geo_modes` runs it over
every object of `data/geo`:

```
python -m orbit_watch.jobs.geo_modes --geo-dir data/geo --out data/geo_modes
```

The job skips the four LEO objects that the manifest marks `by_rule: false`. It also skips the
holdout objects of `groundtruth/splits.json`, taken from `truth.load_splits` before any file is
opened; there are 5 in this data. It writes one row per segment (start, end, mode, windows,
element sets, longitude arc, mean drift, inclination range) to `data/geo_modes/segments.csv`,
which is git-ignored. The summary goes to `findings/geo_modes/`: `year_end_counts.csv`,
`transitions_per_object.csv`, `transition_types.csv` and `summary.json`. The full run over 1,799
objects took 227 s on this laptop. Earlier runs, with the files not yet in the disk cache, took
5 to 12 minutes.

**Modes.** The classes are ESA's, from ESA Space Debris Office, *Classification of
Geosynchronous Objects*, Issue 21.0, 19 July 2019, GEN-DB-LOG-00270-OPS-SD, status at
1 January 2019. Section 2 defines the classes and table 1 (p. 6) the region. ESA does not host the
report publicly; the copy read is at
<https://astronomer.ru/data/0128/Classification_of_Geosynchronous_Objects_I21R0.pdf>. Issue 21
is the newest issue that could be found. Later issues exist (a conference paper cites Issue 23,
GEN-DB-LOG-00290-OPS-SD), but no copy was reachable.

| mode | ESA | meaning and rule |
|---|---|---|
| `controlled_lon_inc` | C1 | longitude held, and the window's median inclination at most 0.3 deg (ESA's bound), or the window lies in an excursion above it between two windows at 0.3 deg or less at most a year apart, since ESA accepts control at larger angles within one year |
| `controlled_lon` | C2 | longitude held, and the inclination above 0.3 deg with no return to it seen within a year |
| `drifting` | D | not held, and either circulating past both potential maxima or manoeuvring inside the window |
| `librating_75E` | L1 | free and trapped in the well of the stable point at 75 deg E |
| `librating_105W` | L2 | free and trapped in the well of the stable point at 105 deg W |
| `librating_both` | L3 | free, above the lower barrier but below the higher one, so it swings over both wells |
| `inclined` | I | median inclination above 25 deg (ESA's bound) |
| `undetermined` | Ind | too few element sets, or held still where a free object could sit as still (a librator's turning point) and no burn or longer hold shows control |
| `out_of_region` | – | median semi-major axis outside 37,948-46,380 km or eccentricity above 0.25 (ESA table 1: the GEO, IGO and EGO classes together) |

Graveyard objects above GEO still read as `drifting`, as they do in ESA's list. ESA's C4
(controlled drift) is not separated, because telling it from D needs manoeuvre detection, the next
layer.

**How a window is classified.** The period from 2021-01-01 to 2026-01-01 is cut into 30-day
windows, laid backwards from 2026-01-01 so that every object shares the grid (the first window is
26 days). Each window is classified from its own element sets, and adjacent windows with the same
mode are merged into segments. Thirty days holds a full east-west keeping cycle (about two weeks
for most operators) and dates a relocation to within a month. The thresholds and their sources:

- A window needs at least 5 element sets spanning 10 days; otherwise it is `undetermined`, because
  fewer sets cannot give a drift rate.
- Longitude is the mean longitude (node + argument of perigee + mean anomaly - GMST), the quantity
  ESA tabulates. The sub-satellite longitude would add an inclined orbit's daily figure-eight.
- A window is held when the 5th-95th percentile spread of its longitude is at most 0.3 deg. ITU
  Radio Regulations No. 22.6 sets +-0.1 deg east-west for geostationary stations. 0.3 leaves room
  for TLE noise and sits in the gap of the spread histogram: in 150 sampled objects, 2,627
  windows spread below 0.15 deg and 147 between 0.15 and 0.5 deg.
- A held window counts as control only if a 90-day run of three windows that includes it is also
  held, or if it is stiller than the natural acceleration lets a free object be. A librator at its
  turning point also sits still for weeks. Within about 6 deg of a stable point or 2 deg of a
  barrier a free path bends less than 0.3 deg in 90 days, so there a held run counts only if it
  holds a burn, or if the consecutive held windows around it spread less than half of what a free
  path bends over their whole span.
- Wide-box keepers (Meteosat at 0 deg E uses a box about 1.3 deg wide) cross their box under the
  natural acceleration and burn at the edge. A window counts as control if it and some 90-day run
  that includes it stay within 1.5 deg, and the run holds a burn. Among 90-day runs with a burn in
  250 sampled objects, 933 spread under 1 deg, 10 spread 1-3 deg and the rest 3 deg or more.
- A burn is a window whose longitude leaves a free path (the robust scatter about a quadratic in
  time is above 0.02 deg; free librators sit near 0.001 deg, 95th percentile 0.007 deg) while
  the windows on either side do not lie on one free path either. That second test fits a cubic
  through both neighbours with its curvature pinned to the natural acceleration. In a seeded
  sample of 400 objects it leaves 0.42 % of 2,153 free-librator windows above 0.02 deg (99th
  percentile 0.017 deg), and 99.5 % of keeper windows and every relocation above it. A window
  of poor element sets between two windows of one free path is therefore no burn. Where a
  neighbour has too little data (a gap), the nearest window with data on that side, up to 3
  windows out, stands in for it. With none on one side (the ends of the record, a longer gap),
  the window's own misfit counts only if it stays above 0.02 deg once its 3 worst element sets
  are dropped: a bad set is one set whatever went wrong in it, while a burn moves every set
  after it. Rejecting sets by semi-major axis instead would miss bad sets whose mean motion is
  fine, such as the one 0.10 deg off in 43646's window of 2024-07-10.
- Energy decides between trapped and drifting. With the tesseral potential of the EGM96 (2,2),
  (3,1) and (3,3) terms, each scaled by Kaula's inclination function for the object's
  inclination, `drift**2 / 2 + potential(longitude)` is conserved for a free object. Comparing
  it with the two potential maxima tells whether the object is trapped in a well, above the lower
  barrier, or circulating. The derived stable points are 75.1 deg E and 104.9 deg W (ESA section
  2 gives 75 E and 105 W).
- Window estimates of that energy still swing by a few per cent with the phase of the libration,
  because luni-solar terms and degree 4 and up are left out. Each run of free windows therefore
  takes one energy, the median of its windows. A run goes on through held windows (a turning
  point, a barrier top) and ends at a burn, or between two windows that each follow a free path
  but clearly not the same one: the pinned fit through both leaves more than 0.06 deg (three
  times the burn limit). At the burn limit this split fired on 6 of 1,968 pairs of clean
  free-librator windows in a seeded sample of 400 objects, all of them 43355 at 14.8 deg, at up
  to 0.051 deg; none reaches 0.06. A drift change of 0.011 deg/day or more between two windows
  still leaves more than 0.06 deg (on synthetic librators the misfit is about 5.6 times the
  change, at any longitude or inclination tried). A run whose path passes over a barrier is
  not trapped behind it, whatever its energy reads: over the high barrier it is drifting, and
  an eastern or western librator that passes over the low one is `librating_both`.

**Year-end counts.** Each object is counted in the mode of its segment that holds 31 December
12:00 UTC. `no_data` is an object whose history does not reach that instant, mostly later
launches.

| mode | 2021 | 2022 | 2023 | 2024 | 2025 |
|---|---|---|---|---|---|
| controlled_lon_inc | 347 | 357 | 367 | 366 | 350 |
| controlled_lon | 152 | 152 | 156 | 155 | 164 |
| drifting | 876 | 891 | 924 | 965 | 1,012 |
| librating_75E | 112 | 113 | 114 | 118 | 123 |
| librating_105W | 35 | 41 | 36 | 35 | 35 |
| librating_both | 18 | 18 | 21 | 20 | 20 |
| inclined | 21 | 21 | 21 | 21 | 20 |
| undetermined | 36 | 36 | 32 | 45 | 31 |
| out_of_region | 12 | 10 | 4 | 4 | 2 |
| no_data | 190 | 160 | 124 | 70 | 42 |

**Transitions.** With undetermined segments ignored (their neighbours then merge), 1,476 of the
1,799 objects keep one mode for the whole period, 132 change once, 97 change twice and 94 change
three times or more. The most common changes:

- `controlled_lon` to `drifting`: 173.
- `drifting` to `controlled_lon_inc`: 159, mostly arrivals.
- `drifting` to `controlled_lon`: 118.
- `controlled_lon_inc` to `drifting`: 100.
- `controlled_lon_inc` to `controlled_lon`: 77, where north-south keeping stops. Each is dated
  to the window where the inclination passes 0.3 deg, including stops in the record's last
  year and stops followed within a year by retirement. 16 go the other way: 12 where the
  inclination is brought down from 0.5-3 deg, and three are the record-start case under the
  limits below.

No object moves between two libration classes. When each window took its own energy, 81 changes
went between `librating_both` and `librating_75E` or `librating_105W`, about 30 each way for the
eastern well. The cause was not noise in the element sets but the energy estimate itself: from
the equatorial potential it swung with the phase of the libration, for Intelsat 804 (25110) from
0.909 to 1.004 of the high barrier's energy, more than these objects' margin to a barrier. Kaula's
inclination factors narrow that swing (0.952 to 1.005 for Intelsat 804), and one energy per run
with the barrier-crossing check removes the flips. Counted over all segments, most changes go
into or out of `undetermined` (`findings/geo_modes/transition_types.csv`).

**Against ESA.** No ESA issue for 2021-2025 could be reached, so there is no same-date
validation. The table puts ESA's counts for 1 January 2019 beside ours at the end of 2021, three
years later. ESA's counts are for the 1,578 objects with orbital data in Issue 21: each class's
count is the opening sentence of its list in section 4 (page given), and the totals match the
abstract (p. 3) and section 7 (p. 216). The table is context, not a check, and nothing was tuned
to it.

| class | ESA, 1 Jan 2019 | source | ours, 31 Dec 2021 |
|---|---|---|---|
| C1 | 372 | 4.1, p. 51 | 347 |
| C2 | 150 | 4.2, p. 83 | 152 |
| C4 | 7 | 4.3, p. 96 | (in drifting or librating) |
| D | 831 | 4.4, p. 97 | 876 |
| L1 | 127 | 4.5, p. 167 | 112 |
| L2 | 46 | 4.6, p. 178 | 35 |
| L3 | 22 | 4.7, p. 182 | 18 |
| I | 21 | 4.8, p. 191 | 21 |
| Ind | 2 | 4.9, p. 193 | 36 |
| total | 1,578 | p. 3, p. 216 | 1,597 (1,799 less 190 with no data and 12 out of region) |

Why the populations differ:

- ESA classifies everything in its DISCOS database. That includes 206 objects classified from JSC
  Vimpel data and 9 from KIAM (p. 216), many of which have no public TLEs. Ours covers the public
  catalogue only, so old librators known only to Vimpel or KIAM are missing.
- Three years of launches, end-of-life manoeuvres and re-orbits separate the two dates.
- ESA classifies each object from its history of orbital data and corrects some by hand, mainly
  small librators that its routine called controlled (section 4, p. 50). We classify 30-day
  windows, with only a free run's energy shared between them, so at a given instant a satellite
  between keeping cycles, or a librator at a turning point, can be undetermined.
- Ours counts every object that was in the region at any time in 2021-2025, less the 5 holdout
  objects. ESA's C4 objects land in our drifting or librating classes.

**Per-object check.** Section 3 of the same report (pp. 10-49) lists each object's class by COSPAR
id. `tools/esa_classification.py` reads it from the PDF's text and prints the table below; its
docstring gives the two commands. A row counts only when it sits on one line and its page
reference falls inside the section 4 chapter of its class, because in places the PDF text shifts
the right-hand columns by a line. That keeps 1,342 rows. Matching them by COSPAR id to our first
determined mode before 1 July 2021 gives 1,272 objects with a mode:

| ESA 2019 | objects | same mode in early 2021 | main other modes |
|---|---|---|---|
| C1 | 332 | 278 (84%) | drifting 25, controlled_lon 25 |
| C2 | 117 | 88 (75%) | drifting 22, controlled_lon_inc 4 |
| C4 | 1 | 0 (0%) | controlled_lon_inc 1 |
| D | 675 | 663 (98%) | librating_75E 5, librating_both 2 |
| L1 | 88 | 82 (93%) | drifting 2, controlled_lon_inc 2 |
| L2 | 29 | 24 (83%) | controlled_lon 4, drifting 1 |
| L3 | 14 | 10 (71%) | librating_75E 2, drifting 2 |
| I | 14 | 14 (100%) | |
| Ind | 2 | 0 (0%) | librating_105W 1, drifting 1 |

Controlled satellites that now read as drifting were not checked one by one; retirements and
relocations in the two years between the dates would explain them. The four L2 objects we call
controlled sit within about 1.5 deg of 105 deg W, where a free path bends so little that a held
run is weak evidence (see the limits below); they were not examined one by one. The two L3
objects we call drifting, Intelsat 804 (25110) and Cosmos 2479 (38101), pass over the high barrier in
2021-2025.

**Known limits.** The older ones are also `shortcut:` comments in `orbit_watch/modes.py`.

- A mode change is dated to the 30-day window that holds it, not to the day.
- A record that starts or ends inside an excursion of the inclination above 0.3 deg reads C2
  there, because the return to 0.3 deg, if any, is not in the record. A keeper that lets its
  inclination run past 0.3 deg between north-south burns shows a C1 -> C2 change in its last
  months, or a C2 -> C1 change in its first. On the belt that gives at least three of each:
  41869, 41911 and 44978 in November and December 2025, and 29155, 36411 and 40732 in early
  2021, all keepers whose inclination rises to 0.4-0.5 deg and comes back about every ten
  windows.
- Across a gap the two-window burn test can span up to 7 windows, and a free path pinned to the
  natural acceleration fits worse over a longer span: on free librators of that 400-object
  sample it leaves 1 % above 0.02 deg over 3 windows, 23 % over 4 and 63 % over 5. Only a good
  fit clears a window, so a noisy window beside a gap is still called a burn more often than
  one with data on both sides.
- A noisy window between two neighbours with data is still a burn when the pinned fit through
  the neighbours misses too. 43355 (14.8 deg) reads `drifting` in its window of 2022-02-21: its
  element sets scatter by 0.03-0.05 deg around that turning point, the last ones of the window
  before sit up to 0.19 deg off the two-window fit, and its curvature is about 20 % above the
  model's (-0.0021 against -0.0017 deg/day^2), so the two-window fit leaves 0.062 deg. Dropping
  the 3 worst sets of every window would clear it, but it also drops 31 % of the burns found in
  keeper windows, which the wide-box and stable-point rules rely on.
- The run split's pinned fit through two windows is plain least squares, so a bad set in a
  sparse window can split a free run: 43396 splits in July and August 2023 (windows of 7 and 8
  sets, 0.07 and 0.12 deg) though the two-window fits around them leave 0.010 and 0.028 deg.
  Each piece then takes its own median energy; there it is far from a barrier and the label
  holds.
- The potential keeps only the resonant terms of degree 2 and 3, so an energy within about 2 % of
  a barrier can fall on the wrong side when the run's path does not cross it. Syncom 3 (858),
  D for ESA, turns back 3 deg east of the high barrier in early 2023 and reads `librating_both`, but
  its last run, after a gap in its element sets in 2025, reads `drifting`.
- A relocation slower than about 0.45 deg/day with no burn inside a window reads as librating,
  because C4 is not separated.
- Within about 6 deg of a stable point or 2 deg of a barrier, a keeper with no burn big enough to
  see reads undetermined until its hold outlasts a free object's. North-south keeping (an
  inclination held near 0) would prove control sooner but is not used. A librator there whose
  element sets scatter enough to pass the burn test still reads controlled at its turning points.
- One wild element set in a sparse window can break the held test and the window's own fit:
  Star One D2 (49055) has one on 2022-06-11 (semi-major axis 43,606 km, longitude about 17 deg off), and that
  window reads `drifting` between two controlled segments at the same slot.
- A wide-box keeper that goes a whole 90-day run without a burn reads as librating or undetermined
  for those windows.
- The EGM96 coefficients in the code are quoted from Lemoine et al., NASA/TP-1998-206861. They were
  checked only through the stable points and barriers they give.

## Running the tests

```
python -m venv .venv
.venv/Scripts/python -m pip install -e .[dev]   # .venv/bin/python on Linux/macOS
.venv/Scripts/python -m pytest -q
```

Test fixtures live in `mock/`; `mock/README.md` says where each one came from.

## Running on Kaggle CPU

When the laptop is busy, `tools/kaggle_run.py` runs a command on a private Kaggle CPU kernel
against the exact commit at HEAD (it refuses a working tree with uncommitted or untracked changes):

```
python tools/kaggle_run.py --slug ow-suite -- pytest -q
```

It needs the `kaggle` CLI installed and authenticated. It embeds `git archive HEAD` and the commit
SHA in a generated script kernel (written to `data/kaggle/<slug>/push/`), pushes it with
`kaggle kernels push`, checks `kaggle kernels status` every 30 seconds, and downloads the outputs
to `data/kaggle/<slug>/out/`: `COMMIT.txt`, `run.log` (stdout and stderr together),
`exit_code.txt`, Kaggle's own `<slug>.log`, and `out/` with anything the command wrote under
`/kaggle/working/out`. It checks that
`COMMIT.txt` matches the pushed commit, prints the end of `run.log` and exits with the command's
exit code. The default command is `pytest -q`. `--attach PATH` (repeatable) embeds an uncommitted file, such as
git-ignored data, at the same relative path next to the source; the kernel writes the sha256 of
each attached file to `ATTACHED.txt`, and the script checks it against the local file. The kernel has internet access because it runs
`pip install -e .[dev]`; each push makes a new version of the kernel named by `--slug`.
`--dataset OWNER/SLUG` (repeatable) mounts a Kaggle dataset read-only under `/kaggle/input`. The
embedded tree leaves out `findings/` (plots and tables, not code) so the script stays under
Kaggle's limit of about 1 MB.

On the owner's Windows machine `kaggle datasets create` fails from Git Bash (forward slashes end up
in the upload's temporary file name); run it from PowerShell if a dataset is ever needed.
`kaggle kernels push` works from either shell. From Git Bash, set `MSYS_NO_PATHCONV=1` when the
command has an absolute path such as `/kaggle/working/out`: otherwise Git Bash rewrites it to
`C:/Program Files/Git/kaggle/working/out`, and `kaggle_run.py` refuses the command.
