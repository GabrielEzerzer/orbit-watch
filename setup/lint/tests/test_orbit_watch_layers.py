# Tests for the orbit-watch import-layer and fixture rules: each rule fires on a bad sample and not on a good one.
import unittest

from test_rules import scan_matches


def hits(files):
    return {(m["file"].replace("\\", "/").removeprefix("./"), m["range"]["start"]["line"] + 1, m["ruleId"])
            for m in scan_matches(files)}


class Layers(unittest.TestCase):
    def check(self, rule, bad, good):
        for name, text in bad.items():
            with self.subTest(bad=name):
                self.assertIn(rule, {r for _, _, r in hits({name: text})})
        for name, text in good.items():
            with self.subTest(good=name):
                self.assertNotIn(rule, {r for _, _, r in hits({name: text})})

    def test_package_never_imports_tests_harness_or_tools(self):
        self.check(
            "package-imports-no-harness-tests-tools",
            {
                "orbit_watch/a.py": "from tests.test_detect import ramp\n",
                "orbit_watch/b.py": "import harness.evals.detector\n",
                "orbit_watch/jobs/c.py": "import os, tools.kaggle_run\n",
            },
            {
                "orbit_watch/d.py": "from orbit_watch.detect import detect\nimport toolz\n",
                "tests/test_e.py": "from harness.evals import detector\n",
                "harness/f.py": "from tools import kaggle_run\n",
            },
        )

    def test_fetchers_are_imported_only_by_jobs_and_fetchers(self):
        self.check(
            "fetchers-imported-only-by-jobs",
            {
                "orbit_watch/calibrate.py": "from orbit_watch import spacetrack\n",
                "orbit_watch/generalise.py": "from orbit_watch.celestrak import cached_fetch\n",
                "orbit_watch/holdout.py": "import orbit_watch.spaceweather as sw\n",
                "orbit_watch/inject.py": "from . import (\n    detect,\n    spacetrack,\n)\n",
            },
            {
                "orbit_watch/jobs/geo_belt.py": "from orbit_watch.spacetrack import SpaceTrackSource\n",
                "orbit_watch/spaceweather.py": "from orbit_watch.celestrak import cached_fetch\n",
                "orbit_watch/spacetrack.py": "from orbit_watch import celestrak\n",
                "tools/fetch_truth_tles.py": "from orbit_watch.spacetrack import SpaceTrackSource\n",
                "orbit_watch/geo_hunt.py": "from orbit_watch.series import to_series\n",
            },
        )

    def test_jobs_are_imported_only_by_jobs(self):
        self.check(
            "jobs-imported-only-by-jobs",
            {
                "orbit_watch/modes.py": "from orbit_watch.jobs.geo_modes import main\n",
                "orbit_watch/generalise.py": "from orbit_watch import jobs\n",
                "orbit_watch/inject.py": "import orbit_watch.jobs.geo_belt\n",
            },
            {
                "orbit_watch/jobs/geo_belt.py": "from orbit_watch.jobs.extract_tle_archive import Collected\n",
                "tests/test_geo_belt.py": "from orbit_watch.jobs import geo_belt\n",
                "orbit_watch/series.py": "from orbit_watch.truth import require_not_holdout\n",
            },
        )

    def test_core_imports_only_core(self):
        self.check(
            "core-imports-only-core",
            {
                "orbit_watch/detect.py": "from orbit_watch.calibrate import FROZEN\n",
                "orbit_watch/series.py": "from orbit_watch import sources\n",
                "orbit_watch/modes.py": "import orbit_watch.geo_hunt\n",
                "orbit_watch/geo.py": "from .manoeuvre_logs import SOURCES\n",
                "orbit_watch/truth.py": "from orbit_watch.spacetrack import SpaceTrackSource\n",
            },
            {
                "orbit_watch/modes.py": "from orbit_watch.geo import longitudes\nfrom orbit_watch.elements import ElementSet\n",
                "orbit_watch/series.py": "from orbit_watch.truth import require_not_holdout\n",
                "orbit_watch/detect.py": "import orbit_watch.series as series\n",
                "orbit_watch/calibrate.py": "from orbit_watch.generalise import covered\n",
            },
        )

    def test_tests_read_fixtures_through_mock_dir(self):
        self.check(
            "tests-read-fixtures-through-mock-dir",
            {
                "tests/test_a.py": "from pathlib import Path\nT = (Path(__file__).parents[1] / \"mock\" / \"x.tle\").read_text()\n",
                "tests/test_b.py": "T = open(\"mock/elements/iss.tle\").read()\n",
                "tests/test_c.py": "from pathlib import Path\nT = Path(\"data/spacetrack/x.json\")\n",
                "tests/test_d.py": "from pathlib import Path\nREPO = Path(__file__).parents[1]\nT = REPO / \"data\" / \"x\"\n",
                "tests/test_h.py": "from pathlib import Path\nREPO_DIR = Path(__file__).parents[1]\nT = REPO_DIR / \"mock\" / \"x.tle\"\n",
                "tests/test_i.py": "from pathlib import Path\nTEST_ROOT = Path(__file__).parent\nT = TEST_ROOT / \"data\"\n",
                "tests/test_j.py": "from pathlib import Path\nT = Path(__file__).parents[1].joinpath(\"mock\", \"x.tle\")\n",
                "tests/test_k.py": "from pathlib import Path\nREPO = Path(__file__).parents[1]\nT = REPO.joinpath(\"data\")\n",
            },
            {
                "tests/test_e.py": "def test_x(mock_dir):\n    return (mock_dir / \"geo\" / \"x.tle\").read_text()\n",
                "tests/test_f.py": "def test_x(tmp_path):\n    (tmp_path / \"data\").mkdir()\n",
                "tests/test_g.py": "def test_x():\n    build(\"mock\", [])\n",
                "tests/conftest.py": "from pathlib import Path\nMOCK = Path(__file__).resolve().parents[1] / \"mock\"\n",
                "tests/test_l.py": "def test_x(tmp_path):\n    tmp_path.joinpath(\"data\").mkdir()\n",
                "tests/test_m.py": "def test_x(mock_dir):\n    return mock_dir.joinpath(\"geo\", \"x.tle\").read_text()\n",
                "tests/test_n.py": "from pathlib import Path\nREPO = Path(__file__).parents[1]\nT = REPO / \"orbit_watch\"\n",
            },
        )


if __name__ == "__main__":
    unittest.main()
