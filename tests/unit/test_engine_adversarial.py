"""Regression tests from the adversarial review of the exact engine (arrangement, relate,
overlay).

Mutation testing planted 39 plausible one-line bugs in ``arrangement.py``, ``relate.py``,
``overlay.py`` and ``predicates.py``, one at a time; four survived the unit suite. The tests
below kill the two that change an answer or an output shape:

- **Points below the Mod-2 line boundary** (DESIGN §1 "Point location": lines before
  points). A Point element that coincides with an odd-count line end is still *Boundary*;
  letting the point win made it Interior, and no unit test noticed.
- **The start of a closed line is a node.** A closed LineString keeps its start vertex in
  overlay output even where the line runs straight through it, as GEOS does; dropping it
  kept the point set but changed the vertex list.

The other two survivors (dropping node-less linear cycles, dropping straight node vertices
inside a line chain) are equivalent mutants: a chain's interior vertices are never nodes
(the walk stops at nodes), and for valid input every cycle of the linear part has a node
(a closed line's start is one; a ring edge in the linear part always carries a second
visible source). Over 6,000 lattice pairs neither branch ever ran.

The last tests keep a small sample of the review's GeometryCollection-heavy fuzzing in the
fast suite (the full sweep is in ``tests/crosscheck/test_engine_adversarial_crosscheck.py``).
"""

from __future__ import annotations

from fractions import Fraction

import pytest

from geotruth.arrangement import build_arrangement
from geotruth.arrangement_api import Location
from geotruth.geom import LineString, Point, Polygon
from geotruth.io import read_wkt
from geotruth.measures import area as shoelace_area
from geotruth.overlay import OPS, VARIANTS, overlay, overlay_all
from geotruth.predicates import transpose
from geotruth.relate import relate
from geotruth.relate_witness import relate_witness
from unit.nasty_lattice import valid_pairs

I, B, E = Location.INTERIOR, Location.BOUNDARY, Location.EXTERIOR


def W(text: str):
    return read_wkt(text)


def both_routes(a, b) -> str:
    """The matrix, asserting that both exact routes and the transposes agree."""
    m = relate(a, b, strict=True).matrix
    assert relate_witness(a, b).matrix == m
    assert relate(b, a, strict=True).matrix == transpose(m)
    assert relate_witness(b, a).matrix == transpose(m)
    return m


# ============================================== lines take precedence over points


@pytest.mark.parametrize(
    ("a", "b", "matrix"),
    [
        # the point sits on the line's only end at (1 0): Boundary, not Interior (GEOS agrees)
        ("GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POINT (1 0))", "POINT (1 0)", "FF10F0FF2"),
        # both ends carry a point: A's boundary is still {(0 0), (1 0)}, so A equals the line
        ("GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POINT (1 0), POINT (0 0))",
         "LINESTRING (0 0, 1 0)", "1FFF0FFF2"),
        # three line ends meet at (1 0) (odd): Boundary despite the Point element there
        ("GEOMETRYCOLLECTION (MULTILINESTRING ((0 0, 1 0), (1 0, 1 1), (1 0, 2 0)), "
         "MULTIPOINT ((1 0), (5 5)))", "POINT (1 0)", "FF10F0FF2"),
        # a zero-length line adds 2 (even) to the count: still odd, still Boundary
        ("GEOMETRYCOLLECTION (LINESTRING (1 0, 1 0), LINESTRING (0 0, 1 0), POINT (1 0))",
         "POINT (1 0)", "FF10F0FF2"),
        # an even count (two line ends) is Interior; the point element changes nothing
        ("GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), LINESTRING (1 0, 2 0), POINT (1 0))",
         "POINT (1 0)", "0F1FF0FF2"),
    ],
)  # fmt: skip
def test_point_element_does_not_override_the_mod2_line_boundary(a, b, matrix):
    ga, gb = W(a), W(b)
    assert both_routes(ga, gb) == matrix
    arr = build_arrangement(ga, gb)
    v = next(v for v in range(arr.num_vertices) if arr.vertex_fractions(v) == (1, 0))
    want = I if matrix[0] == "0" else B
    assert Location(arr.vertex_loc_a[v]) == want


def test_point_on_line_boundary_predicates():
    """touches, not within: the point meets A only on A's boundary."""
    res = relate(W("GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POINT (1 0))"), W("POINT (1 0)"))
    assert res.predicates["touches"] and res.predicates["covers"]
    assert not res.predicates["contains"]


# ====================================================== closed lines keep their start


CLOSED = "LINESTRING (1 0, 2 0, 2 2, 0 2, 0 0, 1 0)"  # straight through its start (1 0)


@pytest.mark.parametrize(
    ("b", "op", "wkt"),
    [
        # GEOS 3.13.1: GEOMETRYCOLLECTION (LINESTRING (1 0, 2 0, 2 2, 0 2, 0 0, 1 0), POINT (5 5))
        ("POINT (5 5)", "union",
         "GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0, 2 0, 2 2, 0 2, 0 0), POINT (5 5))"),
        # GEOS 3.13.1: LINESTRING (1 0, 2 0, 2 2, 0 2, 0 0, 1 0)
        ("POLYGON ((-1 -1, 3 -1, 3 3, -1 3, -1 -1))", "intersection",
         "LINESTRING (0 0, 1 0, 2 0, 2 2, 0 2, 0 0)"),
        ("POLYGON ((5 5, 6 5, 6 6, 5 5))", "difference",
         "LINESTRING (0 0, 1 0, 2 0, 2 2, 0 2, 0 0)"),
    ],
)  # fmt: skip
def test_closed_line_start_vertex_is_a_node(b, op, wkt):
    """The start of a closed line is a node of the result, like every line end: the
    vertex (1 0) survives although the line goes straight through it (canonical order
    then rotates the ring-like line to start at its smallest vertex)."""
    res = overlay(W(CLOSED), W(b), op, certify=True, strict=True)
    assert res.wkt == wkt
    assert res.num_vertices == (7 if "POINT" in wkt else 6)


def test_open_line_drops_its_straight_interior_vertices():
    """Contrast: a straight vertex inside an open line is not a node and is dropped."""
    res = overlay(W("LINESTRING (0 0, 1 0, 2 0)"), W("POINT (5 5)"), "union", strict=True)
    assert res.wkt == "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (5 5))"


# ============================================================= exact scaling


def test_coprime_odd_denominators_scale_exactly():
    """Coordinates with denominators 3, 5 and 7 in one case: the arrangement scales by
    their lcm (105), so every input vertex is reproduced exactly and relate equals the
    relate of the integer copy scaled by 105."""
    fr = Fraction
    a = Polygon([[(0, 0), (fr(4, 3), 0), (fr(4, 3), fr(6, 5)), (0, fr(6, 5)), (0, 0)]])
    b = LineString([(fr(1, 7), fr(3, 5)), (fr(2, 1), fr(3, 5)), (fr(2, 3), fr(1, 7))])
    p = Point((fr(4, 3), fr(3, 5)))
    arr = build_arrangement(a, b)
    arr.validate(geometry=True, planarity=True, labels=True)
    verts = {arr.vertex_fractions(v) for v in range(arr.num_vertices)}
    assert {(Fraction(x), Fraction(y)) for x, y in a.shell} <= verts
    assert {(Fraction(x), Fraction(y)) for x, y in b.coords} <= verts

    def scaled(g):
        return g.map_coords(lambda c: (float(c[0] * 105), float(c[1] * 105)))

    for x, y in ((a, b), (a, p), (b, p)):
        assert both_routes(x, y) == relate(scaled(x), scaled(y), strict=True).matrix
    assert both_routes(a, p) == "FF20F1FF2"  # (4/3, 3/5) is on A's right edge


# ============================================== GeometryCollection-heavy lattice sample


def test_nasty_lattice_sample_routes_agree():
    """Nested collections, MultiPolygon members, empty members, holes touching shells, B
    retracing A's shell: both exact routes agree (with transposes)."""
    for a, b in valid_pairs(seed=2026, count=40):
        both_routes(a, b)


def test_nasty_lattice_sample_overlay_is_certified():
    """Every result passes the certificate, and its reported exact area equals the
    shoelace area of its own polygons (:func:`geotruth.measures.area`, independent code):
    the certificate checks the point set, not the ``area`` field of the expected answer."""
    for a, b in valid_pairs(seed=2027, count=10):
        res = overlay_all(a, b, certify=True, strict=True)
        assert {(op, v) for op in OPS for v in VARIANTS} == {
            (op, v) for op, per in res.items() for v, r in per.items() if r.ok
        }
        for per in res.values():
            for r in per.values():
                assert r.area == shoelace_area(r.geometry)


def test_reported_area_is_the_shoelace_area_of_the_result():
    """Integer input (scale exponent >= 0) and dyadic input (exponent < 0) both take
    the exact area path of :meth:`OverlayResult.area`."""
    for scale in (1.0, 2.0**-3, 2.0**5):
        a = W("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 1 2, 2 2, 2 1, 1 1))")
        b = W("GEOMETRYCOLLECTION (POLYGON ((3 3, 6 3, 6 6, 3 6, 3 3)), LINESTRING (0 5, 9 5))")
        a, b = (g.map_coords(lambda c, s=scale: (c[0] * s, c[1] * s)) for g in (a, b))
        for op in OPS:
            r = overlay(a, b, op, strict=True)
            assert r.area == shoelace_area(r.geometry)
        assert overlay(a, b, "union").area == 23 * Fraction(scale) ** 2  # 15 + 9 - 1
