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
  de-duplicated `ElementSeries` of numpy arrays per object.
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
gap between consecutive epochs it fits one straight line to the `k` epochs before the gap and
another to the `k` epochs after it, extrapolates both to the middle of the gap and takes the
difference as the step. The lines are local, so the drag decay may differ on each side.

The noise model is estimated from the data. At every gap the TLE scatter `sigma` is 1.4826 times
the median absolute deviation of both fits' residuals, floored at half the series' median
`sigma`. Each fit is redone once without points more than 4 `sigma` off, so a transitional TLE
does not drag the line. The step's `z` is the step divided by its standard error, which comes from
`sigma` and each line's prediction variance at the gap. A gap is flagged when `|z|` and `|step|`
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
  listed event is a false positive. The list is a lower bound (Roscosmos burns are missing), so
  unmatched detections are leads to check, not findings.
- The two unplanned attitude events are scored apart from the main numbers.

It writes `calibration.json`, `detections.csv`, `events_scored.csv` and `iss_sma.png` (`a` per
year with events and detections marked). The TLE file is git-ignored, so the Kaggle run attaches
it and records its sha256 in `ATTACHED.txt`:

```
MSYS_NO_PATHCONV=1 python tools/kaggle_run.py --slug ow-calibrate --attach data/archive/25544.tle --     python -m orbit_watch.calibrate --tle data/archive/25544.tle --truth groundtruth/iss_manoeuvres.csv --out /kaggle/working/out
```

RESULTS_PLACEHOLDER

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
