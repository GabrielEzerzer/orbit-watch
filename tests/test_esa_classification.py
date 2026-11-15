import importlib.util
import json
from collections import Counter
from pathlib import Path

_PATH = Path(__file__).resolve().parents[1] / "tools" / "esa_classification.py"
_spec = importlib.util.spec_from_file_location("esa_classification", _PATH)
esa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(esa)

# Laid out like pdftotext -layout output of ESA's issue 21, section 3.
SECTION_3 = """\
3  CLASSIFICATION SUMMARY
1963-031A Syncom 2 (in the text before the table)    I        1.    p. 191
COSPAR Name                                          Status   nn    Page
1963-031A Syncom 2                                   I        1.    p. 191
1964-047A Syncom 3                                   D        594.  p. 146
1965-028A Intelsat I F-1 (Early Bird)                L2       20.   p. 179
1966-053A GGTS 1                                     C1       815.  p. 165
1967-001A A name too long for the column, with the
          class on the next line                     D        3.    p. 98
4  OBJECTS WITH EPHEMERIS
1968-002A After the table                            D        4.    p. 99
"""


def test_section_3_rows_count_only_when_the_page_lies_in_their_class_chapter():
    # 1966-053A says C1 but points at page 165, inside chapter D (97-167): the right-hand columns
    # were shifted by a line, so the row is dropped. Rows split over two lines and rows outside
    # the table are not read.
    assert esa.esa_classes(SECTION_3) == {"1963-031A": "I", "1964-047A": "D", "1965-028A": "L2"}


def test_main_sets_each_esa_class_beside_the_first_mode_of_2021(tmp_path, capsys):
    (tmp_path / "i21.txt").write_text(SECTION_3, encoding="utf-8")
    (tmp_path / "segments.csv").write_text(
        "norad_id,start,end,mode\n"
        "613,2021-01-01,2021-03-01,undetermined\n"  # Syncom 2: first determined segment counts
        "613,2021-03-01,2026-01-01,inclined\n"
        "858,2021-01-01,2026-01-01,librating_both\n"  # Syncom 3: ESA D
        "1317,2021-08-01,2026-01-01,librating_105W\n",  # Early Bird: starts after 1 July 2021
        encoding="utf-8")
    manifest = {"objects": {"613": {"satcat": {"INTLDES": "1963-031A"}}, "858": {"satcat": {"INTLDES": "1964-047A"}},
                            "1317": {"satcat": {"INTLDES": "1965-028A"}}, "999": {}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert esa.first_modes(tmp_path / "segments.csv") == {613: "inclined", 858: "librating_both"}
    assert esa.main([str(tmp_path / "i21.txt"), str(tmp_path / "segments.csv"),
                     "--manifest", str(tmp_path / "manifest.json")]) == 0
    out = capsys.readouterr().out
    assert out.startswith("3 ESA rows kept, 2 matched to a mode")
    assert "| I | 1 | 1 (100%) |  |" in out and "| D | 1 | 0 (0%) | librating_both 1 |" in out
    assert esa.agreement({"1964-047A": "D"}, {"1964-047A": 858}, {858: "drifting"}) == {"D": Counter(drifting=1)}
