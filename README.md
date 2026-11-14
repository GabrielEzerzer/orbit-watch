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

Result of the command above on Kaggle at commit `7df96a6` (the detector and calibration code are
unchanged since then), with the TLE file at sha256 `e102dc92…7c51` (5,076 TLEs). 45 ground-truth
rows fall inside the TLE history:

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
(2021-01-01 to 2025-12-31; 9,855 rows, 9,080 element sets once rows within 1 s are merged (9,077 once epochs under 60 s apart also collapse) and the
latest-issued one kept), using calibrate.py's matching, coverage and precision rules unchanged.
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
| native cadence (about 5.6 TLEs a day), frozen | 0.00 | 0.03 | 0.51 | 0.98 | 1.00 | 1.00 |
| native, `|z| >= 6`, `|step| >= 50 m` | 0.97 | 0.97 | 0.98 | 1.00 | 1.00 | 1.00 |
| thinned to about 1 a day, frozen | 0.00 | 0.04 | 0.46 | 0.91 | 0.99 | 1.00 |
| thinned to about 1 every 2 days, frozen | 0.02 | 0.07 | 0.34 | 0.72 | 0.89 | 0.98 |

The median TLE scatter is 3.4 m, so the 200 m step floor, not `z`, sets what the frozen detector
can see. A looser floor reaches 100 m steps but adds false alarms: about 19 to 20 a year at
`|z| >= 6`, `|step| >= 50 m`, against at most 0.9 a year for the frozen setting (3 detections in
3.2 years of stretches with no listed burn within 3 days; an upper bound, since unlisted burns
count). A clean step leaves out the transitional TLEs a real burn produces, so these recalls are
upper bounds for real burns of the same size.

These figures come from the run with both truth lists (NASA and Roscosmos). With the NASA list
alone the frozen setting had 18 such detections, 5.3 a year. The Roscosmos events also remove a few
gaps (two at the native cadence) from the quiet stretches the injections are drawn from, which reshuffles the random draw, so
the pooled recall figures in the table moved by up to 0.06 from the NASA-only run, and each new
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

On the owner's Windows machine `kaggle datasets create` fails from Git Bash (forward slashes end up
in the upload's temporary file name); run it from PowerShell if a dataset is ever needed.
`kaggle kernels push` works from either shell. From Git Bash, set `MSYS_NO_PATHCONV=1` when the
command has an absolute path such as `/kaggle/working/out`: otherwise Git Bash rewrites it to
`C:/Program Files/Git/kaggle/working/out`, and `kaggle_run.py` refuses the command.
