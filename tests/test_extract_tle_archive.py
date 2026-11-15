import io
import re
from datetime import datetime, timedelta, timezone

from orbit_watch.jobs.extract_tle_archive import COMMIT_MARK, extract, gaps, names_matching

ISS_A1 = "1 25544U 98067A   19343.69339541  .00001764  00000-0  38792-4 0  9991"
ISS_A2 = "2 25544  51.6439 211.2001 0007417  17.6667  85.6398 15.50103472202482"
ISS_B1 = "1 25544U 98067A   19366.82137887  .00016717  00000-0  10270-3 0  9129"
ISS_B2 = "2 25544  51.6392  96.6358 0005156  88.7140 271.4601 15.49497216  6061"
MARIO1 = "1 55123U 98067UQ  23115.44827133  .00787702  29408-3  15680-2 0  9999"
MARIO2 = "2 55123  51.6242 216.2930 0014649 331.8976  28.1241 15.99081912 18396"

DIFF = f"""\
{COMMIT_MARK}1111111111111111111111111111111111111111 2021-01-01T00:05:00+00:00

diff --git a/TLEs/active.txt b/TLEs/active.txt
new file mode 100644
--- /dev/null
+++ b/TLEs/active.txt
@@ -0,0 +1,6 @@
+ISS (ZARYA)             \r
+{ISS_A1}\r
+{ISS_A2}\r
+MARIO                   \r
+{MARIO1}\r
+{MARIO2}\r
{COMMIT_MARK}2222222222222222222222222222222222222222 2021-01-01T01:05:00+00:00

diff --git a/TLEs/active.txt b/TLEs/active.txt
--- a/TLEs/active.txt
+++ b/TLEs/active.txt
@@ -2,2 +2,2 @@
-{ISS_A1}\r
-{ISS_A2}\r
+{ISS_B1}\r
+{ISS_B2}\r
{COMMIT_MARK}3333333333333333333333333333333333333333 2021-01-01T02:05:00+00:00

diff --git a/TLEs/active.txt b/TLEs/active.txt
--- a/TLEs/active.txt
+++ b/TLEs/active.txt
@@ -3 +3 @@
-{ISS_B2}\r
+{ISS_A2}\r
{COMMIT_MARK}4444444444444444444444444444444444444444 2021-01-01T03:05:00+00:00

diff --git a/TLEs/active.txt b/TLEs/active.txt
--- a/TLEs/active.txt
+++ b/TLEs/active.txt
@@ -2 +2 @@
-{ISS_B1}\r
+{ISS_B1[:-1]}0\r
"""


def test_extract_pairs_lines_across_commits_and_dedupes_by_epoch():
    result = extract(io.StringIO(DIFF), {25544})
    assert result.commits == 4
    assert result.last_commit == "4" * 40
    assert set(result.objects) == {25544}
    iss = result.objects[25544]
    assert sorted(iss.lines.values()) == sorted([(ISS_A1, ISS_A2), (ISS_B1, ISS_B2)])
    assert iss.conflicts == 1
    assert iss.invalid == 1


def test_names_matching_reads_3le_name_lines():
    text = f"ISS (ZARYA)             \r\n{ISS_A1}\r\n{ISS_A2}\r\nMARIO                   \r\n{MARIO1}\r\n{MARIO2}\r\n"
    assert names_matching(text, re.compile("MARIO|LUCH")) == {55123: "MARIO"}


def test_gaps_reports_only_spans_longer_than_three_days():
    t0 = datetime(2022, 1, 1, tzinfo=timezone.utc)
    epochs = [t0, t0 + timedelta(days=1), t0 + timedelta(days=5), t0 + timedelta(days=8)]
    assert gaps(epochs) == [(epochs[1], epochs[2])]
