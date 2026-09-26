"""The dual-route relate cross-check (DESIGN §0.2): the arrangement route (§2.3,
:mod:`geotruth.relate`) against the witness route (§2.4, :mod:`geotruth.relate_witness`),
the polygon references (``tests/reference/oracle.py``, ``indep.py``) and GEOS 3.13 as a
third opinion on small-integer lattices.

The machinery lives in ``tools/crosscheck_relate.py`` (also a command-line tool with
larger defaults); these tests run it on every hand-built fixture, the whole seed corpus,
the oracle-review families (``gen_review.py all 50 1``), and seeded random cases of every
type pair (lattice, adversarial derived configurations, exact affine images, ulp-level
near-degeneracies, dense and stacked inputs). The two exact routes must agree on every
case; a GEOS disagreement must be confirmed by GEOS's own point locator (a GEOS defect),
never unexplained.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from geotruth.io import read_wkt
from geotruth.relate import relate
from geotruth.relate_witness import relate_witness

pytestmark = pytest.mark.crosscheck

REPO = Path(__file__).resolve().parents[2]


def _load_tool():
    name = "crosscheck_relate"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / "crosscheck_relate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


X = _load_tool()


def _geos():
    return pytest.importorskip("shapely")


def check_all(cases, *, use_geos: bool = True):
    reports = X.run(list(cases), use_geos=use_geos)
    failures = [(r.id, r.wkt, r.problems) for r in reports if r.failed]
    assert failures == []
    assert all(r.exact_agree for r in reports)
    assert all(r.arrangement_status == "ok" for r in reports)
    return reports


def _geos_stats(reports):
    judged = [r for r in reports if r.geos is not None]
    verdicts = Counter(r.geos_verdict or "agree" for r in judged)
    assert not any(v.startswith("UNEXPLAINED") for v in verdicts), verdicts
    return len(judged), verdicts


# ======================================================================= sources


def test_fixtures():
    reports = check_all(X.fixture_cases())
    assert len(reports) == 12 and all(r.expected_agree for r in reports)


def test_exhaustive_grid_sample():
    """An even stride through every (triangle, point | segment | triangle) pair on the
    3x3 grid, GCs of two triangles and two-segment paths (the full list is slow)."""
    reports = check_all(X.exhaustive_cases(2500))
    assert {r.family for r in reports} == {"A/P", "A/L", "A/A", "GC/P", "GC/L", "L2/L", "L2/A"}
    assert all(r.oracle_agree for r in reports if r.family == "A/A")
    judged, verdicts = _geos_stats(reports)
    assert judged == len(reports) and verdicts["agree"] >= 0.99 * judged


@pytest.mark.slow
def test_exhaustive_grid_full():
    reports = check_all(X.exhaustive_cases())
    assert len(reports) == 23732


@pytest.mark.parametrize("chunk", range(4))
def test_seed_corpus(chunk):
    """All 1000 seed cases (ulp-level polygon pairs): the two routes, oracle and indep."""
    cases = list(X.seed_cases())[chunk::4]
    reports = check_all(cases, use_geos=False)
    assert len(reports) == 250
    assert all(r.oracle_agree and r.indep_agree for r in reports)


def test_review_families():
    """The oracle-review families, 50 per family (convex/general grids, ulp and float
    variants, extreme scales, edge cases)."""
    _geos()
    reports = check_all(X.review_cases(50, 1))
    assert len(reports) == 395
    assert all(r.oracle_agree and r.indep_agree for r in reports)
    judged, verdicts = _geos_stats(reports)
    assert judged > 50 and verdicts["agree"] == judged


@pytest.mark.parametrize("block", range(4))
def test_lattice_every_type_pair(block):
    """1280 lattice cases per block: every ordered pair of Point, MultiPoint, LineString,
    MultiLineString, Polygon, MultiPolygon, mixed GC and GC of rectangles, plus random
    testlib operands; GEOS as a third opinion on each."""
    reports = check_all(X.lattice_cases(1600, seed=100 + block))
    fams = Counter(r.family for r in reports)
    assert len([f for f in fams if "/" in f]) == 64
    judged, verdicts = _geos_stats(reports)
    assert judged == len(reports)
    assert verdicts["agree"] >= 0.97 * judged


@pytest.mark.parametrize("block", range(4))
def test_adversarial(block):
    """Derived configurations (B from A's boundary, vertices, midpoints, re-expressions,
    shifts, holes, extensions), nested and mixed GCs, empties, zero-length lines."""
    reports = check_all(X.adversarial_cases(1000, seed=200 + block))
    kinds = {r.types for r in reports}
    assert len(kinds) >= 40
    judged, verdicts = _geos_stats(reports)
    assert verdicts["agree"] >= 0.95 * judged


@pytest.mark.parametrize("block", range(2))
def test_affine_images(block):
    """Exact affine images (rational maps, 2**-1070 and 2**1000 scalings, axis swaps,
    translations by 2**52): both routes reproduce the untransformed matrix."""
    reports = check_all(X.transformed_cases(250, seed=300 + block))
    assert all(r.expected_agree for r in reports)
    assert {r.family for r in reports} >= {"rational", "scale", "swap", "translate"}


def test_ulp_near_degeneracies():
    reports = check_all(X.ulp_cases(400, seed=400), use_geos=False)
    assert len(reports) == 400


def test_dense_and_stacked():
    reports = check_all(X.dense_cases(240, seed=500))
    assert {r.family for r in reports} >= {"stacked", "testlib-12"}


# ======================================================================= GEOS findings

#: GEOS 3.13.1 crashes (SIGSEGV) on these valid inputs; the exact answer is given.
GEOS_CRASHES = [
    # AdjacentEdgeLocator meets the empty polygon of a GC at a node on a shared edge
    (
        "POINT (2 1)",
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON EMPTY, "
        "POLYGON ((2 0, 4 0, 4 2, 2 2, 2 0)))",
        "0FFFFF212",
    ),
    # an empty LineString in a GC against an empty operand
    ("GEOMETRYCOLLECTION (POINT (0 2), LINESTRING EMPTY)", "POINT EMPTY", "FF0FFFFF2"),
]

#: GEOS 3.13.1 reports the type dimension given by an empty element: a line with an
#: empty polygon gets IE = 2 and BE = 1 (exact, and GEOS's own point locator: 1 and 0).
EMPTY_ELEMENT_DIMENSION = [
    ("GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POLYGON EMPTY)", "POINT EMPTY",
     "FF1FF0FF2", "FF2FF1FF2"),
    ("GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POLYGON EMPTY)", "POINT (5 5)",
     "FF1FF00F2", "FF2FF10F2"),
    ("GEOMETRYCOLLECTION (POINT (0 0), POLYGON EMPTY)", "POINT EMPTY",
     "FF0FFFFF2", "FF2FF1FF2"),
]  # fmt: skip


#: GEOS 3.13.1's point locator is wrong at a reflex vertex of one GC polygon lying on the
#: boundary of another whose union covers the vertex's neighbourhood (AdjacentEdgeLocator):
#: GEOS says Boundary, the exact answer (and GEOS's own ``union`` of the polygons) says
#: Interior, so GEOS reports ``contains`` false and ``touches`` true for an interior point.
GC_REFLEX = (
    "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
    "POLYGON ((1 2, 2 1, 3 4, -1 4, 0 1, 1 2)))"
)
GEOS_POINT_LOCATION = [
    (GC_REFLEX, "POINT (1 2)", "0F2FF1FF2", "FF20F1FF2"),
    (GC_REFLEX, "LINESTRING (1 2, 1 3)", "102FF1FF2", "102F01FF2"),
    # found by the dense source (5 stacked polygons; the reflex vertex is (4 6))
    ("GEOMETRYCOLLECTION (POLYGON ((4 2, 4 4, 0 4, 0 2, 4 2)), POLYGON ((0 0, 4 4, 8 4, "
     "2 0, 0 0)), POLYGON ((6 8, 6 4, 8 4, 8 8, 6 8)), POLYGON ((6 6, 8 4, 0 8, 6 6)), "
     "POLYGON ((6 6, 8 2, 8 0, 6 2, 2 8, 4 6, 6 6)), MULTIPOINT ((0 0), (4 4), (8 4), (2 0)))",
     "MULTILINESTRING ((4 6, 2 4), (2 4, 2 0, 0 6), (4 6, 4 8, 8 4, 4 8, 4 6))",
     "1020F1102", "1F2001102"),
]  # fmt: skip


@pytest.mark.parametrize(("a", "b", "exact", "geos"), GEOS_POINT_LOCATION)
def test_geos_point_location_defect(a, b, exact, geos):
    shapely = _geos()
    ga, gb = read_wkt(a), read_wkt(b)
    rep = X.check_case(X.XCase("adjacent", "pinned", "adjacent", ga, gb))
    assert not rep.failed and rep.arrangement == rep.witness == exact
    if tuple(shapely.geos_version) == (3, 13, 1):
        assert rep.geos == geos
        assert rep.geos_verdict == "geos-point-location (gc-adjacent-edge)"


def test_geos_point_location_contradicts_geos_union():
    """GEOS against itself: its GC point locator says Boundary at (1 2), its overlay
    union of the same two polygons says Interior (the exact answer)."""
    shapely = _geos()
    from geotruth.locate import locate

    gc = shapely.from_wkt(GC_REFLEX)
    p = shapely.Point(1, 2)
    union = shapely.union_all(list(gc.geoms))
    assert locate((1, 2), read_wkt(GC_REFLEX)) == "I"
    assert shapely.relate(p, union) == "0FFFFF212"  # interior of GEOS's own union
    if tuple(shapely.geos_version) == (3, 13, 1):
        assert shapely.relate(p, gc) == "F0FFFF212"
        assert not shapely.contains(gc, p) and shapely.touches(gc, p)


def test_line_end_skip_confirmed_on_a_single_witness():
    """Too large to locate every witness exactly, but the entry GEOS drops (BE) is
    realised by a vertex GEOS itself locates as (Boundary of A, Exterior of B)."""
    _geos()
    a = read_wkt("MULTILINESTRING ((6 3, 6 6, 1 0, 5 10, 6 6, 6 3), (9 8, 11 2))")
    b = read_wkt("LINESTRING (0 0, 11 1, 0 0)")
    rep = X.check_case(X.XCase("les", "pinned", "les", a, b))
    assert not rep.failed and rep.arrangement == rep.witness == "0F1FF01F2"
    assert rep.geos_verdict in (None, "line-end-skip (partial)")


@pytest.mark.parametrize(("a", "b", "exact"), GEOS_CRASHES)
def test_geos_crashes_are_isolated_and_recorded(a, b, exact):
    shapely = _geos()
    ga, gb = read_wkt(a), read_wkt(b)
    assert relate(ga, gb, strict=True).matrix == exact
    assert relate_witness(ga, gb).matrix == exact
    assert X.geos_valid(ga) and X.geos_valid(gb)
    rep = X.check_case(X.XCase("crash", "pinned", "crash", ga, gb))
    assert not rep.failed and rep.exact_agree
    if tuple(shapely.geos_version) == (3, 13, 1):
        assert rep.geos == "CRASH" and rep.geos_verdict.startswith("geos-crash (signal 11")
    # the worker restarts after a crash
    assert X.geos().relate("POINT (0 0)", "POINT (0 0)") == "0FFFFFFF2"


@pytest.mark.parametrize(("a", "b", "exact", "geos"), EMPTY_ELEMENT_DIMENSION)
def test_geos_empty_element_dimension(a, b, exact, geos):
    shapely = _geos()
    ga, gb = read_wkt(a), read_wkt(b)
    rep = X.check_case(X.XCase("empty-dim", "pinned", "empty-dim", ga, gb))
    assert not rep.failed and rep.arrangement == rep.witness == exact
    if tuple(shapely.geos_version) == (3, 13, 1):
        assert rep.geos == geos and rep.geos_verdict == "empty-element-dimension"


def test_geos_disagreements_are_confirmed_by_geos_point_location():
    """A known RelateNG defect (line-end-skip) through the full judging path."""
    _geos()
    a = read_wkt("POINT (10 10)")
    b = read_wkt("MULTILINESTRING ((0 0, 1 0, 1 1, 0 0), (5 5, 6 6))")
    rep = X.check_case(X.XCase("les", "pinned", "les", a, b))
    assert rep.arrangement == rep.witness == "FF0FFF102"
    assert rep.geos_verdict in (None, "line-end-skip")
    w = relate_witness(a, b, keep_witnesses=True)
    assert X.geos_located_matrix(w, a, b) == "FF0FFF102"


def test_geos_worker_timeout_and_restart():
    _geos()
    worker = X.GeosWorker(timeout=30)
    try:
        assert worker.relate("POINT (0 0)", "LINESTRING (0 0, 1 0)") == "F0FFFF102"
        with pytest.raises(RuntimeError, match=r"ParseException|WKT|GEOSException"):
            worker.relate("POINT (0 0", "POINT (0 0)")
        square = "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"
        assert worker.locate([square], [(1, 1), (2, 1), (5, 5)]) == [[0], [1], [2]]
        assert worker.crashes == 0
    finally:
        worker.close()


# ======================================================================= the tool


def test_tool_command_line(tmp_path, capsys):
    out = tmp_path / "report.json"
    status = X.main(["--sources", "fixtures,lattice", "--cases", "64", "--json", str(out)])
    text = capsys.readouterr().out
    assert status == 0
    assert "TOTAL" in text and "type pairs covered" in text
    report = json.loads(out.read_text())
    assert report["total"]["cases"] == 76 and report["total"]["failed"] == 0
    assert report["total"]["exact_agree"] == 76
    assert set(report["sources"]) == {"fixtures", "lattice"}


def test_tool_reports_a_disagreement(monkeypatch):
    """A broken route must be caught: a witness route that drops BB makes cases fail."""
    real = X.relate_witness

    def broken(a, b, **kw):
        res = real(a, b, **kw)
        res.matrix = res.matrix[:4] + "F" + res.matrix[5:]
        return res

    monkeypatch.setattr(X, "relate_witness", broken)
    reps = X.run(list(X.fixture_cases()), use_geos=False)
    bad = [r for r in reps if r.failed]
    assert bad and all("routes disagree" in r.problems[0] for r in bad)
    summary = X.summarize(reps)
    assert summary["total"]["failed"] == len(bad) and summary["failures"]


@pytest.mark.slow
@pytest.mark.parametrize("seed", [7, 8])
def test_tool_large_run(seed):
    """Every source at 2000 random cases per random source (about 7.4k cases)."""
    assert X.main(["--cases", "2000", "--seed", str(seed)]) == 0
