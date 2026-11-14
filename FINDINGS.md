# Findings

Nothing here is claimed as a discovery. These are leads from the calibration run, listed with the evidence so they can be checked.

## ISS steps with no announced manoeuvre (2021-01 to 2023-12)

Source: the calibration run at commit 508838a on Kaggle (`ow-calibrate`), on 5,076 ISS TLEs from the public OndroNR/tle-archive (sha256 `e102dc92…7c51`), with the frozen detector settings `k = 4`, `|z| >= 12`, `|step| >= 200 m`. The plot is `findings/iss_sma.png`; these are the orange markers.

The detector found these steps in semi-major axis, and none of them matches an event in `groundtruth/iss_manoeuvres.csv`. That list comes from NASA pages only and has no Roscosmos announcements, so an unmatched step may be a real burn that NASA did not write up, or a detector error.

| Interval (UTC) | Step in a | z | What the plot shows | Related public text |
|---|---|---|---|---|
| 2021-09-12 00:22 to 01:57 | +966 m | 52.5 | clear step up | none found |
| 2021-12-24 04:27 to 10:55 | −1,755 m | −24.5 | clear step down | The ISS Daily Summary Report of 2021-12-23 lists "Transition to Reboost Mode" among ground activities; no burn is announced (docs research lane, not re-checked here) |
| 2022-03-12 03:37 to 05:13 | +804 m | 47.6 | clear step up | The report of 2022-03-11 lists "Transition to Reboost Mode"; no burn is announced (same caveat) |
| 2023-01-18 10:12 to 15:44 | +1,632 m | 492.1 | clear step up | none found |
| 2023-03-14 08:46 to 03-15 06:14 | +509 m | 72.4 | step up | NASA, 2023-03-14: "At 7:54 a.m. the ISS Progress 83 thrusters performed a 2-minute, 35-second burn to provide extra distance from a fragment of Russian Cosmos 1408 satellite debris." Kept out of the ground truth because the page gives no time zone or burn date beyond the post date. |
| 2023-04-30 05:31 to 07:19 | +1,978 m | 124.8 | clear step up | none found |
| 2023-05-04 16:43 to 05-05 04:38 | +313 m | 12.4 | no clear step; likely a detector false positive | none |
| 2023-12-22 19:10 to 12-23 15:09 | +3,262 m | 254.5 | clear step up | none found |

The next check for each lead is a Roscosmos or TASS announcement on that date, or a second element source (Space-Track's gp_history, once credentials exist) showing the same step.

## Not yet done

The planned first hunt over the Luch / Olymp-K objects at GEO, or a few Starlink shells, has not run. The Luch/Olymp TLE histories (NORAD 37951, 38977, 39727, 40258, 55841, 2021 to 2023) are already extracted by the archive job, but the detector's thresholds are tuned for the ISS in low orbit and would need a GEO noise model first.
