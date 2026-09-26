"""Exports run in the libraries' own test runners (DESIGN §5.6).

The pytest export runs against the installed Shapely (skipped without it).

Needs the JTS TestRunner and the GEOS xmltester built under $GEOTRUTH_BUILD_DIR
(``geotruth export --build-runners``); skipped otherwise.

- known-good (tests/corpus/data/xml_known_good.txt): every test passes in GEOS
  xmltester and in JTS with RelateNG; with the old RelateOp too, apart from
  GeometryCollection arguments (an exception there: unsupported).
- known-failing (tests/corpus/data/xml_known_failing.txt): exactly the listed ops fail,
  in GEOS and in JTS RelateNG.
"""

from __future__ import annotations

import re
import subprocess
import sys

import pytest
from corpus_testlib import DATA, id_list, records_by_id

from geotruth.export import export_records, runners

TOUCH = "relateng-multipolygon-touching-parts:t-touch-part-min"
GC_LEAD = "relateng-gc-polygon-with-exterior-point:gc-poly-exterior-point"

pytestmark = pytest.mark.crosscheck


@pytest.fixture(scope="module")
def have_runners():
    if runners.jts_classpath() is None or runners.geos_xmltester() is None:
        pytest.skip("JTS TestRunner / GEOS xmltester not built (geotruth export --build-runners)")


def _write(tmp_path, records, stem):
    paths = []
    for f in export_records(records, "jts-xml"):
        p = tmp_path / f"{stem}{f.suffix}.xml"
        p.write_text(f.text)
        paths.append(p)
    return paths


def test_known_good_passes_everywhere(have_runners, tmp_path):
    records = records_by_id(id_list("xml_known_good.txt"))
    total = 0
    for path in _write(tmp_path, records, "good"):
        geos = runners.run_geos(path)
        assert geos.ok, geos.failures
        ng = runners.run_jts(path, relate="ng")
        assert ng.ok, ng.failures
        assert ng.tests == geos.tests
        old = runners.run_jts(path, relate="old")
        assert old.failed == 0, old.failures
        assert all("GeometryCollection" in f for f in old.failures)  # exceptions only
        total += geos.tests
    assert total > 300


def test_known_failing_fail_as_expected(have_runners, tmp_path):
    rows = [
        ln.split("\t")
        for ln in (DATA / "xml_known_failing.txt").read_text().splitlines()
        if ln and not ln.startswith("#")
    ]
    for cid, ops in rows:
        [path] = _write(tmp_path, records_by_id([cid]), "bad")
        want = sorted(ops.split(","))
        geos = runners.run_geos(path)
        got = sorted(re.search(r"test \d+: (\w+)\(", f).group(1) for f in geos.failures)
        assert got == want, (cid, geos.failures)
        ng = runners.run_jts(path, relate="ng")
        assert ng.failed == len(want) and ng.exceptions == 0, (cid, ng.failures)


def _run_pytest(tmp_path, records):
    [f] = export_records(records, "pytest")
    path = tmp_path / "test_exported.py"
    path.write_text(f.text)
    # --color=no: CI sets FORCE_COLOR, and colour codes would hide the FAILED lines parsed below
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--color=no", "-p", "no:cacheprovider", str(path)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        check=False,
    )


def test_pytest_export_runs_against_shapely(tmp_path):
    pytest.importorskip("shapely")
    good = _run_pytest(tmp_path, records_by_id(id_list("xml_known_good.txt")))
    assert good.returncode == 0, good.stdout[-3000:]
    bad = _run_pytest(tmp_path, records_by_id([TOUCH, GC_LEAD]))
    assert bad.returncode == 1
    failed = set(re.findall(r"FAILED \S+::(\S+)", bad.stdout))
    assert failed == {
        f"test_relate[{TOUCH}]",
        f"test_predicate[{TOUCH}:overlaps]",
        f"test_predicate[{TOUCH}:contains]",
        f"test_predicate[{TOUCH}:covers]",
        f"test_relate[{GC_LEAD}]",
        f"test_predicate[{GC_LEAD}:overlaps]",
        f"test_predicate[{GC_LEAD}:within]",
        f"test_predicate[{GC_LEAD}:covered_by]",
    }, bad.stdout[-3000:]
