# Findings

Nothing here is claimed as a discovery. These are leads from the calibration run, listed with the evidence so they can be checked.

## ISS steps with no announced manoeuvre (2021-01 to 2023-12)

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

## ISS steps with no announced manoeuvre (2024-01 to 2025-12, clean holdout)

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

## Not yet done

- The unmatched QZS-3 and QZS-6 detections (README, "Beyond the ISS") have not been checked against momentum-unloading windows or any other source.
