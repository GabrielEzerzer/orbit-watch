# Detector hill-climb journal (branch `detector-tune`)

## Goal

Tune the step detector per regime against the operator logs, measured by one frozen evaluation.
This first lane built the measurement and recorded the baseline; it changed no detector behaviour.

## Targets

| Regime | Recall target | False alarms |
|---|---|---|
| LEO (IDS logs) | >= 0.9 on logged burns with \|delta_a_est_m\| >= 50 m | <= 1 per object-year |
| GEO (QZS-3, QZS-6) | >= 0.9 east-west, >= 0.8 north-south | <= 1 per object-year |
| IGSO (QZSS) | reported, no recall target | <= 1 per object-year |
| ISS | >= 0.95 (guardrail) | reported, not checked (the lists are lower bounds) |
| GEO Fengyun | exploratory: reported, never counted | reported, never counted |

False alarms are counted on stretches that a log covers, the detector scores, and no logged
burn's match zone touches (`harness/evals/detector.py` docstring).

## Split (`harness/evals/split.json`, committed in 3ca08ab)

- **train:** the train objects of `groundtruth/splits.json`, events and detections 2021-01-01 to 2023-12-31.
- **dev:** the same objects, 2024-01-01 to 2025-12-31. This is the loop's score.
- **test:** the holdout objects, 2021-2025, only with `--final`. Scored **once**, at baseline
  (below). Nobody runs it again until the final round.

An event belongs to the period that holds the midpoint of its window, and a detection to the
period that holds the epoch before its step. The detector runs on each object's whole 2021-2025
series; then each period's events and detections are matched only with each other.

## Metric command

```
PYTHONPATH=. python -m harness.evals.detector --split dev --data-dir D:/code/orbit-watch/data \
    --settings harness/evals/settings/<name>.json
```

Prints the table and writes `harness/evals/results/<split>-<settings name>.json`. The detector
is deterministic: two runs at 3ca08ab gave byte-identical JSON for train and dev under both
settings. The noise floor is therefore the interval width, not run-to-run spread. A round
beats the baseline only if it moves a recall by more than chance would on this event count;
quote the Wilson interval with every recall.

## Baseline at commit 3ca08ab

Recall is matched / covered events, with a 95% Wilson interval. `hit/ev` is matched / all
events: `covered` shrinks as k grows, so check that `hit/ev` doesn't fall. FA is false alarms;
obj-yr is scored no-burn object-years.

### FROZEN (k=4, |z|>=12, |step|>=200 m, every regime)

| Split | Group | Subset | Events | Covered | Hit | Recall | 95% CI | Width | hit/ev | FA | obj-yr | FA/yr |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| train | LEO | all | 192 | 174 | 4 | 0.023 | 0.01-0.06 | 0.05 | 0.021 | 2 | 13.18 | 0.15 |
| train | LEO | >=50 m | 26 | 18 | 4 | 0.222 | 0.09-0.45 | 0.36 | 0.154 | | | |
| train | GEO | all | 68 | 62 | 48 | 0.774 | 0.66-0.86 | 0.20 | 0.706 | 4 | 2.39 | 1.67 |
| train | GEO | EW | 43 | 39 | 36 | 0.923 | 0.80-0.97 | 0.18 | 0.837 | | | |
| train | GEO | NS | 18 | 17 | 6 | 0.353 | 0.17-0.59 | 0.41 | 0.333 | | | |
| train | GEO | EW+NS | 7 | 6 | 6 | 1.000 | 0.61-1.00 | 0.39 | 0.857 | | | |
| train | IGSO | all | 7 | 0 | 0 | - | - | - | 0.000 | 0 | 1.22 | 0.00 |
| train | ISS | all | 49 | 48 | 45 | 0.938 | 0.83-0.98 | 0.15 | 0.918 | 3 | 2.59 | 1.16 |
| train | Fengyun | EW (= all) | 4 | 3 | 3 | 1.000 | 0.44-1.00 | 0.56 | 0.750 | 0 | 1.00 | 0.00 |
| dev | LEO | all | 196 | 185 | 11 | 0.059 | 0.03-0.10 | 0.07 | 0.056 | 0 | 10.55 | 0.00 |
| dev | LEO | >=50 m | 47 | 40 | 11 | 0.275 | 0.16-0.43 | 0.27 | 0.234 | | | |
| dev | GEO | all | 57 | 51 | 41 | 0.804 | 0.68-0.89 | 0.21 | 0.719 | 7 | 1.96 | 3.58 |
| dev | GEO | EW | 37 | 34 | 33 | 0.971 | 0.85-0.99 | 0.14 | 0.892 | | | |
| dev | GEO | NS | 16 | 14 | 5 | 0.357 | 0.16-0.61 | 0.45 | 0.312 | | | |
| dev | GEO | EW+NS | 4 | 3 | 3 | 1.000 | 0.44-1.00 | 0.56 | 0.750 | | | |
| dev | IGSO | all | 4 | 0 | 0 | - | - | - | 0.000 | 0 | 0.46 | 0.00 |
| dev | ISS | all | 36 | 35 | 35 | 1.000 | 0.90-1.00 | 0.10 | 0.972 | 4 | 1.72 | 2.33 |
| dev | Fengyun | - | 0 | | | | | | | | | |
| test | LEO | all | 121 | 120 | 0 | 0.000 | 0.00-0.03 | 0.03 | 0.000 | 1 | 13.57 | 0.07 |
| test | LEO | >=50 m | 19 | 19 | 0 | 0.000 | 0.00-0.17 | 0.17 | 0.000 | | | |
| test | IGSO | all | 22 | 0 | 0 | - | - | - | 0.000 | 0 | 3.25 | 0.00 |
| test | Fengyun | all | 27 | 23 | 15 | 0.652 | 0.45-0.81 | 0.36 | 0.556 | 10 | 1.73 | 5.78 |
| test | Fengyun | EW | 24 | 20 | 15 | 0.750 | 0.53-0.89 | 0.36 | 0.625 | | | |
| test | Fengyun | NS | 3 | 3 | 0 | 0.000 | 0.00-0.56 | 0.56 | 0.000 | | | |

Test was scored once, at 3ca08ab with `--final`, at FROZEN only. The `generalise` tune below was
not scored on test, so the holdout stays at one look. There are no QZSS GEO or ISS objects in the
holdout, so the GEO and ISS targets have no test score. A blind north-south number does not
exist (`groundtruth/README.md`).

Target check at FROZEN:

| Target | train | dev | test |
|---|---|---|---|
| LEO recall >=50 m >= 0.9 | MISS 0.22 | MISS 0.28 | MISS 0.00 |
| LEO FA <= 1/obj-yr | PASS 0.15 | PASS 0.00 | PASS 0.07 |
| GEO EW >= 0.9 | PASS 0.92 | PASS 0.97 | no events |
| GEO NS >= 0.8 | MISS 0.35 | MISS 0.36 | no events |
| GEO FA <= 1/obj-yr | MISS 1.67 | MISS 3.58 | no exposure |
| IGSO FA <= 1/obj-yr | PASS 0.00 (but nothing is covered, see below) | PASS 0.00 (same) | PASS 0.00 (same) |
| ISS recall >= 0.95 | **MISS 0.938** (45/48) | PASS 1.00 (35/35) | no events |

### generalise's existing tune (`settings/generalise-tune.json`: LEO k=6 |z|>=40 step>=0; GEO and IGSO k=4 |z|>=3 step>=1000 m; ISS FROZEN)

That tune was chosen in `generalise.run` on CryoSat-2, Jason-3, SWOT, SPOT-5, QZS-3 and QZS-6
before each object's 60th-percentile month, so it has seen some train and dev labels here. Treat
it as a reference point, not a clean score.

| Split | Group | Subset | Events | Covered | Hit | Recall | 95% CI | hit/ev | FA | obj-yr | FA/yr |
|---|---|---|---|---|---|---|---|---|---|---|---|
| train | LEO | all | 192 | 156 | 117 | 0.750 | 0.68-0.81 | 0.609 | 8 | 12.04 | 0.66 |
| train | LEO | >=50 m | 26 | 16 | 14 | 0.875 | 0.64-0.96 | 0.538 | | | |
| train | GEO | EW | 43 | 39 | 37 | 0.949 | 0.83-0.99 | 0.861 | 1 | 2.39 | 0.42 |
| train | GEO | NS | 18 | 17 | 7 | 0.412 | 0.22-0.64 | 0.389 | | | |
| dev | LEO | all | 196 | 176 | 158 | 0.898 | 0.84-0.93 | 0.806 | 15 | 9.93 | 1.51 |
| dev | LEO | >=50 m | 47 | 38 | 32 | 0.842 | 0.70-0.93 | 0.681 | | | |
| dev | GEO | EW | 37 | 34 | 33 | 0.971 | 0.85-0.99 | 0.892 | 1 | 1.96 | 0.51 |
| dev | GEO | NS | 16 | 14 | 3 | 0.214 | 0.08-0.48 | 0.188 | | | |

IGSO, ISS and Fengyun come out the same as under FROZEN. The full output is in `harness/evals/results/{train,dev}-generalise-tune.json`.

### What the interval widths say

The eval is small. On dev, one GEO north-south event is 0.07 of recall (n=14), and the interval
is 0.45 wide. Even a dev score of 12/14, which would pass the 0.8 target, has a Wilson lower
bound of about 0.60. GEO east-west (n=34) and LEO >=50 m (n=40) have intervals 0.14 and 0.27
wide, and the ISS (n=35) one 0.10 wide. On test, LEO >=50 m has n=19 and Fengyun north-south
n=3. A pass on any of these is an observed rate on these events, not evidence that a population
target is met.

### Findings from building the baseline

- **IGSO can't be scored at all with the current gap rules.** Space-Track issues no QZS-4
  element sets for about 3-5 days after each burn (for example 2021-01-09 to 2021-01-14 and
  2023-06-30 onward). No gap within `MAX_GAP_DAYS` = 2 overlaps a burn, so 0 of 7 train, 0 of 4
  dev and 0 of 22 test IGSO events are covered. The IGSO FA "PASS" is on the scored time between
  burns only. Recovering IGSO needs `max_gap_days` (a `score_gaps` argument, today a constant and
  not part of `Setting`) to be tuned per regime, which belongs to round 3.
- **The ISS guardrail fails on train at FROZEN.** On Space-Track 2021-2023 the score is 45/48 =
  0.938, which equals `holdout.py`'s Space-Track source check (25/27 + 20/21). The misses are
  2021-12-03 debris avoidance, 2022-06-20 test/aborted burn and 2023-11-09 reboost. The archive
  TLEs give 46/48. Dev is 35/35, the published holdout. A round "keeps ISS >= 0.95" only on dev
  unless train improves.
- **The 2-day late tolerance misses one QZS-3 east-west burn.** QZS-3-160 (2023-04-16 13:59,
  delta_a_est -3,319 m) is missed: its step (-3,238 m, z -3,325) starts 2.4 days after the burn,
  so it also counts as a train false alarm. The 2025-02-25 burn is matched, and a second step 3.1
  days later (-3,043 m) counts as a dev false alarm. This is a limit of `LATE_DAYS`, not a label
  error. It was left as is (the brief: say so before changing a rule).
- **GEO false alarms cluster.** Six of the seven dev GEO false alarms are steps of ±470-780 m
  within days of each other, often of opposite sign: QZS-3 on 2025-12-15 and 12-21, and QZS-6 on
  2025-09-02, 09-10 and twice on 09-22. Train has the same pattern on QZS-3 (2021-06-20 and
  06-25, plus 2021-12-15). None was checked against any source.
- **The LEO >=50 m set at FROZEN is limited by the 200 m step floor:** 0/19 on test. The
  `generalise` tune reaches 0.84-0.88 on train and dev at the cost of 1.5 FA/obj-yr on dev.
- **Burns without `delta_a_est_m`:** none in the IDS logs. All Fengyun lines lack it; they count
  in the all-events recall and in the EW/NS subsets, and never in the LEO >=50 m subset.
  Merged burn/counter-burn pairs use their net estimate.

## DECISION FOR GABRIEL

No label looked wrong in this lane: every GEO false alarm checked lies near, but outside, a
logged burn's match zone, or has no logged burn nearby and no evidence against the log. Four
measurement-rule questions came up. None was changed:

1. **Late tolerance.** Should `LATE_DAYS` (2 days) widen for GEO? The QZS-3 steps above appear
   2.4 and 3.1 days after logged burns. Widening it would turn one train miss and FA into a
   match, and drop one dev FA.
2. **Coverage denominator.** Recall is over covered events, and `covered` depends on k (k=6
   covers 156 train LEO events against 174 at k=4). The table now shows `hit/ev` beside it. Do
   you want the targets judged on a denominator fixed at k=4 instead?
3. **ISS false alarms** are reported but not checked against the <= 1/obj-yr target, because the
   NASA and Roscosmos lists are lower bounds (FINDINGS.md explains several "false alarms" as
   unlisted Russian burns). Confirm, or say if they should count.
4. **ISS guardrail on train** starts below 0.95 (0.938). Should it be judged on dev only, or
   "no worse than 45/48 on train and 35/35 on dev"?

5. **Duplicate detections count toward GEO NS recall** (round 1). QZS-3's NS burns usually come
   less than a day before an EW burn, QZSS events have no expected sign, and `match_near` lets a
   second detection of the EW step match the NS burn. Five of the six train NS hits at FROZEN are
   that. Peak-radius NMS (#13) removes the duplicates (dev GEO FA 3.58 -> 2.56/yr, ISS FA down on
   both splits, no other recall change) but costs those five, so the keep rule reverted it. Should
   the keep rule exempt NS hits that come from a duplicate of an EW step (for example, require an
   NS match to be a detection no EW event also matches within its zone), or should #13 come back
   once an NS channel exists that finds those burns on its own?

Also disclosed: while checking whether any log row lacks `delta_a_est_m`, I read the label CSVs
directly with a one-off script, outside `orbit_watch.truth`. It printed per-object, per-year row
counts by kind for every object, holdout ones included. No detector output was involved and
nothing was tuned. All harness code reads labels only through the guarded loaders.

## Planned rounds (in order; not implemented)

1. **#13 peak-radius NMS.** Each peak absorbs the unassigned flagged gaps fewer than k gaps
   from it, and the detection interval is their union. It must keep the 2025-09-25 aborted ISS
   reboost separate (gaps 8822/8824/8826).
2. **An inclination channel for north-south burns** (GEO NS recall is 0.35 at FROZEN).
3. **Per-regime settings tuned on train,** scored on dev. Candidates include `max_gap_days` /
   `max_span_days` for IGSO (finding above).

## Keep rule

The eval sets are small, so a gain must show on both dev and train, or show on dev with train
unchanged, to count. A round is kept only if:

- its target metric improves;
- no regime's covered recall or matched/all-events recall (`hit/ev`) drops on dev or train;
- false alarms per object-year rise in no regime;
- the ISS stays at or above baseline on both splits (35/35 dev, 45/48 train; pooled 2021-25 >= 0.95);
- the `covered` denominator does not shrink for the regime being improved. A gain that comes from
  events leaving the denominator does not count; `hit/ev` is reported beside it.

A round's write-up says when its gain rests on a handful of events. A round that fails is reverted
with `git revert`, so the history shows the attempt.

## Rounds

### Round 1: #13 peak-radius NMS

**Hypothesis.** One burn flags several neighbouring gaps as the windows slide past it. Time-only
NMS (1 day) keeps a second flagged gap when it sits more than a day from the best one (a
transitional element set between them, or GEO's one or two element sets a day), and that gap is
reported as a second detection: a false alarm on GEO (part of 3.58/yr on dev) and an unmatched
ISS detection (#13's five). Letting each peak absorb the flagged gaps fewer than k gaps from it
removes them without merging distinct burns: a gap k or more away from the peak has a window
whose before-side and after-side are each separated from the peak's by the peak's gap.

**Change.** `detect.pick`: flagged gaps in decreasing |z|; a gap not yet absorbed becomes a peak
unless its centre is within `nms_days` of a kept peak's centre (the existing time rule, between
peaks only); a peak absorbs the unabsorbed flagged gaps fewer than k gaps from it. The detection
spans the union of its gaps; step and z are the peak's. `GapScores` carries k. Not repeated
(earlier failures): window-overlap merging (2k), chained grouping. Test: the real ISS
2025-09-24..27 gaps (8822 z 72, 8824 z 12.4 mixing both burns, 8826 z 177 in the 2021-2025
Space-Track series; 15/17/19 in the `mock/` slice) must give two detections.

**Target.** GEO FA/object-year down, ISS unmatched detections down, no recall lost.

**Result at 3191d57 (FROZEN settings).** REVERTED: train GEO NS recall fell.

| Split | Group | Subset | Baseline hit/cov (hit/ev) | Round 1 hit/cov (hit/ev) |
|---|---|---|---|---|
| dev | LEO | >=50 m | 11/40 (11/47) | 11/40 (11/47) |
| dev | GEO | EW | 33/34 (33/37) | 33/34 (33/37) |
| dev | GEO | NS | 5/14 (5/16) | 5/14 (5/16) |
| dev | GEO | all | 41/51 | 41/51 |
| dev | GEO | FA/obj-yr | 7 / 1.96 = 3.58 | 5 / 1.96 = 2.56 |
| dev | LEO | FA/obj-yr | 0.00 | 0.00 |
| dev | ISS | all | 35/35, FA 4 (2.33/yr), 42 detections | 35/35, FA 3 (1.75/yr), 38 detections |
| train | LEO | >=50 m | 4/18 (4/26) | 4/18 (4/26) |
| train | GEO | EW | 36/39 (36/43) | 36/39 (36/43) |
| train | GEO | NS | 6/17 (6/18) | **1/17 (1/18)** |
| train | GEO | all | 48/62 | **43/62** |
| train | GEO | FA/obj-yr | 4 / 2.39 = 1.67 | 4 / 2.39 = 1.67 |
| train | LEO | FA/obj-yr | 0.15 | 0.15 |
| train | ISS | all | 45/48, FA 3 (1.16/yr) | 45/48, FA 2 (0.77/yr) |

Covered counts are unchanged everywhere (same k). The duplicates went as intended: dev GEO FA
7 -> 5 (QZS-3 2025-02-27 -3,043 m and QZS-6 2025-09-22 -771 m absorbed), ISS dev detections
42 -> 38, ISS FA dev 4 -> 3 and train 3 -> 2 (#13's 2023-03-15 and 2025-11-20 among them). On
train ISS, the 2023-11-09 reboost is now matched and the 2023-11-10 debris avoidance is not (net
45/48 either way).

Why train NS fell: each of the five lost QZS-3 NS burns (110+111, 120, 127, 140, 146) is followed
within a day by an EW burn of about -3 km, and at baseline the NS burn was "matched" by a second
detection of that same EW step, scored at a gap more than a day from the first (QZS-3 2021-11-26:
gaps 840 and 842, steps -3,285 m and -3,361 m). QZSS events carry no expected sign, so any
same-time detection matches them. Peak-radius NMS reports that step once, so it can match only
one of the two events. Baseline NS recall on train therefore rests in part on duplicate
detections, and any change that removes duplicates lowers it. Dev NS stayed 5/14 by chance (one
lost, QZS-3-221+222; one gained, QZS-3-194+195). Under the keep rule this round is reverted;
see DECISION FOR GABRIEL 5.

### Round 2: inclination channel for north-south burns

**Hypothesis.** A GEO north-south burn turns the orbit plane and changes the semi-major axis
little, so the a-only detector misses it (NS 5/14 dev, 6/17 train). On QZS-3 the inclination
series shows NS burns as steps of about 0.005-0.03 deg against a scatter of about 0.0001 deg
(median sigma 0.096 mdeg at k=4), while EW burns leave it flat (|step| under 0.001 deg).
Scoring inclination like semi-major axis should find the NS burns that are more than a day from
an EW burn. The ones less than a day before an EW burn (most QZS-3 NS burns) fall in the EW
step's NMS window and stay unfound: the merge gives the a channel priority.

**Change.** `score_gaps(..., channel="i")` scores inclination in degrees with the same method;
`Detection` and `GapScores` carry the channel. `merge_channels` adds inclination detections whose
centre is more than `nms_days` from every a-detection's centre. `Setting` gains `inc_z_min` and
`inc_step_min_deg` (off when None); the eval's `Obj.detections` runs the inclination channel only
when the setting turns it on, so ISS, LEO and IGSO are untouched. Wiring this through is one call
in `harness/evals/detector.py`; matching and counting are unchanged.

**Threshold, from train only.** Grid on train, GEO only, k=4: inc_z_min in {12, 20},
inc_step_min_deg in {0.003, 0.005, 0.008, 0.011}. Rule: the loosest setting at which train
GEO FA does not rise.

Train grid (GEO; every setting gives train NS 9/17, EW 36/39, EW+NS 6/6):

| inc_z_min | 0.003 deg | 0.005 | 0.008 | 0.011 |
|---|---|---|---|---|
| 12 | FA 9 | 7 | 5 | **4** |
| 20 | 5 | 5 | 4 | 4 |

Chosen: z 12 (the a channel's own floor, so one new parameter) and the smallest step floor with no
train FA rise, 0.011 deg (`settings/inc-channel.json`).
