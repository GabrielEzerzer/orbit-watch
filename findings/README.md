# Results

Every number here is read from a committed file under `findings/` or `harness/evals/results/`,
named with each result. The rules being measured are in
[orbit_watch/README.md](../orbit_watch/README.md).

- [Cited GEO events](#cited-geo-events)
- [False events on satellites with burn logs](#false-events-on-satellites-with-burn-logs)
- [Planted changes](#planted-changes)
- [Hand audits](#hand-audits)
- [Detector evaluation](#detector-evaluation)
- [Operating modes](#operating-modes)
- [ISS regression bench](#iss-regression-bench)
- [QZSS](#qzss)
- [The belt list](#the-belt-list)
- [ISS leads](#iss-leads)

## Cited GEO events

`groundtruth/geo_events.csv` lists real relocations, graveyard moves and ends of station keeping
in the GEO belt, each with a public source. Events go to `dev` or `test` by the last hex digit of
the SHA-256 of their `event_id`. An event matches one dated change within 45 days, closest first,
and a departure of any kind matches a relocation start, graveyard move or end of keeping. The
date error is the change's date minus the event's. Events dated only to the month are scored as
the 15th.

State changes (`orbit_watch.events`), from `findings/state_changes/eval_all.json`:

| split | events | caught | median \|error\| (days) | 90th percentile (days) | same type |
|---|---|---|---|---|---|
| dev | 13 | 13 | 2 | 13 | 13 |
| test | 20 | 18 | 5.5 | 14.9 | 17 |

By type on test: relocation starts 3 of 4, relocation ends 5 of 5, graveyard moves 9 of 10
(median error 7 days), the one keeping stop caught but typed as another departure.

- **How often the test split was used.** The rules were built on the dev events, the first hand
  audit, a second hand reading of the belt list and the dev planted trials. The test split was
  scored at six rule states while steps 6 to 18 were built, the last after the step 14 change
  below, and its score was never used to choose a rule. Steps 19 to 26 were built without it and
  it was scored once after them: the one event that moved is the arrival of 28912 (dated only to
  May 2022), now 24 days early instead of 2, because step 19 dates it where a fast move stops. One test object's belt row was looked at
  while building step 14: the graveyard move of 28707, now dated 17 days before its cited date. Its
  date moved by one day as a result (from 18 to 17 days early), and its departure on 2021-11-09,
  a burn that lowers the orbit by about 50 km and starts an eastward drift, became a
  `relocation_start` instead of a `keeping_stop`.
- **Graveyard moves are the worst dated** (dev median 9 days, mostly early), because sources
  variously date the start of the climb, its end or the decommissioning; three of the 13 dev
  events are dated only to the month.
- **Changes in gaps.** Four test graveyard moves start inside a gap in the element sets and are
  dated inside it, at the latest date the sets allow. ASTRA 1D (23331) is 46° away, moving at
  -4.77°/day, at the first set after an 11-day gap.

The mode layer alone (30-day windows, no dating step) is the baseline, from
`findings/geo_events/summary.json`:

| split | events | caught | median \|error\| (days) | 90th percentile (days) |
|---|---|---|---|---|
| dev | 13 | 11 | 10 | 33 |
| test | 20 | 15 | 14 | 30.8 |
| all | 33 | 26 | 11.5 | 33.5 |

By type over both splits: relocation starts 7 of 8, relocation ends 5 of 8, graveyard moves 12 of
15, ends of keeping 2 of 2. Caught graveyard moves are dated early (median 22 days, 10 of 12
before the source date): several sources date the end of disposal, and the layer dates a change
at the start of its window. Five of the 7 misses are on objects the layer reads as drifting on
both sides of the event, such as Luch (Olymp), whose short moves never hold a 30-day window, and
Express-AM3, already free before a climb the layer cannot see because it does not use the
semi-major axis.

## False events on satellites with burn logs

Three train-split GEO satellites have published burn logs: QZS-3, QZS-6 and Fengyun-2H. While a log
shows a satellite on station, every listed departure, arrival or keeping stop is false. A
satellite counts as on station from its first log row to its last, clipped to its element sets
and to 2021-2025. A gap between east-west burns longer than twice that log's median gap would
mean the log shows it away, and would be dropped; none is in 2021-2025.

| satellites | object-years | events | source |
|---|---|---|---|
| QZS-3 (4.998), QZS-6 (0.414), Fengyun-2H (1.047) | 6.459 | 0 | `findings/state_changes/eval_dev.json` |
| Fengyun-2F (1.01), Fengyun-4A (1.14), held out | 2.15 | 0 | `findings/state_changes/false_events_final.json` |

- The target is at most 0.2 false events per object-year.
- The check sees false events on a held satellite. It does not see extra or mistyped events around
  a real change, or false free burns on objects that are not held.
- The snap-back filter was tuned on the two QZSS satellites.
- The Fengyun logs end in January and February 2022 and have no stated provenance (see
  [groundtruth/README.md](../groundtruth/README.md)), so the count on them supports the QZSS count
  rather than standing alone.
- The held-out count was run at four rule states, 0 events each time, and never used to choose a
  rule. It is measured, not gated.
  `events.state_changes` builds its series without `final=True`, which refuses held-out objects,
  so the evaluation runs a copy of `events.burns` that passes it; a test checks that the copy
  gives the same events on mock data.

## Planted changes

The cited events are few, so `harness/evals/state_injection.py` plants changes into real element
sets in memory and checks what `orbit_watch.events` finds. Results are in
`findings/state_injection/summary.json`, one row per trial in `trials.csv`.

**Hosts.** A candidate is the longest held mode segment, at least 120 days long, of a GEO-region
object; held-out objects and objects with a test-split cited event are left out. A candidate hosts
plants only if it held no state-change event when the host set was frozen. The 594 candidates (491
quiet), each object's last element set and its held-era scatter are frozen in
`harness/evals/state_injection_hosts.json`, so a change to the event code moves neither the hosts
nor the plants. Hosts go to dev or test by the parity of the last hex digit of the SHA-256 of
their NORAD number: 261 dev, 230 test. Every plant starts at least 60 days into the stretch and is
drawn with seed 20261118.

**How a plant edits the sets.** Each edited set keeps its eccentricity, inclination, node and
argument of perigee; it gets a new mean motion from the planted drift rate, a semi-major axis
scaled to match, and a mean anomaly shifted by the planted change in mean longitude.

- **Relocation:** a burn-free drift at constant rate for D days, then the host's own sets shifted
  by the distance moved. The rate is log-uniform within five bins from 0.02 to 3°/day (100 trials
  each); the distance is log-uniform from 1° to 20°, so D is distance over rate, clipped to 2-120
  days. Truth: a start on the first day and an end on the last.
- **Keeping stop:** after the stop the longitude follows a free path integrated with the
  longitude acceleration from `orbit_watch.modes`. 160 trials.
- **Graveyard climb:** a stop, then 1 to 3 burns 0.5-3 days apart that raise the semi-major axis
  200-400 km in all. Truth: a graveyard move at the first burn. 160 trials.
- **Free burn:** a stop, then one burn of 1.5-20 km (log-uniform, either sign) 45-120 days later.
  Truth: a keeping stop and a free burn. 160 trials.

During a drift and on a free path each set keeps the host's own scatter, taken from its residuals
about a local line through 9 sets, cut at detected burns and at jumps over 10 sigma. Manoeuvre
structure neither cut catches is carried along (see below). Scoring uses the cited-event matching
(type families, 45 days, one to one, closest first). Extra events are unmatched ones within 45
days of the plant (near) and, for kinds that leave the object free, any after it (later).

| split | planted | drift rate (°/day) | trials | all truths caught | truth | caught | median \|error\| (days) | p90 (days) | mistyped | extra per trial (near / later) |
|---|---|---|---|---|---|---|---|---|---|---|
| dev | relocation | 0.02-0.1 | 100 | 86/100 = 0.86 | start | 89/100 | 1 | 7.2 | 6 | 0.14 / 0 |
| dev | relocation | 0.02-0.1 | 100 | 86/100 = 0.86 | end | 89/100 | 0 | 4.2 | 0 | 0.14 / 0 |
| dev | relocation | 0.1-3 | 150 | 148/150 = 0.99 | start | 149/150 | 0 | 1 | 0 | 0.007 / 0 |
| dev | relocation | 0.1-3 | 150 | 148/150 = 0.99 | end | 149/150 | 0 | 1 | 0 | 0.007 / 0 |
| dev | relocation | 0.02-0.05 | 50 | 38/50 = 0.76 | start | 41/50 | 2 | 13 | 4 | 0.24 / 0 |
| dev | relocation | 0.02-0.05 | 50 | 38/50 = 0.76 | end | 41/50 | 0 | 9 | 0 | 0.24 / 0 |
| dev | relocation | 0.05-0.1 | 50 | 48/50 = 0.96 | start | 48/50 | 0 | 1.6 | 2 | 0.04 / 0 |
| dev | relocation | 0.05-0.1 | 50 | 48/50 = 0.96 | end | 48/50 | 0 | 2 | 0 | 0.04 / 0 |
| dev | relocation | 0.1-0.3 | 50 | 49/50 = 0.98 | start | 50/50 | 0 | 1 | 0 | 0.02 / 0 |
| dev | relocation | 0.1-0.3 | 50 | 49/50 = 0.98 | end | 49/50 | 0 | 1.2 | 0 | 0.02 / 0 |
| dev | relocation | 0.3-1 | 50 | 49/50 = 0.98 | start | 49/50 | 0 | 1 | 0 | 0 / 0 |
| dev | relocation | 0.3-1 | 50 | 49/50 = 0.98 | end | 50/50 | 0 | 1 | 0 | 0 / 0 |
| dev | relocation | 1-3 | 50 | 50/50 = 1.00 | start | 50/50 | 0 | 1 | 0 | 0 / 0 |
| dev | relocation | 1-3 | 50 | 50/50 = 1.00 | end | 50/50 | 0 | 1 | 0 | 0 / 0 |
| dev | keeping stop | | 80 | - | keeping_stop | 68/80 | 8 | 30.3 | 0 | 0 / 0.325 |
| dev | graveyard climb | | 80 | - | graveyard | 80/80 | 0 | 1 | 0 | 0.037 / 0.25 |
| dev | free burn | | 80 | 46/80 = 0.57 | keeping_stop | 64/80 | 12 | 30 | 4 | 0.3 / 0.362 |
| dev | free burn | | 80 | 46/80 = 0.57 | free_burn | 48/80 | 0 | 1 | 0 | 0.3 / 0.362 |
| test | relocation | 0.02-0.1 | 100 | 87/100 = 0.87 | start | 92/100 | 1 | 8 | 0 | 0.07 / 0 |
| test | relocation | 0.02-0.1 | 100 | 87/100 = 0.87 | end | 89/100 | 0 | 10 | 0 | 0.07 / 0 |
| test | relocation | 0.1-3 | 150 | 147/150 = 0.98 | start | 147/150 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 0.1-3 | 150 | 147/150 = 0.98 | end | 149/150 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 0.02-0.05 | 50 | 39/50 = 0.78 | start | 44/50 | 2 | 9.7 | 0 | 0.14 / 0 |
| test | relocation | 0.02-0.05 | 50 | 39/50 = 0.78 | end | 41/50 | 1 | 30 | 0 | 0.14 / 0 |
| test | relocation | 0.05-0.1 | 50 | 48/50 = 0.96 | start | 48/50 | 0 | 2 | 0 | 0 / 0 |
| test | relocation | 0.05-0.1 | 50 | 48/50 = 0.96 | end | 48/50 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 0.1-0.3 | 50 | 49/50 = 0.98 | start | 49/50 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 0.1-0.3 | 50 | 49/50 = 0.98 | end | 49/50 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 0.3-1 | 50 | 48/50 = 0.96 | start | 48/50 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 0.3-1 | 50 | 48/50 = 0.96 | end | 50/50 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 1-3 | 50 | 50/50 = 1.00 | start | 50/50 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 1-3 | 50 | 50/50 = 1.00 | end | 50/50 | 0 | 1 | 0 | 0 / 0 |
| test | keeping stop | | 80 | - | keeping_stop | 62/80 | 7 | 25.8 | 0 | 0 / 0.338 |
| test | graveyard climb | | 80 | - | graveyard | 80/80 | 0 | 1 | 0 | 0.037 / 0.163 |
| test | free burn | | 80 | 45/80 = 0.56 | keeping_stop | 59/80 | 8 | 26.2 | 1 | 0.263 / 0.2 |
| test | free burn | | 80 | 45/80 = 0.56 | free_burn | 49/80 | 0 | 1 | 0 | 0.263 / 0.2 |

The 0.02-0.1 and 0.1-3 rows pool the five bins below them. "All truths caught" counts trials where
every planted truth is matched: both ends of a relocation, or the stop and the burn.

**False events on untouched stretches.** Unmatched events on the host stretch before the plant
(and after a relocation): dev 15 over 1,412.5 trial-object-years, test 13 over 1,315.9. A stretch
used by several trials counts once per trial, and most of these are real: 10 of the dev ones are
one 1.1° move of 23553 in April 2021, 2 a shift of 34713 in January 2021, and 2 the keeping stop
of 25258 that the first hand audit dates a day earlier. On test, 33750 and 55912 make real moves
and 26638's graveyard move is dated inside a gap; the keeping stop of 29162 (trial 301's host) is
now dated 2024-01-31 by step 25, inside its host stretch. Two are not real: a 0.1° keeping excursion of
26880 on 2025-03-31, and a 10° jump in a day on 52903 on 2022-11-17, a mix-up between element
sets.

**Inside all 594 candidate held stretches, before any plant**, with 45 days trimmed from each end:
52 events over 2,131.9 object-years (0.024 per object-year): 9 relocation pairs and 34 ends of
north-south keeping. The relocation pairs are on 23553, 27168, 28626, 28885, 35755, 37237, 52903 (the element-set mix-up), 55912 and 58204; most are real moves that
the 30-day windows hid when the hosts were chosen. The 34 north-south stops are real: they were
listed before too, about 100 days later and outside the stretch, and step 8 now dates them at the
last inclination correction, inside it. This is an upper bound on false events on held satellites.

**Extra events after a planted stop, by the host's held-era scatter** (median absolute change of
the semi-major axis between consecutive sets in the host stretch):

| split | planted | host scatter | trials | hosts | extra events | of which free burns | extras per trial (mean / median) |
|---|---|---|---|---|---|---|---|
| dev | keeping stop | < 0.1 km | 68 | 60 | 16 | 0 | 0.235 / 0 |
| dev | keeping stop | >= 0.1 km | 12 | 10 | 10 | 5 | 0.833 / 0 |
| dev | graveyard climb | < 0.1 km | 68 | 58 | 3 | 3 | 0.044 / 0 |
| dev | graveyard climb | >= 0.1 km | 12 | 11 | 20 | 20 | 1.667 / 0.5 |
| dev | free burn | < 0.1 km | 68 | 58 | 41 | 0 | 0.603 / 0 |
| dev | free burn | >= 0.1 km | 12 | 11 | 12 | 10 | 1 / 0.5 |
| test | keeping stop | < 0.1 km | 69 | 56 | 23 | 0 | 0.333 / 0 |
| test | keeping stop | >= 0.1 km | 11 | 10 | 4 | 4 | 0.364 / 0 |
| test | graveyard climb | < 0.1 km | 67 | 61 | 3 | 3 | 0.045 / 0 |
| test | graveyard climb | >= 0.1 km | 13 | 12 | 13 | 13 | 1 / 1 |
| test | free burn | < 0.1 km | 64 | 57 | 26 | 1 | 0.406 / 0 |
| test | free burn | >= 0.1 km | 16 | 12 | 11 | 8 | 0.688 / 1 |

What the trials show:

- **Short moves.** Relocations under 1.5° are caught at both ends in 40 of 46 trials. Starts
  caught: 1.5-3° 115 of 128, 3-6° 155 of 158, 6° and more 167 of 168.
- **The slowest moves.** Below 0.03°/day the drift can stay inside the held band, so a start is
  dated when the longitude leaves the box (62374 from 2025-04-29, 38 days late) or missed: 9 of 35
  starts and 11 of 35 ends are missed (44186 from 2024-09-28 gives no event).
- **Keeping stops near a stable longitude.** Near 105° W and 75° E a free object barely drifts, so
  its stop is dated late or missed: GOES 17 (43226) stopped on 2024-03-20 and MUOS 5 (41622) on
  2024-02-13 are both missed. Slow libration can also read as holds: EWS-G3 (35491) stopped on
  2021-04-19 gives later relocation pairs, and GSAT 11 (43824) and DirecTV 10 (31862) do the same.
- **Extra free burns after a stop are mostly a planting artefact.** The 76 trials on hosts with
  held-era scatter of at least 0.1 km give 60 extra free burns; the other 404 give 7. The free path
  carries the host's manoeuvre-like excursions that no detected burn explains. These extras say
  little about the belt, and **the free-burn threshold must not be tuned on these trials**. Three
  planted free burns count as caught 4 to 29 days off (trials 829, 868 and 919), most likely
  through such noise rather than the planted burn.
- **Stop then burn.** A free burn soon after a stop near the slot can split the stop with a short
  hold, so the stop is typed `relocation_start` (trials 834, 861, 906, 928 and 930).

## Hand audits

Verdicts are judgments read from each object's element sets, not cited ground truth. An event is
`real` if the change it describes shows in the sets (whatever its date error), `artefact` if
nothing changed at that date, `wrong_type` if a real change has another type and `duplicate` if
another event already covers it. Each event was charted over 60 days either side (mean
longitude, drift rate, semi-major axis and the inclination vector, with raw and filtered sets,
neighbouring events and mode segments) and judged on the same checklist: did the change happen, of
this type, and when. Both samples leave out the held-out objects and every object with a
test-split cited event, take at least 5 events of each type and share the rest in proportion to
each type's count.

### Out-of-sample audit

`findings/state_audit_fresh/`: 50 events drawn with their own seed from the belt list frozen in
that folder's `events.csv`, leaving out every object in the first audit. One rule changed after
the draw: step 14 now types the departures of 26719 and 28707 as `relocation_start` instead of
`keeping_stop`, and 239 rows have a different `size`. Neither departure is in the sample (26719's
sampled row is a later free burn). Steps 19 to 26 and the lone-set filter came after the verdicts
and change 5 sampled rows, listed below the table. Two sampled objects were read while writing rules: HYLAS 1 (37237) for step 12, before
the draw, and EUTE 28A (26719) for the step 14 change, after it.

| type | sampled | real | artefact | duplicate | wrong type |
|---|---|---|---|---|---|
| relocation_start | 11 | 11 | 0 | 0 | 0 |
| relocation_end | 14 | 14 | 0 | 0 | 0 |
| graveyard | 7 | 6 | 1 | 0 | 0 |
| keeping_stop | 5 | 3 | 0 | 1 | 1 |
| ns_keeping_stop | 7 | 7 | 0 | 0 | 0 |
| free_burn | 6 | 6 | 0 | 0 | 0 |
| all | 50 | 47 | 1 | 1 | 1 |

47 of 50 are real with the right type. 45 could be dated from the sets: median error 0 days, 90th
percentile 3, maximum 50; 42 are within 3 days and 43 within 7. The misses: Express 80 (45986) is
held to its last set, and one bad set at the end reads as a graveyard move
([#71](../../../issues/71)); GOES 16's (41866) keeping stop is a pause before a move already listed,
and SJ-23's (55131) is a move with no later hold ([#72](../../../issues/72)). The largest error is
EUTE 113 West A's (29162) keeping stop, 50 days late because a small burn after keeping ended
anchors it ([#73](../../../issues/73)). DSN-3's (61733) arrival is dated at a trim 9 days after it
settled ([#74](../../../issues/74)). The 2 real events left undated are arrivals after a transfer
orbit, which the sets bound only to a window across a gap ([#70](../../../issues/70)).

The 5 sampled rows that changed in the final list, against the verdicts above (not re-judged):
45986's graveyard move is gone (verdict artefact); 29162's keeping stop is dated 2024-01-31
(estimate 2024-01-30, was 50 days late); 55131's departure is a `relocation_start` on the same day
(verdict wrong type, correct type `relocation_start`); 45985's arrival is dated 2021-03-14
(estimate 03-15, was 3 days late); 61733's arrival is dated 2024-11-12 (estimate 11-18, was 9 days
late, now 6 early).

### In-sample audit

`findings/state_audit/`: 50 events drawn from the belt list as it stood before steps 6-18 (frozen
in that folder's `events.csv`). **This audit is in-sample**: steps 6-18 of the dating rules were
written after reading these verdicts, so it describes the earlier list and cannot measure the
final one.

| type | sampled | real | artefact | duplicate | wrong type |
|---|---|---|---|---|---|
| relocation_start | 10 | 10 | 0 | 0 | 0 |
| relocation_end | 13 | 13 | 0 | 0 | 0 |
| graveyard | 7 | 7 | 0 | 0 | 0 |
| keeping_stop | 6 | 5 | 1 | 0 | 0 |
| ns_keeping_stop | 7 | 5 | 2 | 0 | 0 |
| free_burn | 7 | 2 | 3 | 2 | 0 |
| all | 50 | 42 | 6 | 2 | 0 |

Of the 42 real events, 41 could be dated. Leaving out north-south stops, the median error was 1
day and 27 of 36 were within 3 days; 8 of the 9 more than 3 days off were late, mostly changes in
a gap dated at its end. The 5 real north-south stops were dated 82 to 114 days late (median 108).
Steps 19 to 26 moved three sampled rows further: 58990's start to 2024-06-16 (verdict: the change
falls between the 06-14 and 06-18 sets), 32478's keeping stop to 2022-08-17 (estimate 08-17) and
54225's arrival to 2023-05-26 (estimate 05-25).

Four sampled rows are corroborated by public pages, quoted in `summary.json` under
`public_sources`: Intelsat 33E (41748), COMS 1 (36744), Astra 2D (26638) and Astra 5B (39617).

## Detector evaluation

`harness/evals/` scores the step detector against burn logs. `harness/evals/split.json` fixes
`train` (the train objects of `groundtruth/splits.json`, 2021-2023), `dev` (the same objects,
2024-2025) and `test` (held-out objects, 2021-2025, refused without `--final`). Coverage, matching
and counting rules are fixed in `harness/evals/detector.py`. Label files are read only through
`orbit_watch.truth.read_label_rows` and series built only through `to_series`, both of which refuse
held-out objects unless `final=True`: a guard against tuning on them by accident, not a wall.

The kept setting is `harness/evals/settings/inc-vector.json`: the ISS setting in every regime,
plus an inclination channel on GEO (`inc_z_min` 30, `inc_step_min_deg` 0.02). The GEO logs are
two QZSS satellites, kept far more cleanly than most of the belt, so the detector is not tuned
burn by burn against them; a change has to pass these gates instead (scores in
`harness/evals/results/<split>-inc-vector.json`):

| Gate | Status |
|---|---|
| GEO east-west recall >= 0.9 | met: train 36/39 = 0.923, dev 33/34 = 0.971 |
| ISS recall >= 0.95 | dev 35/35 = 1.000 met; train 45/48 = 0.938 not met |
| At most 0.2 false state-change events per object-year on logged satellites | met: 0 in 6.459 object-years (see above) |
| The same on the held-out Fengyun-2F and Fengyun-4A | measured, not gated: 0 in 2.15 object-years at each of four rule states |
| Planted changes in held satellites | measured, not gated (see above) |
| Recall and dating error on cited GEO events | dev 13/13, median 2 days; test 18/20, median 5 days |
| Hand audit of about 50 belt events | out of sample: 47 of 50 real with the right type |

- GEO north-south recall is reported, not gated: train 6/17, dev 4/14. The inclination channel's
  job is to help date when north-south keeping stops, not to catch each burn.
- At the detection level GEO has 4 false alarms (unmatched detections away from any logged burn)
  over 2.388 object-years on train and 7 over 1.956 on dev; another 15 on train and 12 on dev fall
  in a burn's match zone and count as duplicates.
- The test split was scored once, at the FROZEN setting (`results/test-frozen.json`). On the
  Fengyun-2F and Fengyun-4A logs: east-west 15 of 20 covered burns, north-south 0 of 3, 10 false
  alarms in 1.73 object-years. On IGSO (QZS-1, QZS-2, QZS-1R) none of the 22 logged events falls
  inside the element-set coverage, and there are 0 false alarms in 3.251 object-years. The kept
  setting has never been scored on test.

## Operating modes

`orbit_watch.modes` labels 1,799 objects (the 1,804 less the 5 held out) per 30-day window.
Year-end counts, transitions and the summary are in `findings/geo_modes/`; 1,477 objects keep one
mode for the whole period, not counting undetermined windows. Known limits:
[#21](../../../issues/21), [#28](../../../issues/28), [#29](../../../issues/29), [#30](../../../issues/30), [#32](../../../issues/32).

No ESA classification for 2021-2025 could be reached, so there is no same-date check. The table
puts ESA's counts for 1 January 2019 (*Classification of Geosynchronous Objects*, Issue 21.0, each
class's opening sentence in section 4) beside ours at the end of 2021
(`findings/geo_modes/year_end_counts.csv`). It is context; nothing was tuned to it.

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

The populations differ: ESA classifies everything in DISCOS, including 206 objects from JSC
Vimpel data and 9 from KIAM (p. 216), many of which have no public element sets; three years of launches, retirements and re-orbits separate the dates; ESA
classifies each object from its whole history and corrects some by hand (p. 50), while this repo
labels 30-day windows, so a keeper between cycles or a librator at a turning point can be
undetermined; and ESA's C4 objects land in the drifting or librating classes here.

## ISS regression bench

The ISS is where the step detector's setting was chosen, and it is not tuned further: every
detector change must keep these numbers. Setting: `k = 4`, `|z| >= 12`, `|step| >= 200 m`,
non-maximum suppression over 1 day, chosen by F1 on 2021-2022 only. An event matches a detection
when its time overlaps the detection's interval widened by 0.5 day, one to one.

| Source, period | NASA list: precision | recall | NASA + Roscosmos: precision | recall |
|---|---|---|---|---|
| Archive 2021-2022 (tuning) | 24/27 | 24/25 | 26/27 | 26/27 |
| Archive 2023 | 16/21 | 16/17 | 20/21 | 20/21 |
| Space-Track 2021-2022 | 23/26 | 23/25 | 25/26 | 25/27 |
| Space-Track 2023 | 16/22 | 16/17 | 20/22 | 20/21 |
| **Space-Track 2024-2025 (held out)** | 27/42 | 27/27 | **35/42 = 0.83** | **35/35 = 1.00** |

Sources: `findings/holdout_2024_2025/report.json` (NASA list) and
`findings/combined_truth_holdout/holdout_2024_2025/report.json` (both lists), each with a
`source_check` block for the earlier periods.

- **Both burn lists are lower bounds**, so an unmatched detection is a lead, not a proven false
  alarm. The unmatched detections are listed under [ISS leads](#iss-leads).
- **2023 is unseen by the thresholds but not by the method**: an earlier detector was scored on it
  once before it was replaced. 2024-2025 is the clean holdout.
- **Space-Track loses one archive event in 2021-2022**, the 2021-12-03 retrograde debris
  avoidance: two transitional element sets that the archive lacks pull the measured step from
  -461 m to about -210 m and `z` below 12.
- **Leave-one-year-out cross-validation** over 2021-2025 on Space-Track with the NASA list:
  precision 64/86 = 0.74, recall 64/69 = 0.93 (`findings/cv_2021_2025/report.json`). It was not
  rerun with the Roscosmos list, because it re-chooses the setting.

**Sensitivity** (`findings/injection/`): synthetic steps planted in quiet stretches of the ISS
series, 600 trials per size.

| Recall at step size | 100 m | 150 m | 200 m | 300 m | 500 m | 1 km |
|---|---|---|---|---|---|---|
| native cadence (about 5 sets a day), frozen setting | 0.01 | 0.01 | 0.52 | 0.98 | 1.00 | 1.00 |
| native, `\|z\| >= 6`, `\|step\| >= 50 m` | 0.95 | 0.98 | 0.98 | 1.00 | 1.00 | 1.00 |
| thinned to about 1 a day, frozen | 0.01 | 0.06 | 0.48 | 0.92 | 0.97 | 1.00 |
| thinned to about 1 every 2 days, frozen | 0.02 | 0.07 | 0.34 | 0.72 | 0.89 | 0.98 |

The 200 m floor, not `z`, sets what the frozen setting sees. On quiet stretches the looser setting
gives about 19 to 21 false alarms a year against 0.94 for the frozen one; unlisted real burns
count as false alarms here. A clean step leaves out a real burn's transitional sets, so these recalls are
upper bounds; thinned series keep the ISS's per-set scatter, so thinned recall is optimistic for
objects tracked less often.

## QZSS

`findings/generalise/report.json`, on the operator logs of QZS-3 and QZS-6 in geostationary
orbit. Chance recall comes from the logs shifted by 7, 13 and 19 days either way.

| Setting | Precision | Recall |
|---|---|---|
| Frozen ISS setting, whole history | 179/253 = 0.71 | 179/232 = 0.77 (chance about 0.10) |
| GEO tune (k = 4, z >= 3, step >= 1,000 m), later part (not blind) | 70/92 | 70/93 |

The ISS setting carries over to GEO east-west burns (about 3 km in semi-major axis). The tuned
later part is not a blind holdout: four method changes came after it was first scored
(`test_part_not_blind` in the report). The unmatched QZS-3 and QZS-6 detections have not been
checked against anything else.

## The belt list

`findings/state_changes/summary.json` (which records the commit it was run at): 1,799 objects,
760 events on 300 of them. The list is `findings/state_changes/events.csv`.

| type | 2021 | 2022 | 2023 | 2024 | 2025 | total |
|---|---|---|---|---|---|---|
| relocation_start | 41 | 39 | 57 | 48 | 57 | 242 |
| relocation_end | 65 | 58 | 84 | 64 | 67 | 338 |
| graveyard | 16 | 11 | 21 | 15 | 19 | 82 |
| keeping_stop | 2 | 7 | 0 | 2 | 4 | 15 |
| ns_keeping_stop | 9 | 7 | 14 | 14 | 15 | 59 |
| free_burn | 0 | 0 | 5 | 10 | 9 | 24 |

One row is dated at the mode-layer boundary (`signal` is `mode_change`) because no sustained
exit or entry was found within 45 days of it, and five have an empty `lon_before` or `lon_after`
because the 10 days used for it hold no element set.

Known limits of the list:

- Arrivals outnumber starts because 108 objects' first relocation event is an arrival: mostly
  objects launched in 2021-2025 or already moving at the start of 2021.
- A slow keeping stop followed by a move more than one burn interval later gives two departures
  for one physical move.
- A move made entirely inside one gap is dated at the gap's end at both ends, as Meteosat-11
  (40732) is in April 2023.
- A climb that has risen less than 150 km when the data end reads as a move under way: SJ-17
  (41838) is listed as a `relocation_start` in November 2025, 115 km above its slot at the end.
- A climb by an object never held in the data is listed as free burns.

All open limits are [issues labelled `debt`](../../../issues?q=is%3Aissue+is%3Aopen+label%3Adebt).

## ISS leads

Nothing here is claimed as a discovery. These are leads from the calibration run, listed with the evidence so they can be checked.

### ISS steps with no announced manoeuvre (2021-01 to 2023-12)

Source: `python -m orbit_watch.calibrate` run at commit 508838a on 5,076 ISS TLEs from the public OndroNR/tle-archive (sha256 `e102dc92…7c51`), with the frozen detector settings `k = 4`, `|z| >= 12`, `|step| >= 200 m`. The plot is `findings/iss_sma.png`; these are the orange markers. A rerun after the 60 s collapse (issue #11), on 5,075 TLEs, gives the same leads; only the 2023-12-22 row changed (it was +3,262 m at z 254.5), because two TLEs 0.02 s apart, two epochs after the step (2023-12-23 17:57), are now one.

The detector found these steps in semi-major axis, and none of them matches an event in `groundtruth/iss_manoeuvres.csv`. That list comes from NASA pages only, so an unmatched step may be a real burn that NASA did not write up, or a detector error.

The last column gives the burn from `groundtruth/iss_roscosmos_manoeuvres.csv` (Roscosmos announcements, compiled without looking at detector output) that each lead now matches under calibrate.py's rule. Six of the eight match. With both lists as ground truth, the same frozen setting on the same TLEs leaves two unmatched (`findings/combined_truth/`): 2021-09-12 (+966 m), for which neither list has a burn (the Roscosmos list's coverage is rated medium for January to October 2021), and 2023-05-04 (+313 m, at the `z` threshold), which this table already marked as a likely false positive.

| Interval (UTC) | Step in a | z | What the plot shows | Related public text | Corroborated by Roscosmos |
|---|---|---|---|---|---|
| 2021-09-12 00:22 to 01:57 | +966 m | 52.5 | clear step up | none found | no |
| 2021-12-24 04:27 to 10:55 | −1,755 m | −24.5 | clear step down | The ISS Daily Summary Report of 2021-12-23 lists "Transition to Reboost Mode" among ground activities; no burn is announced (found in an earlier search of the reports, not re-checked here) | 2021-12-24 01:18 UTC, deboost ([post 2204](https://t.me/roscosmos_gk/2204)) |
| 2022-03-12 03:37 to 05:13 | +804 m | 47.6 | clear step up | The report of 2022-03-11 lists "Transition to Reboost Mode"; no burn is announced (same caveat) | 2022-03-11 19:35 UTC, reboost ([post 3023](https://t.me/roscosmos_gk/3023)) |
| 2023-01-18 10:12 to 15:44 | +1,632 m | 492.1 | clear step up | none found | 2023-01-18 14:57 UTC, reboost ([post 8151](https://t.me/roscosmos_gk/8151)) |
| 2023-03-14 08:46 to 03-15 06:14 | +509 m | 72.4 | step up | NASA, 2023-03-14: "At 7:54 a.m. the ISS Progress 83 thrusters performed a 2-minute, 35-second burn to provide extra distance from a fragment of Russian Cosmos 1408 satellite debris." Kept out of the ground truth because the page gives no time zone or burn date beyond the post date. | 2023-03-14 11:54 UTC, debris avoidance ([post 8766](https://t.me/roscosmos_gk/8766)) |
| 2023-04-30 05:31 to 07:19 | +1,978 m | 124.8 | clear step up | none found | 2023-04-30 00:31 UTC, reboost ([post 9345](https://t.me/roscosmos_gk/9345)) |
| 2023-05-04 16:43 to 05-05 04:38 | +313 m | 12.4 | no clear step; likely a detector false positive | none | no |
| 2023-12-22 19:10 to 12-23 15:09 | +3,234 m | 736.2 | clear step up | none found | 2023-12-23 01:55 UTC, reboost ([post 11900](https://t.me/roscosmos_gk/11900)) |

For the two remaining leads, the next check is a TASS or roscosmos.ru announcement, neither of which could be read for the Roscosmos list. On Space-Track's gp_history the same setting finds the same 2021-09-12 and 2023-05-04 steps and one more unmatched step in 2023, from 2023-03-15 06:14 to 09:18 (+489 m). It lies a day after the 2023-03-14 debris avoidance, which on Space-Track matches a +483 m step from 05:27 to 08:46 that day. Whether it is a second burn or the same burn seen twice in the element sets has not been checked.

### ISS steps with no announced manoeuvre (2024-01 to 2025-12, clean holdout)

Source: `python -m orbit_watch.holdout` on Space-Track gp_history for the ISS (9,077 element sets after merging rows under 60 s apart and keeping the latest issued), frozen setting `k = 4`, `|z| >= 12`, `|step| >= 200 m`. Full table: `findings/holdout_2024_2025/detections.csv`; plot: `findings/holdout_2024_2025/iss_sma_2024_2025.png`.

The detector matched all 27 covered NASA-listed events in this period and made 15 detections that match none of them. Most are steps up of 1.7 to 4.9 km with `z` in the hundreds, the size of a typical reboost.

The last column gives the Roscosmos-announced burn from `groundtruth/iss_roscosmos_manoeuvres.csv` that each detection now matches. Eight of the 15 match; with both lists as ground truth the holdout scores precision 35/42 and recall 35/35 (`findings/combined_truth_holdout/`).

| Interval (UTC) | Step in a | z | Corroborated by Roscosmos |
|---|---|---|---|
| 2024-06-14 11:46 to 19:30 | +3,465 m | 188.5 | no |
| 2024-09-09 01:02 to 05:39 | −257 m | −27.4 | no |
| 2024-09-29 04:02 to 09:41 | +231 m | 60.4 | no |
| 2024-10-04 12:26 to 20:09 | +2,826 m | 74.0 | 2024-10-04 08:44 UTC, reboost ([post 15170](https://t.me/roscosmos_gk/15170)) |
| 2024-11-13 22:09 to 11-14 07:16 | +4,913 m | 1,050.1 | 2024-11-13 16:47 UTC, reboost ([post 15610](https://t.me/roscosmos_gk/15610)) |
| 2024-12-21 20:20 to 12-22 11:31 | +2,204 m | 295.3 | 2024-12-22 01:10 UTC, reboost ([post 16076](https://t.me/roscosmos_gk/16076)) |
| 2025-01-11 18:40 to 01-12 09:54 | +3,137 m | 626.0 | 2025-01-11 17:45 UTC, reboost ([post 16291](https://t.me/roscosmos_gk/16291)) |
| 2025-02-01 03:54 to 17:34 | +3,321 m | 596.6 | 2025-02-01 08:58 UTC, reboost ([post 16452](https://t.me/roscosmos_gk/16452)) |
| 2025-04-02 09:22 to 19:42 | +3,621 m | 717.6 | 2025-04-02 09:52 UTC, reboost ([post 17098](https://t.me/roscosmos_gk/17098)) |
| 2025-04-28 16:46 to 04-29 04:34 | +462 m | 12.0 (at the threshold; the likeliest false positive) | no |
| 2025-06-18 19:26 to 20:01 | +521 m | 345.7 | 2025-06-19 02:34 UTC, reboost ([post 17612](https://t.me/roscosmos_gk/17612)) |
| 2025-08-13 19:51 to 08-14 19:04 | +1,730 m | 1,022.4 | 2025-08-14 04:28 UTC, reboost ([post 17980](https://t.me/roscosmos_gk/17980)) |
| 2025-09-04 02:26 to 21:00 | +945 m | 220.2 | no |
| 2025-10-15 07:11 to 19:34 | +2,394 m | 652.7 | no |
| 2025-11-20 05:19 to 13:04 | +2,730 m | 1,042.2 | no |

Seven remain unexplained. Four of them lie about a day from a burn in the NASA list and have a step within 1% of the step matched to that burn: 2024-06-14 (+3,465 m; the 2024-06-15 reboost matched +3,474 m), 2025-09-04 (+945 m; 2025-09-03 test burn, +941 m), 2025-10-15 (+2,394 m; 2025-10-14 reboost, +2,399 m) and 2025-11-20 (+2,730 m; 2025-11-19 reboost, +2,710 m). Whether each is a second burn or the same burn seen twice in the element sets has not been checked. The other three are small: 2024-09-09 (−257 m), 2024-09-29 (+231 m) and 2025-04-28 (+462 m, at the `z` threshold). September to December 2025 is the thinnest part of the Roscosmos list (see `groundtruth/README.md`), so a Russian burn there may still be missing from it.

### Not yet done

- The unmatched QZS-3 and QZS-6 detections (see [QZSS](#qzss)) have not been checked against momentum-unloading windows or any other source.
