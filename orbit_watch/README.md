# Method

The rules, thresholds and sources behind the state-change list, the mode layer, the step detector
and the evaluations. The numbers they produce are in [findings/README.md](../findings/README.md);
every command is in [docs/features.md](../docs/features.md).

- [Code layout](#code-layout)
- [Data and downloads](#data-and-downloads)
- [The GEO-region set](#the-geo-region-set)
- [Cleaning](#cleaning)
- [Operating modes](#operating-modes)
- [State changes](#state-changes)
- [Step detector](#step-detector)
- [Ground truth and splits](#ground-truth-and-splits)
- [Notes per module](#notes-per-module)

## Code layout

| Module | What it does |
|---|---|
| `orbit_watch.elements` | Parses TLEs (2- and 3-line, checksums checked) and GP records (JSON, CSV) into one `ElementSet` |
| `orbit_watch.series` | `to_series`: an epoch-sorted `ElementSeries` per object; epochs under 60 s apart collapse to the later one; refuses holdout objects unless `final=True` |
| `orbit_watch.propagate` | TEME position and velocity through `sgp4`; raises `PropagationError` on SGP4 error codes |
| `orbit_watch.sources`, `celestrak`, `spacetrack` | `ElementSource` implementations: a local directory, CelesTrak current GP, Space-Track `gp_history` |
| `orbit_watch.detect` | The step detector: Theil-Sen detrending, median step, robust `z`, optional inclination-vector channel |
| `orbit_watch.calibrate` | Chooses and scores the ISS setting against the NASA (and Roscosmos) lists |
| `orbit_watch.holdout` | Scores the frozen setting on Space-Track ISS history, plus leave-one-year-out cross-validation |
| `orbit_watch.inject` | Synthetic injection-recovery on the real ISS series |
| `orbit_watch.manoeuvre_logs`, `truth` | Build the QZSS and Fengyun label CSVs; the only reader of label files, with the holdout guard |
| `orbit_watch.generalise` | Scores the ISS setting and a GEO tune on the QZSS (GEO) logs |
| `orbit_watch.geo` | Sub-satellite longitude |
| `orbit_watch.modes` | ESA operating mode of a GEO-region object per 30-day window |
| `orbit_watch.clean` | Drops snap-back blocks |
| `orbit_watch.events` | Dated station-keeping state changes of a GEO-region object, one per change, with the signal that dated it |
| `orbit_watch.jobs.*` | Long jobs: `extract_tle_archive`, `geo_belt`, `geo_modes`, `state_changes` |
| `harness.evals.*` | The evaluations: `detector`, `mode_events`, `state_changes`, `state_injection`, `state_audit`; nothing in `orbit_watch` imports `harness` |

Tests never touch the network: every loader takes its fetch function or HTTP session as an
argument, and the tests pass fakes. Fixtures live in `mock/`; `mock/README.md` says where each came
from.

## Data and downloads

Data lives outside the repo, in the folder named by the `ORBIT_WATCH_DATA` environment variable
(written `$ORBIT_WATCH_DATA` below). The fetchers, the tools and the evaluations read it from there
and stop with a message naming the variable when it is unset; the jobs take their folders as
arguments. The tests need no data.

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
  uses it. It keeps under 30 requests a minute and 300 an hour. Space-Track allows each object's
  `gp_history` to be downloaded once, so every answer under `$ORBIT_WATCH_DATA/spacetrack/` is kept
  with no expiry and never fetched again. Keep that folder. SATCAT is one full-catalogue query
  (Space-Track allows it once a day and asks for combined queries, not one per object), kept the
  same way; delete `$ORBIT_WATCH_DATA/spacetrack/satcat-<fields>.json` to fetch a newer one.

## The GEO-region set

`orbit_watch.jobs.geo_belt` collects every element set from 2021 to 2025 of every object that was
in the GEO region (ESA's definition: mean motion 0.9-1.1 rev/day, eccentricity at most 0.2,
inclination at most 70 deg) at any epoch in the period, and keeps all of that object's element
sets in the period, including ones outside those bounds. Space-Track's own yearly bundles are
behind an end-to-end encrypted share, so it reads the yearly bundles of the CC0 Kaggle dataset
`vaibhavpandey12382/historical-tle-datasets`. It reads any local `.txt` or `.zip` bundle, so
Space-Track's zips also work.

```
python -m orbit_watch.jobs.geo_belt build --source https://www.kaggle.com/datasets/vaibhavpandey12382/historical-tle-datasets --bundle '<bundles>/**/tle2021.txt' --bundle '<bundles>/**/tle2022.txt' --bundle '<bundles>/**/tle2023.txt' --bundle '<bundles>/**/tle2024.txt' --bundle '<bundles>/**/tle2025.txt' --out $ORBIT_WATCH_DATA/geo
python -I -m orbit_watch.jobs.geo_belt satcat --out $ORBIT_WATCH_DATA/geo
```

The `satcat` step needs the Space-Track variables. The manifest records the rule, each bundle's
sha256 and per-object counts.

The counts in this section and the next come from the full run and a one-off comparison; they
are not committed. The full run read 177,075,602 lines (88,220,159 pairs). The set holds 1,804
objects and 4,940,529 TLEs; 136 objects have sets outside the region, such as a transfer orbit before arrival. 635,284
lines were rejected (the ones looked at are 68-character lines of analyst objects, 8xxxx), 785,425
pairs restated an epoch already held with different lines, and 8 pairs failed `parse_tle`.

**Restated epochs.** The mirror's element set numbers and line 1 checksums differ from
Space-Track's, but the orbital fields match. Against the `gp_history` files of Fengyun-2H (43491)
and QZS-4 (42965), every epoch the mirror holds matches Space-Track's latest-issued set (highest
`GP_ID`) on those fields: 4,220 and 1,851 epochs, including all 390 and 718 epochs Space-Track
issued more than once. So keeping the later record, as `geo_belt` and `series.to_series` do,
matches Space-Track's latest issue. The mirror lacks 2 of 43491's 4,222 epochs.

## Cleaning

`orbit_watch.clean` drops snap-back blocks before anything else. A snap-back block is a run of up
to 10 days where the semi-major axis or the inclination vector jumps away and comes back while the
mean longitude carries on: an alternate orbit solution, not a burn, because a real move does not
return. When the sets on either side of a block are fewer than 3 or span less than a day, only the
inclination vector is judged, so a block that is the start of a new orbit is kept. The rule was
built on the detector evaluation's QZS-3 and QZS-6 false alarms; blocks are about 1.6% of sets on a
100-object sample (not committed), and none of the logged QZS burns is lost.

A lone set is dropped too: one whose semi-major axis is at least 10 km off the line between its
two neighbours (both within 3 days, differing by at most a quarter of that) while the longitude
carries on between them. One wild set can make a graveyard climb that never happened (45986 at the end of
its data). The two wild sets behind that issue were about 212 km (45985) and 577 km (45986)
off, with neighbours 1 to 3 days away; 10 km is far below both and ten times the 1 km burn floor, and neighbours that
agree within a quarter of the offset rule out a real burn, after which the orbit does not return.

## Operating modes

`orbit_watch.modes` labels each object's mode per 30-day window with ESA's classes (*Classification
of Geosynchronous Objects*, Issue 21.0, 2019): `controlled_lon_inc` (C1), `controlled_lon` (C2),
`drifting` (D), `librating_75E` (L1), `librating_105W` (L2), `librating_both` (L3), `inclined`
(I), `undetermined` (Ind) and `out_of_region`. The windows are merged into segments of one mode.
`jobs.geo_modes` skips the 5 holdout objects, so 1,799 objects are classified. The sample counts
below that justify each threshold come from one-off runs whose outputs are not committed.

- Classes and region: ESA Space Debris Office, *Classification of Geosynchronous Objects*, Issue
  21.0, 19 July 2019, GEN-DB-LOG-00270-OPS-SD, status at 1 January 2019, section 2 and table 1
  (p. 6). ESA does not host it publicly; the copy read is at
  <https://astronomer.ru/data/0128/Classification_of_Geosynchronous_Objects_I21R0.pdf>.
- `out_of_region`: median semi-major axis outside 37,948-46,380 km or eccentricity above 0.25
  (ESA's GEO, IGO and EGO classes together). `inclined`: median inclination above 25 deg.
- Longitude is the mean longitude (node + argument of perigee + mean anomaly - GMST), the quantity
  ESA tabulates. The sub-satellite longitude adds an inclined orbit's daily figure-eight, about
  ±1 deg at 15 deg inclination. The drift rate of a set is 360 times the difference between its mean
  motion and one sidereal revolution per day (1.00273790935 rev/day), in deg/day.
- A window needs at least 5 sets spanning at least 10 days; otherwise it is `undetermined`.
- Held: the 5th-95th percentile longitude spread is at most 0.3 deg. ITU Radio Regulations
  No. 22.6 sets ±0.1 deg east-west for geostationary stations; 0.3 leaves room for TLE noise and
  sits in the gap of the spread histogram (150 sampled objects: 2,627 windows below 0.15 deg, 147
  between 0.15 and 0.5 deg). A held window counts as control only if a 90-day run of three windows
  that includes it is held too, or it is stiller than a free object could be.
- A held window is `controlled_lon_inc` when its median inclination is at most 0.3 deg, or when it
  lies between two such windows less than a year apart; otherwise `controlled_lon`.
- `BOX_DEG` 1.5: a window with a spread of up to 1.5 deg also counts as held when a 90-day run
  that includes it spreads at most 1.5 deg and contains a burn. Among 90-day runs with a burn in
  250 sampled objects, 933 spread under 1 deg, 10 spread 1-3 deg and the rest 3 deg or more.
- A window holds a burn when no free path fits it: `FREE_RESIDUAL_DEG` 0.02. In a seeded sample of
  400 objects the two-window fit leaves 0.42% of 2,153 free-librator windows above it, and 99.5% of
  keeper windows and every relocation above it.
- Free objects are told apart by their energy in the longitude potential of the EGM96 tesseral
  terms (2,2), (3,1) and (3,3): above the higher barrier they drift, between the barriers they
  librate around both stable points, and below the lower barrier around 75 E or 105 W. A run
  whose longitude passes over a barrier is classed by that.
- The 30-day windows are laid back from 2026-01-01 so every object shares the grid; the first
  window is 26 days.

## State changes

The event unit is one change of an object's station-keeping state, dated to the day, with the
signal that dated it and its size. `jobs.state_changes` writes one row per event for every
GEO-region object except the 5 holdout objects: `norad_id`, `event_type`, `date`, `signal`,
`size`, `lon_before`, `lon_after`, `mode_before`, `mode_after` and `mode_change` (the date of the
mode-layer boundary the event came from). On an arrival from a stretch that is not held,
`lon_before` is the median longitude of the 10 days before it; for a departure with no later
hold, `lon_after` is the median longitude of the last 10 days of the data. Either is empty when
those 10 days hold no element set.

`orbit_watch.events` works on the cleaned element sets, the mode segments of `orbit_watch.modes`
(with `undetermined` and `inclined` segments skipped) and the burns the step detector finds in the
semi-major axis at the frozen ISS setting (`k = 4`, `|z| >= 12`, `|step| >= 200 m`).

| type | what it is | dated by (`signal`) | `size` |
|---|---|---|---|
| `relocation_start` | a held object leaves its slot and is held again later, is still moving at relocation speed when the data end, or moves at relocation speed until a graveyard climb (step 14) | `rate_exit`: the first set that leaves the held drift band or longitude box and stays out 5 days (inside a gap, see step 7); `a_step` when that exit is slow drift and a burn starts the move later (step 16), or at a step in the semi-major axis after a slow burn cycle (step 26); `burn_gap` when the exit is slow and the burns stop first (steps 4, 15 and 30) | median semi-major axis of the first run of at least 3 moving sets (drift at least 0.05 deg/day away from the hold's, all one way) after the start, before the next held mode segment, the end of the data or the climb, minus the hold's median, km: negative when that run drifts east. When the span moves at least 0.5 deg net, the first run going that way is used (step 28). All sets in that span are used when none moves that fast; 0 when the next mode segment is already held |
| `relocation_end` | a moving object starts to hold a slot | `rate_entry`: the first set that stays inside the new slot's band (inside a gap, see step 7), or the set where a fast move stops near the slot (step 19) | 0 |
| `graveyard` | a held object leaves and its semi-major axis rises at least 150 km, with no later hold; or an object never held in the data climbs at least 150 km above its first 90 days and stays there (step 29) | `rate_exit`; `a_step` when the climb starts with a burn after a slow drift or a stall (steps 14 and 16), or for an object never held (step 29) | highest semi-major axis from the end of the held mode segment to the end of the data, minus the hold's median, km; for an object never held, from the climb, minus the median of its first 90 days |
| `keeping_stop` | a held object leaves with no climb, no later hold and no move under way at the end of the data, or drifts slowly for more than 90 days before a climb (step 14) | `burn_gap`: the last east-west burn plus half the burn interval (step 4, step 15 on a slow cycle, or step 25 after small burns of the other sign); `a_step` at a last burn that drives the object across the box (step 24); `rate_exit` when the burns give no date | highest semi-major axis from the end of the held mode segment to the end of the data (to the climb under step 14), minus the hold's median, km; 0 when a move or climb follows it (step 4) |
| `ns_keeping_stop` | `controlled_lon_inc` to `controlled_lon` at the same slot, with at least 2 inclination corrections found | `ns_gap`: the last correction plus half the median interval between corrections (step 8) | largest inclination in the `controlled_lon` segment after it, deg |
| `free_burn` | a semi-major-axis step of at least 1 km by an object that is never held again (steps 10 and 18) | `a_step`: the step detector's peak | the step detector's step, m: the change in median semi-major axis across the detection once the local linear trend of the 4 sets on each side is removed. On a steady climb it can have the opposite sign to the net change: 29155 on 2024-07-16 is listed at -1179 m while its semi-major axis climbs about 11 km between 8 and 20 July |

Any type except `ns_keeping_stop` and `free_burn` can carry `mode_change` instead: no sustained
exit from the hold or entry into it was found within 45 days of the mode-layer boundary, so the
boundary's date is used. Burns after a graveyard move are listed as free burns when they are not
part of the climb (step 10): an object in a graveyard orbit can keep manoeuvring, as 28790 and
29155 do in 2024.

The rules were built on the dev split of the cited events (`groundtruth/geo_events.csv`), the first
hand audit and the dev trials of the planted-change test; steps 12 to 18 came from a second hand
reading of the belt list after steps 6 to 11, and steps 19 to 30 from the issues left open on it. Each was kept only if none of these got worse. The test split, the out-of-sample audit and the held-out Fengyun satellites were not
used to choose a rule (see [findings/README.md](../findings/README.md)).

1. **Snap-back blocks** are dropped first (see [Cleaning](#cleaning)).
2. **Dating from the drift rate.** The mode layer dates a change at a 30-day window boundary; the
   per-set drift rate leaves the held band within a day of a real departure. The band is the
   hold's median drift rate ± the larger of 0.02 deg/day and 4 times 1.4826 times its median
   absolute deviation, and the box is the hold's longitude range widened by 0.05 deg each side.
3. **Short holds.** Inside stretches that are not held, a run of at least 5 sets with drift at
   most 0.02 deg/day inside a 0.3 deg box for at least 10 days, entered by a set moving at 0.05
   deg/day or more within 5 days, is a hold. This catches stops the windows cannot see, such as
   SJ-17's 13-day move in November 2024 and Luch (Olymp)'s stops in 2021 and 2025. The entry burn
   keeps librating objects out.
4. **Burn gap.** When keeping simply stops, the longitude leaves the box weeks after the last
   burn; the midpoint between the last burn and the one that never came dates it. It applies when
   at least 3 burns fall in the 60 days before an exit that is not already fast. If the object
   climbs later, the climb is a second event.
5. **One slot.** Two holds whose longitude ranges come within 0.5 deg of each other are the same
   slot, so a re-centred box or a hold split by a short drift is not a relocation. Across a
   stretch that is not held, this applies only when nothing in the stretch drifts at 0.05
   deg/day or more for 5 days; a move out and back to the same slot is a start and an end. An
   arrival is dated no earlier than the departure it follows.
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
   rate relative to the hold, as if the burn were instant: the latest start the sets allow. When
   that would place the change after the set (the drift reversed inside the gap) and the
   longitude moved at least 0.5 deg across it, the change is dated at the first set after the gap.
8. **End of north-south keeping.** Corrections are steps in the inclination vector (i cos RAAN,
   i sin RAAN) once its free drift, fitted on the 60 days after the window boundary, is removed. A
   correction is a step between 3-set medians, spanning at most 12 days, of at least 5 times the
   set-to-set scatter and at least 0.006 deg, in the 180 days before; steps within 2 days of a
   larger one are merged. The stop is the last correction plus half the median interval. With
   fewer than 2 corrections nothing is listed, which drops stops on objects that never kept
   inclination.
9. **Moves still under way at the end of the data.** A departure with no later hold and no climb
   is a `relocation_start`, not a `keeping_stop`, when the data end within 90 days of it and the
   drift goes from under 0.025 to a sustained 0.05 deg/day or more relative to the hold within 5
   days, or between consecutive sets. That takes a burn: natural drift needs 15 days or more to
   change that much.
10. **Free burns.** A burn is listed only with at least 10 days of data after it (a hold takes 10
    days to show, so a burn in the last 10 days can be a new slot's first trim); not after a
    relocation start still under way at the end of the data within 90 days of it, whose burns are
    part of the move;
    not within 15 days of another listed event (`CLIMB_DAYS`); and not as part of a graveyard
    climb, where each burn follows the departure or the previous climb burn within 30 days.
11. **Inclined orbits.** Above 25 deg inclination (IGSO and QZO objects) the mode layer's hold
    test does not apply: a single held window between inclined stretches would read as an arrival
    and a departure, and every later keeping burn as a free burn. Inclined stretches are skipped,
    like undetermined ones.
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

Steps 19 to 26 came from the belt-list issues left open after step 18, each checked on the dev
cited events and dev planted trials in the same way.

19. **Arrival before a trim.** When a fast move (0.05 deg/day or more relative to the new hold)
    enters a sustained run of sets inside the new hold's drift band and within 0.5 deg of its
    box, starting before the band entry and staying there, the arrival is the start of that run:
    a trim inside the slot after the move stops is not the arrival.
20. **A pause in a move.** A relocation end followed within 10 days by a start in the same
    direction is a pause, not a stop: the pair is dropped and the move is one start and one end.
21. **A move within one slow cycle.** A relocation or graveyard departure dated by step 15 whose
    first fast set comes within one burn interval of that date is one departure dated at the first
    fast set (run back across a gap as in step 7), not a keeping stop and then a move.
22. **Burns into fast drift.** A keeping stop whose drift jumps to fast within 5 days, as in step
    9, and is followed more than 15 days later by a burn of at least 1 km before the next hold or
    the end of the data, is a `relocation_start`.
23. **Size from the first run.** A relocation start's size uses only the first run of at least 3
    moving sets after it (see the table), so a later drift inside the same span, or a burst of one
    or two sets, does not set it. Step 28 picks which run counts as first.
24. **A last burn across the box.** A keeping stop dated by the drift-rate exit is dated at the
    last burn in the hold when the object was on the other side of the slot just before that burn
    and every set from the burn to the exit drifts toward the exit side.
25. **Small burns of the other sign.** When the last burns before the exit have the opposite sign
    to the usual keeping burns (at least 80% of the earlier burns in the 180 days before), are no
    larger, and push the drift away from the slot on the side the object is on, the stop is the
    last usual burn plus half the median interval of the usual burns in the 60 days before it.
    80% asks for a clear usual sign; it was the only share tried, and adding it changed one dev
    trial (a stop 21 days late became 13).
26. **A step after a slow cycle.** A move or climb dated by step 15 is dated at a step of at least
    0.3 km in the semi-major axis between that date and the next mode segment, when there is one:
    3-set medians on each side differ by that much, and the date is between the two sets of the
    first single jump of that size. The search stops at the day the departure was detected, so a
    later burn that ends the move is not taken. 0.3 km is a drift change of about 0.004 deg/day,
    six times the median scatter of a held host's semi-major axis (0.048 km); taking the largest
    jump instead of the first dated 58990 at a jump across a gap (2024-06-29).
27. **Held again before the move.** A keeping stop dated by the burns (step 4) before a move is
    dropped, leaving only the move, when a later burn of at least 1 km holds the object again:
    the first set after the burn comes within 5 days of it, and every set from there to the move
    drifts at most 0.02 deg/day inside a 0.3 deg box, for at least 5 sets and 10 days. These are
    the short-hold test of step 3, so a slow drift away after the burn does not count. GOES 16
    (41866) stopped its burns in February 2025, was held again by a burn, and moved on 2025-04-10.
28. **Size toward the net move.** A run of moving sets ends where the drift relative to the hold
    changes sign, so one run never joins sets drifting both ways. When the size span (see the
    table) moves at least 0.5 deg net (the shift that makes a move in step 6), the first run going that
    way is used, so a short hop the other way before the move does not set the size's sign.
    This fixed 53355 (2023-10-11), 43874 (2022-07-05) and 55131 (2023-03-18).
29. **A climb by an object never held.** An object with no held mode segment in the data has no
    departure to type. Its reference semi-major axis is the median of its first 90 days, when
    those sets are in the GEO region of the mode layer (37,948-46,380 km, eccentricity at most
    0.25). The climb starts at the first set from which the 3-set median stays at least 150 km
    (the graveyard rise) above that reference to the end of the data, so an inspector that
    climbs and comes back is not listed. It is dated at the first burn of at least 1 km after
    the last set below 10% of the rise, or across the gap from that set as in step 7, and both
    sets must be in readable mode segments. 34779 climbs 1,694 km on 2022-01-22.
30. **Already drifting when the burns stop.** A relocation or graveyard departure dated by the
    burns (step 4) on a normal burn cycle is one departure at that date, not a keeping stop and
    then a move, when the median drift relative to the hold over the first 10 days after it (at
    least 3 sets, and before the first fast set) is at least 0.02 deg/day toward the move. A
    held object's drift stays inside 0.02 deg/day (step 3), and an object that just stopped
    keeping starts drifting from about zero, so the move had already begun. In the dev trials
    the six slow planted moves listed as a stop then a move drift 0.024-0.057 deg/day over those
    10 days; the five such pairs in the belt list (28884, 29162, 31800, 37150 and 45465) and one
    planted free-burn trial drift 0.005 deg/day or less, and keep both rows.

## Step detector

`orbit_watch.detect` scores every gap between consecutive element sets. It takes the `k` sets on
each side, fits one Theil-Sen slope from the point pairs within each side, removes it, and takes
the step as the median of the sets after the gap minus the median before. A gap is scored only when
it is at most 2 days long and each side spans at most 3 days. The step's robust `z` divides it by
its standard error (see the notes on `detect` below). Steps that pass both `|z|` and `|step|` are
kept in order of `|z|`, dropping any within `nms_days` (1 day) of a stronger one.

- **Frozen ISS setting**: `k = 4`, `|z| >= 12`, `|step| >= 200 m`, `nms_days` 1, chosen by F1 on
  the ISS in 2021-2022 only. An event matches a detection when its time overlaps the detection's
  interval widened by 0.5 day, one to one. The state-change list uses this setting unchanged.
- **Inclination channel** (detector evaluation only): the same score on the step of the inclination
  vector (i cos RAAN, i sin RAAN), with `inc_z_min` 30 and `inc_step_min_deg` 0.02
  (`harness/evals/settings/inc-vector.json`). `merge_channels` keeps every semi-major-axis
  detection and drops an inclination detection within `nms_days` of one.
- **GEO tune** (`generalise`, reported for comparison, not used elsewhere): `k = 4`, `|z| >= 3`,
  `|step| >= 1000 m`, chosen by F1 pooled over QZS-3 and QZS-6 before each satellite's split date.

## Ground truth and splits

Sources, caveats and the build of every label file are in
[groundtruth/README.md](../groundtruth/README.md). The split rules:

- **Labelled objects** (`groundtruth/splits.json`, written by `python -m orbit_watch.truth --write`
  and checked by `tests/test_truth.py`). Every object scored before the split (the ISS, QZS-3,
  QZS-6) is `train`. The objects added with the split are grouped by regime (GEO, IGSO); each group
  is sorted by NORAD id and shuffled with Python's `random.Random("orbit-watch truth-sets
  2026-11-14")`, and the first ceil(2n/3) objects of each group are `holdout`. That gives a holdout
  of Fengyun-2F and Fengyun-4A (GEO) and QZS-1, QZS-1R and QZS-2 (IGSO).
- **Holdout guards.** Label files are read only through `orbit_watch.truth.read_label_rows`, and
  series are built only through `orbit_watch.series.to_series`; both refuse holdout objects unless
  called with `final=True`. These are code-path guards against tuning on the holdout by accident,
  not a wall: the labels are in committed CSVs. The belt jobs skip the 5 holdout objects.
- **Detector evaluation periods** (`harness/evals/split.json`): `train` is the train objects in
  2021-2023, `dev` the same objects in 2024-2025, and `test` the holdout objects in 2021-2025,
  refused without `--final`. Coverage, matching and counting rules are fixed in
  `harness/evals/detector.py`, so no detector change can move them.
- **Cited GEO events** (`groundtruth/geo_events.csv`): `event_id` is
  `<norad_id>-<event_type>-<date>`, and an event is `dev` when the last hex digit of the sha256 of
  its `event_id` is even, else `test`. Events on holdout objects, outside 2021-2025 or on objects
  missing from the GEO-region set are listed, not scored.
- **Planted-change hosts** (`harness/evals/state_injection_hosts.json`): a host is `dev` or `test`
  by the parity of the last hex digit of the SHA-256 of its NORAD number. Holdout objects and
  objects with a test-split cited event are left out.
- **Hand audits**: both samples leave out the holdout objects and every object with a test-split
  cited event; the second also leaves out every object in the first.

## Notes per module

Rules, thresholds and sources that the code does not state.

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
- `merge_channels` puts the semi-major axis first because `z` is not comparable across channels.

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

### `harness.evals.state_changes`

- Matching: one event per change, closest first, within 45 days; a departure of any kind matches a
  relocation start, graveyard move or end of keeping.
- A satellite counts as on station from its first log row to its last, clipped to its element sets
  and to 2021-2025; a gap between east-west burns longer than twice that log's median east-west
  gap would mean the log shows it away, so that span is dropped and named in the output.
- `events.state_changes` builds its series without `final=True`, so the evaluation runs a copy of
  `events.burns` that passes it; a test checks that the copy gives the same events on mock data.

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
