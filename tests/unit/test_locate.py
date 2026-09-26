"""Unit tests of the standalone point locator (DESIGN §1 "Point location", §2.4)."""

from __future__ import annotations

import math
from fractions import Fraction
from itertools import pairwise

import pytest

from geotruth.exact import angle_cmp, angle_key, hp_in_ring, hp_on_segment, hpoint
from geotruth.geom import GeometryCollection, LineString, Point, Polygon
from geotruth.io import read_wkt
from geotruth.locate import (
    BOUNDARY,
    EXTERIOR,
    INTERIOR,
    Frame,
    PointLocator,
    direction_between,
    exact_value,
    locate,
    locate_with_dim,
    location_char,
    safe_step_exponent,
)
from geotruth.numbers import DyadicScale, NonFiniteError

from .fixtures_arrangement import FIXTURES

SQUARE = "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))"


def loc(wkt: str, point) -> str:
    return locate(point, read_wkt(wkt))


# ============================================================================ points


@pytest.mark.parametrize(
    ("wkt", "point", "expected"),
    [
        ("POINT (1 2)", (1, 2), "I"),
        ("POINT (1 2)", (1, 3), "E"),
        ("POINT (1 2)", (Fraction(1), Fraction(2)), "I"),
        ("POINT (0.5 2)", (Fraction(1, 2), 2), "I"),
        ("MULTIPOINT ((0 0), (1 1), (1 1))", (1, 1), "I"),
        ("MULTIPOINT ((0 0), (1 1))", (Fraction(1, 2), Fraction(1, 2)), "E"),
        ("MULTIPOINT ((0 0), EMPTY)", (0, 0), "I"),
    ],
)
def test_points(wkt, point, expected):
    assert loc(wkt, point) == expected


# ============================================================================ lines


@pytest.mark.parametrize(
    ("wkt", "point", "expected"),
    [
        # a simple line: endpoints are its boundary, the rest its interior
        ("LINESTRING (0 0, 2 0)", (0, 0), "B"),
        ("LINESTRING (0 0, 2 0)", (2, 0), "B"),
        ("LINESTRING (0 0, 2 0)", (1, 0), "I"),
        ("LINESTRING (0 0, 2 0)", (Fraction(1, 3), 0), "I"),
        ("LINESTRING (0 0, 2 0)", (3, 0), "E"),
        ("LINESTRING (0 0, 2 0)", (1, Fraction(1, 10**30)), "E"),
        ("LINESTRING (0 0, 1 1, 2 0)", (1, 1), "I"),  # an inner vertex
        # a closed line has no boundary: its start point counts twice
        ("LINESTRING (0 0, 1 0, 1 1, 0 0)", (0, 0), "I"),
        ("LINESTRING (0 0, 1 0, 0 0)", (0, 0), "I"),
        ("LINESTRING (0 0, 1 0, 0 0)", (1, 0), "I"),
        # Mod-2 over all elements: shared by two lines -> interior, by three -> boundary
        ("MULTILINESTRING ((0 0, 1 0), (1 0, 2 0))", (1, 0), "I"),
        ("MULTILINESTRING ((0 0, 1 0), (1 0, 2 0), (1 0, 1 1))", (1, 0), "B"),
        ("MULTILINESTRING ((0 0, 1 0), (1 0, 2 0), (1 0, 1 1), (1 -1, 1 0))", (1, 0), "I"),
        # an endpoint of one element interior to another is still boundary (test order)
        ("MULTILINESTRING ((0 0, 2 0), (1 0, 1 1))", (1, 0), "B"),
        ("MULTILINESTRING ((0 0, 2 0), (1 0, 1 1), (1 0, 1 -1))", (1, 0), "I"),
        # a closed element plus an open one ending on it
        ("MULTILINESTRING ((0 0, 2 0, 2 2, 0 0), (0 0, -1 0))", (0, 0), "B"),
        # zero-length lines are the point they repeat (RelateNG), with no boundary
        ("LINESTRING (1 1, 1 1)", (1, 1), "I"),
        ("LINESTRING (1 1, 1 1)", (1, 2), "E"),
        ("MULTILINESTRING ((1 1, 1 1), (1 1, 3 1))", (1, 1), "B"),  # degree 3
        # repeated points do not change anything
        ("LINESTRING (0 0, 0 0, 2 0, 2 0)", (0, 0), "B"),
        ("LINESTRING (0 0, 0 0, 2 0, 2 0)", (1, 0), "I"),
    ],
)
def test_lines_mod2(wkt, point, expected):
    assert loc(wkt, point) == expected


# ========================================================================= polygons


@pytest.mark.parametrize(
    ("wkt", "point", "expected"),
    [
        (SQUARE, (2, 2), "I"),
        (SQUARE, (0, 0), "B"),
        (SQUARE, (2, 0), "B"),
        (SQUARE, (4, Fraction(7, 3)), "B"),
        (SQUARE, (5, 2), "E"),
        (SQUARE, (-Fraction(1, 2**80), 2), "E"),
        (SQUARE, (Fraction(1, 2**80), 2), "I"),
        # clockwise shell: orientation is irrelevant
        ("POLYGON ((0 0, 0 4, 4 4, 4 0, 0 0))", (1, 1), "I"),
        # holes
        ("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 3 1, 3 3, 1 3, 1 1))", (2, 2), "E"),
        ("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 3 1, 3 3, 1 3, 1 1))", (1, 2), "B"),
        (
            "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 3 1, 3 3, 1 3, 1 1))",
            (Fraction(1, 2), 2),
            "I",
        ),
        # a hole touching the shell at (0 2) (valid)
        ("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (0 2, 2 1, 2 3, 0 2))", (0, 2), "B"),
        ("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (0 2, 2 1, 2 3, 0 2))", (1, 2), "E"),
        # a MultiPolygon whose parts touch at a vertex: the touch point is boundary
        ("MULTIPOLYGON (((0 0, 1 0, 1 1, 0 1, 0 0)), ((1 1, 2 1, 2 2, 1 2, 1 1)))", (1, 1), "B"),
        (
            "MULTIPOLYGON (((0 0, 1 0, 1 1, 0 1, 0 0)), ((1 1, 2 1, 2 2, 1 2, 1 1)))",
            (Fraction(3, 2), Fraction(3, 2)),
            "I",
        ),
        # an island inside a hole
        (
            "MULTIPOLYGON (((0 0, 6 0, 6 6, 0 6, 0 0), (1 1, 5 1, 5 5, 1 5, 1 1)), "
            "((2 2, 4 2, 4 4, 2 4, 2 2)))",
            (3, 3),
            "I",
        ),
        (
            "MULTIPOLYGON (((0 0, 6 0, 6 6, 0 6, 0 0), (1 1, 5 1, 5 5, 1 5, 1 1)), "
            "((2 2, 4 2, 4 4, 2 4, 2 2)))",
            (Fraction(3, 2), 3),
            "E",
        ),
    ],
)
def test_polygons(wkt, point, expected):
    assert loc(wkt, point) == expected


# =================================================== geometry collections (union)


GC_SHARED_EDGE = (
    "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0)), POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0)))"
)
GC_FOUR = (
    "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0)), POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0)), "
    "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)), POLYGON ((0 1, 1 1, 1 2, 0 2, 0 1)))"
)
GC_THREE = (
    "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0)), POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0)), "
    "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)))"
)
GC_OVERLAP = (
    "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)))"
)
GC_HOLE_FILLED = (
    "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 3 1, 3 3, 1 3, 1 1)), "
    "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)))"
)
# a hole touching its shell at (2 0), and a second element touching that point from below:
# the union does not cover the hole's wedge, so the point stays on the boundary
GC_HOLE_TOUCH = (
    "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0)), "
    "POLYGON ((2 0, 3 -1, 1 -1, 2 0)))"
)
# same, but the second element fills the hole: the wedge above and the one below are both
# covered, but the two side wedges of the lower triangle are not
GC_HOLE_TOUCH_FILLED = (
    "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0)), "
    "POLYGON ((2 0, 3 1, 1 1, 2 0)), POLYGON ((0 0, 4 0, 4 -4, 0 -4, 0 0)))"
)


@pytest.mark.parametrize(
    ("wkt", "point", "expected"),
    [
        # design review: two squares sharing x = 1 -> the shared edge is interior
        (GC_SHARED_EDGE, (1, Fraction(1, 2)), "I"),
        (GC_SHARED_EDGE, (1, 0), "B"),  # the shared edge's end is on the union boundary
        (GC_SHARED_EDGE, (1, 1), "B"),
        (GC_SHARED_EDGE, (Fraction(1, 2), 1), "B"),
        # four squares around (1 1): fully covered; three: not
        (GC_FOUR, (1, 1), "I"),
        (GC_FOUR, (1, Fraction(3, 2)), "I"),
        (GC_FOUR, (0, 1), "B"),
        (GC_THREE, (1, 1), "B"),
        (GC_THREE, (1, Fraction(1, 2)), "I"),
        # design review: overlapping squares -> the overlap is interior (not even-odd)
        (GC_OVERLAP, (Fraction(3, 2), Fraction(3, 2)), "I"),
        (GC_OVERLAP, (2, Fraction(3, 2)), "I"),  # boundary of one, interior of the other
        # the boundaries cross at (2 1), a reflex corner of the union: the sector
        # x > 2, y < 1 is covered by neither square
        (GC_OVERLAP, (2, 1), "B"),
        (GC_OVERLAP, (2, 2), "I"),
        (GC_OVERLAP, (2, 3), "B"),
        (GC_OVERLAP, (2, 4), "E"),
        (GC_OVERLAP, (Fraction(5, 2), Fraction(1, 2)), "E"),
        (GC_OVERLAP, (3, 3), "B"),
        (GC_OVERLAP, (1, 3), "B"),
        # a hole exactly filled by another element: its ring is interior of the union
        (GC_HOLE_FILLED, (2, 1), "I"),
        (GC_HOLE_FILLED, (1, 1), "I"),
        (GC_HOLE_FILLED, (2, 2), "I"),
        (GC_HOLE_TOUCH, (2, 0), "B"),
        (GC_HOLE_TOUCH, (2, Fraction(1, 2)), "E"),
        (GC_HOLE_TOUCH_FILLED, (2, 0), "I"),
        (GC_HOLE_TOUCH_FILLED, (Fraction(5, 2), Fraction(1, 2)), "I"),
        (GC_HOLE_TOUCH_FILLED, (1, 0), "I"),
        # identical elements: the shared boundary is still boundary
        (
            "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 1 1, 0 0)), POLYGON ((0 0, 1 0, 1 1, 0 0)))",
            (Fraction(1, 2), 0),
            "B",
        ),
        # design review: a line end inside a polygon of the same GC is interior (polygon wins)
        (
            "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (1 1, 3 1))",
            (1, 1),
            "I",
        ),
        (
            "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (1 1, 3 1))",
            (3, 1),
            "B",
        ),
        (
            "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (1 1, 3 1))",
            (2, 1),
            "B",
        ),  # the polygon boundary wins over the line interior
        (
            "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (1 1, 3 1))",
            (Fraction(5, 2), 1),
            "I",
        ),
        # points last
        ("GEOMETRYCOLLECTION (POINT (5 5), LINESTRING (0 0, 1 0))", (5, 5), "I"),
        ("GEOMETRYCOLLECTION (POINT (0 0), LINESTRING (0 0, 1 0))", (0, 0), "B"),
        ("GEOMETRYCOLLECTION (POINT (1 1), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))", (1, 1), "I"),
        ("GEOMETRYCOLLECTION (POINT (0 1), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))", (0, 1), "B"),
        # nested collections, multi-geometries inside collections
        (
            "GEOMETRYCOLLECTION (GEOMETRYCOLLECTION (MULTILINESTRING ((0 0, 2 0), (1 0, 1 1))))",
            (1, 0),
            "B",
        ),
        (
            "GEOMETRYCOLLECTION (MULTIPOLYGON (((0 0, 1 0, 1 1, 0 1, 0 0))), "
            "POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0)))",
            (1, Fraction(1, 3)),
            "I",
        ),
        ("GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), LINESTRING (1 0, 2 0))", (1, 0), "I"),
    ],
)
def test_collections_union_semantics(wkt, point, expected):
    assert loc(wkt, point) == expected


def test_invalid_multipolygon_shared_edge_is_union_interior():
    # an invalid MultiPolygon whose parts share an edge: union semantics (the design) make
    # the shared edge interior; RelateNG would count the MultiPolygon once and say B
    wkt = "MULTIPOLYGON (((0 0, 1 0, 1 1, 0 1, 0 0)), ((1 0, 2 0, 2 1, 1 1, 1 0)))"
    assert loc(wkt, (1, Fraction(1, 2))) == "I"


# ================================================================ dimension, empties


@pytest.mark.parametrize(
    ("wkt", "point", "expected"),
    [
        ("GEOMETRYCOLLECTION (POINT (1 1), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))", (1, 1), ("I", 2)),
        ("GEOMETRYCOLLECTION (POINT (3 3), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))", (3, 3), ("I", 0)),
        (
            "GEOMETRYCOLLECTION (LINESTRING (0 0, 5 0), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))",
            (1, 0),
            ("B", 2),
        ),
        (
            "GEOMETRYCOLLECTION (LINESTRING (0 0, 5 0), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))",
            (5, 0),
            ("B", 1),
        ),
        (
            "GEOMETRYCOLLECTION (LINESTRING (0 0, 5 0), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))",
            (4, 0),
            ("I", 1),
        ),
        (
            "GEOMETRYCOLLECTION (LINESTRING (0 0, 5 0), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))",
            (4, 1),
            ("E", -1),
        ),
    ],
)
def test_locate_with_dim(wkt, point, expected):
    assert locate_with_dim(point, read_wkt(wkt)) == expected


@pytest.mark.parametrize(
    "wkt",
    [
        "POINT EMPTY",
        "LINESTRING EMPTY",
        "POLYGON EMPTY",
        "MULTIPOLYGON EMPTY",
        "GEOMETRYCOLLECTION EMPTY",
        "GEOMETRYCOLLECTION (POINT EMPTY, POLYGON EMPTY)",
    ],
)
def test_empty_geometries_locate_exterior(wkt):
    assert loc(wkt, (0, 0)) == "E"
    assert loc(wkt, (Fraction(1, 3), 7)) == "E"


def test_empty_elements_are_ignored():
    wkt = "GEOMETRYCOLLECTION (POLYGON EMPTY, LINESTRING EMPTY, POINT (1 1))"
    assert loc(wkt, (1, 1)) == "I"
    assert loc(wkt, (0, 0)) == "E"


# ==================================================================== point formats


def test_point_formats_agree():
    g = read_wkt("LINESTRING (0 0, 3 3)")
    forms = [
        (1, 1),
        (1.0, 1.0),
        (Fraction(1), Fraction(1)),
        (2, 2, 2),  # homogeneous
        (-1, -1, -1),  # homogeneous with negative weight
        Point((1.0, 1.0)),
    ]
    assert {locate(p, g) for p in forms} == {"I"}
    assert locate((1, 2, 3), g) == "E"  # (1/3, 2/3)
    assert locate((1, 1, 3), g) == "I"  # (1/3, 1/3)


def test_mpq_points():
    gmpy2 = pytest.importorskip("gmpy2")
    g = read_wkt("LINESTRING (0 0, 3 3)")
    assert locate((gmpy2.mpq(1, 3), gmpy2.mpq(1, 3)), g) == "I"
    assert locate((gmpy2.mpq(1, 3), gmpy2.mpq(2, 3)), g) == "E"


def test_bad_points_raise():
    g = read_wkt(SQUARE)
    with pytest.raises(ValueError):
        locate(Point(), g)
    with pytest.raises(ZeroDivisionError):
        locate((1, 1, 0), g)
    with pytest.raises(TypeError):
        locate((1, 1.5, 2), g)
    with pytest.raises(ValueError):
        locate((1, 2, 3, 4), g)
    with pytest.raises(NonFiniteError):
        locate((math.nan, 1.0), g)
    with pytest.raises(TypeError):
        locate((True, 1), g)
    with pytest.raises(TypeError):
        locate(("1", 1), g)


def test_nonfinite_geometry_raises():
    with pytest.raises(NonFiniteError):
        locate((0, 0), read_wkt("LINESTRING (0 0, Inf 1)"))


# ====================================================================== frames


def test_frame_for_doubles_is_the_dyadic_scale():
    g = read_wkt("POLYGON ((0.5 0, 4 0, 4 4.25, 0.5 0))")
    f = Frame.for_geometries(g)
    assert f.scale == DyadicScale.for_values(list(g.iter_values()))
    assert (f.num, f.den) == (1, 4)
    assert f.to_int(4.25) == 17
    assert f.to_fractions(hpoint(17, 2, 1)) == (Fraction(17, 4), Fraction(1, 2))


def test_frame_for_large_even_doubles_scales_down():
    f = Frame.for_values([2.0**60, 2.0**62])
    assert (f.num, f.den) == (2**60, 1)
    assert f.to_int(2.0**62) == 4


def test_frame_for_rationals():
    g = Polygon([[(Fraction(1, 3), 0), (1, 0), (1, Fraction(2, 5)), (Fraction(1, 3), 0)]])
    f = Frame.for_geometries(g)
    assert (f.num, f.den) == (1, 15)
    assert f.to_int(Fraction(2, 5)) == 6
    with pytest.raises(ValueError):
        f.to_int(Fraction(1, 7))
    assert locate((Fraction(2, 3), Fraction(1, 10)), g) == "I"
    assert locate((Fraction(1, 3), 0), g) == "B"


def test_frame_for_integers_and_zero():
    assert (Frame.for_values([]).num, Frame.for_values([]).den) == (1, 1)
    assert (Frame.for_values([0, 0]).num, Frame.for_values([0, 0]).den) == (1, 1)
    f = Frame.for_values([6, 9, 0])
    assert (f.num, f.den) == (1, 1)  # integers keep the dyadic frame: 2**0
    f = Frame.for_values([Fraction(6), Fraction(9)])
    assert (f.num, f.den) == (1, 1)  # dyadic values always get the dyadic scale
    f = Frame.for_values([Fraction(2, 3), Fraction(4, 3)])
    assert (f.num, f.den) == (2, 3)  # non-dyadic: the gcd of the values


def test_frame_for_wide_integers_is_exact():
    # integers wider than a double's mantissa must not be rounded on the way
    big = 2**60 + 1
    f = Frame.for_values([big, Fraction(1, 2)])
    assert (f.num, f.den) == (1, 2)
    assert f.to_int(big) == 2 * big
    g = LineString([(0, 0), (big, big)])
    assert locate((big - 1, big - 1), g) == "I"
    assert locate((big, big - 1), g) == "E"
    f = Frame.for_values([2**70, 3 * 2**64])
    assert (f.num, f.den) == (2**64, 1)


def test_invalid_hole_outside_shell_is_still_seen():
    # a hole outside its shell (invalid): the shell test comes first, as in JTS
    g = read_wkt("POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0), (5 5, 6 5, 6 6, 5 5))")
    assert loc(g.wkt, (1, 1)) == "I"
    assert loc(g.wkt, (Fraction(11, 2), Fraction(21, 4))) == "E"
    assert loc(g.wkt, (6, 5)) == "E"  # on the hole ring but outside the shell


def test_exact_value():
    assert exact_value(0.1) == Fraction(0.1)
    assert exact_value(3) == 3
    with pytest.raises(NonFiniteError):
        exact_value(math.inf)
    with pytest.raises(TypeError):
        exact_value(False)


def test_location_char():
    assert [location_char(x) for x in (INTERIOR, BOUNDARY, EXTERIOR)] == ["I", "B", "E"]


# ====================================================== adjacent-edge machinery


@pytest.mark.parametrize(
    ("u", "v"),
    [((1, 0), (0, 1)), ((1, 0), (-1, 0)), ((1, 0), (0, -1)), ((1, 0), (1, -1)), ((2, 1), (1, 3))],
)
def test_direction_between(u, v):
    d = direction_between(u, v)

    def rel(x):  # angle measured counter-clockwise from u, as a sort key
        return (angle_cmp(x, u) < 0, angle_key(x))

    assert rel(u) < rel(d) < rel(v)


def test_direction_between_single_ray():
    assert direction_between((2, 3), (2, 3), single=True) == (-2, -3)


def test_safe_step_exponent():
    # d2 / 4**k < n / d
    for d2, dist in [(1, (1, 1)), (5, (1, 1)), (2, (1, 100)), (10**6, (3, 7)), (1, (10**9, 1))]:
        k = safe_step_exponent(d2, dist)
        assert d2 * dist[1] < dist[0] * 4**k
        assert k == 0 or not d2 * dist[1] < dist[0] * 4 ** (k - 1)
    with pytest.raises(ValueError):
        safe_step_exponent(1, (0, 1))


@pytest.mark.parametrize("wkt", [GC_FOUR, GC_THREE, GC_OVERLAP, GC_HOLE_TOUCH, GC_HOLE_FILLED])
def test_sector_samples_avoid_every_ring(wkt):
    g = read_wkt(wkt)
    loc_ = PointLocator(g)
    rings = [[loc_.frame.to_int_point(c) for c in r] for r in (rr.coords for rr in g.iter_rings())]
    for p in [(1, 1, 1), (2, 1, 1), (2, 0, 1), (1, 0, 1), (3, 1, 1), (4, 2, 1)]:
        samples = loc_.sector_samples(p)
        dirs = loc_.incident_directions(p)
        assert len(samples) == len(dirs)
        for q in samples:
            assert q != p
            for r in rings:
                assert hp_in_ring(q, r) != 0
                for a, b in pairwise(r):
                    assert not hp_on_segment(q, a, b)


def test_prepared_locator_reuse():
    g = read_wkt(GC_OVERLAP)
    lp = PointLocator(g)
    assert lp.locate(hpoint(3, 3, 2)) == INTERIOR
    assert lp.locate_with_dim(hpoint(3, 3, 1)) == (BOUNDARY, 2)
    assert lp.locate_polygonal(hpoint(9, 9, 1)) == EXTERIOR
    assert PointLocator(read_wkt("LINESTRING (0 0, 1 1)")).locate_polygonal((0, 0, 1)) == EXTERIOR


def test_unclosed_ring_is_closed_implicitly():
    g = Polygon([[(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)]])
    assert locate((0, 2), g) == "B"
    assert locate((2, 2), g) == "I"


def test_single_point_line_is_its_point():
    g = LineString([(1.0, 1.0)])  # not constructible in JTS; treated as a zero-length line
    assert locate((1, 1), g) == "I"
    assert locate((0, 1), g) == "E"


def test_exact_near_misses():
    # points one ulp-scale step off a sloped edge, at extreme coordinates
    g = read_wkt("LINESTRING (1e-300 1e-300, 3e300 1e300)")
    x, y = Fraction(1e-300), Fraction(1e-300)
    dx, dy = Fraction(3e300) - x, Fraction(1e300) - y
    mid = (x + dx / 2, y + dy / 2)
    assert locate(mid, g) == "I"
    assert locate((mid[0], mid[1] + Fraction(1, 10**400)), g) == "E"
    poly = GeometryCollection((read_wkt("POLYGON ((0 0, 1 0, 0 1, 0 0))"),))
    assert locate((Fraction(1, 2), Fraction(1, 2)), poly) == "B"
    assert locate((Fraction(1, 2), Fraction(1, 2) - Fraction(1, 2**1100)), poly) == "I"
    assert locate((Fraction(1, 2), Fraction(1, 2) + Fraction(1, 2**1100)), poly) == "E"


# ====================================================== against the hand fixtures


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_labels(name):
    """Every vertex, edge midpoint and face witness of the hand-built arrangement
    fixtures, located in A and B, gives the fixture's hand-written label."""
    spec = FIXTURES[name]
    a, b = read_wkt(spec.a), read_wkt(spec.b)
    frame = Frame.for_geometries(a, b)
    la, lb = PointLocator(a, frame), PointLocator(b, frame)

    def label(pt) -> str:
        p = frame.hpoint(pt)
        return location_char(la.locate(p)) + location_char(lb.locate(p))

    verts = [v if len(v) == 3 else (*v, 1) for v in spec.vertices]
    for v, lab in zip(verts, spec.vertex_labels, strict=True):
        assert label(v) == lab, (name, "vertex", v)
    for u, v, _, lab in spec.edges:
        (x0, y0, w0), (x1, y1, w1) = verts[u], verts[v]
        mid = (x0 * w1 + x1 * w0, y0 * w1 + y1 * w0, 2 * w0 * w1)
        assert label(mid) == lab, (name, "edge", u, v)
    for witness, lab in spec.faces:
        assert label(witness) == lab, (name, "face", witness)
