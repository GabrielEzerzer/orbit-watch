# Ground truth

`iss_manoeuvres.csv` lists publicly announced ISS manoeuvres (reboosts, debris-avoidance burns and other orbit-changing burns) from 2021-01 to 2025-12. Each row carries the NASA page it came from (`source_url`) and a verbatim quote from that page (`quote`) supporting every field in the row. Every quote was checked word for word against the fetched page. Nothing in this file is estimated or inferred.

How to read it:
- `time_utc` is filled only when the page gives a clock time with a time zone (converted with CDT = UTC-5, CST = UTC-6, EDT = UTC-4, EST = UTC-5). Where only "CT" is given, CST or CDT follows the US daylight-saving calendar.
- When `time_utc` is empty, `date_utc` is the US-local calendar date the page states or implies, so treat it as plus or minus one day.
- `quote` joins fragments from one page with ` … `; ` || ` separates quotes from different pages, whose URLs appear in `source_url` separated by ` ; ` in the same order.
- Two rows typed `other (unplanned attitude/thruster event)` (Nauka 2021-07-29, Soyuz MS-18 2021-10-15) are attitude upsets. The pages do not describe an orbit change, so they are not calibration targets.
- The list is a lower bound. Roscosmos and TASS announcements were not searched, and the ISS Daily Summary Reports only appear on weekdays.

Sources: NASA's Space Station blog (nasa.gov/blogs/spacestation) and the ISS Daily Summary Reports (nasa.gov/blogs/stationreport), found through the nasa.gov WordPress API and a full-text scan of the 2021-2023 posts.
