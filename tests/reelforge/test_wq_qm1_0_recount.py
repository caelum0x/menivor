"""Wave Q QM1.0 steward: the Menivor parity recount script (``tools/parity/recount.py``).

The recount prints H1-H24 and U1-U47 from test results. With every evidence
test passing and no Wave Q test present (today's ``main``), it reproduces the
2026-09-30 counts: 11 / 10 / 3 and 21 / 21 / 5.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load():
    folder = REPO / "tools" / "parity"
    sys.path.insert(0, str(folder))
    spec = importlib.util.spec_from_file_location("menivor_recount", folder / "recount.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recount = _load()


def test_rows_cover_h1_h24_and_u1_u47_once():
    ids = {g: [r.id for r in rows] for g, rows in recount.GROUPS.items()}
    assert ids["higgsfield"] == [f"H{n}" for n in range(1, 25)]
    assert ids["muvi"] == [f"U{n}" for n in range(1, 48)]


def test_every_evidence_file_exists():
    for rows in recount.GROUPS.values():
        for row in rows:
            for ref in row.evidence:
                assert (REPO / ref.split("::", 1)[0]).is_file(), (row.id, ref)


def test_self_test_reproduces_the_baseline():
    assert recount.self_test() == []
    assert recount.BASELINE == {"higgsfield": (11, 10, 3), "muvi": (21, 21, 5)}


def test_junit_parsing_folds_parametrised_cases_and_failures(tmp_path):
    xml = tmp_path / "j.xml"
    xml.write_text(
        '<testsuites><testsuite>'
        '<testcase classname="tests.reelforge.test_routing" name="test_a[x]"/>'
        '<testcase classname="tests.reelforge.test_routing" name="test_a[y]"><failure message="no"/></testcase>'
        '<testcase classname="tests.reelforge.test_motion" name="test_b"><skipped/></testcase>'
        '<testcase classname="tests.reelforge.test_motion" name="test_c"/>'
        '</testsuite></testsuites>', encoding="utf-8")
    results = recount.parse_junit([xml])
    assert results.outcomes["tests/reelforge/test_routing.py::test_a"] == ["passed", "failed"]
    assert not results.passed("tests/reelforge/test_routing.py")
    assert results.passed("tests/reelforge/test_motion.py")
    assert not results.passed("tests/reelforge/test_motion.py::test_b")


def test_main_self_test_exit_code(capsys):
    assert recount.main(["--self-test"]) == 0
    assert "self-test ok" in capsys.readouterr().out
