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
