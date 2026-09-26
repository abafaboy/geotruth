"""Unit tests of the overlay certificate (DESIGN §2.6, :mod:`geotruth.overlay_certify`).

The certificate must accept every correct result and reject wrong ones: wrong point sets
(missing or extra faces, edges, points), wrong boundaries, and -- with ``structure`` --
results that are not in canonical form (invalid polygons, covered or overlapping parts,
repeated points, the wrong type or typed empty, non-canonical order).
"""

from __future__ import annotations

import os
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from geotruth.geom import GeometryCollection, LineString, Point, Polygon
from geotruth.io import read_wkt
from geotruth.overlay import OPS, VARIANTS, overlay_all
from geotruth.overlay_certify import (
    Certificate,
    CertificateError,
    Mismatch,
    certify,
    certify_many,
)

SQ = "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"
SQ2 = "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))"
RIGHT = "POLYGON ((2 0, 4 0, 4 2, 2 2, 2 0))"
X1, X2 = "LINESTRING (0 0, 2 0)", "LINESTRING (1 -1, 1 1)"


def W(text: str):
    return read_wkt(text)


def cert(a: str, b: str, op: str, r: str, variant: str = "non_strict", **kw) -> Certificate:
    return certify(W(a), W(b), op, W(r), variant, **kw)


# ============================================================ correct results

CORRECT = [
    (SQ, SQ2, "intersection", "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))", "non_strict"),
    (SQ, SQ2, "union", "POLYGON ((0 0, 2 0, 2 1, 3 1, 3 3, 1 3, 1 2, 0 2, 0 0))", "areal"),
    (SQ, RIGHT, "intersection", "LINESTRING (2 0, 2 2)", "non_strict"),
    (SQ, RIGHT, "intersection", "POLYGON EMPTY", "areal"),
    (X1, X2, "difference", "MULTILINESTRING ((0 0, 1 0), (1 0, 2 0))", "non_strict"),
    (X1, X2, "intersection", "POINT (1 0)", "non_strict"),
    (X1, X2, "symdifference",
     "MULTILINESTRING ((0 0, 1 0), (1 -1, 1 0), (1 0, 1 1), (1 0, 2 0))", "non_strict"),
    (SQ, "POINT (3 3)", "union", f"GEOMETRYCOLLECTION ({SQ}, POINT (3 3))", "non_strict"),
    (SQ, "POINT (1 1)", "union", SQ, "non_strict"),
    ("POINT EMPTY", "POLYGON EMPTY", "union", "POLYGON EMPTY", "non_strict"),
    ("GEOMETRYCOLLECTION EMPTY", "POINT (1 1)", "intersection", "GEOMETRYCOLLECTION EMPTY",
     "non_strict"),
    ("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))", "POLYGON ((0 2, 2 1, 2 3, 0 2))", "difference",
     "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 2, 0 0), (0 2, 2 3, 2 1, 0 2))", "areal"),
]  # fmt: skip


@pytest.mark.parametrize(("a", "b", "op", "r", "variant"), CORRECT)
def test_correct_results_are_certified(a, b, op, r, variant):
    c = cert(a, b, op, r, variant)
    assert c.ok, c.summary()
    assert c.summary().startswith("ok (") and c.witnesses == sum(c.counts.values()) > 0
    assert c.to_json()["ok"] is True and c.to_json()["problems"] == []
    c.raise_if_failed()


def test_every_engine_result_is_certified():
    a, b = W(SQ), W("LINESTRING (-1 1, 3 1)")
    res = overlay_all(a, b)
    items = [(op, v, res[op][v].geometry) for op in OPS for v in VARIANTS]
    certs = certify_many(a, b, items)
    assert [(c.op, c.variant) for c in certs] == [(op, v) for op, v, _ in items]
    assert all(c.ok for c in certs)


# ============================================================ wrong point sets

WRONG = [
    # a missing corner triangle (area too small)
    (SQ, SQ2, "intersection", "POLYGON ((1 1, 2 1, 2 2, 1 1))", "face"),
    # the result of another operation
    (SQ, SQ2, "intersection", "POLYGON ((0 0, 2 0, 2 1, 3 1, 3 3, 1 3, 1 2, 0 2, 0 0))", "face"),
    (SQ, SQ2, "difference", "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))", "face"),
    # a boundary touch dropped from the non-strict intersection
    (SQ, RIGHT, "intersection", "POLYGON EMPTY", "edge"),
    (SQ, RIGHT, "intersection", "LINESTRING (2 0, 2 1)", "edge"),
    # a crossing point dropped / added
    (X1, X2, "intersection", "POINT EMPTY", "vertex"),
    (X1, X2, "difference", "LINESTRING (0 0, 1 0)", "edge"),
    # a spurious point outside everything
    (X1, X2, "intersection", "MULTIPOINT ((1 0), (5 5))", "vertex"),
    # a line where the areal variant has none
    (SQ, RIGHT, "intersection", "LINESTRING (2 0, 2 2)", "edge"),
    # a hole that is not there
    (SQ, "POINT (1 1)", "difference",
     "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0), (0.5 0.5, 0.5 1.5, 1.5 1.5, 0.5 0.5))", "face"),
]  # fmt: skip


@pytest.mark.parametrize(("a", "b", "op", "r", "kind"), WRONG)
def test_wrong_point_sets_are_rejected(a, b, op, r, kind):
    variant = "areal" if (a, b, r) == (SQ, RIGHT, "LINESTRING (2 0, 2 2)") else "non_strict"
    for structure in (True, False):
        c = cert(a, b, op, r, variant, structure=structure)
        assert not c.ok
        assert c.num_mismatches > 0 or c.problems
        assert any(m.cell == kind for m in c.mismatches) or c.problems, c.summary()
    with pytest.raises(CertificateError, match="overlay certificate failed"):
        c.raise_if_failed()


def test_mismatch_reports_exact_locations():
    c = cert(SQ, SQ2, "intersection", "POLYGON ((1 1, 2 1, 2 2, 1 1))")
    m = c.mismatches[0]
    assert isinstance(m, Mismatch)
    assert all(isinstance(v, Fraction) for v in m.point)
    text = str(m)
    assert "in A" in text and "R must give" in text
    assert c.to_json()["mismatches"] == c.num_mismatches >= len(c.mismatches)


def test_max_problems_caps_the_list_not_the_count():
    c = certify(W(SQ), W(SQ2), "union", W("POINT (9 9)"), max_problems=2)
    assert len(c.mismatches) == 2 and c.num_mismatches > 2
    assert "more)" in c.summary()


def test_boundary_parity_of_lines():
    """The same point set with the wrong Mod-2 boundary: a closed loop where the exact
    result is an open line (the loop would have no boundary at its ends)."""
    a, b = "LINESTRING (0 0, 2 0, 2 2)", "POINT (9 9)"
    good = "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0, 2 2), POINT (9 9))"
    assert cert(a, b, "union", good).ok
    # the line doubled back: the same points, but (2 2) is no longer an endpoint
    bad = "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0, 2 2, 2 0), POINT (9 9))"
    c = cert(a, b, "union", bad)
    assert not c.ok
    assert any(m.cell == "vertex" and m.expected == "B" and m.got == "I" for m in c.mismatches)
    # without structure only the point set is checked, and it is right
    assert cert(a, b, "union", bad, structure=False).ok
    assert cert(a, b, "union", good, structure=False).ok


# ============================================================ structure

STRUCTURE = [
    # two polygons sharing an edge instead of their union
    (SQ, RIGHT, "union", "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((2 0, 4 0, 4 2, 2 2, 2 0)))",
     "invalid"),
    # a self-touching (inverted) shell instead of a shell and a touching hole
    ("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))", "POLYGON ((0 2, 2 1, 2 3, 0 2))", "difference",
     "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 2, 2 3, 2 1, 0 2, 0 0))", "invalid"),
    # a covered point and a covered line
    (SQ, "POINT (1 1)", "union", f"GEOMETRYCOLLECTION ({SQ}, POINT (1 1))", "covered"),
    (SQ, "LINESTRING (2 0, 2 2)", "union", f"GEOMETRYCOLLECTION ({SQ}, LINESTRING (2 0, 2 2))",
     "lies on or in"),
    # overlapping lines, a repeated point
    (X1, X2, "union", "MULTILINESTRING ((0 0, 2 0), (0 0, 1 0), (1 -1, 1 1))", "overlap"),
    (X1, X2, "intersection", "MULTIPOINT ((1 0), (1 0))", "repeats"),
    # the typed empty
    (SQ, RIGHT, "intersection", "LINESTRING EMPTY", "empty result must be"),
    ("POINT (0 0)", "POINT (1 1)", "intersection", "GEOMETRYCOLLECTION EMPTY",
     "empty result must be"),
    ("POINT (0 0)", "POINT (1 1)", "intersection", "MULTIPOINT EMPTY", "empty result must be"),
    # a less specific type, a nested collection, an empty part
    (SQ, SQ2, "intersection", "MULTIPOLYGON (((1 1, 2 1, 2 2, 1 2, 1 1)))", "parts make"),
    (SQ, "POINT (3 3)", "union",
     "GEOMETRYCOLLECTION (MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0))), POINT (3 3))", "nests"),
    (SQ, SQ2, "intersection", "MULTIPOLYGON (((1 1, 2 1, 2 2, 1 2, 1 1)), EMPTY)", "empty parts"),
    # order
    (SQ, "POINT (3 3)", "union", f"GEOMETRYCOLLECTION (POINT (3 3), {SQ})", "canonical order"),
    (SQ, SQ2, "intersection", "POLYGON ((2 2, 1 2, 1 1, 2 1, 2 2))", "canonical order"),
]  # fmt: skip


@pytest.mark.parametrize(("a", "b", "op", "r", "fragment"), STRUCTURE)
def test_non_canonical_results_are_rejected_only_with_structure(a, b, op, r, fragment):
    c = cert(a, b, op, r)
    assert not c.ok and any(fragment in p for p in c.problems), c.summary()
    if fragment not in ("empty result must be", "repeats", "overlap"):
        assert cert(a, b, op, r, structure=False).ok, "the point set itself is right"


def test_areal_variant_must_be_polygonal():
    c = cert(SQ, "LINESTRING (-1 1, 3 1)", "union",
             "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 1, 2 2, 0 2, 0 1, 0 0)), "
             "LINESTRING (-1 1, 0 1), LINESTRING (2 1, 3 1))", "areal")  # fmt: skip
    assert not c.ok


def test_zero_length_result_line():
    c = certify(W(X1), W(X2), "intersection", LineString([(1.0, 0.0), (1.0, 0.0)]))
    assert not c.ok and any("zero length" in p for p in c.problems)


def test_alternative_structures_of_the_same_point_set():
    """Other valid representations (unsplit lines, extra collinear vertices) have the
    right point set and boundary; the certificate does not prescribe nodes."""
    assert cert(X1, X2, "difference", "LINESTRING (0 0, 2 0)").ok
    assert cert(SQ, RIGHT, "union", "POLYGON ((0 0, 4 0, 4 2, 0 2, 0 0))").ok
    assert cert(SQ, RIGHT, "union", "POLYGON ((0 0, 1 0, 2 0, 4 0, 4 2, 2 2, 0 2, 0 0))").ok


def test_library_output_with_doubles_and_rationals():
    """A result given with doubles (a library's) or rationals (the engine's) certifies
    the same way; the frame covers non-dyadic coordinates."""
    a, b = W("LINESTRING (0 0, 3 1)"), W("LINESTRING (0 1, 2 0)")
    assert certify(a, b, "intersection", Point((Fraction(6, 5), Fraction(2, 5)))).ok
    rounded = certify(a, b, "intersection", Point((1.2, 0.4)))
    assert not rounded.ok  # the double is not the crossing point
    tri = Polygon([[(0.0, 0.0), (Fraction(1, 3), 0.0), (0.0, Fraction(1, 3)), (0.0, 0.0)]])
    assert certify(tri, W("POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"), "intersection", tri).ok


def test_unreadable_results_fail_cleanly():
    c = certify(W(SQ), W(SQ2), "union", Point((float("nan"), 0.0)))
    assert not c.ok and "cannot refine" in c.problems[0]
    with pytest.raises(ValueError, match="unknown overlay operation"):
        certify(W(SQ), W(SQ2), "clip", W(SQ))
    with pytest.raises(ValueError, match="unknown overlay variant"):
        certify(W(SQ), W(SQ2), "union", W(SQ), "strict")
    assert certify_many(W(SQ), W(SQ2), []) == []


def test_aliases():
    assert certify(W(X1), W(X2), "symmetric_difference",
                   W("MULTILINESTRING ((0 0, 1 0), (1 -1, 1 0), (1 0, 1 1), (1 0, 2 0))"),
                   "non-strict").ok  # fmt: skip


def test_empty_operands_and_results():
    e = GeometryCollection()
    assert certify(e, e, "union", e).ok
    assert certify(W("POINT (1 1)"), e, "union", W("POINT (1 1)")).ok
    assert not certify(W("POINT (1 1)"), e, "union", W("POINT EMPTY")).ok


def test_certificate_is_independent_of_the_overlay_builder():
    """overlay_certify shares only the §2.1 primitives and the point locator with the
    engine: it never imports the arrangement or the overlay builder."""
    code = (
        "import sys; import geotruth.overlay_certify as c; "
        "from geotruth.io import read_wkt as W; "
        "assert c.certify(W('POINT (0 0)'), W('POINT (1 1)'), 'union', "
        "W('MULTIPOINT ((0 0), (1 1))')).ok; "
        "bad = [m for m in ('geotruth.arrangement', 'geotruth.overlay', 'geotruth.relate', "
        "'geotruth.relate_witness') if m in sys.modules]; print(bad)"
    )
    src = Path(__file__).resolve().parents[2] / "src"
    env = {**os.environ, "PYTHONPATH": str(src)}
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env
    ).stdout.strip()
    assert out == "[]"
