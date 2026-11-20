# GEO station-keeping state changes and irregularity rank, 2021-2025

Dated changes in how every object in the geostationary belt was flown from 2021 to 2025, and a rank of
the objects whose relocations break their own routine, built only from public orbital elements.
Written by `python -m orbit_watch.jobs.dataset` from the committed results in `findings/`; do not edit
by hand.

| File | What it holds |
|---|---|
| [`events.csv`](events.csv) | 768 state changes on 301 objects, one row each, with the object's name, owner and type and, for departures, the routine score |
| [`objects.csv`](objects.csv) | the 1,799 objects in the population, one row each: rated or not and why, rank, bits per year and counts |
| [`evidence/`](evidence/README.md) | the top 30 of the rank: each object's state changes, a longitude chart and the blind hand audit's verdict |

## What it covers

- **Period.** Element sets with epochs from 2021-01-01 to 2025-12-31. Dates are UTC calendar days.
- **Population.** The 1,804 objects with any element set in ESA's GEO region (mean motion
  0.9-1.1 rev/day, eccentricity at most 0.2, inclination at most 70 deg) in that period, less the
  5 objects held out to score the method (37158, 38049, 41882, 42738, 49336): **1,799 objects**, payloads,
  rocket bodies and debris alike. 532 are rated (held at least 2 years in total) and 1,267 are
  not; 1,172 of those were never held.
- **State change.** One change of an object's station-keeping state, dated to the day from the element
  sets. Each 30-day window is first labelled with ESA's mode classes (held in longitude, drifting,
  librating and so on); where the mode changes, the day is found from the drift rate, the longitude
  box or the burns in the semi-major axis.

| `event_type` | What happened |
|---|---|
| `relocation_start` | a held object left its slot and was held again later, was still moving at relocation speed when the data end, or moved at relocation speed until a graveyard climb |
| `relocation_end` | a moving object started to hold a slot |
| `graveyard` | a held object left and its semi-major axis rose at least 150 km, with no later hold; or an object never held climbed at least 150 km above its first 90 days and stayed there |
| `keeping_stop` | a held object stopped east-west station keeping with no climb, no later hold and no move under way at the end of the data, or drifted slowly for more than 90 days before a climb |
| `ns_keeping_stop` | a held object stopped correcting its inclination but kept its longitude |
| `free_burn` | a step of at least 1 km in the semi-major axis by an object never held again |

Rows per type and year (`findings/state_changes/summary.json`):

| type | 2021 | 2022 | 2023 | 2024 | 2025 | total |
|---|---|---|---|---|---|---|
| `relocation_start` | 41 | 39 | 58 | 48 | 58 | 244 |
| `relocation_end` | 65 | 58 | 85 | 64 | 68 | 340 |
| `graveyard` | 16 | 12 | 21 | 15 | 19 | 83 |
| `keeping_stop` | 2 | 7 | 0 | 2 | 3 | 14 |
| `ns_keeping_stop` | 9 | 7 | 14 | 14 | 13 | 57 |
| `free_burn` | 0 | 0 | 5 | 11 | 14 | 30 |

Arrivals outnumber starts because many objects' first relocation event is an arrival: objects launched
in the period or already moving in January 2021.

**Departures and the rank.** A *departure* is a `relocation_start`, `graveyard` or `keeping_stop` row
(341 in all). Each `relocation_start` is scored by how surprising it is against the object's own
record before it, in bits (`-log2 p`): with 3 or more past stays (arrival to next departure), by
where the stay falls under a log-normal fitted to those stays (the *stay* model); otherwise by the
object's own departure rate shrunk towards the belt's (the *rate* model, which ignores timing). A
departure of 5 bits or more is *off-routine*. Graveyard moves and keeping stops are end of life:
listed, never scored. Relocation starts in the first 180 days after an object's first element set are
listed and not scored. Of the 341 departures, 197 are scored (33 by the stay
model, 164 by the rate model), 97 are end of life and 47 are early starts;
131 are off-routine. There are 8 stay overruns, and 35 of the 340 arrivals,
on 29 objects, carry a proximity flag. Objects held at least 2 years are ranked by bits
per year; only 104 of the 532 rated objects have any bits. The 2-year bar is part of
the method, so recently launched inspectors and rarely held objects are on the unrated list, not in
the rank. The full method is in
[orbit_watch/README.md](../orbit_watch/README.md#routine-score-and-irregularity-rank).

## Columns of `events.csv`

Rows are sorted by `norad_id`, then `date`. An empty cell means the column does not apply to that row
unless the column says otherwise.

| Column | Meaning |
|---|---|
| `norad_id` | NORAD catalogue number |
| `name` | SATCAT object name; empty for the 6 objects with no SATCAT entry |
| `owner` | SATCAT owner code (`COUNTRY`): a country or organisation, such as `US`, `PRC`, `CIS`, `ITSO`, `SES` or `EUTE`; every US operator is `US`; empty with no SATCAT entry |
| `object_type` | SATCAT type: `PAYLOAD`, `ROCKET BODY` or `DEBRIS`; empty with no SATCAT entry |
| `event_type` | one of the six types above |
| `date` | the UTC day of the change. A departure is the first element set that leaves the hold's drift band or longitude box and stays out 5 days, or the last burn plus half the burn interval; an arrival the first set that stays inside the new slot's band; a change inside a gap of more than 2 days is placed in the gap from the first set after it |
| `signal` | what dated the change: `rate_exit` or `rate_entry` (drift rate or longitude leaving or entering the hold), `burn_gap` (last east-west burn plus half the burn interval), `a_step` (a step in the semi-major axis), `ns_gap` (last inclination correction plus half the median interval between corrections), `mode_change` (no sustained exit or entry within 45 days, so the 30-day mode boundary is used) |
| `size` | per type: `relocation_start` km, the median semi-major axis of the first moving run minus the hold's, negative when the object drifts east (0 when the next window is already held); `relocation_end` 0; `graveyard` and `keeping_stop` km, the highest semi-major axis after the hold minus the hold's median (0 for a keeping stop followed by a move or climb); `ns_keeping_stop` deg, the largest inclination after it; `free_burn` m, the step detector's step, which can have the opposite sign to the net change on a steady climb |
| `lon_before`, `lon_after` | mean longitude before and after the change, deg east from -180 to 180 (west is negative): from or into a hold, the centre of the hold's longitude range (of its 30 days next to the change when the range is wider than 0.5 deg); on an arrival from a stretch that is not held, `lon_before` is the median of the 10 days before it; for a departure with no later hold, `lon_after` is the median of the last 10 days of the data. Empty when those 10 days hold no element set (5 rows) |
| `mode_before`, `mode_after` | ESA mode class of the 30-day mode segments either side: `controlled_lon_inc` (held, inclination controlled), `controlled_lon` (held), `drifting`, `librating_75E`, `librating_105W`, `librating_both`, `out_of_region` |
| `mode_change` | the date of the 30-day mode boundary the change came from |
| `scored` | departures only: 1 if the relocation start is scored; 0 for end-of-life rows and for starts in an object's first 180 days |
| `end_of_life` | departures only: 1 for `graveyard` and `keeping_stop`, else 0 |
| `model` | `stays` or `rate` for a relocation start; empty for end-of-life rows |
| `past_stays` | departures only: measured stays in the object's record before it |
| `stay_days` | departures only: days since the arrival that opened the stay; empty when the hold started without an arrival row |
| `bits` | relocation starts only: `-log2 p`, with `p` floored at 1e-4 (13.3 bits). Also shown for unscored early starts, where it does not count toward the rank; empty when no belt rate existed yet |
| `off_routine` | departures only: 1 if scored at 5 bits or more, else 0 |
| `proximity_flag` | `relocation_end` rows only: 1 when, over the 10 days from the arrival, another object with a different owner code and launch was already there, within 0.1 deg in longitude and 10 km in semi-major axis; else 0 |
| `near_norad_id` | the neighbour that raised the proximity flag |

## Columns of `objects.csv`

Rated objects come first in rank order, then the unrated ones by `norad_id`. An empty cell means the
column does not apply to that object.

| Column | Meaning |
|---|---|
| `norad_id`, `name`, `owner`, `object_type` | as in `events.csv` |
| `rated` | 1 if held at least 2 years in total, else 0 |
| `unrated_reason` | unrated only: `never_held` (no held span in the data) or `held_under_2_years` |
| `rank` | rated only: 1 is the most irregular; ties are broken by departures per held year, then `norad_id` |
| `bits_per_year` | rated only: the sum of the bits of the object's scored departures over `years_since_first_hold` |
| `stay_bits_per_year`, `rate_bits_per_year` | rated only: the same, split by the model that scored each departure |
| `departures_per_held_year` | rated only: `scored_departures` over `held_years` |
| `held_years` | years held in longitude, summed over held spans |
| `years_since_first_hold` | rated only: years from the start of the first hold to the last element set; a hold under way in January 2021 starts at the first element set |
| `state_changes` | rows in `events.csv` |
| `relocation_starts` | `relocation_start` rows, scored or not |
| `scored_departures` | scored relocation starts |
| `end_of_life` | `graveyard` and `keeping_stop` rows |
| `off_routine` | off-routine departures |
| `overruns` | stays that lasted past the 99th percentile of the object's own fitted stays (needs 3 past stays); dated in `findings/routine/overruns.csv`, not part of the rank |
| `proximity_flags` | flagged arrivals |
| `steps_outside_holds_unchecked` | unrated only: steps the burn detector finds outside holds. They are unchecked: outside holds the detector also fires on dead objects |

## How good it is

Every number below is read from the file named with it.

### The state-change list

**Cited events.** Real relocations, graveyard moves and ends of keeping with a public source
(`groundtruth/geo_events.csv`), split by a hash into dev (used to build the rules) and test (never used
to choose a rule). An event counts as found when a change lies within 45 days of it
(`findings/state_changes/eval_all.json`):

| split | cited events | found | median date error (days) | 90th percentile (days) | same type |
|---|---|---|---|---|---|
| dev | 13 | 13 | 2 | 13 | 13 |
| test | 20 | 18 | 5.5 | 14.9 | 17 |

**False events on logged keepers.** Satellites with published burn logs, while the logs show them on
station; every departure, arrival or stop listed there is false. The target is at most 0.2 per
object-year (`eval_all.json` and `false_events_final.json` in `findings/state_changes/`):

| satellites (object-years) | object-years | false events | held out |
|---|---|---|---|
| QZS-3 (4.998), QZS-6 (0.414), Fengyun-2H (1.047) | 6.459 | 0 | no |
| Fengyun-2F (1.01), Fengyun-4A (1.14) | 2.15 | 0 | yes |

**Planted changes.** Relocations, keeping stops, graveyard climbs and free burns planted in the real
element sets of held satellites (`findings/state_injection/summary.json`):

| planted change | dev: found, median date error | test: found, median date error |
|---|---|---|
| relocation, 0.1-3 deg/day, start | 149/150, 0 d | 147/150, 0 d |
| relocation, 0.1-3 deg/day, end | 149/150, 0 d | 149/150, 0 d |
| relocation, 0.02-0.1 deg/day, start | 92/100, 1 d | 96/100, 1 d |
| relocation, 0.02-0.1 deg/day, end | 92/100, 0 d | 93/100, 0 d |
| keeping stop | 68/80, 7.5 d | 64/80, 7 d |
| graveyard climb | 80/80, 0 d | 80/80, 0 d |
| free burn: the stop | 64/80, 10.5 d | 62/80, 5.5 d |
| free burn: the burn | 53/80, 0 d | 55/80, 0 d |

**Hand audit.** 50 events drawn from a frozen copy of the list, leaving out every object in an
earlier audit, and judged from charts of their element sets (`findings/state_audit_fresh/summary.json`):
47 are real with the right type; of the 45 that could be dated, the median error is
0 days, 42 are within 3 days and the largest is 50 days. Six sampled rows
changed in the final list after the verdicts, each toward the hand reading, and were not judged again.
An earlier audit (`findings/state_audit/`) is in-sample, since rules were written after it, and is not
counted here.

| type | sampled | real, right type | artefact | duplicate | wrong type |
|---|---|---|---|---|---|
| `relocation_start` | 11 | 11 | 0 | 0 | 0 |
| `relocation_end` | 14 | 14 | 0 | 0 | 0 |
| `graveyard` | 7 | 6 | 1 | 0 | 0 |
| `keeping_stop` | 5 | 3 | 0 | 1 | 1 |
| `ns_keeping_stop` | 7 | 7 | 0 | 0 | 0 |
| `free_burn` | 6 | 6 | 0 | 0 | 0 |

### The routine score and rank

**Of the 10 rows below (check 6 has one row per run it is compared with), 4 pass,
5 fail and 1 passes only in part.** Every target was set before the first run,
with one exception: the stay window's share was chosen on check 4's dev trials, so check 4's test
trials are its held-out result. The rank agrees with a blind reading of its top 30 charts and keeps
cited steady keepers out of its upper half, but it flags few cited relocations as off-routine, only
4 of the 6 cited irregular objects held long enough to rate are in its
top 5%, it is not stable between the two halves of the period, a rank on part of the data does not
predict the five-year rank, and the planted rhythm test is below its target. Only 8 rated
objects get any bits from the stay model (ranks 1, 2, 3, 4, 5, 6, 7, 28); everywhere else the order is set by the
rate model alone, which counts how often and how late an object left, not whether it left on its own
schedule. Sources: `checks_all.json` and `planted_all.json` in `findings/routine/`.

| check | result | target | verdict |
|---|---|---|---|
| 1. Off-routine rows on rocket bodies and debris | 0 in 1898.2 object-years on 445 objects; 0 rated | about 0.01 per object-year | pass |
| 2. Off-routine rows on QZS-3, QZS-6 and Fengyun-2H on station | 0 in 6.46 object-years | 0 | pass |
| 3. Cited relocation starts on objects held a year before them, flagged off-routine when caught | 1 of 4 caught (8 cited, 4 on objects held a year before, 4 caught) | 90% of those caught | **fail** |
| 4. Planted rhythm: 4 moves on a fixed rhythm, then one on or off it; both kinds scored right | dev 0.811 of 90 caught and scored, 0.73 of all 100; test 0.804 of 92 caught and scored, 0.74 of all 100 (3 moves then 1: dev 0.057, test 0.053) | 90% of trials | **fail** |
| 5. Top 30 on 2021 to mid-2023 in the top 60 on the rest | 5 of 24; Spearman 0.068 | half | **fail** |
| 6. Spearman of reruns on data cut at each year-end, against the full run cut at the same date | 2022-01-01: 0.705, 2023-01-01: 0.918, 2024-01-01: 1.0, 2025-01-01: 0.976 | 0.9 | part, pass at 2023-01-01, 2024-01-01, 2025-01-01; fail at 2022-01-01 |
| 6. Spearman of reruns on data cut at each year-end, against the final run | 2022-01-01: 0.089, 2023-01-01: 0.342, 2024-01-01: 0.726, 2025-01-01: 0.841 | 0.9 | **fail** |
| 7. Top 30 judged irregular in the blind hand audit | 27 of 30 | 24 of 30 | pass |
| 8. Cited irregular objects in the top 5% | 4 of 6 rateable (18 listed) | 75% | **fail** |
| 9. Cited steady keepers in the lower half | 31 of 31; none of the 31 has a scored departure, and 80.5% of rated objects (428 of 532) have none (chance 0.000944) | 90% | pass, but weak: the median rated object has 0 bits per year |

**Blind audit (check 7).** The top 30 and 20 objects from the middle of the rank were shuffled, and a
judge who saw only one chart per object (longitude, drift rate, semi-major axis and inclination with
holds and changes marked, no ranks or scores) gave each a class (`audit_verdicts.csv` and
`audit_key.csv` in `findings/routine/`):

| group | objects | irregular | rhythm | end_of_life | none | unclear |
|---|---|---|---|---|---|---|
| top | 30 | 27 | 1 | 0 | 0 | 2 |
| middle | 20 | 0 | 0 | 1 | 19 | 0 |

The [evidence page](evidence/README.md) shows each top-30 object with its class and the judge's note.

### Independent cross-check

The list was checked against public sources that were not used to build it
([findings/README.md](../findings/README.md#independent-cross-check); numbers from
`findings/cross_check/summary.json`).

- **Sample:** the top 30 of the rank and 20 objects drawn at random from the rest of the list.
- **Search:** 179 web searches in 2 rounds:
  round 1, 72 for 50 objects (median 1 per object);
  round 2, 107 for 40 objects (median 3 per object).
- **Coverage:** for 38 of the 50 objects the search found no dated claim from any source.
- **Agreement:** 9 of the 9 dated claims from operators and the press match
  the list, on 7 objects, with median and worst date errors of 1 and
  5 days.
- **Element-set analyses, counted apart:** 20 of their 26 dated claims match.
- **Disagreements:** 6 claims, 6 from element-set analyses and
  0 from operators or the press. Two small LUCH (OLYMP) 2 moves are each held inside a
  listed stay ([#101](../../../issues/101)), TJS-10's first arrival on station is not listed
  ([#102](../../../issues/102)), and an SJ-17 burn the list has as a departure is a typing
  difference with no issue.

## Known limits

Each is an open issue labelled `debt`.

- Slow relocations, 0.02-0.05 deg/day, are missed more often and dated later ([#78](../../../issues/78)).
- Keeping stops near the stable longitudes 75 deg E and 105 deg W are dated late or missed, because a
  free object there barely drifts ([#79](../../../issues/79)).
- A change inside a long gap in the element sets is dated at the edge of the gap ([#70](../../../issues/70)).
- A slow keeping stop more than one burn interval before a move gives two departures for one move
  ([#81](../../../issues/81)).
- Rows known to be off: 36411's relocation start is dated months before its real departure in April
  2023 ([#96](../../../issues/96)); 43874's late-2022 start is dated 15 days early, at a hop inside its
  slot ([#94](../../../issues/94)); SJ-17 (41838) is listed as a relocation start in November 2025 that may
  be an unfinished graveyard climb ([#68](../../../issues/68)).
- A keeping stop dated from a natural exit has no upper limit on the gap after the last burn
  ([#97](../../../issues/97)); three event rules have synthetic failure cases not seen in the belt list
  ([#84](../../../issues/84)).
- The mode layer works in 30-day windows, and near the stable points a hold can be misread as control or
  left undetermined ([#32](../../../issues/32), [#30](../../../issues/30), [#29](../../../issues/29)).
- Most departures are scored by the rate model, so below the top few the rank counts departures rather
  than judging their timing ([#87](../../../issues/87)).
- The planted rhythm test stays under its target ([#88](../../../issues/88)).
- Check 9 is weak while the median rated object has 0 bits per year ([#90](../../../issues/90)).
- The proximity flag's owner code is per country, so an arrival next to another operator of the same
  country is never flagged ([#89](../../../issues/89)).
- Moves of 0.4-0.6 deg inside a hold are not listed, such as two LUCH (OLYMP) 2 repositionings
  ([#101](../../../issues/101)).
- TJS-10's (58204) first arrival on station, in November 2023, is not listed
  ([#102](../../../issues/102)).

All open limits: [issues labelled `debt`](../../../issues?q=is%3Aissue+is%3Aopen+label%3Adebt).

## Provenance and licence

- Element sets: the yearly full-catalogue TLE bundles of the CC0 Kaggle dataset
  [historical-tle-datasets](https://www.kaggle.com/datasets/vaibhavpandey12382/historical-tle-datasets).
  The raw element sets are not redistributed here.
- Object names, owners and types: the [Space-Track](https://www.space-track.org) SATCAT.
- Mode classes: ESA Space Debris Office, *Classification of Geosynchronous Objects*, Issue 21.0 (2019).
- Cited events and burn logs used for scoring: [groundtruth/README.md](../groundtruth/README.md).
- The list was written at commit `83cd62d` and scored against the cited events at
  `c3740ff` and the planted changes at `c3740ff`; the rank at `c260adf` from a
  belt cache built at `b405a3c`, and its checks at `bbd6b89` and `3e3d1f9`. Each
  result file records the commit that wrote it.
- Licence: MIT, as the repository; see [LICENSE](../LICENSE).

## Regenerate

From the repository root, with the package installed (`pip install -e .`):

```
python -m orbit_watch.jobs.dataset
```

This rewrites the two tables, this card and the evidence page from `findings/` and needs no data or
network; names, owners and types are kept from `objects.csv`. `--catalogue PATH` takes them from a
GEO-region `manifest.json` with SATCAT entries instead, and `--charts` redraws the evidence charts,
which need the element sets and the belt cache under `$ORBIT_WATCH_DATA` (see
[docs/features.md](../docs/features.md)). `tests/test_dataset.py` fails when a table, this card or the
evidence page no longer matches what the job writes.

## Cite

Cite the orbit-watch repository and the commit you used (`git rev-parse HEAD`), and name the files.
