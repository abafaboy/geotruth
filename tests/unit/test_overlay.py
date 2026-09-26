"""Unit tests of the exact overlay (DESIGN §1 "Overlay", §2.5).

Every overlay computed here is also checked by the independent certificate
(:mod:`geotruth.overlay_certify`, DESIGN §2.6): :func:`run` certifies all four operations
in both variants. Expected shapes marked "GEOS" were checked against GEOS 3.13.1 /
OverlayNG during development (the exact result keeps GEOS's nodes but drops collinear
input vertices that are not nodes).
"""

from __future__ import annotations

import math
import random
from fractions import Fraction

import pytest

import geotruth.overlay as O
from geotruth.arrangement import Budget, InvalidInputError, build_arrangement
from geotruth.geom import (
    GeometryCollection,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
)
from geotruth.io import canonicalize, geometry_from_json, geometry_to_json, read_wkt, to_wkt
from geotruth.measures import area as shoelace_area
from geotruth.numbers import use_backend
from geotruth.overlay import (
    OPS,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_SKIPPED,
    VARIANTS,
    OverlayAssertionError,
    normalize_op,
    normalize_variant,
    num_vertices,
    overlay,
    overlay_all,
    overlay_arrangement,
    result_dimension,
    select,
)
from geotruth.overlay_certify import certify_many
from unit.arrangement_testlib import random_operand
from unit.fixtures_arrangement import FIXTURES, fixture

SQ = "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"
EMPTY = GeometryCollection()


def W(text: str):
    return read_wkt(text)


def ej(g) -> dict:
    return geometry_to_json(g, exact=True)


def run(a, b, **kw):
    """overlay_all with every result certified; returns the results."""
    a = W(a) if isinstance(a, str) else a
    b = W(b) if isinstance(b, str) else b
    res = overlay_all(a, b, certify=True, strict=True, **kw)
    for per in res.values():
        for r in per.values():
            assert r.ok, r.reason
            assert r.certificate is not None and r.certificate.ok, r.certificate.summary()
    return res


def same(g, wkt: str) -> bool:
    """Exact equality with the canonical form of a WKT geometry."""
    return ej(g) == ej(canonicalize(W(wkt)))


# ============================================================ semantics helpers


def test_selection_table():
    table = {
        "intersection": (True, False, False, False),
        "union": (True, True, True, False),
        "difference": (False, True, False, False),
        "symdifference": (False, True, True, False),
    }
    cells = ((True, True), (True, False), (False, True), (False, False))
    for op, want in table.items():
        assert tuple(select(op, a, b) for a, b in cells) == want
    with pytest.raises(ValueError, match="unknown"):
        select("xor-ish", True, True)


def test_result_dimension_is_overlayutil():
    assert result_dimension("intersection", 2, 1) == 1
    assert result_dimension("union", 0, 1) == 1
    assert result_dimension("difference", 0, 2) == 0
    assert result_dimension("symdifference", 1, 2) == 2
    assert result_dimension("intersection", -1, 0) == -1


def test_names_and_aliases():
    assert normalize_op("Symmetric_Difference") == "symdifference"
    assert normalize_op("sym-difference") == "symdifference"
    assert normalize_op("xor") == "symdifference"
    assert normalize_op("intersect") == "intersection"
    assert normalize_variant("non-strict") == "non_strict"
    assert normalize_variant("regularized") == "areal"
    with pytest.raises(ValueError, match="unknown overlay operation"):
        normalize_op("clip")
    with pytest.raises(ValueError, match="unknown overlay variant"):
        normalize_variant("strict")
    assert OPS == ("intersection", "union", "difference", "symdifference")
    assert VARIANTS == ("non_strict", "areal")


# ============================================================ hand cases

# (A, B, op, non-strict result, areal result or None for "the typed empty")
HAND = [
    # lines: split at nodes, collinear non-node vertices removed (GEOS)
    ("LINESTRING (0 0, 2 0)", "LINESTRING (1 -1, 1 1)", "difference",
     "MULTILINESTRING ((0 0, 1 0), (1 0, 2 0))", None),
    ("LINESTRING (0 0, 1 0)", "LINESTRING (1 0, 2 0)", "union",
     "MULTILINESTRING ((0 0, 1 0), (1 0, 2 0))", None),
    ("LINESTRING (0 0, 1 0, 2 0)", "POLYGON ((-1 -1, 3 -1, 3 1, -1 1, -1 -1))", "intersection",
     "LINESTRING (0 0, 2 0)", None),
    ("MULTILINESTRING ((0 0, 1 0), (1 0, 2 0))", "POLYGON ((-1 -1, 3 -1, 3 1, -1 1, -1 -1))",
     "intersection", "MULTILINESTRING ((0 0, 1 0), (1 0, 2 0))", None),
    ("LINESTRING (0 0, 1 0, 2 0)", "LINESTRING (1 0, 1 1)", "union",
     "MULTILINESTRING ((0 0, 1 0), (1 0, 2 0), (1 0, 1 1))", None),
    ("LINESTRING (0 0, 2 0)", "LINESTRING (1 0, 3 0)", "difference", "LINESTRING (0 0, 1 0)", None),
    ("LINESTRING (0 0, 2 0)", "LINESTRING (0 0, 2 0)", "symdifference", "LINESTRING EMPTY", None),
    ("LINESTRING (0 0, 1 0, 2 0)", "POINT (1 0)", "difference", "LINESTRING (0 0, 2 0)", None),
    # polygons (GEOS shapes)
    ("POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))", "POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0))", "union",
     "POLYGON ((0 0, 1 0, 2 0, 2 1, 1 1, 0 1, 0 0))",
     "POLYGON ((0 0, 1 0, 2 0, 2 1, 1 1, 0 1, 0 0))"),
    ("POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))", "POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0))", "intersection",
     "LINESTRING (1 0, 1 1)", None),
    ("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))", "POLYGON ((4 0, 6 0, 6 4, 4 4, 4 0))",
     "symdifference", "POLYGON ((0 0, 4 0, 6 0, 6 4, 4 4, 0 4, 0 0))",
     "POLYGON ((0 0, 4 0, 6 0, 6 4, 4 4, 0 4, 0 0))"),
    (SQ, "POLYGON ((2 2, 4 2, 4 4, 2 4, 2 2))", "union",
     "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((2 2, 4 2, 4 4, 2 4, 2 2)))",
     "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((2 2, 4 2, 4 4, 2 4, 2 2)))"),
    (SQ, "POLYGON ((2 2, 4 2, 4 4, 2 4, 2 2))", "intersection", "POINT (2 2)", None),
    (SQ, "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))", "symdifference",
     "MULTIPOLYGON (((0 0, 2 0, 2 1, 1 1, 1 2, 0 2, 0 0)), ((1 2, 2 2, 2 1, 3 1, 3 3, 1 3, 1 2)))",
     "MULTIPOLYGON (((0 0, 2 0, 2 1, 1 1, 1 2, 0 2, 0 0)), ((1 2, 2 2, 2 1, 3 1, 3 3, 1 3, 1 2)))"),
    # polygon and line / point (GEOS)
    (SQ, "LINESTRING (-1 1, 3 1)", "union",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 1, 2 2, 0 2, 0 1, 0 0)), "
     "LINESTRING (-1 1, 0 1), LINESTRING (2 1, 3 1))",
     "POLYGON ((0 0, 2 0, 2 1, 2 2, 0 2, 0 1, 0 0))"),
    (SQ, "LINESTRING (-1 1, 3 1)", "difference",
     "POLYGON ((0 0, 2 0, 2 1, 2 2, 0 2, 0 1, 0 0))",
     "POLYGON ((0 0, 2 0, 2 1, 2 2, 0 2, 0 1, 0 0))"),
    (SQ, "LINESTRING (-1 1, 3 1)", "intersection", "LINESTRING (0 1, 2 1)", None),
    (SQ, "POINT (1 1)", "symdifference", SQ, SQ),
    (SQ, "POINT (3 3)", "union", f"GEOMETRYCOLLECTION ({SQ}, POINT (3 3))", SQ),
    (SQ, "POINT (2 1)", "difference", SQ, SQ),
    # boundary touches in the non-strict intersection (GEOS)
    ("POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))",
     "MULTIPOLYGON (((1 1, 2 1, 2 2, 1 2, 1 1)), ((3 0, 4 0, 4 1, 3 1, 3 0)), "
     "((3 3, 4 3, 4 4, 3 4, 3 3)), ((0 3, 0 5, -1 5, -1 3, 0 3)))", "intersection",
     "GEOMETRYCOLLECTION (POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)), LINESTRING (3 0, 3 1), "
     "POINT (0 3), POINT (3 3))",
     "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))"),
    # a hole filled exactly: the intersection is the hole's boundary, noded at every vertex
    ("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 3 1, 3 3, 1 3, 1 1))",
     "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))", "intersection",
     "MULTILINESTRING ((1 1, 3 1), (3 1, 3 3), (3 3, 1 3), (1 3, 1 1))", None),
    # a pinch: a shell plus a hole touching it at (0 2) (GEOS)
    ("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))", "POLYGON ((0 2, 2 1, 2 3, 0 2))", "difference",
     "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 2, 0 0), (0 2, 2 3, 2 1, 0 2))",
     "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 2, 0 0), (0 2, 2 3, 2 1, 0 2))"),
    # faces touching only at vertices stay separate polygons (GEOS)
    ("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))", "POLYGON ((1 0, 2 1, 3 0, 4 4, 0 4, 1 0))",
     "difference",
     "MULTIPOLYGON (((0 0, 1 0, 0 4, 0 0)), ((1 0, 3 0, 2 1, 1 0)), ((3 0, 4 0, 4 4, 3 0)))",
     "MULTIPOLYGON (((0 0, 1 0, 0 4, 0 0)), ((1 0, 3 0, 2 1, 1 0)), ((3 0, 4 0, 4 4, 3 0)))"),
    # two holes touching at a point
    ("POLYGON ((0 0, 6 0, 6 6, 0 6, 0 0))",
     "MULTIPOLYGON (((1 1, 3 1, 3 3, 1 1)), ((3 3, 5 3, 5 5, 3 3)))", "difference",
     "POLYGON ((0 0, 6 0, 6 6, 0 6, 0 0), (1 1, 3 3, 3 1, 1 1), (3 3, 5 5, 5 3, 3 3))",
     "POLYGON ((0 0, 6 0, 6 6, 0 6, 0 0), (1 1, 3 3, 3 1, 1 1), (3 3, 5 5, 5 3, 3 3))"),
    # the union of two L shapes encloses a hole that touches the shell nowhere but has
    # nodes where the Ls meet
    ("POLYGON ((0 0, 4 0, 4 1, 1 1, 1 3, 2 3, 2 4, 0 4, 0 0))",
     "POLYGON ((4 0, 4 4, 2 4, 2 3, 3 3, 3 1, 2 1, 4 0))", "union",
     "POLYGON ((0 0, 4 0, 4 1, 4 4, 2 4, 0 4, 0 0), (1 1, 1 3, 2 3, 3 3, 3 1, 2 1, 1 1))",
     "POLYGON ((0 0, 4 0, 4 1, 4 4, 2 4, 0 4, 0 0), (1 1, 1 3, 2 3, 3 3, 3 1, 2 1, 1 1))"),
    # an island in a hole, touching the hole's boundary at (2 5): a separate part
    ("POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 8 2, 8 8, 2 8, 2 2))",
     "POLYGON ((2 5, 5 3, 7 5, 5 7, 2 5))", "union",
     "MULTIPOLYGON (((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 2 5, 2 8, 8 8, 8 2, 2 2)), "
     "((2 5, 5 3, 7 5, 5 7, 2 5)))",
     "MULTIPOLYGON (((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 2 5, 2 8, 8 8, 8 2, 2 2)), "
     "((2 5, 5 3, 7 5, 5 7, 2 5)))"),
    # points
    ("MULTIPOINT ((0 0), (1 1))", "POINT (1 1)", "difference", "POINT (0 0)", None),
    ("MULTIPOINT ((0 0), (1 1))", "POINT (1 1)", "intersection", "POINT (1 1)", None),
    ("MULTIPOINT ((0 0), (1 1))", "POINT (1 1)", "union", "MULTIPOINT ((0 0), (1 1))", None),
    ("MULTIPOINT ((0 0), (1 1))", "MULTIPOINT ((1 1), (0 0))", "symdifference", "POINT EMPTY",
     None),
    ("MULTIPOINT ((4 4), (4 4))", SQ, "union", f"GEOMETRYCOLLECTION ({SQ}, POINT (4 4))", SQ),
    ("POINT (1 0)", "LINESTRING (0 0, 2 0)", "union", "LINESTRING (0 0, 2 0)", None),
    ("POINT (2 0)", "LINESTRING (0 0, 2 0)", "intersection", "POINT (2 0)", None),
    # a closed line's start is a node; a self-overlapping line is noded where it folds
    ("LINESTRING (0 0, 1 0, 1 1, 0 0)", "POINT (9 9)", "union",
     "GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0, 1 1, 0 0), POINT (9 9))", None),
    ("LINESTRING (0 0, 1 0, 2 0, 0 0)", "POINT (9 9)", "union",
     "GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), LINESTRING (1 0, 2 0), POINT (9 9))", None),
    # zero-length lines are points (RelateNG real dimension 0)
    ("LINESTRING (1 1, 1 1)", "POINT (5 5)", "union", "MULTIPOINT ((1 1), (5 5))", None),
    ("LINESTRING (1 1, 1 1)", SQ, "difference", "LINESTRING EMPTY", None),
    # GeometryCollections: union semantics; internal edges of the union make no nodes
    ("GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
     "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)))", "LINESTRING (-1 1.5, 4 1.5)", "intersection",
     "LINESTRING (0 1.5, 3 1.5)", None),
    ("GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
     "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)), POINT (1 1))", "POINT (9 9)", "union",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 1, 3 1, 3 3, 1 3, 1 2, 0 2, 0 0)), "
     "POINT (9 9))", "POLYGON ((0 0, 2 0, 2 1, 3 1, 3 3, 1 3, 1 2, 0 2, 0 0))"),
]  # fmt: skip


@pytest.mark.parametrize(("a", "b", "op", "want", "areal"), HAND)
def test_hand_cases(a, b, op, want, areal):
    res = run(a, b)
    got = res[op]["non_strict"].geometry
    assert same(got, want), f"{op}: got {to_wkt(got)}"
    ar = res[op]["areal"].geometry
    if areal is None:
        dim = result_dimension(op, W(a).dimension, W(b).dimension)
        assert ar.is_empty and ar.geom_type == O.empty_of_dimension(dim).geom_type
    else:
        assert same(ar, areal), f"{op} areal: got {to_wkt(ar)}"


def test_non_dyadic_result_is_exact():
    r = overlay(W("LINESTRING (0 0, 3 1)"), W("LINESTRING (0 1, 2 0)"), "intersection")
    assert r.geometry == Point((Fraction(6, 5), Fraction(2, 5)))
    assert r.exact == {"type": "Point", "coordinates": ["6/5", "2/5"]}
    assert r.wkt == "POINT (1.2 0.4)"


def test_every_ring_is_canonical_and_oriented():
    res = run("POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 8 2, 8 8, 2 8, 2 2))",
              "POLYGON ((3 3, 7 3, 7 7, 3 7, 3 3), (4 4, 6 4, 6 6, 4 6, 4 4))")  # fmt: skip
    g = res["union"]["non_strict"].geometry
    assert isinstance(g, MultiPolygon) and len(g.polygons) == 2
    for p in g.polygons:
        shell, *holes = p.rings
        assert shell[0] == min(shell)
        assert _area2(shell) > 0 and all(_area2(h) < 0 for h in holes)
    assert ej(canonicalize(g)) == ej(g)


def _area2(ring) -> Fraction:
    return sum(
        (Fraction(ring[i - 1][0]) * Fraction(ring[i][1]) - Fraction(ring[i][0]) * Fraction(ring[i - 1][1])
         for i in range(len(ring))), Fraction(0))  # fmt: skip


# ============================================================ typed empties


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("POLYGON EMPTY", "LINESTRING (0 0, 1 1)"),
        ("POINT EMPTY", "POLYGON EMPTY"),
        ("MULTIPOLYGON EMPTY", "LINESTRING EMPTY"),
        ("GEOMETRYCOLLECTION EMPTY", "POINT (1 1)"),
        ("GEOMETRYCOLLECTION EMPTY", "GEOMETRYCOLLECTION EMPTY"),
        ("GEOMETRYCOLLECTION (POLYGON EMPTY)", "POINT (1 1)"),
        ("LINESTRING (0 0, 1 1)", "POLYGON ((5 5, 6 5, 6 6, 5 5))"),
        ("POINT (0 0)", "POINT (1 1)"),
        (SQ, "POLYGON ((5 5, 6 5, 6 6, 5 5))"),
    ],
)
def test_typed_empties(a, b):
    ga, gb = W(a), W(b)
    res = run(ga, gb)
    for op in OPS:
        for v in VARIANTS:
            g = res[op][v].geometry
            if g.is_empty:
                want = O.empty_of_dimension(result_dimension(op, ga.dimension, gb.dimension))
                assert g == want, (op, v, to_wkt(g))
                assert res[op][v].area == 0
    # GEOS 3.13 gives these for the plain types
    if (a, b) == ("POLYGON EMPTY", "LINESTRING (0 0, 1 1)"):
        assert to_wkt(res["intersection"]["non_strict"].geometry) == "LINESTRING EMPTY"
        assert to_wkt(res["difference"]["non_strict"].geometry) == "POLYGON EMPTY"
    if (a, b) == ("GEOMETRYCOLLECTION EMPTY", "POINT (1 1)"):
        assert to_wkt(res["intersection"]["non_strict"].geometry) == "GEOMETRYCOLLECTION EMPTY"
        assert to_wkt(res["union"]["non_strict"].geometry) == "POINT (1 1)"


# ============================================================ fixtures


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_hand_built_fixture_arrangements(name):
    """The assembly alone, on the Phase-0 hand-built arrangements, must give the same
    results as a real arrangement."""
    spec = FIXTURES[name]
    res = run(spec.a, spec.b)
    arr = fixture(name)
    for op in OPS:
        for v in VARIANTS:
            got = overlay_arrangement(arr, op, v)
            assert ej(got) == ej(res[op][v].geometry), (name, op, v)


def test_fixture_results():
    res = run(FIXTURES["nested_squares"].a, FIXTURES["nested_squares"].b)
    assert same(res["difference"]["areal"].geometry,
                "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (4 4, 4 6, 6 6, 6 4, 4 4))")  # fmt: skip
    assert res["difference"]["areal"].area == 96
    res = run(FIXTURES["dangling_line"].a, FIXTURES["dangling_line"].b)
    assert same(res["union"]["non_strict"].geometry,
                "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 2, 4 4, 0 4, 0 0)), "
                "LINESTRING (4 2, 6 2))")  # fmt: skip
    assert same(res["intersection"]["non_strict"].geometry, "LINESTRING (2 2, 4 2)")
    res = run(FIXTURES["hole_touching_shell"].a, FIXTURES["hole_touching_shell"].b)
    assert same(res["union"]["non_strict"].geometry,
                "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 2, 0 0), "
                "(0 2, 2 1, 2 3, 0 2)), POINT (1 2))")  # fmt: skip


# ============================================================ result object


def test_result_accessors_and_json():
    r = overlay(W(SQ), W("POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))"), "union", certify=True)
    assert r.ok and r.status == STATUS_OK and r.reason is None
    assert r.op == "union" and r.variant == "non_strict"
    assert r.area == 7 and r.num_vertices == 8 and r.geom_type == "Polygon"
    assert not r.is_empty
    assert r.wkt == "POLYGON ((0 0, 2 0, 2 1, 3 1, 3 3, 1 3, 1 2, 0 2, 0 0))"
    j = r.to_json()
    assert j["area"] == "7" and j["num_vertices"] == 8 and j["wkt"] == r.wkt
    assert geometry_from_json(j["exact"], exact=True) == r.geometry
    assert r.certificate.ok and r.stats["V"] > 0 and "t_overlay" in r.stats
    assert r.arrangement is None
    kept = overlay(W(SQ), W("POINT (1 1)"), "union", keep_arrangement=True)
    assert kept.arrangement is not None and kept.arrangement.num_faces == 2


def test_expected_record_validates_against_the_schema():
    pytest.importorskip("jsonschema")
    from geotruth import ENGINE_VERSION, schemas
    from geotruth.relate import relate
    from geotruth.validity import validate

    for a, b in (
        (SQ, "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))"),
        ("LINESTRING (0 0, 3 1)", "LINESTRING (0 1, 2 0)"),
        (SQ, "LINESTRING (-1 1, 3 1)"),
        ("POINT EMPTY", "POLYGON EMPTY"),
    ):
        ga, gb = W(a), W(b)
        res = overlay_all(ga, gb, certify=True)
        rec = {
            "id": "unit",
            "engine": {"version": ENGINE_VERSION},
            **relate(ga, gb).to_json(),
            "validity": {"a": validate(ga).to_json(), "b": validate(gb).to_json()},
            "overlay": {op: {v: res[op][v].to_json() for v in VARIANTS} for op in OPS},
        }
        schemas.validate("expected", rec)


def test_num_vertices():
    assert num_vertices(W("GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 0 1, 0 0)), "
                          "LINESTRING (5 5, 6 6, 7 5), POINT (9 9))")) == 7  # fmt: skip
    assert num_vertices(W("POLYGON EMPTY")) == 0


def test_no_result_accessors_raise_on_failure():
    r = overlay(W("POINT (1 1)"), W("POINT (1 1)"), "union", budget=Budget(max_size=0))
    assert r.status == STATUS_SKIPPED and not r.ok and r.geometry is None
    with pytest.raises(ValueError, match="no result"):
        _ = r.wkt
    with pytest.raises(ValueError, match="no result"):
        r.to_json()


# ============================================================ statuses and assertions


def test_budget_gives_engine_skipped_for_every_result():
    res = overlay_all(W(SQ), W("POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))"), budget=Budget(max_size=3))
    for per in res.values():
        for r in per.values():
            assert r.status == STATUS_SKIPPED and "size" in r.reason


def test_time_budget_is_shared_with_the_assembly(monkeypatch):
    class Clock:
        t = 0.0

        @classmethod
        def perf_counter(cls):
            cls.t += 10.0
            return cls.t

    monkeypatch.setattr(O, "time", Clock)
    r = overlay(W(SQ), W("POINT (1 1)"), "union", budget=Budget(None, 15.0, None))
    assert r.status == STATUS_SKIPPED and "time" in r.reason


def test_memory_error_is_engine_skipped(monkeypatch):
    def oom(*a, **k):
        raise MemoryError

    monkeypatch.setattr(O, "build_arrangement", oom)
    assert overlay(W(SQ), W(SQ), "union").status == STATUS_SKIPPED


def test_engine_exceptions_become_engine_error(monkeypatch):
    def boom(*a, **k):
        raise KeyError("broken")

    monkeypatch.setattr(O, "build_arrangement", boom)
    r = overlay(W(SQ), W(SQ), "union")
    assert r.status == STATUS_ERROR and "KeyError" in r.reason
    with pytest.raises(KeyError):
        overlay(W(SQ), W(SQ), "union", strict=True)


def test_assembly_assertions(monkeypatch):
    """A broken ring assembly is caught by the internal checks (area identity)."""
    real = O._Overlay._split

    def drop_last_ring(self, cyc):
        rings = real(self, cyc)
        return rings[:-1] if len(rings) > 1 else rings

    monkeypatch.setattr(O._Overlay, "_split", drop_last_ring)
    r = overlay(W("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))"), W("POLYGON ((0 2, 2 1, 2 3, 0 2))"),
                "difference")  # fmt: skip
    assert r.status == STATUS_ERROR and "OverlayAssertionError" in r.reason
    with pytest.raises(OverlayAssertionError, match="area"):
        overlay(W("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))"), W("POLYGON ((0 2, 2 1, 2 3, 0 2))"),
                "difference", strict=True)  # fmt: skip


def test_a_wrong_selection_is_caught_by_the_certificate(monkeypatch):
    """Swap two operations: the internal checks pass, the certificate does not."""
    monkeypatch.setattr(O, "select", lambda op, a, b: a or b)  # every op becomes union
    r = overlay(W(SQ), W("POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))"), "intersection", certify=True)
    assert r.status == STATUS_ERROR and r.reason.startswith("certificate failed")
    assert not r.certificate.ok and r.certificate.num_mismatches > 0
    from geotruth.overlay_certify import CertificateError

    with pytest.raises(CertificateError):
        overlay(W(SQ), W("POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))"), "intersection",
                certify=True, strict=True)  # fmt: skip


def test_unlabelled_arrangement_is_an_error():
    arr = fixture("two_disjoint_squares")
    arr.face_loc_a[1] = -1
    with pytest.raises(Exception, match="not labelled"):
        overlay_arrangement(arr, "union")


def test_invalid_input_raises():
    with pytest.raises(InvalidInputError):
        overlay(W("POLYGON ((0 0, 1 1, 1 0, 0 1, 0 0))"), W(SQ), "union")
    with pytest.raises(InvalidInputError):
        overlay(W("POLYGON ((0 0, 1 0, 1 1, 0 0))"), W("POINT (nan 0)"), "union")
    with pytest.raises(ValueError, match="unknown overlay operation"):
        overlay(W(SQ), W(SQ), "clip")


# ============================================================ coordinates


def test_rational_input_is_accepted():
    r = overlay(W("POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0))"), W("POLYGON ((1 -1, 4 2, 1 2, 1 -1))"),
                "intersection").geometry  # fmt: skip
    res = run(r, W("LINESTRING (0 0, 3 3)"))
    assert same(res["intersection"]["non_strict"].geometry, "LINESTRING (1 1, 2 2)")
    thirds = Polygon([[(Fraction(0), Fraction(0)), (Fraction(1, 3), Fraction(0)),
                       (Fraction(0), Fraction(1, 3)), (Fraction(0), Fraction(0))]])  # fmt: skip
    res = run(thirds, W("POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"))
    assert res["intersection"]["areal"].area == Fraction(1, 18)


@pytest.mark.parametrize("k", [-1074, -1060, -600, 0, 600, 1000])
def test_extreme_scales(k):
    a = W("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))")
    b = W("POLYGON ((1 1, 5 2, 3 5, 1 1))")
    base = run(a, b)
    sa = a.map_coords(lambda c: (math.ldexp(c[0], k), math.ldexp(c[1], k)))
    sb = b.map_coords(lambda c: (math.ldexp(c[0], k), math.ldexp(c[1], k)))
    if not all(v == 0 or math.isfinite(v) for v in (*sa.iter_values(), *sb.iter_values())):
        pytest.skip("overflow")
    res = run(sa, sb)
    s = Fraction(2) ** k
    for op in OPS:
        assert res[op]["areal"].area == base[op]["areal"].area * s * s
        want = canonicalize(base[op]["non_strict"].geometry.map_coords(
            lambda c: (Fraction(c[0]) * s, Fraction(c[1]) * s)))  # fmt: skip
        assert ej(res[op]["non_strict"].geometry) == ej(want)


def test_subnormal_coordinates():
    res = run("POLYGON ((0 0, 5e-324 0, 5e-324 1e-323, 0 5e-324, 0 0))",
              "POLYGON ((0 0, 1e-323 5e-324, 0 1e-323, 0 0))")  # fmt: skip
    assert res["intersection"]["areal"].area > 0
    assert res["union"]["areal"].area == (
        shoelace_area(W("POLYGON ((0 0, 5e-324 0, 5e-324 1e-323, 0 5e-324, 0 0))"))
        + shoelace_area(W("POLYGON ((0 0, 1e-323 5e-324, 0 1e-323, 0 0))"))
        - res["intersection"]["areal"].area
    )


# ============================================================ properties (small)


def _random_cases(n: int, seed: int):
    rng = random.Random(seed)
    for _ in range(n):
        yield random_operand(rng, 6), random_operand(rng, 6)


def test_area_identities_on_random_cases():
    for a, b in _random_cases(40, 11):
        res = run(a, b)
        ba = overlay(b, a, "difference", "areal").area
        pa = overlay(a, EMPTY, "union", "areal").area
        pb = overlay(b, EMPTY, "union", "areal").area
        i, u, d, s = (res[op]["areal"].area for op in OPS)
        assert i + d == pa and i + ba == pb
        assert u == i + d + ba and s == d + ba
        for g, p in ((a, pa), (b, pb)):
            if isinstance(g, (Polygon, MultiPolygon)):
                assert shoelace_area(g) == p


def test_symmetric_operations_commute_exactly():
    for a, b in _random_cases(30, 12):
        res, swapped = run(a, b), run(b, a)
        for op in ("intersection", "union", "symdifference"):
            for v in VARIANTS:
                assert ej(res[op][v].geometry) == ej(swapped[op][v].geometry), op


def same_point_set(x, y) -> bool:
    """Exact point-set equality, from the exact relate (IE = BE = EI = EB = F)."""
    from geotruth.relate import relate

    if x.is_empty or y.is_empty:
        return x.is_empty == y.is_empty
    m = relate(x, y, strict=True).matrix
    return m[2] == m[5] == m[6] == m[7] == "F"


def test_self_and_empty_identities():
    for a, _ in _random_cases(25, 13):
        res = run(a, a)
        assert res["difference"]["non_strict"].geometry.is_empty
        assert res["symdifference"]["non_strict"].geometry.is_empty
        u = res["union"]["non_strict"].geometry
        assert ej(res["intersection"]["non_strict"].geometry) == ej(u)
        e = run(a, EMPTY)["union"]["non_strict"].geometry
        # A u A has a node wherever the two copies' segment strings overlap, as in GEOS,
        # so it equals A u {} as a point set, not structurally
        assert same_point_set(e, u) and same_point_set(e, a)
        # idempotent: overlaying a result with the empty geometry changes nothing
        assert ej(run(e, EMPTY)["union"]["non_strict"].geometry) == ej(e)


def test_a_union_a_is_noded_like_geos():
    a = W("LINESTRING (2 4, 3 2, 9 7)")
    assert same(overlay(a, EMPTY, "union").geometry, "LINESTRING (2 4, 3 2, 9 7)")
    assert same(overlay(a, a, "union").geometry, "MULTILINESTRING ((2 4, 3 2), (3 2, 9 7))")


TRANSFORMS = {
    "translate": (lambda c: (c[0] + 0.5, c[1] - 1024.0),
                  lambda c: (Fraction(c[0]) + Fraction(1, 2), Fraction(c[1]) - 1024)),
    "rotate90": (lambda c: (-c[1], c[0]), lambda c: (-Fraction(c[1]), Fraction(c[0]))),
    "reflect": (lambda c: (-c[0], c[1]), lambda c: (-Fraction(c[0]), Fraction(c[1]))),
    "scale": (lambda c: (c[0] * 0.25, c[1] * 0.25),
              lambda c: (Fraction(c[0]) / 4, Fraction(c[1]) / 4)),
}  # fmt: skip


@pytest.mark.parametrize("name", sorted(TRANSFORMS))
def test_exact_transform_invariance(name):
    fd, fe = TRANSFORMS[name]
    for a, b in _random_cases(15, 14):
        res = run(a, b)
        tres = run(a.map_coords(fd), b.map_coords(fd))
        for op in OPS:
            for v in VARIANTS:
                want = canonicalize(res[op][v].geometry.map_coords(fe))
                assert ej(tres[op][v].geometry) == ej(want), (name, op, v)


def test_deterministic_and_backend_independent():
    cases = list(_random_cases(10, 15))
    first = [ej(r.geometry) for a, b in cases for per in run(a, b).values() for r in per.values()]
    again = [ej(r.geometry) for a, b in cases for per in run(a, b).values() for r in per.values()]
    assert first == again
    with use_backend("fractions"):
        frac = [
            ej(r.geometry)
            for a, b in cases
            for per in overlay_all(a, b, strict=True).values()
            for r in per.values()
        ]
    assert frac == first


def test_one_arrangement_for_all_results(monkeypatch):
    calls = []
    real = O.build_arrangement

    def spy(*a, **k):
        calls.append(1)
        return real(*a, **k)

    monkeypatch.setattr(O, "build_arrangement", spy)
    res = overlay_all(W(SQ), W("LINESTRING (-1 1, 3 1)"))
    assert len(calls) == 1 and sum(len(v) for v in res.values()) == 8


def test_certify_many_matches_individual_certificates():
    a, b = W(SQ), W("LINESTRING (-1 1, 3 1)")
    res = overlay_all(a, b)
    items = [(r.op, r.variant, r.geometry) for per in res.values() for r in per.values()]
    assert all(c.ok for c in certify_many(a, b, items))


# ============================================================ integrations


def test_measures_and_harness_use_this_engine():
    from geotruth import measures
    from geotruth.harness import engine

    a, b = W(SQ), W("POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))")
    assert measures.overlay_area(a, b, "intersection") == 1
    assert measures.overlay_area(a, b, "symdifference") == 6
    assert measures.engine_backends()["overlay"] == "geotruth.overlay"
    ans = engine.overlay_answers(W(SQ), W("LINESTRING (-1 1, 3 1)"))
    assert ans["union"]["non_strict"].route == "engine"
    assert ans["union"]["non_strict"].geometry.geom_type == "GeometryCollection"
    assert ans["union"]["areal"].area == 4


def test_arrangement_build_matches_direct_build():
    a, b = W(SQ), W("POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))")
    arr = build_arrangement(a, b)
    res = overlay_all(a, b)
    for op in OPS:
        for v in VARIANTS:
            assert ej(overlay_arrangement(arr, op, v)) == ej(res[op][v].geometry)


def test_polygon_with_line_output_types():
    res = run(SQ, "LINESTRING (1 1, 3 1)")
    assert same(res["union"]["non_strict"].geometry,
                f"GEOMETRYCOLLECTION ({SQ.replace('2 0, 2 2', '2 0, 2 1, 2 2')}, "
                "LINESTRING (2 1, 3 1))")  # fmt: skip
    assert isinstance(res["intersection"]["non_strict"].geometry, LineString)
    assert res["difference"]["non_strict"].geometry.geom_type == "Polygon"
