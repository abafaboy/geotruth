"""Overlay cross-checks (DESIGN §0.2, §2.5, §2.6).

The machinery lives in ``tools/crosscheck_overlay.py`` (also a command-line tool with
larger defaults). For every case, all four operations in both variants are:

- certified by the independent certificate (:mod:`geotruth.overlay_certify`);
- compared, for valid polygon/polygon cases, with the exact areas of
  ``tests/reference/oracle.py`` and ``indep.py`` (equal as rationals);
- checked for validity with the audited reference rules (``tests/reference/validity.py``);
- checked against exact identities and invariances (area identities, commutativity,
  ``A x B = (A u B) - (A n B)``, ``A u {} = A``, exact similarity transforms);
- compared with GEOS 3.13 (OverlayNG) on small-integer lattices, where every difference
  must fall into an explained class (never ``UNEXPLAINED``).

The cases: every hand-built fixture, the whole seed corpus, the oracle-review families
(``gen_review.py all 50 1``) and seeded random cases of every type pair (lattice,
adversarial derived configurations, exact affine images, ulp-level near-degeneracies,
dense and stacked inputs, the exhaustive 3x3 grid). The GEOS findings are pinned below
with minimal inputs.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

import pytest

from geotruth.io import canonicalize, geometry_to_json, read_wkt
from geotruth.overlay import OPS, overlay, overlay_all

pytestmark = pytest.mark.crosscheck

REPO = Path(__file__).resolve().parents[2]


def _load_tool():
    name = "crosscheck_overlay"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / "crosscheck_overlay.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


X = _load_tool()
R = X.R  # the relate tool: case generators


def _shapely():
    return pytest.importorskip("shapely")


def geos_313() -> bool:
    try:
        import shapely
    except ImportError:
        return False
    return shapely.geos_version == (3, 13, 1)


def check_all(cases, *, use_geos: bool = True, properties: bool = True):
    reports = X.run(list(cases), use_geos=use_geos, properties=properties)
    failures = [(r.id, r.wkt, r.problems) for r in reports if r.failed]
    assert failures == []
    for r in reports:
        assert r.status == "ok" and r.results == 8 and r.certified == 8, r.id
        assert r.validity_agree
        assert all(v != "UNEXPLAINED" for v in r.geos.values())
    return reports


# ============================================================================ sources


def test_fixtures():
    reports = check_all(R.fixture_cases())
    assert len(reports) == 12
    assert sum(r.oracle_agree is True for r in reports) == 6
    assert all(r.identities for r in reports)


@pytest.mark.parametrize("chunk", range(4))
def test_seed_corpus(chunk):
    """All 1000 seed cases: certified, exact areas equal to oracle.py and indep.py, valid
    output; the identities on a quarter of them."""
    cases = list(R.seed_cases())[chunk::4]
    props = [c for i, c in enumerate(cases) if i % 4 == 0]
    rest = [c for i, c in enumerate(cases) if i % 4 != 0]
    reports = check_all(props, use_geos=False) + check_all(rest, use_geos=False, properties=False)
    assert len(reports) == 250
    assert all(r.oracle_agree and r.indep_agree for r in reports)


def test_review_families():
    _shapely()  # the generator uses Shapely
    cases = list(R.review_cases(50, 1))
    props = [c for i, c in enumerate(cases) if i % 3 == 0]
    rest = [c for i, c in enumerate(cases) if i % 3 != 0]
    reports = check_all(props, use_geos=False) + check_all(rest, use_geos=False, properties=False)
    assert len(reports) == 395
    assert all(r.oracle_agree and r.indep_agree for r in reports)
    assert sum(r.transform_agree is True for r in reports) > 100


@pytest.mark.parametrize("seed", [1, 2])
def test_lattice(seed):
    reports = check_all(R.lattice_cases(400, seed))
    kinds = Counter(k for r in reports for k in r.kinds.values())
    assert {"GeometryCollection", "Polygon", "LineString", "Point", "MultiPolygon"} <= set(kinds)
    if X.R._shapely() is not None:
        assert sum(len(r.geos) for r in reports) > 1000


@pytest.mark.parametrize("seed", [1, 2])
def test_adversarial(seed):
    check_all(R.adversarial_cases(400, seed))


def test_exhaustive_grid_sample():
    check_all(R.exhaustive_cases(1200), properties=False)


def test_transformed():
    check_all(R.transformed_cases(150, 3))


def test_ulp():
    check_all(R.ulp_cases(60, 4), use_geos=False)


def test_dense():
    check_all(R.dense_cases(90, 5))


def test_all_type_pairs_are_covered():
    reports = X.run(
        list(R.lattice_cases(320, 9)) + list(R.adversarial_cases(200, 9)),
        use_geos=False,
        properties=False,
    )
    assert not any(r.failed for r in reports)
    pairs = {r.types for r in reports}
    assert len(pairs) == 49


# ============================================================================ GEOS findings

#: GEOS 3.13.1 GeometryCollection overlay (GEOS's heuristic for GC operands) against the
#: exact answer: (A, B, op, GEOS's result, the exact result). OverlayNG proper (JTS)
#: rejects such mixed GCs.
GEOS_GC_OVERLAY = [
    # symdifference with a GC operand drops the lower-dimensional parts of the result
    ("GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
     "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)))", "POINT (5 5)", "symdifference",
     "POLYGON ((0 0, 0 2, 1 2, 1 3, 3 3, 3 1, 2 1, 2 0, 0 0))",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 1, 3 1, 3 3, 1 3, 1 2, 0 2, 0 0)), "
     "POINT (5 5))"),
    ("GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POINT (5 5))", "POINT (6 6)",
     "symdifference", "GEOMETRYCOLLECTION (POINT (5 5), POLYGON ((0 2, 2 2, 2 0, 0 0, 0 2)))",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POINT (5 5), POINT (6 6))"),
    # difference ignores the lines of a GC operand when removing points
    ("POINT (2 3)", "GEOMETRYCOLLECTION (LINESTRING (2 0, 2 4), POINT (9 9))", "difference",
     "POINT (2 3)", "POINT EMPTY"),
    ("MULTIPOINT ((4 1), (0 2))", "GEOMETRYCOLLECTION (POINT (3 0), LINESTRING (4 2, 4 1))",
     "difference", "MULTIPOINT ((0 2), (4 1))", "POINT (0 2)"),
    # an empty polygon element: the symmetric difference loses the point
    ("GEOMETRYCOLLECTION (POLYGON EMPTY)", "POINT (1 1)", "symdifference", "POINT EMPTY",
     "POINT (1 1)"),
]  # fmt: skip

#: GEOS raises "AssertionFailedException: Should never reach here: Unable to determine
#: overlay result geometry dimension" for these (exact result given).
GEOS_GC_EMPTY_ASSERTION = [
    ("GEOMETRYCOLLECTION (POLYGON EMPTY)", "POINT (1 1)", "intersection", "POINT EMPTY"),
    ("GEOMETRYCOLLECTION (POINT (0 2), LINESTRING (0 0, 6 0))", "MULTIPOLYGON EMPTY",
     "intersection", "LINESTRING EMPTY"),
]  # fmt: skip

#: Same point set, other structure: GEOS's result, the verdict class of the tool.
GEOS_STRUCTURE = [
    # OverlayMixedPoints copies the other operand as it is: repeated points survive ...
    ("MULTIPOINT ((4 4), (4 4))", "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))", "union",
     "GEOMETRYCOLLECTION (POINT (4 4), POINT (4 4), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))",
     "same-point-set (duplicate-points)"),
    # ... and so do retraced lines and collinear input vertices
    ("LINESTRING (3 2, 3 0, 3 2)", "POINT (1 2)", "union",
     "GEOMETRYCOLLECTION (LINESTRING (3 2, 3 0, 3 2), POINT (1 2))",
     "same-point-set (unnoded-lines)"),
    ("POLYGON ((0 0, 2 0, 2 2, 1 2, 0 2, 0 0))", "POINT (5 5)", "union",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 1 2, 0 2, 0 0)), POINT (5 5))",
     "same-point-set (collinear-vertices)"),
    # the disjoint-envelope shortcut does not node a self-crossing input line
    ("LINESTRING (1 3, 4 4, 1 2, 3 4)", "LINESTRING (4 1, 2 1)", "union",
     "MULTILINESTRING ((1 3, 4 4, 1 2, 3 4), (4 1, 2 1))", "same-point-set (nodes)"),
    # a rounded node lands exactly on A's segment: a different node, the same point set
    ("LINESTRING (0 1, 4 0, 4 2, 4 1)", "LINESTRING (0 3, 1 1, 1 4, 2 0)", "difference",
     "MULTILINESTRING ((0 1, 1.8666666666666667 0.5333333333333333), "
     "(1.8666666666666667 0.5333333333333333, 4 0, 4 1), (4 1, 4 2))",
     "same-point-set (nodes)"),
    # a rounded line end overshoots into the polygon: a covered sliver, the same point set
    ("GEOMETRYCOLLECTION (POLYGON ((0 1, 1 1, 2 2, 0 1)), POLYGON ((1 0, 1 1, 2 2, 1 0)))",
     "LINESTRING (0 2, 1 0)", "union",
     "GEOMETRYCOLLECTION (LINESTRING (0 2, 0.4 1.2), LINESTRING (0.5 1, 1 0), "
     "POLYGON ((0 1, 2 2, 1 0, 1 1, 0 1)))", "same-point-set (covered-parts)"),
]  # fmt: skip


def _geos_result(a: str, b: str, op: str):
    shapely = _shapely()
    return getattr(shapely, X.SHAPELY_OPS[op])(shapely.from_wkt(a), shapely.from_wkt(b))


@pytest.mark.parametrize(("a", "b", "op", "geos_wkt", "exact_wkt"), GEOS_GC_OVERLAY)
def test_geos_gc_overlay_findings(a, b, op, geos_wkt, exact_wkt):
    ga, gb = read_wkt(a), read_wkt(b)
    ours = overlay(ga, gb, op, certify=True, strict=True)
    assert geometry_to_json(ours.geometry, exact=True) == geometry_to_json(
        canonicalize(read_wkt(exact_wkt)), exact=True
    )
    theirs = read_wkt(geos_wkt)
    verdict, _ = X.geos_verdict(ga, gb, op, ours.geometry, theirs)
    assert verdict.startswith("gc-overlay")
    if geos_313():
        assert _geos_result(a, b, op).equals_exact(_shapely().from_wkt(geos_wkt), 0)


@pytest.mark.parametrize(("a", "b", "op", "exact_wkt"), GEOS_GC_EMPTY_ASSERTION)
def test_geos_gc_empty_assertion(a, b, op, exact_wkt):
    ours = overlay(read_wkt(a), read_wkt(b), op, certify=True, strict=True)
    assert ours.wkt == exact_wkt
    if geos_313():
        with pytest.raises(Exception, match="Unable to determine overlay result"):
            _geos_result(a, b, op)


@pytest.mark.parametrize(("a", "b", "op", "geos_wkt", "verdict"), GEOS_STRUCTURE)
def test_geos_structure_findings(a, b, op, geos_wkt, verdict):
    ga, gb = read_wkt(a), read_wkt(b)
    ours = overlay(ga, gb, op, certify=True, strict=True)
    assert X.geos_verdict(ga, gb, op, ours.geometry, read_wkt(geos_wkt))[0] == verdict
    if geos_313():
        assert _geos_result(a, b, op).equals_exact(_shapely().from_wkt(geos_wkt), 0)


def test_geos_output_is_transferred_exactly():
    """The GEOS worker returns the doubles themselves (JSON repr), not Shapely's WKT,
    which drops digits: here GEOS's node x = 5/11 is the correctly rounded double
    0.45454545454545453, which Shapely's ``.wkt`` prints as 0.4545454545454545."""
    lines = read_wkt("MULTILINESTRING ((1 11, 0 1, 2 2), (4 12, 5 9, 8 4), (1 4, 3 9, 12 11, 7 2))")
    gc = read_wkt(
        "GEOMETRYCOLLECTION (POLYGON ((8 7, 8 11, 2 8, 0 8, 5 0, 8 7), "
        "(7 7, 5 3, 3 5, 3 6, 7 7)), POLYGON ((11 8, 5 1, 0 6, 1 9, 11 8)))"
    )
    ours = overlay(lines, gc, "union", certify=True, strict=True)
    assert "LINESTRING (0.45454545454545453 5.545454545454546, 0 1, 2 2)" in ours.wkt
    if geos_313():
        theirs = X.geos().overlays(lines, gc)["union"]
        assert "LINESTRING (0.45454545454545453 5.545454545454546, 0 1, 2 2)" in X.to_wkt(theirs)
        shapely = _shapely()
        shown = shapely.union(shapely.from_wkt(X.to_wkt(lines)), shapely.from_wkt(X.to_wkt(gc)))
        assert "0.4545454545454545 5.545454545454546" in shown.wkt
        # GEOS does not node its polygon where the lines end on it (the GC heuristic)
        verdict = X.geos_verdict(lines, gc, "union", ours.geometry, theirs)[0]
        assert verdict == "rounding (same parts)"


# ============================================================================ the tool


def test_geos_worker_survives_errors():
    if X.R._shapely() is None:
        pytest.skip("Shapely is not installed")
    res = X.geos().overlays(read_wkt("GEOMETRYCOLLECTION (POLYGON EMPTY)"), read_wkt("POINT (1 1)"))
    assert isinstance(res["intersection"], str) and "Unable to determine" in res["intersection"]
    assert res["union"].geom_type == "Point"


def test_tool_command_line(tmp_path, capsys):
    out = tmp_path / "report.json"
    status = X.main(["--sources", "fixtures", "--json", str(out)])
    assert status == 0
    summary = json.loads(out.read_text())
    assert summary["total"]["cases"] == 12 and summary["total"]["failed"] == 0
    assert summary["total"]["certified"] == 96
    assert "certified" in capsys.readouterr().out


def test_tool_catches_a_broken_overlay(monkeypatch):
    """A wrong selection rule must be caught (by the certificate and the references)."""
    import geotruth.overlay as O

    real = O.select

    def broken(op, a, b):
        return real("union" if op == "intersection" else op, a, b)

    monkeypatch.setattr(O, "select", broken)
    reports = X.run(list(R.fixture_cases()), use_geos=False, properties=False)
    assert any(r.failed for r in reports)
    text = " ".join(p for r in reports for p in r.problems)
    assert "certificate of intersection" in text and "oracle.py" in text


def test_tool_catches_a_broken_assembly(monkeypatch):
    """A result vertex moved by one unit breaks the point set: caught."""
    import geotruth.overlay as O

    real = O._Overlay.xy

    def shifted(self, v):
        x, y = real(self, v)
        return (x + 1, y) if v == 0 else (x, y)

    monkeypatch.setattr(O._Overlay, "xy", shifted)
    reports = X.run(list(R.fixture_cases()), use_geos=False, properties=False)
    assert any(r.failed for r in reports)


def test_engine_answers_every_op_from_one_arrangement():
    a, b = read_wkt("POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"), read_wkt("POINT (1 1)")
    res = overlay_all(a, b, certify=True)
    assert all(res[op][v].certificate.ok for op in OPS for v in ("non_strict", "areal"))
