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
- `SW-All-sample.csv`: the header and six rows cut from one download of
  `https://celestrak.org/SpaceData/SW-All.csv` on 2026-11-14 at about 05:16 UTC, with the line
  endings changed to LF. The rows are 1957-10-01 (the first row), 2024-05-10 and 2024-05-11 (the
  May 2024 storm), 2026-11-13 (observed), 2026-11-14 (a daily prediction, `PRD`) and 2027-01-01
  (a monthly prediction, `PRM`, with no Kp or Ap). Row values are unchanged.

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
- `gp_history-25544-2025-09-17--2025-10-04.json`: **recorded data.** The 44 records with `EPOCH`
  from 2025-09-17 to 2025-10-04 (UTC), copied unchanged from the Space-Track `gp_history` download
  `data/spacetrack/gp_history-25544-2021-01-01--2026-01-01.json`. Through `holdout.load_gp_history`
  they give 35 element sets, whose gaps 15, 17 and 19 are gaps 8822, 8824 and 8826 of the full
  series (the 2025-09-25 aborted reboost and the 09-26 reboost) with the same step and z at k=4.
