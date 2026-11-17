# Test fixtures

Every element set here is a real, published one. Nothing is invented. The tests
read these files; package code never does.

## `elements/`

Read by the file loader tests, so it holds all three input formats.

- `iss.tle`: two ISS (NORAD 25544) element sets.
  - The first, with the `ISS (ZARYA)` name line, is the example TLE in the
    `sgp4` package README (PyPI `sgp4` 2.27, "Usage" section; the name is the
    one the README passes to `export_omm`).
  - The second, without a name line, is the epoch `19366.82137887` TLE from
    `test_december_32` in `sgp4/tests.py` (sgp4 2.27).
- `mario.tle`, `mario.csv`: the MARIO cubesat (NORAD 55123), copied from
  `MARIO_TLE` and `MARIO_CSV` in `sgp4/tests.py` (sgp4 2.27). The CSV there is
  CelesTrak's `gp.php?CATNR=55123&FORMAT=CSV` output.
- `mario.json`: the same MARIO record as `mario.csv`, written in the field
  names and value types CelesTrak's `FORMAT=json` returns (numbers as JSON
  numbers, `EPOCH` as a string). The values are transcribed from the CSV, not
  downloaded as JSON.

## `vallado/`

From the Vallado SGP4 verification set ("Revisiting Spacetrack Report #3",
AIAA 2006-6753) as shipped in the `sgp4` 2.27 package.

- `SGP4-VER-subset.tle`: objects 00005, 04632 and 06251 from `sgp4/SGP4-VER.TLE`,
  cut to the standard 69 columns (the original lines carry start, stop and step
  times after column 69).
- `tcppver-subset.out`: the blocks for those three objects from
  `sgp4/tcppver.out`, verbatim: minutes since epoch, then TEME position (km)
  and velocity (km/s).

## `celestrak/`

- `gp-CATNR-25544.json`: a recorded CelesTrak response, saved byte for byte. It is
  `https://celestrak.org/NORAD/elements/gp.php?CATNR=25544&FORMAT=json`, fetched once on
  2026-11-14 at about 05:16 UTC (ISS element set with epoch 2026-11-13T21:59:13.395264).

## `spacetrack/`

- `gp_history-25544-format-sample.json`: **a format sample, not a recorded response.** No
  Space-Track account exists, so nothing has been downloaded from it. The two records are the two
  real ISS TLEs in `elements/iss.tle`, rewritten as Space-Track `gp_history` JSON: every value is
  a JSON string; the OMM fields come from `sgp4.exporter.export_omm` (sgp4 2.27), with the
  angles, eccentricity, mean motion and its first derivative copied as text from the TLE columns.
  `TLE_LINE0`, `TLE_LINE1` and `TLE_LINE2` are added; the name `ISS (ZARYA)` is used for both. Fields
  Space-Track adds that the TLE cannot supply (`GP_ID`, `CREATION_DATE`, `FILE` and the like)
  are left out rather than invented. The field names follow CelesTrak's GP format, which uses the
  same OMM keyword names; Space-Track's own field list sits behind its login and was not checked.

## `geo/`

- `bundle-sample.txt`: five real TLEs laid out like a full-catalogue yearly bundle (2-line, no
  names), copied byte for byte from `data/archive/` (the OndroNR/tle-archive extract of CelesTrak's
  `active.txt`): the first two Luch 5A (37951) sets, the first ISS (25544), Luch-5X / Olymp-K 2
  (55841) and Luch / Olymp-K 1 (40258) sets of 2021 (2023 for 55841). The rule's edge cases (GTO,
  a 24-hour orbit with e > 0.2, an object that arrives) are synthetic TLE pairs built inside
  `tests/test_geo_belt.py`, not files here.
- `37344_every_2_days.tle`: real element sets of Elektro-L No. 1 (NORAD 37344, 2011-001A),
  cut from `data/geo/37344.tle`, which `orbit_watch.jobs.geo_belt` extracted from the Kaggle
  dataset `vaibhavpandey12382/historical-tle-datasets` (yearly TLE bundles 2021-2025; the
  bundle names and sha256 are in that folder's `manifest.json`). The first element set in each
  two-day bucket counted from 2021-01-01 is kept: 904 of 2,914, lines unchanged. Read by
  `tests/test_modes.py`, which checks it against ESA's issue-21 classification of the object.
- `22269_every_4_days.tle` and `25110_every_4_days.tle`: real element sets of Cosmos 2224
  (NORAD 22269, 1992-088A) and Intelsat 804 (NORAD 25110, 1997-083A), cut the same way from
  `data/geo/22269.tle` and `data/geo/25110.tle`, keeping the first element set in each four-day
  bucket counted from 2021-01-01: 456 of 2,398 and 456 of 2,766, lines unchanged. Both energies
  sit within about 2 % of a potential barrier and both paths pass over it (the low barrier for
  22269, the high one for 25110). Read by `tests/test_modes.py`, which checks that neither is
  labelled as trapped behind the barrier it crosses.
