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

False alarms are counted on stretches that a log covers, the k=4 coverage reference or the
setting scores, and no logged burn's match zone touches (`harness/evals/detector.py` docstring).

## Split (`harness/evals/split.json`, committed in 3ca08ab)

- **train:** the train objects of `groundtruth/splits.json`, events and detections 2021-01-01 to 2023-12-31.
- **dev:** the same objects, 2024-01-01 to 2025-12-31. This is the loop's score.
- **test:** the holdout objects, 2021-2025, only with `--final`. Scored **once**, at baseline
  (below). Nobody runs it again until the final round.

An event belongs to the period that holds the midpoint of its window, and a detection to the
period that holds the first epoch of its peak gap. The detector runs on each object's whole 2021-2025
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

## Eval correction at 896ae19 (the measurement changed, the detector did not)

Three things let a detector change move its own score: coverage depended on the setting's k, a
detection was matched by its whole interval, and two detections of one step could each be
credited with a different event. 896ae19 fixes the measurement. The detector behaves as before;
the only production change is two `Detection` fields, `peak_start`/`peak_end`, which `pick` sets
to the detection's one gap (so they equal `start`/`end`). The rules are in the
`harness/evals/detector.py` docstring. Every fix that has a test was confirmed by breaking the
code: 13 breaks, each failing its test.

1. **Coverage reference.** An event is covered when a gap the k=4 reference scores overlaps its
   window (`REF_K` = 4, `REF_MAX_SPAN_DAYS` = 3, `REF_MAX_GAP_DAYS` = 2, eval constants). A
   covered event stays in the denominator at every setting and is a miss unless a detection
   matches it; `hit/ev` (matched / all events) is kept. The brief said to compute the reference
   with `score_gaps` at k=4. I copied its gap rule into the eval instead (`reference_scored`), so
   a later change to `score_gaps` or to `generalise`'s constants cannot move the denominator. A
   test pins the copy to `score_gaps` at k=4 on regular and irregular series, and the two agree
   on all 13 train objects.
2. **Exposure** is the no-burn time that the reference or the setting scores (the union). The new
   `scored` column is exposure over no-burn time: 0.92-0.99 in every regime except IGSO, where
   it is 0.41 on train and 0.23 on dev. The docstring's QZS-4 example is corrected: QZS-4 has
   about one element set a day, so four sets often span more than 3 days, and it has none for
   3-5 days after each burn.
3. **Peak gap.** A detection is assigned to a period, matched and judged a false alarm by its
   peak gap, never by its interval. A test pins that a detection whose interval overlaps a burn
   but whose peak does not is a miss plus a false alarm.
4. **Label guard.** The label-read scan in `tests/test_truth.py` now covers `harness/` as well as
   `orbit_watch/`. A new test checks that the `data/geo` fallback refuses a holdout object
   unless `final` is set.
5. **README** says that the >=50 m subset uses the merged net `delta_a_est_m`. It says that seven
   SWOT pairs in 2021-2025 (four train, three dev; holdout not checked) have every row at 50 m
   or more but a smaller net, so they are left out. It also says that a merged EW+NS event counts
   toward neither GEO target.
6. **Duplicates** (`dup`) are unmatched detections, not false alarms, whose peak gap overlaps a
   logged burn's match zone. They are reported per regime.
7. **One-to-one matching.** Each detection goes to its nearest eligible event, centre to centre
   (ties to the earlier event), and to no other. An event that several detections pick goes to
   the nearest of them (ties to the earlier detection). Under the old rule, a second detection
   of one step could be credited with a neighbouring event.
8. **Round 2's eval edit** (`Obj.detections(setting)`) is wiring only. With the inclination
   channel off it is the old single `pick` call; with it on, it adds `merge_channels`. Kept.

Train and dev were re-run at 896ae19 for FROZEN, generalise's tune and `settings/inc-channel.json`
(`harness/evals/results/`, committed in cce7ebc). Test was not rerun (see below).

## Baseline (FROZEN at 3ca08ab, re-scored on the corrected eval at 896ae19)

Recall is matched / covered events, with a 95% Wilson interval. Since 896ae19, `covered` comes
from the k=4 reference whatever the setting. `hit/ev` is matched / all events. FA is false
alarms. obj-yr is exposure in object-years: no-burn time the reference or the setting scores.
`scored` is exposure / no-burn time. `dup` counts duplicates. Where a cell changed with the
correction it reads old → new; the `scored` and `dup` columns are new.

### FROZEN (k=4, |z|>=12, |step|>=200 m, every regime)

| Split | Group | Subset | Events | Covered | Hit | Recall | 95% CI | Width | hit/ev | FA | obj-yr | scored | FA/yr | dup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| train | LEO | all | 192 | 174 | 4 | 0.023 | 0.01-0.06 | 0.05 | 0.021 | 2 | 13.18 | 0.93 | 0.15 | 0 |
| train | LEO | >=50 m | 26 | 18 | 4 | 0.222 | 0.09-0.45 | 0.36 | 0.154 | | | | | |
| train | GEO | all | 68 | 62 | 48 → **46** | 0.774 → 0.742 | 0.66-0.86 → 0.62-0.83 | 0.20 → 0.21 | 0.706 → 0.676 | 4 | 2.39 | 0.92 | 1.67 | 14 |
| train | GEO | EW | 43 | 39 | 36 | 0.923 | 0.80-0.97 | 0.18 | 0.837 | | | | | |
| train | GEO | NS | 18 | 17 | 6 → **4** | 0.353 → 0.235 | 0.17-0.59 → 0.10-0.47 | 0.41 → 0.38 | 0.333 → 0.222 | | | | | |
| train | GEO | EW+NS | 7 | 6 | 6 | 1.000 | 0.61-1.00 | 0.39 | 0.857 | | | | | |
| train | IGSO | all | 7 | 0 | 0 | - | - | - | 0.000 | 0 | 1.22 | 0.41 | 0.00 | 0 |
| train | ISS | all | 49 | 48 | 45 | 0.938 | 0.83-0.98 | 0.15 | 0.918 | 3 | 2.59 | 0.99 | 1.16 | 0 |
| train | Fengyun | EW (= all) | 4 | 3 | 3 | 1.000 | 0.44-1.00 | 0.56 | 0.750 | 0 | 1.00 | 0.98 | 0.00 | 1 |
| dev | LEO | all | 196 | 185 | 11 | 0.059 | 0.03-0.10 | 0.07 | 0.056 | 0 | 10.55 | 0.98 | 0.00 | 1 |
| dev | LEO | >=50 m | 47 | 40 | 11 | 0.275 | 0.16-0.43 | 0.27 | 0.234 | | | | | |
| dev | GEO | all | 57 | 51 | 41 | 0.804 | 0.68-0.89 | 0.21 | 0.719 | 7 | 1.96 | 0.94 | 3.58 | 11 |
| dev | GEO | EW | 37 | 34 | 33 | 0.971 | 0.85-0.99 | 0.14 | 0.892 | | | | | |
| dev | GEO | NS | 16 | 14 | 5 | 0.357 | 0.16-0.61 | 0.45 | 0.312 | | | | | |
| dev | GEO | EW+NS | 4 | 3 | 3 | 1.000 | 0.44-1.00 | 0.56 | 0.750 | | | | | |
| dev | IGSO | all | 4 | 0 | 0 | - | - | - | 0.000 | 0 | 0.46 | 0.23 | 0.00 | 0 |
| dev | ISS | all | 36 | 35 | 35 | 1.000 | 0.90-1.00 | 0.10 | 0.972 | 4 | 1.72 | 0.99 | 2.33 | 3 |
| dev | Fengyun | - | 0 | | | | | | | | | | | |
| test | LEO | all | 121 | 120 | 0 | 0.000 | 0.00-0.03 | 0.03 | 0.000 | 1 | 13.57 | not run | 0.07 | not run |
| test | LEO | >=50 m | 19 | 19 | 0 | 0.000 | 0.00-0.17 | 0.17 | 0.000 | | | | | |
| test | IGSO | all | 22 | 0 | 0 | - | - | - | 0.000 | 0 | 3.25 | not run | 0.00 | not run |
| test | Fengyun | all | 27 | 23 | 15 | 0.652 | 0.45-0.81 | 0.36 | 0.556 | 10 | 1.73 | not run | 5.78 | not run |
| test | Fengyun | EW | 24 | 20 | 15 | 0.750 | 0.53-0.89 | 0.36 | 0.625 | | | | | |
| test | Fengyun | NS | 3 | 3 | 0 | 0.000 | 0.00-0.56 | 0.56 | 0.000 | | | | | |

**Why the FROZEN train and dev numbers changed.** Only train GEO changed: NS 6/17 → 4/17 and
all 48/62 → 46/62, both from one-to-one matching (item 7). QZS-3-120 and QZS-3-140 were credited
by a second detection of the east-west step that follows each of them within a day. That
detection's nearest event is the east-west burn, which the first detection already holds, so it
is now a duplicate and the north-south burn is a miss. Everything else is identical, object by
object: coverage, the false-alarm list, exposure, and every other hit, on both splits. That is
what the rules predict at FROZEN. k=4 is the reference, so coverage (item 1) and exposure
(item 2) are the same sets. FROZEN's `pick` reports one-gap detections, so the peak gap is the
interval (item 3). Duplicates (item 6) are a new column, not a change to any count. The 14 train
GEO duplicates are all QZS-3. The 11 dev GEO duplicates are QZS-3 10 and QZS-6 1; the other
duplicates are dev ISS 3, dev LEO 1 (CryoSat-2) and train Fengyun 1.

**Why the FROZEN test baseline should be unchanged** (test is not rerun; it stays at one look).
The same argument holds on the holdout. Coverage, exposure and peak assignment are identities at
FROZEN, so `covered`, obj-yr and the false-alarm counts stay the same. The false-alarm count does
not depend on which event a detection is matched to: an unmatched detection inside a burn zone is
a duplicate, outside one it is a false alarm, under both rules. One-to-one matching can change a
hit only where some detection is eligible for an event. On test, LEO has 0 hits and IGSO has 0
covered events, so neither has anything to reassign. Fengyun (15/23, exploratory, never counted)
is the only test number that could move, and only where two of its burns lie within one
detection's match zone. There are no QZSS GEO or ISS objects in the holdout, so the GEO and ISS
targets have no test score. A blind north-south number does not exist (`groundtruth/README.md`).
The `generalise` tune below was never scored on test.

Target check at FROZEN:

| Target | train | dev | test |
|---|---|---|---|
| LEO recall >=50 m >= 0.9 | MISS 0.22 | MISS 0.28 | MISS 0.00 |
| LEO FA <= 1/obj-yr | PASS 0.15 | PASS 0.00 | PASS 0.07 |
| GEO EW >= 0.9 | PASS 0.92 | PASS 0.97 | no events |
| GEO NS >= 0.8 | MISS 0.24 (0.35 before 896ae19) | MISS 0.36 | no events |
| GEO FA <= 1/obj-yr | MISS 1.67 | MISS 3.58 | no exposure |
| IGSO FA <= 1/obj-yr | PASS 0.00 (but nothing is covered, see below) | PASS 0.00 (same) | PASS 0.00 (same) |
| ISS recall >= 0.95 | **MISS 0.938** (45/48) | PASS 1.00 (35/35) | no events |

### generalise's existing tune (`settings/generalise-tune.json`: LEO k=6 |z|>=40 step>=0; GEO and IGSO k=4 |z|>=3 step>=1000 m; ISS FROZEN)

That tune was chosen in `generalise.run` on CryoSat-2, Jason-3, SWOT, SPOT-5, QZS-3 and QZS-6
before each object's 60th-percentile month, so it has seen some train and dev labels here. Treat
it as a reference point, not a clean score. Old → new is 3ca08ab's eval → 896ae19's.

| Split | Group | Subset | Events | Covered | Hit | Recall | 95% CI | hit/ev | FA | obj-yr | FA/yr | dup |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| train | LEO | all | 192 | 156 → 174 | 117 | 0.750 → 0.672 | 0.68-0.81 → 0.60-0.74 | 0.609 | 8 | 12.04 → 13.18 | 0.66 → 0.61 | 53 |
| train | LEO | >=50 m | 26 | 16 → 18 | 14 | 0.875 → 0.778 | 0.64-0.96 → 0.55-0.91 | 0.538 | | | | |
| train | GEO | EW | 43 | 39 | 37 | 0.949 | 0.83-0.99 | 0.861 | 1 | 2.39 | 0.42 | 14 |
| train | GEO | NS | 18 | 17 | 7 → 5 | 0.412 → 0.294 | 0.22-0.64 → 0.13-0.53 | 0.389 → 0.278 | | | | |
| dev | LEO | all | 196 | 176 → 185 | 158 | 0.898 → 0.854 | 0.84-0.93 → 0.80-0.90 | 0.806 | 15 | 9.93 → 10.55 | 1.51 → 1.42 | 91 |
| dev | LEO | >=50 m | 47 | 38 → 40 | 32 | 0.842 → 0.800 | 0.70-0.93 → 0.65-0.90 | 0.681 | | | | |
| dev | GEO | EW | 37 | 34 | 33 | 0.971 | 0.85-0.99 | 0.892 | 1 | 1.96 | 0.51 | 12 |
| dev | GEO | NS | 16 | 14 | 3 → 1 | 0.214 → 0.071 | 0.08-0.48 → 0.01-0.31 | 0.188 → 0.062 | | | | |

This tune shows item 1 at work. Its LEO k=6 used to leave 18 train and 9 dev events out of
`covered`; they are now misses, so LEO recall falls with no change in hits. Its LEO exposure
grows to the reference's, so FA/yr falls slightly with the same false alarms. GEO NS loses two
hits on each split to one-to-one matching (item 7, the only rule that can move GEO at k=4). The
`dup` column shows what this tune's LEO recall costs: 53 train and 91 dev duplicates, against 0
and 1 at FROZEN, so it often reports more than one detection at a burn. IGSO, ISS and Fengyun
come out the same as under FROZEN. The full output is in `harness/evals/results/{train,dev}-generalise-tune.json`.

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
  burns only, which is 0.41 of QZS-4's no-burn time on train and 0.23 on dev (`scored`). Recovering IGSO needs `max_gap_days` (a `score_gaps` argument, today a constant and
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
  `generalise` tune reaches 0.78-0.80 on train and dev on the k=4 denominator (0.84-0.88 on its
  own k=6 one before 896ae19), at the cost of 1.4 FA/obj-yr and 91 duplicates on dev.
- **Burns without `delta_a_est_m`:** none in the IDS logs. All Fengyun lines lack it; they count
  in the all-events recall and in the EW/NS subsets, and never in the LEO >=50 m subset.
  Merged burn/counter-burn pairs use their net estimate. Seven SWOT pairs in 2021-2025 (four
  train, three dev) have every row at 50 m or more but a net under 50 m, so they are outside the
  >=50 m subset.

## DECISION FOR GABRIEL

No label looked wrong in this lane: every GEO false alarm checked lies near, but outside, a
logged burn's match zone, or has no logged burn nearby and no evidence against the log. Four
measurement-rule questions came up. None was changed:

1. **Late tolerance.** Should `LATE_DAYS` (2 days) widen for GEO? The QZS-3 steps above appear
   2.4 and 3.1 days after logged burns. Widening it would turn one train miss and FA into a
   match, and drop one dev FA.
2. **Coverage denominator.** Settled at 896ae19: `covered` comes from a frozen k=4 reference
   whatever k a setting uses, and a covered event no detection matches is a miss.
3. **ISS false alarms** are reported but not checked against the <= 1/obj-yr target, because the
   NASA and Roscosmos lists are lower bounds (FINDINGS.md explains several "false alarms" as
   unlisted Russian burns). Confirm, or say if they should count.
4. **ISS guardrail on train** starts below 0.95 (0.938). Should it be judged on dev only, or
   "no worse than 45/48 on train and 35/35 on dev"?

5. **GEO NS hits that rest on a-channel steps near an EW burn.** Settled at 84555a6 (Step A below):
   an NS hit needs an inclination-channel detection. The question as first asked: QZS-3's NS burns usually come
   less than a day before an EW burn, and QZSS events have no expected sign, so time is the only
   thing that ties a step to one of the two burns. One-to-one matching (896ae19) stopped a second
   detection of one EW step from being credited with the NS burn too; that removed QZS-3-120 and
   -140 from train NS (6 → 4). Three of the four remaining train NS hits at FROZEN (QZS-3-110+111,
   127, 146) are a-channel steps of 2.7-3.1 km whose peak gap starts within 7 hours of the NS
   burn. The EW burn comes about a day after the NS one, and a second step of the same size,
   3-14 hours after it, takes it. A 3 km
   change in a is EW-sized. I did not check whether these NS burns carry an east-west part or the
   first steps are element-set artefacts. Should a
   GEO NS hit require something an NS burn produces, such as an inclination-channel detection
   (round 2) or a step size an NS burn can explain, rather than any detection nearest in time?
   On the corrected eval, round 1 (#13) still loses train NS and also one train ISS burn (below),
   so it stays reverted either way.
6. **Sub-kilometre a-steps at NS burns.** Under Step A, five of the nine NS events matched by a
   semi-major-axis detection have steps of 350-810 m (dev QZS-3-180+181, 187, 211+212, 225+226;
   train QZS-3-143), not the ~3 km of an EW burn. If an NS burn's own change in a can be that size,
   a size-aware rule would credit them. Not changed: the rule stands as decided.

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
- the `covered` denominator does not shrink for the regime being improved. Since 896ae19 it comes
  from the k=4 reference, so a setting can no longer shrink it; `hit/ev` is still reported beside
  it. `dup` is reported beside FA so that a gain bought with extra detections at burns shows.

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
in `harness/evals/detector.py`; matching and counting are unchanged. (Reviewed with the eval
correction at 896ae19: wiring only, kept.)

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

**Result at bc4f8bb (`settings/inc-channel.json` against FROZEN).** KEPT.

| Split | Group | Subset | FROZEN hit/cov (hit/ev) | Round 2 hit/cov (hit/ev) |
|---|---|---|---|---|
| dev | GEO | NS | 5/14 (5/16) | **6/14 (6/16)**, 0.43 [0.21, 0.67] |
| dev | GEO | EW | 33/34 (33/37) | 33/34 (33/37) |
| dev | GEO | EW+NS | 3/3 (3/4) | 3/3 (3/4) |
| dev | GEO | all | 41/51 (41/57) | 42/51 (42/57) |
| dev | GEO | FA/obj-yr | 7 / 1.96 = 3.58 | 7 / 1.96 = 3.58 |
| dev | LEO | >=50 m; FA/yr | 11/40 (11/47); 0.00 | unchanged |
| dev | ISS | all; FA | 35/35; 4 | unchanged |
| train | GEO | NS | 6/17 (6/18) | **9/17 (9/18)**, 0.53 [0.31, 0.74] |
| train | GEO | EW | 36/39 (36/43) | 36/39 (36/43) |
| train | GEO | EW+NS | 6/6 (6/7) | 6/6 (6/7) |
| train | GEO | all | 48/62 (48/68) | 51/62 (51/68) |
| train | GEO | FA/obj-yr | 4 / 2.39 = 1.67 | 4 / 2.39 = 1.67 |
| train | LEO | >=50 m; FA/yr | 4/18 (4/26); 0.15 | unchanged |
| train | ISS | all; FA | 45/48; 3 | unchanged |
| train | Fengyun | all; FA | 3/3; 0 | unchanged |

Covered counts are unchanged in every regime. The gain rests on few events: three on train
(QZS-3-103, 159, 162+163) and one on dev (QZS-3-235+236); the dev interval still spans 0.21-0.67.
The inclination channel kept five detections after the merge: the four QZS-3 ones are exactly
the recovered burns (train detections 64 -> 67, matched 48 -> 51; dev 49 -> 50, matched 36 -> 37),
and one QZS-6 detection on 2025-03-17 (+0.034 deg) lies before QZS-6's log coverage starts on
2025-08-02, so it is not scored. The NS
burns less than a day before an EW burn are still found only through duplicate a detections
(round 1), as the hypothesis expected.

### Rounds 1 and 2 re-scored on the corrected eval (896ae19)

Round 2 is `settings/inc-channel.json` at 896ae19. Round 1 is 3191d57's `pick` ported into a
scratch copy of 896ae19 (outside the repo), with its peak fields set to the peak gap, which is the
gap its step and z come from. Both are against the new FROZEN baseline. "Journalled" is the
number in the round's own write-up above, on the old eval.

| Split | Group | Metric | FROZEN | Round 1 | R1 journalled | Round 2 | R2 journalled |
|---|---|---|---|---|---|---|---|
| train | GEO | EW hit/cov | 36/39 | **35/39** | 36/39 | 36/39 | 36/39 |
| train | GEO | NS hit/cov | 4/17 | **2/17** | 1/17 | **7/17**, 0.41 [0.22, 0.64] | 9/17 |
| train | GEO | all hit/cov | 46/62 | 43/62 | 43/62 | 49/62 | 51/62 |
| train | GEO | FA (FA/yr); dup | 4 (1.67); 14 | 4 (1.67); 2 | 4 (1.67) | 4 (1.67); 14 | 4 (1.67) |
| train | ISS | hit/cov; FA | 45/48; 3 | **44/48**; 3 | 45/48; 2 | 45/48; 3 | 45/48; 3 |
| train | LEO, Fengyun | all rows | as baseline | same; Fengyun dup 1 → 0 | same | same | same |
| dev | GEO | EW hit/cov | 33/34 | 33/34 | 33/34 | 33/34 | 33/34 |
| dev | GEO | NS hit/cov | 5/14 | **4/14** | 5/14 | **6/14**, 0.43 [0.21, 0.67] | 6/14 |
| dev | GEO | all hit/cov | 41/51 | 40/51 | 41/51 | 42/51 | 42/51 |
| dev | GEO | FA (FA/yr); dup | 7 (3.58); 11 | 5 (2.56); 1 | 5 (2.56) | 7 (3.58); 11 | 7 (3.58) |
| dev | ISS | hit/cov; FA (FA/yr); dup | 35/35; 4 (2.33); 3 | 35/35; 3 (1.75); 0 | 35/35; 3 (1.75) | as FROZEN | as FROZEN |
| dev | LEO | >=50 m; FA; dup | 11/40; 0; 1 | same; 0; 0 | same | same | same |

`covered` is the same in every column.

**Round 1 stays reverted.** On the corrected eval it loses train GEO NS (4 → 2) and EW (36 → 35),
train ISS (45 → 44) and dev GEO NS (5 → 4), while it still removes the duplicates it was built
for (train GEO 14 → 2, dev GEO 11 → 1, dev ISS 3 → 0) and two dev GEO false alarms and one dev ISS
false alarm. Its numbers differ from the journalled ones in three places, each explained by a
corrected rule:

- **Train ISS 45 → 44, FA 2 → 3.** Round 1 absorbed the gap at the 2023-03-14 11:54 debris
  avoidance into a stronger peak (z 90) that starts 2023-03-15 06:14. Its interval covers the
  burn, but its peak gap starts 18 hours after it, past the ISS's 0.5-day late tolerance. The old
  eval matched by interval; the new one, by peak gap (item 3). So it is now a miss plus a false
  alarm, which is the case item 3's test pins. The journalled trade of 2023-11-10 for 2023-11-09
  is gone: each detection now goes to its nearest event, as at FROZEN.
- **Train NS 1 → 2, EW 36 → 35** (GEO all 43 either way). Round 1 reports the QZS-3-127/128 step
  once, and its peak gap is nearer NS 127 than EW 128, so one-to-one matching (item 7) gives it to
  127. The old rule gave it to 128.
- **Dev NS 5 → 4.** The journalled gain, QZS-3-194+195, is gone. Round 1's +420 m detection there
  (peak gap 2024-06-30 03:48 to 12:56) has its centre 17 hours after that NS burn and 8 hours
  before EW QZS-3-196, so item 7 gives it to 196. The -3,795 m detection of the EW step then
  becomes a duplicate. The loss of QZS-3-221+222 stands.

**Round 2 stays kept.** On the corrected eval it still gains three train NS burns (4 → 7:
QZS-3-103, 159, 162+163) and one dev NS burn (5 → 6: QZS-3-235+236). It adds no false alarm or
duplicate, and `covered` is unchanged. Its journalled train figure (6 → 9) falls to 4 → 7 for the
same reason as FROZEN's: QZS-3-120 and -140 no longer count. The dev figure is unchanged.

### ISS holdout guardrail (`orbit_watch.holdout`, NASA + Roscosmos lists; already spent, not a target)

| Code | Holdout 2024-25 precision | recall | Space-Track 2023 | Archive 2023 |
|---|---|---|---|---|
| committed findings (FROZEN pick) | 35/42 | 35/35 | 20/22, recall 20/21 | 20/21, recall 20/21 |
| round 1, 3191d57 (reverted) | **35/38** | 35/35 | 20/21, recall 20/21 | 20/21, recall 20/21 |
| round 2, 2347c87 (head) | 35/42 | 35/35 | identical to committed | identical |

Round 1 removed four unmatched holdout detections, which is #13's prediction ("as high as 35/38"),
and in 2023 it traded the 2023-11-10 debris avoidance for the 2023-11-09 reboost. Round 2 leaves
every ISS number unchanged: the head report equals the committed one except for the input paths.
These outputs went to a scratch folder; `findings/` is unchanged.

## Step A: a north-south hit needs the inclination channel (eval rule, 84555a6)

Decision 5, as decided: a GEO `NS` event is a hit only when the detection matched to it carries the
inclination channel. A semi-major-axis detection matched to an NS event still counts as matched for
one-to-one purposes, so it is neither a duplicate nor a false alarm and no other detection can take
the event, but the event is a miss in every subset, `all` included. The new `wrong_channel` field
(`wch` in the table) counts those events, and `_detail.wrong_channel` lists them. `Detection.channel`
already existed (`pick` sets it from `GapScores.channel` since round 2), so the detector did not
change. `counts_as_hit` reads `"i" in channel.split("+")`, so round 3's merged detections (`a+i`)
count. `EW+NS` events keep the old rule: they count toward neither target, and a semi-major-axis
step there is the east-west part of the merged burn. That is one constant (`INC_ONLY_SUBSETS`) if it
should change. Test: `test_a_north_south_hit_needs_the_inclination_channel`, which fails on the old
eval.

| Split | Setting | GEO NS hit/cov | GEO all hit/cov | wch | EW, EW+NS, FA, dup, other regimes |
|---|---|---|---|---|---|
| train | FROZEN | 4/17 → **0/17**, 0.00 [0.00, 0.18] | 46/62 → 42/62 | 4 | unchanged (EW 36/39, EW+NS 6/6, FA 4, dup 14) |
| train | inc-channel | 7/17 → **3/17**, 0.18 [0.06, 0.41] | 49/62 → 45/62 | 4 | unchanged |
| dev | FROZEN | 5/14 → **0/14**, 0.00 [0.00, 0.22] | 41/51 → 36/51 | 5 | unchanged (EW 33/34, EW+NS 3/3, FA 7, dup 11) |
| dev | inc-channel | 6/14 → **1/14**, 0.07 [0.01, 0.31] | 42/51 → 37/51 | 5 | unchanged |

The inclination channel's hits are exactly round 2's recovered burns: train QZS-3-103, 159 and
162+163, dev QZS-3-235+236. The a-matched NS events (`wch`), the same under both settings:

- train QZS-3-110+111 (-2,770 m), 127 (-3,136 m), 146 (-2,706 m): EW-sized, as decision 5 said.
  QZS-3-143 (+507 m, peak gap 29 min after the burn) is the fourth.
- dev QZS-3-221+222 (-2,980 m), and four smaller steps: 180+181 (-354 m), 187 (+361 m, peak 4 h
  before the burn), 211+212 (-811 m), 225+226 (-781 m).

Not every a-matched NS event is EW-sized: five of the nine are steps of 350-810 m. Whether those
are the NS burns' own change in a (a north-south burn is not purely out of plane) or the following EW
burn was not checked; the rule counts them as misses either way (DECISION FOR GABRIEL 6).

Every baseline below is on this eval. Result JSONs: `harness/evals/results/{train,dev}-{frozen,inc-channel}.json`.

### Round 3: merge channels by gap identity, not by time

**Hypothesis.** `merge_channels` drops an inclination detection whose centre lies within `nms_days`
of any semi-major-axis detection's centre, so an NS burn next to an EW burn (QZS-3 often fires NS
then EW within a day) can never be found: the EW step suppresses it. Under Step A those NS burns
are misses. Keeping an inclination detection unless its peak gap is the same gap as (or overlaps)
a semi-major-axis detection's peak gap, and in that case keeping one detection that carries both
channels (`a+i`), should turn them into NS hits.

**Risk, seen before the change** (a scratch listing of `pick`'s inclination detections on the
train objects, 2021-2025, against the nearest semi-major-axis peak). Of the 45 inclination
detections, 18 share their peak gap with an a-detection (these become `a+i`) and 21 more are
dropped today at 1-7 gaps from one. Several of those 21 sit in the GEO false-alarm clusters
(QZS-3 2021-06-19/25, 2021-12-14/20, 2025-12-21; QZS-6 2025-09-03/10): pairs of opposite-sign
inclination steps of about 0.03 deg a few days apart, next to the ±500-700 m a-steps already
counted as false alarms. Kept, they are new false alarms, which would fail the keep rule.

**Target.** GEO NS hit/cov up on dev and train; GEO FA/obj-yr and `dup` not up.

**Result at e6f2901 (`settings/inc-channel.json`, against Step A's inc-channel baseline).** REVERTED:
GEO false alarms rose on both splits.

| Split | Group | Metric | Baseline (bda5807) | Round 3 |
|---|---|---|---|---|
| train | GEO | NS hit/cov | 3/17, 0.18 [0.06, 0.41] | **7/17**, 0.41 [0.22, 0.64] |
| train | GEO | EW; EW+NS; all | 36/39; 6/6; 45/62 | 36/39; 6/6; 49/62 |
| train | GEO | FA (FA/yr); dup; wch | 4 (1.67); 14; 4 | **7 (2.93)**; 18; 1 |
| train | LEO, IGSO, ISS, Fengyun | every row | as baseline | unchanged (ISS 45/48, FA 3) |
| dev | GEO | NS hit/cov | 1/14, 0.07 [0.01, 0.31] | **3/14**, 0.21 [0.08, 0.48] |
| dev | GEO | EW; EW+NS; all | 33/34; 3/3; 37/51 | 33/34; 3/3; 39/51 |
| dev | GEO | FA (FA/yr); dup; wch | 7 (3.58); 11; 5 | **10 (5.11)**; 15; 5 |
| dev | LEO, IGSO, ISS | every row | as baseline | unchanged (ISS 35/35, FA 4, dup 3) |

`covered` is unchanged everywhere. The NS gains come from two mechanisms:

- **Folding on a shared peak gap** (`a+i`): train QZS-3-110+111, 127 and 146, which Step A had
  made misses (the a-step and the inclination step peak on the same gap). Dev gains nothing this
  way: its two shared-gap detections near NS burns (2024-11-09, 2025-09-05) are nearer the EW
  burn that follows.
- **Keeping an inclination detection on another gap within a day of an a-detection:** train
  QZS-3-140, dev QZS-3-184 and 194+195.

The six new false alarms are all of the second kind and are the ones listed under Risk: train
QZS-3 2021-06-19, 06-25, 12-14 and dev QZS-3 2025-12-21, QZS-6 2025-09-03, 09-10. Each is an
inclination step of 0.02-0.04 deg that, with an opposite-sign step 5-8 days away, brackets the
±500-780 m a-steps already counted as false alarms. The four new duplicates per split are kept
inclination detections at burns whose event a nearer detection holds (train 2021-10-16, 12-20,
2022-06-28 and the EW step 2022-04-03 they displaced), or EW a-steps an inclination detection
displaced (dev 2024-04-03, 2025-10-18, QZS-6 2025-11-19).

The fold alone (shared gap, old time rule otherwise) would gain train 3 and dev 0, so it fails the
keep rule's "gain on dev, or on both" as well; not tried as a round. What would let the second
mechanism through is a way to reject the opposite-sign excursions (a run of offset element sets
that returns within about a week, in both a and i). That is a new detector rule, outside this
lane; it is proposed in the return, not built.

### Round 4: #13 peak-radius NMS again, on top of Step A

**Hypothesis.** Round 1's change (3191d57) removed the duplicates it was built for (train GEO dup
14 → 2, dev 11 → 1, dev ISS 3 → 0) and two dev GEO false alarms, and was reverted for its NS loss,
which came from semi-major-axis duplicates credited to NS burns. Under Step A those detections no
longer count as NS hits, so re-applying it should cut GEO false alarms and duplicates and leave NS
recall alone. Round 3 was reverted, so this goes on top of Step A only. Its known cost is the ISS:
on the fixed eval it absorbed the 2023-03-14 debris avoidance into the peak 18 h later (train ISS
45 → 44/48). If that remains, the round fails the ISS guardrail.

**Change.** 3191d57's `pick` and its two tests, re-applied by hand (the code has moved since), with
the mock ISS slice restored. `peak_start`/`peak_end` are the peak gap, and the interval is the union
of the absorbed gaps. `merge_channels` now measures centres from the peak gap, not the interval, so
wider intervals do not change which inclination detections it keeps. While peak = interval this is
a no-op; a test pins it.
