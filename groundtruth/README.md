# Ground truth

`iss_manoeuvres.csv` lists publicly announced ISS manoeuvres (reboosts, debris-avoidance burns and other orbit-changing burns) from 2021-01 to 2025-12. Each row carries the NASA page it came from (`source_url`) and a verbatim quote from that page (`quote`) supporting every field in the row. Every quote was checked word for word against the fetched page. Nothing in this file is estimated or inferred.

How to read it:
- `time_utc` is filled only when the page gives a clock time with a time zone (converted with CDT = UTC-5, CST = UTC-6, EDT = UTC-4, EST = UTC-5). Where only "CT" is given, CST or CDT follows the US daylight-saving calendar.
- When `time_utc` is empty, `date_utc` is the US-local calendar date the page states or implies, so treat it as plus or minus one day.
- `quote` joins fragments from one page with ` … `; ` || ` separates quotes from different pages, whose URLs appear in `source_url` separated by ` ; ` in the same order.
- Two rows typed `other (unplanned attitude/thruster event)` (Nauka 2021-07-29, Soyuz MS-18 2021-10-15) are attitude upsets. The pages do not describe an orbit change, so they are not calibration targets.
- The list is a lower bound. Roscosmos and TASS announcements were not searched, and the ISS Daily Summary Reports only appear on weekdays.

Sources: NASA's Space Station blog (nasa.gov/blogs/spacestation) and the ISS Daily Summary Reports (nasa.gov/blogs/stationreport), found through the nasa.gov WordPress API and a full-text scan of the 2021-2023 posts.

## IDS and QZSS manoeuvre logs (`ids_manoeuvres.csv`, `qzss_manoeuvres.csv`)

Both files are built by `python -m orbit_watch.manoeuvre_logs --ids-dir <dir> --qzss-dir <dir> --out groundtruth` from the operators' published logs. The raw logs are not committed; each row names its source file, the file's revision date and its URL, so the CSVs can be rebuilt after downloading those files. The module docstring explains the parsing.

- `ids_manoeuvres.csv`: CryoSat-2 (36508), Jason-3 (41240), SWOT (54754) and SPOT-5 (27421), from the International DORIS Service manoeuvre files at `ftp://ftp.ids-doris.org/pub/ids/satellites/` (`cs2man.txt`, `ja3man.txt`, `swoman.txt`, `sp5man.txt`; format in `man.readme`). There is one row per source row. A row can hold several burns: their times are in `burn_times_utc` and their Delta-v is summed per axis (radial, along-track, cross-track). Rows starting on or after the file's revision date are dropped as predictions. The archive (`maneuver-archive/`) shows that the newest row of a file is published before the burn and restated afterwards with executed values. Four revisions were checked (CryoSat-2, Sentinel-3B, Jason-3 and SWOT), and the restatements changed the burn time by under 0.3 s and Delta-v by a few percent. The readme does not state the time scale, so times are read as UTC.
- `qzss_manoeuvres.csv`: QZS-3 (42917) and QZS-6 (62876), both geostationary, from the Cabinet Office's QZSS Operational History Information (`https://qzss.go.jp/en/technical/qzssinfo/index.html`, files `ohi-qzs3.txt` and `ohi-qzs6.txt`). Times are UTC to the second. The Delta-v is the planned value, as the source says. The frame of DVX/DVY/DVZ is not documented: EW burns load DVX, and NS burns load DVY. An NS-1 row and the NS-2 row after it share `event_group`.
- `delta_a_est_m` is **an estimate, not a source value**: 2 x along-track Delta-v / mean motion (the Gauss relation for a circular orbit), using one nominal semi-major axis per satellite. For QZSS it assumes that DVX is the along-track component.

Credits and citations, as the sources ask:

- IDS: "It is important that you acknowledge the IDS in your papers and presentations that rely on DORIS data and results. The following article is suggested for citation: Willis, P.; Lemoine, F.G.; … 2015. The International DORIS Service (IDS), recent developments in preparation for ITRF2013, IAG SYMPOSIA SERIES, 143, 631-639, DOI: 10.1007/1345_2015_164" (`https://ids-doris.org/citation.html`). Manoeuvre data: International DORIS Service (IDS), satellite manoeuvre files, `ftp://ftp.ids-doris.org/pub/ids/satellites/`.
- QZSS: "The user shall indicate proper credit and describe as reference document in any publication of the user the analysis result obtained by using this data." Reference document: Cabinet Office, Government of Japan, QZSS Operational History Information (QZS-3, QZS-6), `https://qzss.go.jp/en/technical/qzssinfo/index.html`, page dated 2026-11-04.
