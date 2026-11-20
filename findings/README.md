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
- [Routine score and irregularity rank](#routine-score-and-irregularity-rank)
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
  below, and its score was never used to choose a rule. Steps 19 to 30 were built without it.
  After them the test split, the planted test hosts and the held-out check were scored at three
  commits (3098372, 3b56a09 and d8bd4e0) with the same numbers each time, the later changes
  coming from belt rows, and once more after two review fixes (9eb916b), where only the planted
  test trial 835 moved (see Planted changes). The one cited test event that moved is the arrival of
  28912, cited only to May 2022 and so scored as 15 May. Its sets show a 48.7 km burn on
  2022-04-21 that stops a 0.59°/day drift at 45.56°, 0.06° from the slot, after which the object
  only settles within ±0.04°/day; step 19 dates the arrival at that burn, 24 days before the
  mid-month date instead of 2. One test object's belt row was looked at
  while building step 14: the graveyard move of 28707, now dated 17 days before its cited date. Its
  date moved by one day as a result (from 18 to 17 days early), and its departure on 2021-11-09,
  a burn that lowers the orbit by about 50 km and starts an eastward drift, became a
  `relocation_start` instead of a `keeping_stop`. After steps 27 to 30 the test split, the
  planted test hosts and the held-out check were scored once more (3279456): every number is
  the same as before them. After steps 31 to 34 and the merge of the mode-layer changes they were
  scored once more, at the commit each result file records: the cited test split and the held-out
  check are unchanged, and the planted test changes are listed under Planted changes.
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
| dev | 13 | 12 | 10 | 32.9 |
| test | 20 | 18 | 13 | 34.3 |
| all | 33 | 30 | 11.5 | 34.1 |

By type over both splits: relocation starts 8 of 8, relocation ends 7 of 8, graveyard moves 13 of
15, ends of keeping 2 of 2. Caught graveyard moves are dated early (median 22 days, 11 of 13
before the source date): several sources date the end of disposal, and the layer dates a change
at the start of its window. Luch (Olymp)'s short stays between moves read as control because a
burn brackets them on both sides, so its four events are caught. The 3 misses: Express-AM33's
arrival, whose hold ends in a keeping stop rather than a burn and so stays undetermined;
Express-AM3, already free before a climb the layer cannot see because it does not use the
semi-major axis; and Astra 3A, whose change the layer dates 2022-11-18, 58 days before the middle
of the month the source gives.

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
- The held-out count was run at eight rule states, 0 events each time, and never used to choose a
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
| dev | relocation | 0.02-0.1 | 100 | 89/100 = 0.89 | start | 92/100 | 1 | 6 | 0 | 0.08 / 0 |
| dev | relocation | 0.02-0.1 | 100 | 89/100 = 0.89 | end | 92/100 | 0 | 4 | 0 | 0.08 / 0 |
| dev | relocation | 0.1-3 | 150 | 148/150 = 0.99 | start | 149/150 | 0 | 1 | 0 | 0.007 / 0 |
| dev | relocation | 0.1-3 | 150 | 148/150 = 0.99 | end | 149/150 | 0 | 1 | 0 | 0.007 / 0 |
| dev | relocation | 0.02-0.05 | 50 | 40/50 = 0.80 | start | 43/50 | 2 | 10.4 | 0 | 0.16 / 0 |
| dev | relocation | 0.02-0.05 | 50 | 40/50 = 0.80 | end | 43/50 | 0 | 8.2 | 0 | 0.16 / 0 |
| dev | relocation | 0.05-0.1 | 50 | 49/50 = 0.98 | start | 49/50 | 0 | 1.4 | 0 | 0 / 0 |
| dev | relocation | 0.05-0.1 | 50 | 49/50 = 0.98 | end | 49/50 | 0 | 2 | 0 | 0 / 0 |
| dev | relocation | 0.1-0.3 | 50 | 49/50 = 0.98 | start | 50/50 | 0 | 1 | 0 | 0.02 / 0 |
| dev | relocation | 0.1-0.3 | 50 | 49/50 = 0.98 | end | 49/50 | 0 | 1.2 | 0 | 0.02 / 0 |
| dev | relocation | 0.3-1 | 50 | 49/50 = 0.98 | start | 49/50 | 0 | 1 | 0 | 0 / 0 |
| dev | relocation | 0.3-1 | 50 | 49/50 = 0.98 | end | 50/50 | 0 | 1 | 0 | 0 / 0 |
| dev | relocation | 1-3 | 50 | 50/50 = 1.00 | start | 50/50 | 0 | 1 | 0 | 0 / 0 |
| dev | relocation | 1-3 | 50 | 50/50 = 1.00 | end | 50/50 | 0 | 1 | 0 | 0 / 0 |
| dev | keeping stop | | 80 | - | keeping_stop | 68/80 | 7.5 | 30.3 | 0 | 0 / 0.325 |
| dev | graveyard climb | | 80 | - | graveyard | 80/80 | 0 | 1 | 0 | 0.037 / 0.25 |
| dev | free burn | | 80 | 51/80 = 0.64 | keeping_stop | 64/80 | 10.5 | 29.7 | 4 | 0.3 / 0.362 |
| dev | free burn | | 80 | 51/80 = 0.64 | free_burn | 53/80 | 0 | 1 | 0 | 0.3 / 0.362 |
| test | relocation | 0.02-0.1 | 100 | 91/100 = 0.91 | start | 96/100 | 1 | 8 | 0 | 0.07 / 0 |
| test | relocation | 0.02-0.1 | 100 | 91/100 = 0.91 | end | 93/100 | 0 | 7.8 | 0 | 0.07 / 0 |
| test | relocation | 0.1-3 | 150 | 147/150 = 0.98 | start | 147/150 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 0.1-3 | 150 | 147/150 = 0.98 | end | 149/150 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 0.02-0.05 | 50 | 41/50 = 0.82 | start | 46/50 | 2 | 10 | 0 | 0.14 / 0 |
| test | relocation | 0.02-0.05 | 50 | 41/50 = 0.82 | end | 43/50 | 1 | 29.6 | 0 | 0.14 / 0 |
| test | relocation | 0.05-0.1 | 50 | 50/50 = 1.00 | start | 50/50 | 0 | 2 | 0 | 0 / 0 |
| test | relocation | 0.05-0.1 | 50 | 50/50 = 1.00 | end | 50/50 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 0.1-0.3 | 50 | 49/50 = 0.98 | start | 49/50 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 0.1-0.3 | 50 | 49/50 = 0.98 | end | 49/50 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 0.3-1 | 50 | 48/50 = 0.96 | start | 48/50 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 0.3-1 | 50 | 48/50 = 0.96 | end | 50/50 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 1-3 | 50 | 50/50 = 1.00 | start | 50/50 | 0 | 1 | 0 | 0 / 0 |
| test | relocation | 1-3 | 50 | 50/50 = 1.00 | end | 50/50 | 0 | 1 | 0 | 0 / 0 |
| test | keeping stop | | 80 | - | keeping_stop | 64/80 | 7 | 28.8 | 0 | 0 / 0.312 |
| test | graveyard climb | | 80 | - | graveyard | 80/80 | 0 | 1 | 0 | 0.037 / 0.163 |
| test | free burn | | 80 | 52/80 = 0.65 | keeping_stop | 62/80 | 5.5 | 23 | 2 | 0.263 / 0.225 |
| test | free burn | | 80 | 52/80 = 0.65 | free_burn | 55/80 | 0 | 1 | 0 | 0.263 / 0.225 |

The 0.02-0.1 and 0.1-3 rows pool the five bins below them. "All truths caught" counts trials where
every planted truth is matched: both ends of a relocation, or the stop and the burn.

**False events on untouched stretches.** Unmatched events on the host stretch before the plant
(and after a relocation): dev 15 over 1,412.5 trial-object-years, test 14 over 1,315.9. A stretch
used by several trials counts once per trial, and most of these are real: 10 of the dev ones are
one 1.1° move of 23553 in April 2021, 2 a shift of 34713 in January 2021, and 2 the keeping stop
of 25258 that the first hand audit dates a day earlier. On test, 33750 and 55912 make real moves
and 26638's graveyard move is dated inside a gap; the keeping stop of 29162 (trial 301's host) is
now dated 2024-01-31 by step 25, inside its host stretch. Step 31 dates a keeping stop of 47851
(trial 639's host) on 2022-12-09, inside its host stretch and 59 days before the planted stop,
which that trial now misses. The planted free path leaves the box 71 days after the host's last
burn, about four of its 17.46-day burn intervals, and step 31 sets no upper limit on that gap,
so it dates the stop half an interval after the last burn. The dev trials step 31 improves have
gaps of 1.0 to 6.1 intervals, so they cannot set a limit that would exclude this one
([#97](../../../issues/97)). Two are not real: a 0.1° keeping excursion of
26880 on 2025-03-31, and a 10° jump in a day on 52903 on 2022-11-17, a mix-up between element
sets.

**Inside all 594 candidate held stretches, before any plant**, with 45 days trimmed from each end:
50 events over 2,131.9 object-years (0.023 per object-year): 9 relocation pairs and 32 ends of
north-south keeping. The relocation pairs are on 23553, 27168, 28626, 28885, 35755, 37237, 52903 (the element-set mix-up), 55912 and 58204; most are real moves that
the 30-day windows hid when the hosts were chosen. The 32 north-south stops are real (two more on
41911 and 44978, keepers on an inclination sawtooth at the end of the record, are gone): they were
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
| test | keeping stop | < 0.1 km | 69 | 56 | 20 | 0 | 0.29 / 0 |
| test | keeping stop | >= 0.1 km | 11 | 10 | 5 | 5 | 0.455 / 0 |
| test | graveyard climb | < 0.1 km | 67 | 61 | 3 | 3 | 0.045 / 0 |
| test | graveyard climb | >= 0.1 km | 13 | 12 | 13 | 13 | 1 / 1 |
| test | free burn | < 0.1 km | 64 | 57 | 28 | 1 | 0.438 / 0 |
| test | free burn | >= 0.1 km | 16 | 12 | 11 | 8 | 0.688 / 1 |

What the trials show:

- **Short moves.** Relocations under 1.5° are caught at both ends in 43 of 46 trials. Starts
  caught: 1.5-3° 119 of 128, 3-6° 155 of 158, 6° and more 167 of 168.
- **The slowest moves.** Below 0.03°/day the drift can stay inside the held band, so a start is
  dated when the longitude leaves the box (62374 from 2025-04-29, 38 days late) or missed: 6 of 35
  starts and 8 of 35 ends are missed (44186 from 2024-09-28 gives no event).
- **Keeping stops near a stable longitude.** Near 105° W and 75° E a free object barely drifts, so
  its stop is dated late or missed: GOES 17 (43226) stopped on 2024-03-20 and MUOS 5 (41622) on
  2024-02-13 are both missed. Slow libration can also read as holds: EWS-G3 (35491) stopped on
  2021-04-19 gives later relocation pairs, and GSAT 11 (43824) and DirecTV 10 (31862) do the same.
- **Extra free burns after a stop are mostly a planting artefact.** The 76 trials on hosts with
  held-era scatter of at least 0.1 km give 61 extra free burns; the other 404 give 7. The free path
  carries the host's manoeuvre-like excursions that no detected burn explains. These extras say
  little about the belt, and **the free-burn threshold must not be tuned on these trials**. Three
  planted free burns count as caught 4 to 29 days off (trials 829, 868 and 919), most likely
  through such noise rather than the planted burn.
- **Steps the detector misses.** Step 34 finds 5 dev free burns the detector misses because the
  step ramps over several sets or sits next to a gap (trials 866, 910, 912, 948 and 966). Trial
  950 (host 23553), caught before the mode-layer changes were merged, now misses both its stop
  and its burn.
  Two more (824 and 852) stay missed: their steps are under 12 times the host's set-to-set
  scatter, the detector's frozen threshold.
- **Slow moves read as a stop then a move.** Six dev slow relocations (trials 2, 54, 58, 62, 122
  and 154) were listed as a keeping stop at the planted start and a relocation start at the first
  fast set. Step 30 lists one relocation start at the stop's date; their dates did not change.
- **Stop then burn.** A free burn soon after a stop near the slot can split the stop with a short
  hold, so the stop is typed `relocation_start` (trials 834, 861, 906, 928 and 930).
- **Planted stops read as moves on test.** Two test trials now read the free drift after a planted
  stop as a move: trial 909 (host 48618) types the stop `relocation_start` with an extra
  `relocation_end`, so the test free-burn trials' mistyped stops go from 1 to 2, and trial 957
  (host 38977) gains a relocation pair near a stop it still misses. The same pattern shows on 11
  dev keeping-stop and free-burn trials both before and after steps 31 to 34, with no new dev
  case, so the dev trials cannot choose a fix.

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
sampled row is a later free burn). Steps 19 to 34 and the lone-set filter came after the verdicts
and change 6 sampled rows (and the size of 2 more), listed below the table. Two sampled objects were read while writing rules: HYLAS 1 (37237) for step 12, before
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

The 6 sampled rows that changed in the final list, against the verdicts above (not re-judged):
45986's graveyard move is gone (verdict artefact); 29162's keeping stop is dated 2024-01-31
(estimate 2024-01-30, was 50 days late); 55131's departure is a `relocation_start` on the same day
(verdict wrong type, correct type `relocation_start`); 45985's arrival is dated 2021-03-14
(estimate 03-15, was 3 days late); 61733's arrival is dated 2024-11-12 (estimate 11-18, was 9 days
late, now 6 early); GOES 16's (41866) keeping stop on 2025-02-13 is gone (verdict duplicate).
Only the size changed on two more: TJS-3's (43874) start on 2024-11-12 (31.317 to 31.323 km) and
ChinaSat 6C's (44067) on 2023-04-29 (-24.123 to -24.13 km). Step 33 moves `lon_before` or
`lon_after` on 9 sampled rows, by up to 5.81°: 41937's start on 2025-01-16 now reads -96.81°,
where its sets sit for the month before it, instead of the wide hold's centre at -102.62°. No date
or type changed.

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
54225's arrival to 2023-05-26 (estimate 05-25). Step 33 moves `lon_before` or `lon_after` on 6
sampled rows, by up to 7.83°: 25954's graveyard move on 2023-02-11 now starts from -134.92°, where
its sets sit before the climb, instead of the wide hold's centre at -142.75°. No date or type
changed.

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
| The same on the held-out Fengyun-2F and Fengyun-4A | measured, not gated: 0 in 2.15 object-years at each of eight rule states |
| Planted changes in held satellites | measured, not gated (see above) |
| Recall and dating error on cited GEO events | dev 13/13, median 2 days; test 18/20, median 5.5 days |
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
| C2 | 150 | 4.2, p. 83 | 148 |
| C4 | 7 | 4.3, p. 96 | (in drifting or librating) |
| D | 831 | 4.4, p. 97 | 876 |
| L1 | 127 | 4.5, p. 167 | 113 |
| L2 | 46 | 4.6, p. 178 | 41 |
| L3 | 22 | 4.7, p. 182 | 18 |
| I | 21 | 4.8, p. 191 | 21 |
| Ind | 2 | 4.9, p. 193 | 33 |
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
768 events on 301 of them. The list is `findings/state_changes/events.csv`.

| type | 2021 | 2022 | 2023 | 2024 | 2025 | total |
|---|---|---|---|---|---|---|
| relocation_start | 41 | 39 | 58 | 48 | 58 | 244 |
| relocation_end | 65 | 58 | 85 | 64 | 68 | 340 |
| graveyard | 16 | 12 | 21 | 15 | 19 | 83 |
| keeping_stop | 2 | 7 | 0 | 2 | 3 | 14 |
| ns_keeping_stop | 9 | 7 | 14 | 14 | 13 | 57 |
| free_burn | 0 | 0 | 5 | 11 | 14 | 30 |

One row is dated at the mode-layer boundary (`signal` is `mode_change`) because no sustained
exit or entry was found within 45 days of it, and five have an empty `lon_before` or `lon_after`
because the 10 days used for it hold no element set.

Two free burns sit at the edge of other changes. 28790's on 2025-01-23 is a +3.47 km step in the
semi-major axis across a three-day gap in the sets (01-22 to 01-25), the third of three small
raises of an object drifting at -4.86°/day above the belt; the first two, on 01-16 and 01-18, were
listed before. 62852's on 2025-12-13 (-138 km) is the burn that ends a westward move at
1.78°/day and stops the object at 29.04°; the burns that started that move, between 2025-12-04
and 12-09, fall in gaps between sets and are not listed, and the move is not typed a relocation
because the last mode window, from 2025-12-02 to the end of the data, reads as drifting.

Known limits of the list:

- Arrivals outnumber starts because 108 objects' first relocation event is an arrival: mostly
  objects launched in 2021-2025 or already moving at the start of 2021.
- A slow keeping stop followed by a move more than one burn interval later, with no burn at the
  move, gives two departures for one physical move: 28884 (keeping stop 2022-08-10, relocation
  start 2022-09-27) and 31800 (2025-04-22 and 2025-05-17), whose drift relative to the hold
  reaches 0.057 and 0.040°/day between them ([#81](../../../issues/81)). In the three other
  stop-then-move pairs (29162, 37150 and 45465) a large burn starts the move.
- 36411's relocation start is listed on 2022-12-19, but its sets show it kept inside a 1.1° box
  until a 32 km burn on 2023-04-05 starts the move ([#96](../../../issues/96)).
- A move made entirely inside one gap is dated at the gap's end at both ends, as Meteosat-11
  (40732) is in April 2023.
- A climb that has risen less than 150 km when the data end reads as a move under way: SJ-17
  (41838) is listed as a `relocation_start` in November 2025, 115 km above its slot at the end.
- 9 of the 244 relocation starts have a `size` whose sign disagrees with the shorter way round
  from `lon_before` to `lon_after`. Five are moves the long way round (26719, 27632 twice, 28707
  and 41937), 40732 in 2021 goes out and comes back to the same slot, and 27380, 40732 in 2023
  and 44076 move inside a gap with no fast set, so the size uses every set in the span.

All open limits are [issues labelled `debt`](../../../issues?q=is%3Aissue+is%3Aopen+label%3Adebt).

## Routine score and irregularity rank

`findings/routine/summary.json` (which records the commit it was run at) and the files beside it.
The method is in [orbit_watch/README.md](../orbit_watch/README.md#routine-score-and-irregularity-rank);
the checks are in `findings/routine/checks_all.json`, `planted_all.json` and `planted_all.csv`. This
is the second version of the score. Its six changes from the first were published before it was
rerun ([#87](../../../issues/87#issuecomment-7020316572)), and none was changed after a result.

The scorer rebuilt `findings/state_changes/events.csv` (768 rows) from the element sets with no row
missing or added either way. Of the 1,799 objects, 532 are rated (held at least 2 years) and 1,267
are not; 1,172 of those were never held. The 341 departures on the list are 197 scored relocation
starts, 47 relocation starts in an object's first 180 days, which are not scored, and 97
end-of-life rows (83 graveyard moves and 14 keeping stops). End-of-life departures are listed in
`departures.csv` with `end_of_life` 1 but not ranked: they add no bits, and the rank's
`end_of_life` column counts them. 104 rated objects have any bits; the other 428 have no scored
departure, 32 of them with only end-of-life rows. There are 8 stay overruns, and 35 of the 340
arrivals, on 29 objects, are flagged by the proximity rule. The belt rate is 0.0962 relocation
starts per held year at the end (`belt_prior.csv`; by year 0.0832, 0.0782, 0.1137, 0.093 and
0.1118 for 2021 to 2025).

**What the order means.** Only 33 of the 197 scored departures have a stay record (three measured
stays before them); the other 164 are scored by the rate model, where an object's first departure
scores 7.326 to 10.457 bits (106 first departures). 131 departures are off-routine, 8 of them on
the stay model. Only eight rated objects get any bits from the stay model: the top 7, and HYLAS 1
(rank 28), whose nine stay-scored departures keep its rhythm at 0.457 to 0.566 bits each. Below
rank 7 the order is set by the rate model alone, which counts how many times an object left and
how late. That stays open in [#87](../../../issues/87), with held years that start at the first
element set: few objects have three measured stays in five years, and the rate model ignores
timing.

The stay window is now the smaller of ±15 days and ±0.2 times the stay, so it narrows only for
stays under 75 days. The plan expected the bits of every stay-scored departure to rise. That was
wrong, and the window change moved essentially no belt departure. Only 2 of the 33 stay-scored
departures have stays under 75 days, both TJS-3: the 45-day one on 2023-03-25 is new on this list,
and the 60-day one on 2025-03-17 fell from 3.686 to 3.281 bits because its past stays went from 4
to 5. Of the 32 departures scored by the stay model in both versions (same object and date in both
`departures.csv` files), 8 rose, 21 were unchanged (stays of 83 days or more) and 3 fell slightly,
and every rise and fall comes from past stays that changed with the event list. All 8 rises have
stays of 84 to 541 days, where the window is still ±15 days: seven are HYLAS 1, whose past stays
shifted with the event list (its 2022-03-04 stay went from 86 to 92 days), and the eighth is TJS-3
on 2024-11-12 (541 days), whose past stays went from 3 to 4. The three falls are two HYLAS 1
departures and the 60-day TJS-3 one. 31 objects with bits in the first
version have none now. XM-3 (first version rank 15) is rank 58, and EUTE 113 WEST A (rank 24) is
rank 161 with no bits; both were judged end of life in the first audit.

The top 20 of `rank.csv` (bits per year, in total and from each model):

| rank | object | NORAD | bits per year | stay model | rate model | departures per held year | end of life | off-routine | proximity flags |
|---|---|---|---|---|---|---|---|---|---|
| 1 | SJ-17 | 41838 | 8.02 | 3.7 | 4.321 | 2.007 | 0 | 2 | 0 |
| 2 | LUCH (OLYMP) | 40258 | 7.755 | 6.445 | 1.309 | 1.423 | 1 | 3 | 6 |
| 3 | SJ-20 | 44910 | 6.792 | 3.041 | 3.751 | 1.74 | 0 | 1 | 0 |
| 4 | TJS-3 | 43874 | 6.342 | 2.944 | 3.397 | 1.74 | 0 | 2 | 0 |
| 5 | WGS F3 (USA 211) | 36108 | 6.106 | 4.214 | 1.893 | 2.172 | 0 | 1 | 0 |
| 6 | LUCH (OLYMP) 2 | 55841 | 5.131 | 2.883 | 2.248 | 1.754 | 0 | 0 | 2 |
| 7 | JCSAT 16 | 41729 | 5.119 | 3.191 | 1.928 | 1.174 | 0 | 1 | 0 |
| 8 | SYRACUSE 3A | 28885 | 4.214 | 0.0 | 4.214 | 0.633 | 0 | 2 | 0 |
| 9 | TJS-10 | 58204 | 3.787 | 0.0 | 3.787 | 0.471 | 0 | 1 | 0 |
| 10 | CHINASAT 6C | 44067 | 3.568 | 0.0 | 3.568 | 0.631 | 0 | 1 | 0 |
| 11 | CHINASAT 10 | 37677 | 3.215 | 0.0 | 3.215 | 0.428 | 0 | 2 | 0 |
| 12 | INTELSAT 904 | 27380 | 3.214 | 0.0 | 3.214 | 0.414 | 0 | 2 | 0 |
| 13 | GAOFEN 13 02 | 55912 | 3.206 | 0.0 | 3.206 | 0.359 | 0 | 1 | 0 |
| 14 | AEHF 5 (USA 292) | 44481 | 3.178 | 0.0 | 3.178 | 0.428 | 0 | 2 | 1 |
| 15 | TDRS 5 | 21639 | 3.166 | 0.0 | 3.166 | 0.47 | 0 | 2 | 0 |
| 16 | HYLAS 2 | 38741 | 3.14 | 0.0 | 3.14 | 0.444 | 0 | 2 | 0 |
| 17 | USA 170 | 27875 | 3.117 | 0.0 | 3.117 | 0.452 | 0 | 2 | 0 |
| 18 | USA 164 | 27168 | 3.088 | 0.0 | 3.088 | 0.413 | 0 | 2 | 0 |
| 19 | EUTE HOT BIRD 13C (HB 9) | 33459 | 3.067 | 0.0 | 3.067 | 0.425 | 0 | 2 | 0 |
| 20 | GOES 17 | 43226 | 3.066 | 0.0 | 3.066 | 0.421 | 0 | 2 | 0 |

Ranks 8 to 30 are objects held 2.124 to 4.847 years with one to three scored departures (HYLAS 1
has 12), at 2.763 to 4.214 bits per year; below them bits per year fall to 0.832 at rank 104, the
last object with bits. The top 5% cut is 2.798 bits per year and 27 objects reach it.

### Checks

Each target below was set in the design before the first run, and the score was not tuned to any
of them, with one exception: the stay window's share `f` was chosen on check 4's dev trials, so
check 4's dev shares are not out of sample and its test trials are the held-out result. The
targets did not change for the second version.

| Check | Result | Target | Verdict |
|---|---|---|---|
| 1. Off-routine rows on rocket bodies and debris | 0 in 1,898.2 object-years on 445 objects; none rated | about 0.01 per object-year | pass |
| 2. Off-routine rows on QZS-3, QZS-6 and Fengyun-2H on station | 0 in 6.46 object-years | 0 | pass |
| 3. Cited relocation starts on objects held a year before them, flagged when caught | 1 of 4 (dev: 4 cited, 2 held, 2 caught, 1 flagged; test: 4 cited, 2 held, 2 caught, 0 flagged) | 90% | fail |
| 4. Planted rhythm, 4 moves then 1, both on- and off-rhythm right | over trials whose last move was caught and scored: 0.811 (dev, 73 of 90), 0.804 (test, 74 of 92); over all 100 trials: 0.73 and 0.74 | 90% of trials | fail |
| 5. Top 30 on 2021 to mid-2023 in the top 60 on the rest | 5 of 24 (24 objects have bits in the first half, 43 in the second; 412 rated in both), Spearman 0.068 | half | fail |
| 6. Spearman of as-of reruns against the full run cut at the same date | 0.705 (2022, one object with bits), 0.918, 1.0, 0.976 | 0.9 | pass at the 2023-2025 cuts, fail at 2022 |
| 6. The same against the final run | 0.089, 0.342, 0.726, 0.841 | 0.9 | fail |
| 7. Top 30 judged irregular in the blind hand audit | 27 of 30 | 24 of 30 | pass |
| 8. Cited irregular objects in the top 5% | 4 of 6 rateable (18 listed); `evidence` = `object` only: 4 of 6 rateable (15 listed) | 75% | fail |
| 9. Cited steady keepers in the lower half | 31 of 31 rateable; with no scored departure: 31 of 31, against 428 of 532 rated objects (0.805), chance 0.00094 | 90% | pass, but weak (see below) |

**Cited departures (check 3).** Only cited relocation starts are scored now; 8 are cited and 4 are
on objects held a year before them, too few for a firm percentage. Luch (Olymp)'s move in March
2025 is flagged (13.288 bits, stay model). The three caught but not flagged are SJ-17's move in
February 2023 (4.862 bits, rate model), SJ-17 in November 2024 (1.395 bits, stay model) and Luch
(Olymp) 2 in February 2025 (4.97 bits, stay model), whose earlier stays make the timing
unsurprising. Cited graveyard moves and keeping stops are reported apart: of the 17 cited (6 dev,
11 test), 11 are on objects held a year before them, the list catches 10 and types all 10 as end
of life. The one not caught is 27400's graveyard move, cited for January 2023 (read as
2023-01-15): the list has it on 2022-11-17, 59 days earlier, outside the 45-day matching window.

**Cited lists (checks 8 and 9).** `groundtruth/irregular_objects.csv` and
`groundtruth/steady_objects.csv`. The four irregular objects in the top 5% are SJ-17 (rank 1), Luch
(Olymp) (2), TJS-3 (4) and Luch (Olymp) 2 (6). MEV-1 is rank 37 (2.143 bits per year, one scored
departure) and MEV-2 rank 475 (no scored departure). The other 12 are unrated: five of the six
GSSAP satellites have no held span in the element sets and the sixth is held 0.028 years, and
SJ-21, SJ-23, SJ-25, Shiyan-12 01 and 02 and LDPE-3A are held under 2 years. `unrated.csv` lists 15
to 54 unchecked steps outside holds for those six. All six rateable irregular objects have `object`
evidence, so the two shares are the same. The lower-half share is weak: the median of bits per year
among rated objects is 0, so any object without a scored departure is in the lower half. The
comparison beside it is the informative number: none of the 31 keepers has a scored departure,
against 80.5% of rated objects with none, and a random draw of 31 rated objects has all 31 with none
with chance 0.00094. That shows the keepers leave less often than the belt, not that the rank
orders the objects that do leave; [#90](../../../issues/90) stays open for a check that does not
rest on a median of 0.

**Causality (check 6).** The list and held spans rebuilt from element sets cut at each date,
against the full run cut at the same date (the effect of look-ahead alone) and against the final
run:

| cut | held years bar | objects | with bits as of | Spearman, same date | Spearman, final | objects whose bits differ by 0.1 or more |
|---|---|---|---|---|---|---|
| 2022-01-01 | 0.9 | 443 | 1 | 0.705 | 0.089 | 2 |
| 2023-01-01 | 1.8 | 446 | 13 | 0.918 | 0.342 | 4 |
| 2024-01-01 | 2.0 | 478 | 54 | 1.0 | 0.726 | 0 |
| 2025-01-01 | 2.0 | 503 | 75 | 0.976 | 0.841 | 4 |

Against the 0.9 target, look-ahead alone passes from the 2023 cut on; at the end of 2021 only one
object has bits, so that correlation means little. Against the final run every cut fails: a rank
built on one to four years of data does not predict the five-year rank. Where look-ahead changes
an object, it changes a whole departure (the largest gap is 9.869 bits in the 2025 cut): a
departure typed or dated differently once later sets arrive.

**Planted rhythm (check 4).** 100 trials per split and variant, seed 20261119, stay window share
0.2. "On" counts last departures under 2 bits on rhythm; "off" counts 5 bits or more off it. The
target is both right in 90% of trials. It is stated both ways: over trials whose last planted
departure was caught and scored, as in the first version, and over all 100.

`f` was chosen on the dev `4+1` trials alone, before this run, from the five values in the plan:
0.653, 0.764, 0.764, 0.778 and 0.764 for `f` = 0.05, 0.1, 0.15, 0.2 and 0.25 (47, 55, 55, 56 and 55
right of the 72 trials whose last move was caught and scored). Those shares were measured on the
state-change list as it stood at 4d2fe9d (760 rows), before the mode and event changes, which is
why the same `f` gives 0.811 on the final list. The sweep's outputs are not committed; it can be
rerun with `python -m harness.evals.routine planted --split dev --share F`.

| split | variant | caught and scored | on rhythm under 2 bits | off rhythm at least 5 bits | both targets, of caught and scored | both targets, of all 100 | scored by the stay model | verdict |
|---|---|---|---|---|---|---|---|---|
| dev | 3+1 | 88 | 0 of 45 | 5 of 43 | 0.057 | 0.05 | 16 | fail |
| dev | 4+1 | 90 | 41 of 48 | 32 of 42 | 0.811 | 0.73 | 83 | fail |
| test | 3+1 | 95 | 4 of 49 | 1 of 46 | 0.053 | 0.05 | 14 | fail |
| test | 4+1 | 92 | 39 of 47 | 35 of 45 | 0.804 | 0.74 | 83 | fail |

`3+1` is the test as first specified. Its last departure has only 2 past stays and falls to the
rate model, which ignores timing, so it cannot pass. With `4+1`, where every rhythm move was caught
and the stay model scored it, on-rhythm departures are under 2 bits in 41 of 44 (dev) and 38 of 42
(test), and off-rhythm ones reach 5 bits in 32 of 39 and 35 of 40. Off-rhythm stays shorter than
the rhythm (less than 1/1.3 of it) are flagged in 15 of 21 (dev) and 16 of 21 (test) scored `4+1`
trials, and longer ones (more than 1.3 times) in 17 of 21 and 19 of 24. The last move is not caught
in 10 (dev) and 8 (test) `4+1` trials. [#88](../../../issues/88) stays open: 0.811 and 0.804
against 90%, and 0.73 and 0.74 counting every trial.

**Hand audit (check 7).** A fresh sample drawn from this version's rank with a new seed:
`audit_sample.csv` lists 50 objects (the top 30, and ranks 257 to 276 from the middle) in a shuffled
order, each with a chart of its longitude, drift rate, semi-major axis and inclination with holds
shaded and every listed change marked. A blind judge saw only the 50 charts and
`audit_sample.csv`, never the ranks, groups or any other file, and gave each object one class:

- `none`: no real departure;
- `end_of_life`: only ending keeping and/or a graveyard climb;
- `rhythm`: relocations on a roughly steady interval;
- `irregular`: uneven moves, a move after a long hold that is not end of life, or drifting between
  short stays;
- `unclear`.

It also said whether the listed departures are real. The verdicts are `audit_verdicts.csv`;
`audit_key.csv` maps each audit id to its group, rank and bits per year, and the checks count them
per group (`hand_audit` in `checks_all.json`):

| group | irregular | end_of_life | rhythm | none | unclear | departures real (yes / partly / no / n/a) |
|---|---|---|---|---|---|---|
| top 30 | 27 | 0 | 1 | 0 | 2 | 28 / 0 / 2 / 0 |
| middle 20 | 0 | 1 | 0 | 19 | 0 | 1 / 0 / 0 / 19 |

In the top 30, HYLAS 1 (rank 28) keeps a rhythm: moves every three to six months, each followed by
a hold of two to four months. TJS-10 (rank 9) and GAOFEN 13 02 (rank 13) are `unclear`: their
launch points stretch the chart axes, so a move under about 3° cannot be seen. Their
`departures_real` of `no` means "not visible on the chart", not "disproved". In the middle,
TIANLIAN 1-03 (rank 268) is end of life: its November 2023 graveyard climb is listed and, as an
end-of-life row, adds no bits. On many charts the `relocation_start` and `graveyard` lines render
dark rather than red; the judge treated every line labelled as a departure as one. The charts are
written to `$ORBIT_WATCH_DATA/routine/audit_charts_v2/` and are not committed.

Known limits:

- Only objects held at least 2 years are rated, so recently launched inspectors and objects that
  are rarely held (12 of the 18 cited irregular objects) are on the unrated list instead.
- Most departures are scored by the rate model, which says only that an object left, not whether
  it left on its own schedule, and held years start at the start of the data for objects already
  held then ([#87](../../../issues/87)).
- The planted test stays under target: 10 (dev) and 8 (test) `4+1` last moves are not caught, and
  the stay model still misses some off-rhythm stays ([#88](../../../issues/88)).
- Check 9's lower-half share says little while the median is 0 ([#90](../../../issues/90)).
- The proximity flag's owner code is per country (all US operators share `US`) and it reads 10
  days past the arrival ([#89](../../../issues/89)).

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
