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

The next check for each lead is a Roscosmos or TASS announcement on that date. Space-Track's gp_history is now available as a second element source; the source check (README) gives the same frozen-setting counts for 2023 and one fewer matched event for 2021-2022, but no lead-by-lead comparison has been written up yet.

## ISS steps with no announced manoeuvre (2024-01 to 2025-12, clean holdout)

Source: `python -m orbit_watch.holdout` on Space-Track gp_history for the ISS (9,080 element sets after merging rows within 1 s), frozen setting `k = 4`, `|z| >= 12`, `|step| >= 200 m`. Full table: `findings/holdout_2024_2025/detections.csv`; plot: `findings/holdout_2024_2025/iss_sma_2024_2025.png`.

The detector matched all 27 covered NASA-listed events in this period and made 15 detections that match none. The NASA list has no Roscosmos announcements, so these are leads, not findings. Most are steps up of 1.7 to 4.9 km with `z` in the hundreds, the size of a typical reboost.

| Interval (UTC) | Step in a | z |
|---|---|---|
| 2024-06-14 11:46 to 19:30 | +3,465 m | 188.5 |
| 2024-09-09 01:02 to 05:39 | −257 m | −27.4 |
| 2024-09-29 04:02 to 09:41 | +231 m | 60.4 |
| 2024-10-04 12:26 to 20:09 | +2,826 m | 74.0 |
| 2024-11-13 22:09 to 11-14 07:16 | +4,913 m | 1,050.1 |
| 2024-12-21 20:20 to 12-22 11:31 | +2,204 m | 295.3 |
| 2025-01-11 18:40 to 01-12 09:54 | +3,137 m | 626.0 |
| 2025-02-01 03:54 to 17:34 | +3,321 m | 596.6 |
| 2025-04-02 09:22 to 19:42 | +3,621 m | 717.6 |
| 2025-04-28 16:46 to 04-29 04:34 | +462 m | 12.0 (at the threshold; the likeliest false positive) |
| 2025-06-18 19:26 to 20:01 | +521 m | 345.7 |
| 2025-08-13 19:51 to 08-14 19:04 | +1,730 m | 1,022.4 |
| 2025-09-04 02:26 to 21:00 | +945 m | 220.2 |
| 2025-10-15 07:11 to 19:34 | +2,394 m | 652.7 |
| 2025-11-20 05:19 to 13:04 | +2,730 m | 1,042.2 |

No outside source has been checked for these dates yet.

## Luch / Olymp-K objects at GEO (2021-01 to 2023-12): uncalibrated leads

Source: `python -m orbit_watch.geo_hunt` at commit 02dfab5 on Kaggle, one kernel per object (`ow-geo-37951`, `ow-geo-38977`, `ow-geo-39727`, `ow-geo-hunt-c` for 40258, `ow-geo-55841`), on TLEs from the public OndroNR/tle-archive. The inputs as unpacked on Kaggle (sha256):

| NORAD | Archive names | TLEs used | sha256 |
|---|---|---|---|
| 37951 | LUCH 5A | 2,275 | `1defac97…5824` |
| 38977 | LUCH 5B | 1,798 | `7bad758c…d4bc` |
| 39727 | LUCH 5V | 2,499 | `dd00f4d1…5cb1` |
| 40258 | LUCH (OLYMP-K 1) | 2,217 | `cdb3ef4e…1d71` |
| 55841 | LUCH-5X (OLYMP-K 2), from 2023-03-13 | 513 | `d4f1cf06…21ab` |

**These are not calibrated detections.** There is no GEO ground truth in this repo. The detector is the ISS one (`orbit_watch/detect.py`, `k = 4`), and each object's thresholds come from its own scatter: `|z| >= 8` and `|step| >= 10 x` the median per-gap scatter of its semi-major axis, which gives step thresholds of 31 m for 37951, 38 m for 38977, 24 m for 39727, 1,597 m for 40258 and 815 m for 55841. Gaps of more than 3 days are not scored. Many flagged steps on the station-keeping objects are probably not burns (see each object). The longitude is the sub-satellite longitude at each TLE epoch (SGP4 to TEME, rotated by GMST; `orbit_watch/geo.py`). It carries a daily wobble of up to about ±0.2° from inclination and eccentricity, because the epochs fall at different times of day, so the drift rates in the table (a least-squares fit over 4 epochs) mean something only during a relocation, where they reach 1 to 4°/day.

The full step table, 283 rows, is `findings/geo_steps.csv` (columns: object, interval, step in a, z, longitude before and after, drift rate before and after). The plots are `findings/geo_<norad>.png`: longitude on top, mean semi-major axis below, a vertical line at every flagged step.

### 40258, Luch (Olymp-K 1): six relocations, then stationary at about 18.1°W

`findings/geo_40258.png`. The longitude plot shows a series of moves, each with semi-major axis away from its usual 42,166 km while the longitude drifts:

| Interval (from the table and plot) | Longitude | What the plot and table show |
|---|---|---|
| 2021-02-09 | 3.0°W → about 8°W | step of +11.6 km in a (z 163), drift after −0.15°/day; a back to 42,166 km within days |
| 2021-04 to 2021-05-19 | about 8°W → 45.2°E | a lowered to about 42,045 km; drift +1.5°/day on 2021-04-20; a back up by late May |
| 2021-07-13 to 07-25 | 45.9°E → 56.9°E | drift up to 1.6°/day; step of +11.9 km on 2021-07-24/25 with drift after 0.006°/day |
| 2021-09-27 to 10-04 | 56.9°E → 59.9°E | step of −47.9 km (z −155) starts a 0.65°/day drift; drift after 0.008°/day on 2021-10-04 |
| 2022-01-17 to 01-24 | 59.95°E → 61.9°E | step of −11.4 km starts a 0.19°/day drift, later 0.50°/day |
| 2022-07-14 to 08-29 | 61.9°E → 18.1°W | a raised to about 42,333 km; drift −0.37°/day on 2022-07-14, up to −2.16°/day; stops by 2022-08-29 |

From 2022-09 to the end of 2023 the longitude stays within 18.03°W to 18.12°W. The 1,600-to-3,700 m steps flagged between moves are near the threshold and are not visible at the scale of the plot; they are candidates for station-keeping only.

### 55841, Luch-5X (Olymp-K 2): arrival drift, then three relocations in 2023

`findings/geo_55841.png`. The record starts on 2023-03-13 with the longitude at about 55°E, a at about 41,922 km and the longitude increasing. It peaks at 78.9°E in late March (a gap of TLEs falls on 2023-03-24 to 03-27), then decreases.

| Interval | Longitude | What the plot and table show |
|---|---|---|
| 2023-04-01 to 04-09 (end of the arrival drift) | 62.2°E → 58.0°E | three steps down in a (−7.2, −17.6, −19.7 km); drift −1.96°/day falls to 0.0007°/day |
| 2023-05-02 to 05-22 | 58.0°E → 8.9°E | a raised to about 42,512 km; drift up to −4.4°/day; step of −36.7 km on 2023-05-22 ends it |
| 2023-09-26 to 10-04 | 8.5°E → 3.3°E | step of +67.4 km, drift −1.0°/day; step of −17.3 km on 2023-10-03/04 ends it |
| 2023-12-03 to 12-06 | 3.16°E → 2.6°E | step of +17.0 km starts a −0.34°/day drift; step of −16.6 km ends it |

Between moves the longitude holds near 58.0°E, 8.9°E, 3.2°E and 2.6°E. July and August 2023 have sparse TLEs and three gaps of 3 to 4 days.

The size cuts used below to count likely station-keeping steps (500 m for 37951, 150 m for 38977, 1 km for 39727) were chosen after looking at the plots. They are not calibrated.

### 37951, Luch 5A: station-keeping near 167.0°E, no relocation

`findings/geo_37951.png`. The longitude stays between 166.64°E and 167.34°E and swings slowly by about ±0.25° with a period of two to three months. Semi-major axis shows a sawtooth: a jumps up by about 2 km and then falls over the next two to three months. 15 flagged steps are rises of 500 m or more (median +2,119 m), with a median spacing of 76 days (2 to 147). A further jump visible in late June 2023 falls in the data gap of 2023-06-28 to 07-01 and was not scored. The other 70 flagged steps lie on the falling parts, which the plot shows are not straight; with a 31 m threshold the linear detrend of the detector flags them, and they may be detector artefacts rather than burns.

### 38977, Luch 5B: station-keeping near 16.4°W, no relocation

`findings/geo_38977.png`. The longitude stays between 16.72°W and 15.94°W. Semi-major axis shows a sawtooth the other way round: a rises by about 0.5 to 0.8 km over a few weeks and then drops by a few hundred metres. 50 of the 89 flagged steps are drops of 150 m or more (median −359 m), with a median spacing of 21 days (2 to 58). The 24 flagged rises do not match visible jumps in the plot and are likely detector noise at a 38 m threshold.

### 39727, Luch 5V: regular station-keeping near 94.7°E, no relocation

`findings/geo_39727.png`. The longitude stays between 94.54°E and 94.84°E. Semi-major axis shows the most regular pattern of the five: a rises by about 2.5 km over three to four weeks, then drops back. 43 of the 46 flagged steps are drops of 1 km or more (median −2,570 m), with a median spacing of 25 days (2 to 62); those drops line up with most resets visible in the plot (two resets, around 2021-03 and 2021-09, carry step-up lines instead).

### What would check these leads

A second element source (Space-Track gp_history) showing the same steps, and operator or agency notices for the relocation dates of 40258 and 55841. No outside source was consulted for this section, so it says nothing about why any object moved or what it was near.

## Not yet done

The Starlink shell hunt has not run.
