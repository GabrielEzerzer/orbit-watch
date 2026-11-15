# Ground truth

`iss_manoeuvres.csv` lists publicly announced ISS manoeuvres (reboosts, debris-avoidance burns and other orbit-changing burns) from 2021-01 to 2025-12. Each row carries the NASA page it came from (`source_url`) and a verbatim quote from that page (`quote`) supporting every field in the row. Every quote was checked word for word against the fetched page. Nothing in this file is estimated or inferred.

How to read it:
- `time_utc` is filled only when the page gives a clock time with a time zone (converted with CDT = UTC-5, CST = UTC-6, EDT = UTC-4, EST = UTC-5). Where only "CT" is given, CST or CDT follows the US daylight-saving calendar.
- When `time_utc` is empty, `date_utc` is the US-local calendar date the page states or implies, so treat it as plus or minus one day.
- `quote` joins fragments from one page with ` … `; ` || ` separates quotes from different pages, whose URLs appear in `source_url` separated by ` ; ` in the same order.
- Two rows typed `other (unplanned attitude/thruster event)` (Nauka 2021-07-29, Soyuz MS-18 2021-10-15) are attitude upsets. The pages do not describe an orbit change, so they are not calibration targets.
- The list is a lower bound. Roscosmos and TASS announcements were not searched, and the ISS Daily Summary Reports only appear on weekdays.

Sources: NASA's Space Station blog (nasa.gov/blogs/spacestation) and the ISS Daily Summary Reports (nasa.gov/blogs/stationreport), found through the nasa.gov WordPress API and a full-text scan of the 2021-2023 posts.

## Roscosmos-reported ISS manoeuvres (`iss_roscosmos_manoeuvres.csv`)

`iss_roscosmos_manoeuvres.csv` lists 14 ISS orbit corrections from 2021 to 2025 that Roscosmos reported as executed and that are not in `iss_manoeuvres.csv`: one deboost (2021-12-24), one debris avoidance (2023-03-14) and 12 reboosts. Every row has a clock time and a verbatim quote, in Russian with an English gloss in brackets. The file has the same columns as `iss_manoeuvres.csv` plus `source_time_zone`, and the scoring tools take both files together (`--truth groundtruth/iss_manoeuvres.csv groundtruth/iss_roscosmos_manoeuvres.csv`). They refuse an event that appears in both, and none does: the closest pair across the two files is five days apart.

How it was built:
- The list was compiled without looking at any detector output or detection dates. Rows were chosen only by reading the sources and comparing them with `iss_manoeuvres.csv`.
- The Roscosmos Telegram channel (`t.me/roscosmos_gk`) was read post by post through its public web archive, every post from December 2020 to the end of 2025. RIA Novosti articles found through the site's search, quarter by quarter, were used to cross-check posts and to add details. Where a row has two sources, `source_url` separates them with ` ; ` and `quote` separates their quotes with ` || `, as in `iss_manoeuvres.csv`.
- Every quote fragment was checked by script against the fetched page text. Two quotes were also checked by hand against the live Telegram posts and match.
- Source times are Moscow time (MSK = UTC+3; Russia has had no daylight-saving time since 2014), so `time_utc` is the MSK time minus 3 hours. A post that says "today" is dated by the post's own timestamp in MSK. The 2021-12-24 time comes from the RIA article, because the Telegram post gives none.
- `vehicle` uses Roscosmos names (Progress MS-NN), and NASA numbers the same ships differently (Progress 79 = 79P). Rows therefore match NASA rows and detections on date and time, not on vehicle.
- `type` is `deboost`, `debris_avoidance` or `reboost`. `deboost` must step down and the other two may step either way under calibrate.py's sign rule, the same as NASA's `debris avoidance`.

Coverage confidence, from checking the list against Roscosmos's own running counts of corrections:
- **High, November 2021 to August 2024.** The counts match the combined list from November 2021 to December 2023 and from February to August 2024. One total in mid-2022 is one higher than the list, most likely because Roscosmos counted a Cygnus test burn that is already in the NASA file; the Progress-only count for the same months matches exactly.
- **Medium elsewhere:** January to October 2021, September to December 2024, and 2025. No running count covers these months, so the list rests on Telegram and RIA alone.
- **Thinnest, September to December 2025.** Only one Russian burn was found (2025-11-19, already in the NASA file). A burn reported only by TASS or roscosmos.ru could not be ruled out, because neither site could be fetched.

The list is still a lower bound: TASS and roscosmos.ru were not readable, and Cygnus and Dragon burns reported outside NASA were not searched.

### Kept out of the CSV

**Events not executed, or not confirmed as executed**
- **2021-11-16, 20:40 MSK, Progress MS-18, 478 s (plan).** Announced on 2021-11-08 ([RIA](https://ria.ru/20211108/mks-1758100024.html): «Плановая коррекция орбиты МКС запланирована на 16 ноября»). It did not run: on 2021-11-29 Roscosmos wrote «Предыдущая коррекция высоты орбиты проводилась 10 ноября для уклонения от «космического мусора»» ([post 1845](https://t.me/roscosmos_gk/1845)), and the MS-18 count of nine excludes it.
- **2021-08-19, 07:04 MSK, Zvezda (plan).** Moved to the reserve date of 21 August at NASA's request ([RIA](https://ria.ru/20210819/orbita-1746304779.html)). The 08-21 burn is already in the NASA file.
- **2022-02-06 (plan).** Moved to 8 February ([post 2508](https://t.me/roscosmos_gk/2508)). The 02-08 burn is in the NASA file.

**Seen and judged not to belong**
- Nauka module free-flight burns, 2021-07-23 to 2021-07-28 (posts 1265, 1286, 1287). These were the module's own approach manoeuvres before docking, not ISS orbit changes.
- Progress and Soyuz phasing, deorbit and descent burns (for example posts 741, 1275, 2030, 4950). These are not ISS orbit changes.
- Weekly digest posts (15641, 15850, 17992) that only refer back to burns already listed.

**No row was dropped for doubt about whether it happened.** Every executed burn found is either a CSV row or matched to a NASA row below.

### Burns already in the NASA file, with the Roscosmos time

These matched a NASA row within ±1 day, so they are not in the CSV. Many NASA rows have no clock time, and the Roscosmos post gives one. Use the MSK→UTC conversion and date rule described above. Where the NASA row date is one day earlier, NASA dated a late US-evening burn by US local time.

| NASA row date | Roscosmos post | time in post (MSK) | burn time UTC |
|---|---|---|---|
| 2021-01-21 | [711](https://t.me/roscosmos_gk/711) | 19:14 | 2021-01-21 16:14 (date stated in post) |
| 2021-05-20 | [1038](https://t.me/roscosmos_gk/1038) | 20:01 | 2021-05-20 17:01 |
| 2021-08-21 | [1401](https://t.me/roscosmos_gk/1401) | 07:04 | 2021-08-21 04:04 |
| 2021-12-03 | [1890](https://t.me/roscosmos_gk/1890) | 10:58 | 2021-12-03 07:58 |
| 2022-01-12 | [2356](https://t.me/roscosmos_gk/2356) | 21:24 | 2022-01-12 18:24 |
| 2022-02-08 | [2521](https://t.me/roscosmos_gk/2521) | 10:56 | 2022-02-08 07:56 |
| 2022-04-23 | [4113](https://t.me/roscosmos_gk/4113) | 16:25 | 2022-04-23 13:25 |
| 2022-06-16 | [5284](https://t.me/roscosmos_gk/5284) | 22:03 | 2022-06-16 19:03 |
| 2022-08-10 | [6168](https://t.me/roscosmos_gk/6168) | 10:16 | 2022-08-10 07:16 |
| 2022-08-24 | [6354](https://t.me/roscosmos_gk/6354) | 05:20 | 2022-08-25 02:20 |
| 2022-09-15 | [6696](https://t.me/roscosmos_gk/6696) | 21:10 | 2022-09-15 18:10 |
| 2022-10-01 | [6938](https://t.me/roscosmos_gk/6938) | 14:05 | 2022-10-01 11:05 |
| 2022-10-17 | [7143](https://t.me/roscosmos_gk/7143) | 22:27 | 2022-10-17 19:27 |
| 2022-10-25 | [7302](https://t.me/roscosmos_gk/7302) | 03:25 | 2022-10-25 00:25 |
| 2022-11-30 | [7714](https://t.me/roscosmos_gk/7714) | 15:25 | 2022-11-30 12:25 |
| 2022-12-21 | [7949](https://t.me/roscosmos_gk/7949) | 16:42 | 2022-12-21 13:42 |
| 2023-02-03 | [8298](https://t.me/roscosmos_gk/8298) | 13:30 | 2023-02-03 10:30 |
| 2023-02-19 | [8508](https://t.me/roscosmos_gk/8508) | 07:20 | 2023-02-20 04:20 |
| 2023-03-06 | [8671](https://t.me/roscosmos_gk/8671) | 15:42 | 2023-03-06 12:42 |
| 2023-03-08 | [8695](https://t.me/roscosmos_gk/8695) | 22:47 | 2023-03-08 19:47 |
| 2023-05-18 | [9501](https://t.me/roscosmos_gk/9501) | 19:43 | 2023-05-18 16:43 |
| 2023-06-16 | [9790](https://t.me/roscosmos_gk/9790) | 09:27 | 2023-06-16 06:27 |
| 2023-07-04 | [10006](https://t.me/roscosmos_gk/10006) | 00:17 | 2023-07-04 21:17 |
| 2023-07-27 | [10237](https://t.me/roscosmos_gk/10237) | 15:02 | 2023-07-27 12:02 |
| 2023-08-05 | [10324](https://t.me/roscosmos_gk/10324) | 05:03 | 2023-08-06 02:03 |
| 2023-08-24 | [10604](https://t.me/roscosmos_gk/10604) | 18:00 | 2023-08-24 15:00 |
| 2023-09-08 | [10762](https://t.me/roscosmos_gk/10762) | 21:52 | 2023-09-08 18:52 |
| 2023-09-29 | [11019](https://t.me/roscosmos_gk/11019) | 15:01 | 2023-09-29 12:01 |
| 2023-10-18 | [11242](https://t.me/roscosmos_gk/11242) | 06:46 | 2023-10-19 03:46 |
| 2023-11-09 | [11468](https://t.me/roscosmos_gk/11468) | 00:11 (post omits "мск") | 2023-11-09 21:11 |
| 2023-11-10 | [11473](https://t.me/roscosmos_gk/11473) | 18:07 | 2023-11-10 15:07 |
| 2024-01-12 | [12057](https://t.me/roscosmos_gk/12057) | 19:30 | 2024-01-12 16:30 |
| 2024-01-27 | [12162](https://t.me/roscosmos_gk/12162) | 14:39 | 2024-01-27 11:39 |
| 2024-02-23 | [12464](https://t.me/roscosmos_gk/12464) | 03:21 | 2024-02-24 00:21 |
| 2024-03-14 | [12765](https://t.me/roscosmos_gk/12765) | 16:11 | 2024-03-14 13:11 |
| 2024-04-25 | [13416](https://t.me/roscosmos_gk/13416) | 05:35 | 2024-04-26 02:35 |
| 2024-06-15 | [13913](https://t.me/roscosmos_gk/13913) | 07:40 | 2024-06-15 04:40 |
| 2024-06-29 | [14037](https://t.me/roscosmos_gk/14037) | 01:39 | 2024-06-29 22:39 |
| 2024-07-31 | [14324](https://t.me/roscosmos_gk/14324) | 12:51 | 2024-07-31 09:51 |
| 2024-08-27 | [14692](https://t.me/roscosmos_gk/14692) | 04:46 | 2024-08-28 01:46 |
| 2024-09-05 | [14779](https://t.me/roscosmos_gk/14779) | 22:45 | 2024-09-05 19:45 |
| 2024-11-19 | [15688](https://t.me/roscosmos_gk/15688) | 23:09 | 2024-11-19 20:09 |
| 2024-11-25 | [15772](https://t.me/roscosmos_gk/15772) | 12:49 | 2024-11-25 09:49 |
| 2025-02-19 | [16625](https://t.me/roscosmos_gk/16625) | 04:30 | 2025-02-20 01:30 |
| 2025-03-17 | [16984](https://t.me/roscosmos_gk/16984) | 19:00 | 2025-03-17 16:00 |
| 2025-04-23 | [17341](https://t.me/roscosmos_gk/17341) | 03:08 | 2025-04-24 00:08 |
| 2025-04-30 | [17375](https://t.me/roscosmos_gk/17375) | 01:10 | 2025-04-30 22:10 |
| 2025-07-16 | [17807](https://t.me/roscosmos_gk/17807) | 17:45 | 2025-07-16 14:45 |
| 2025-11-19 | [18688](https://t.me/roscosmos_gk/18688) | 16:04 | 2025-11-19 13:04 |

Times above were checked by script: the time string occurs in the post, the burn is not later than the post, and the UTC date is within one day of the NASA row. NASA rows that already carry a time agree with these to the minute (for example 2021-12-03 07:58, 2022-10-25 00:25, 2024-11-19 20:09). Matched NASA rows not in the table (2021-03-12, 2021-04-02, 2021-06-24, 2021-10-12, 2022-02-25) have Roscosmos posts with no burn time. 2021-09-24 and 2021-11-10 have only pre-burn plan posts (17:38 and 23:15 MSK), so they are not listed as times.

## IDS, QZSS and Fengyun manoeuvre logs (`ids_manoeuvres.csv`, `qzss_manoeuvres.csv`, `fengyun_manoeuvres.csv`)

The three files are built by `python -m orbit_watch.manoeuvre_logs --ids-dir <dir> --qzss-dir <dir> --fengyun-dir <dir> --out groundtruth` from the published logs. The raw logs are not committed; each row names its source file, the file's revision date and its URL, so the CSVs can be rebuilt after downloading those files. The module docstring explains the parsing. Every object these files cover is assigned to `train` or `holdout` in `splits.json` (below).

- `ids_manoeuvres.csv`: CryoSat-2 (36508), Jason-3 (41240), SWOT (54754) and SPOT-5 (27421), and, added with `splits.json`, Sentinel-3A (41335), Sentinel-3B (43437), Sentinel-6A (46984), Sentinel-6B (66514), SARAL (39086), HY-2C (46469) and HY-2D (48621): every satellite in the directory with a logged burn in 2021-2025. They come from the International DORIS Service manoeuvre files at `ftp://ftp.ids-doris.org/pub/ids/satellites/` (`cs2man.txt`, `ja3man.txt`, `swoman.txt`, `sp5man.txt`, `s3aman.txt`, `s3bman.txt`, `s6aman.txt`, `s6bman.txt`, `srlman.txt`, `h2cman.txt`, `h2dman.txt`; format in `man.readme`; the revision date is the file's date in the directory listing). The other files there have no 2021-2025 rows: Sentinel-3C (`s3cman.txt`) starts in 2026, HY-2A (`h2aman.txt`) ends in 2020, and Envisat, Jason-1, Jason-2, SPOT-2/3/4 and TOPEX end earlier still. All the added files use parameter type 006 (radial, along-track, cross-track), which `man.readme` defines for Envisat and CryoSat-2 only; the readme's satellite list predates them. There is one row per source row. A row can hold several burns: their times are in `burn_times_utc` and their Delta-v is summed per axis (radial, along-track, cross-track). Rows starting on or after the file's revision date are dropped as predictions. The archive (`maneuver-archive/`) shows that the newest row of a file is published before the burn and restated afterwards with executed values. Four revisions were checked (CryoSat-2, Sentinel-3B, Jason-3 and SWOT), and the restatements changed the burn time by under 0.3 s and Delta-v by a few percent. The readme does not state the time scale, so times are read as UTC.
- `qzss_manoeuvres.csv`: QZS-3 (42917) and QZS-6 (62876), both geostationary, and, added with `splits.json`, the inclined geosynchronous (IGSO) QZS-1 (37158), QZS-1R (49336), QZS-2 (42738) and QZS-4 (42965), from the Cabinet Office's QZSS Operational History Information (`https://qzss.go.jp/en/technical/qzssinfo/index.html`, files `ohi-qzs1.txt`, `ohi-qzs1r.txt`, `ohi-qzs2.txt`, `ohi-qzs3.txt`, `ohi-qzs4.txt` and `ohi-qzs6.txt`). Those six are every file the page lists; QZS-5 and QZS-7 have none. QZS-1 was retired in 2022 and its last logged burns are on 2022-02-28. Times are UTC to the second. The Delta-v is the planned value, as the source says. The frame of DVX/DVY/DVZ is not documented: EW burns load DVX, and NS burns load DVY. An NS-1 row and the NS-2 row after it share `event_group`. The IGSO files have no NS/EW column, so their `ns_ew` is empty and `kind` is `unspecified`. Their burns come in groups a few hours apart (for example −4.666 then +4.376 m/s DVX on QZS-1R, 2022-02-08), which the PDF version of each file labels #1, #2, #3 of one "orbit maintenance maneuver"; the CSV keeps one row per burn, and the net change is what a TLE sees.
- `fengyun_manoeuvres.csv`: Fengyun-2F (38049), Fengyun-2H (43491) and Fengyun-4A (41882), all geostationary, from the `raw_data/manoeuvres/manFY*.txt.fy` files of the GitHub repository `dpshorten/TLE_observation_benchmark_dataset` at commit `4cf0b15600658a486eff9e6a967ebd520e2354d1` (2022-11-22, the last commit touching them). These three are the Fengyun files with lines in 2021-2025; their last lines are in January and February 2022, so later element sets have no labels. Each line gives a type (`GEO-EW-STATION-KEEPING`, `GEO-NS-STATION-KEEPING` or `GEO-ATTITUDE-CONTROL`, kept as `source_type` and mapped to `kind` EW, NS or attitude), the COSPAR designator and a start and end time marked `CST`. There is no Delta-v, so `delta_a_est_m` is empty; the scorer still matches these events and leaves them out of its size bins. The one attitude line (Fengyun-2H) changes no orbit, so it is not a scoring target: the scorer keeps it out of recall and drops a detection that matches it, as the ISS scorer does with its unplanned attitude events. **Caveats:** the repository does not say where these lines come from, and it has no licence file. The time zone is ambiguous: the lines say `CST` (China Standard Time is UTC+8), while the repository's README calls its processed timestamps UTC and its YAML files keep the same clock times. The CSV assumes neither reading: `start_utc` is the start read as UTC+8 and `end_utc` the end read as UTC, so the window is the logged duration plus 8 h (about 8.5 h for the 28-minute EW lines, 13 h for the 5-hour NS lines) and holds the manoeuvre either way. Because the windows are this wide, two Fengyun lines up to about 20 h apart (start to start, plus the first line's duration) merge into one event under the scorer's 12 h merge rule. The clock times are kept verbatim in `source_start` and `source_end`. One FY-2F line appears twice and is kept once.
- `delta_a_est_m` is **an estimate, not a source value**: 2 x along-track Delta-v / mean motion (the Gauss relation for a circular orbit), using one nominal semi-major axis per satellite: the median, over the log span (for the satellites added with `splits.json`, over 2021-2025 or the part of it the log covers), of the semi-major axis `orbit_watch.elements` derives from each element set, which is SGP4's Brouwer mean semi-major axis (the Kozai mean motion un-Kozaied, times the WGS72 radius). It is not Space-Track's `SEMIMAJOR_AXIS` field, which is (mu / n_Kozai^2)^(1/3): for the LEO satellites the nominal value is 1.5-3 km below that field's median, and for QZS-4 0.4 km above it. The method and these differences were checked by recomputing the medians for the five train objects added with `splits.json` (Sentinel-3B, Sentinel-6B, HY-2C, HY-2D, QZS-4), which match the constants to 0.1 km; the holdout objects were not reopened, and the element sets for the first six objects are no longer cached. For QZSS it assumes that DVX is the along-track component. The IGSO orbits have an eccentricity of about 0.075, so the circular-orbit relation is rougher there.

Credits and citations, as the sources ask:

- IDS: "It is important that you acknowledge the IDS in your papers and presentations that rely on DORIS data and results. The following article is suggested for citation: Willis, P.; Lemoine, F.G.; … 2015. The International DORIS Service (IDS), recent developments in preparation for ITRF2013, IAG SYMPOSIA SERIES, 143, 631-639, DOI: 10.1007/1345_2015_164" (`https://ids-doris.org/citation.html`). Manoeuvre data: International DORIS Service (IDS), satellite manoeuvre files, `ftp://ftp.ids-doris.org/pub/ids/satellites/`.
- QZSS: "The user shall indicate proper credit and describe as reference document in any publication of the user the analysis result obtained by using this data." Reference document: Cabinet Office, Government of Japan, QZSS Operational History Information (QZS-1, QZS-1R, QZS-2, QZS-3, QZS-4, QZS-6), `https://qzss.go.jp/en/technical/qzssinfo/index.html`, page dated 2026-11-04.
- Fengyun: the repository asks for no particular credit and states no licence. Its README points to the paper *Wide-scale Monitoring of Satellite Lifetimes: Pitfalls and a Benchmark Dataset* for a description of the data set; cite that paper and `https://github.com/dpshorten/TLE_observation_benchmark_dataset` (commit `4cf0b15`). The labels are used here for internal tuning and scoring only.

## Train and holdout (`splits.json`, `objects.md`)

`splits.json` assigns every labelled object to `train` or `holdout`. It is written by `python -m orbit_watch.truth --write`, and `tests/test_truth.py` checks that the committed file still follows the rule, which was fixed before any detector output existed for the new objects:

- Every object scored before the split (the ISS, CryoSat-2, Jason-3, SWOT, SPOT-5, QZS-3, QZS-6) is `train`.
- The objects added with the split are grouped by regime (LEO, GEO, IGSO). Each group is sorted by NORAD id and shuffled with Python's `random.Random("orbit-watch truth-sets 2026-11-14")`. The first ceil(n/3) LEO objects and the first ceil(2n/3) GEO and IGSO objects are `holdout`; the rest are `train`.

That gives a holdout of Sentinel-3A, Sentinel-6A and SARAL (LEO, 3 of 7), Fengyun-2F and Fengyun-4A (GEO, 2 of 3), and QZS-1, QZS-1R and QZS-2 (IGSO, 3 of 4). Two guards keep the holdout out of tuning. Labels: `orbit_watch.truth.read_label_rows` is the only package code that opens a ground-truth CSV (`tests/test_truth.py` scans the package for others), and it raises `HoldoutError` for a holdout object unless called with `final=True`; it also refuses objects `splits.json` does not list, so a new object has to be assigned first. Element sets: `orbit_watch.series.to_series`, which every detector entry point (`calibrate`, `holdout`, `inject`, `geo_hunt`, `generalise`) uses to build its input, refuses a holdout object's series unless `final=True`, and lets objects `splits.json` does not list through, because belt-wide hunts are unlabelled. `generalise` tunes, so it refuses `--final`. The one caller that passes `final=True` is the frozen evaluation, `python -m harness.evals.detector --split test --final` (README, "Frozen per-regime evaluation"), which scores a train-chosen setting without tuning. **These are code-path guards, not a wall:** the labels are in committed CSVs anyone can open. They stop the package's own code from tuning on the holdout by accident.

Scoring is restricted to each log's coverage: from its first row to the IDS file's revision date (an IDS file is the operator's live record, updated with each burn), or to the last row for QZSS and Fengyun (their revision dates are a web page's date and a repository commit date, which do not say when the log was last kept; QZS-1's log ends on 2022-02-28 and the Fengyun lines in January and February 2022). Detections outside that span do not count as false alarms (`generalise.log_coverage`). The holdout is small: 20 holdout LEO log rows in 2021-2025 have an estimated |Delta-a| of 50 m or more, and the GEO holdout has 3 NS rows (all Fengyun-4A). A holdout score is therefore an observed recall on these events, not evidence that a population target is met: even a perfect score gives a one-sided 95% binomial lower bound of about 0.86 for 20 events and about 0.37 for 3 (treating events as independent).

**What the holdout can and cannot claim.** The Fengyun labels (both GEO holdout objects, Fengyun-2F and Fengyun-4A, and the train object Fengyun-2H) have no stated provenance, an ambiguous time zone, and no evidence that they are complete between their first and last lines; trimming to first and last row bounds the span but does not show the log is continuous. They stay in the files and in the split as exploratory benchmark data, and their scores are reported, but **no acceptance claim (recall or false-alarm rate against a target) rests on them**. GEO-belt acceptance rests on the QZSS operator logs: the IGSO holdout (QZS-1, QZS-1R, QZS-2; same semi-major axis as GEO, burns without an east-west or north-south label) for blind recall and false-alarm rate, and QZS-3 and QZS-6 (train) for east-west and north-south recall. There is no blind north-south set from an operator log, so the north-south target can only be checked on QZS-3 and QZS-6, and that number is not blind.

`objects.md` lists every object with its split, its log rows in 2021-2025 and its cached Space-Track element sets, generated by `python tools/truth_table.py --tle-dir <data/spacetrack>`. The element sets for the new objects were fetched by `hush run -- python tools/fetch_truth_tles.py` (2021-01-01 to 2026-01-01, one request per object). The cached files for the six objects of the first generalisation run (CryoSat-2, Jason-3, SWOT, SPOT-5, QZS-3, QZS-6) are no longer on disk, so the table says "not cached" for them; they were not fetched again, because Space-Track allows each object's history to be downloaded once.

## Sources checked and not added

- **NOAA GOES navigation summary** (`https://www.ospo.noaa.gov/resources/cemscs/navsum.txt`, US-Government public domain): each copy states only the day of each GOES satellite's last manoeuvre, so a history needs archived copies. The Wayback Machine holds 31 distinct copies, all from 2026 (checked 2026-11-14), so it gives nothing for 2021-2025.
- **BeiDou NABU notices** (CSNO test and assessment centre, `https://www.csno-tarc.cn/en/support/announcement`): an operator feed that names GEO and IGSO satellites, but the page is a JavaScript application, the notice-list endpoints found in its code did not answer a plain request, and the zip URL pattern `…/data/upload/nabu/NABU-<year>-<n>.zip` described by astro-tools/maneuver-detect returned 404 for the one notice tried. No terms of use were found.
- **EUMETSAT notices for Metop and Meteosat**: one web page per notice with a planned time and no log; they were not crawled.
- **astro-tools/maneuver-detect labels** (`dataset/v0.3/labels.json`, MIT): built from the same IDS and QZSS files, GPS and Galileo notices (MEO), the GOES navigation summary above, and longitude-drift labels it derives itself for Meteosat and Himawari. The GEO labels it derives are not operator logs, so none of its labels were added.
