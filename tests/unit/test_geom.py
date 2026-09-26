"""Unit tests for the typed geometry model (geotruth.geom)."""

from __future__ import annotations

import math

import pytest

from geotruth.geom import (
    DIM_A,
    DIM_FALSE,
    DIM_L,
    DIM_P,
    GEOM_A,
    GEOM_B,
    LINE,
    TYPES,
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    SourceTag,
    build_geometry,
    empty_of_dimension,
    flatten,
    partition_by_dimension,
)
from geotruth.io import read_wkt

SQUARE = [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0), (0.0, 0.0)]
HOLE = [(1.0, 1.0), (1.0, 2.0), (2.0, 2.0), (1.0, 1.0)]


def test_constructors_normalise_to_tuples():
    p = Polygon([[list(c) for c in SQUARE]])
    assert isinstance(p.rings, tuple) and isinstance(p.rings[0], tuple)
    assert p.rings[0][1] == (4.0, 0.0)
    ls = LineString([[0, 0, 7], [1, 1, 8]])  # Z is dropped
    assert ls.coords == ((0, 0), (1, 1))
    mp = MultiPoint([(1, 2), Point((3, 4)), Point()])
    assert mp.points == (Point((1, 2)), Point((3, 4)), Point())
    mls = MultiLineString([[(0, 0), (1, 1)], LineString()])
    assert mls.lines[1] == LineString()
    mpoly = MultiPolygon([[SQUARE], Polygon()])
    assert mpoly.polygons[0].shell == tuple(SQUARE)
    with pytest.raises(ValueError):
        Point((1,))
    with pytest.raises(TypeError):
        GeometryCollection([(1, 2)])


def test_geometries_are_immutable_and_hashable():
    p = Point((1.0, 2.0))
    with pytest.raises(AttributeError):
        p.coord = (0, 0)  # type: ignore[misc]
    assert hash(Polygon([SQUARE])) == hash(Polygon([SQUARE]))
    assert {Point((1, 2)), Point((1, 2))} == {Point((1, 2))}


@pytest.mark.parametrize(
    ("wkt", "empty"),
    [
        ("POINT EMPTY", True),
        ("POINT (1 2)", False),
        ("LINESTRING EMPTY", True),
        ("LINESTRING (0 0, 1 1)", False),
        ("POLYGON EMPTY", True),
        ("POLYGON ((0 0, 1 0, 1 1, 0 0))", False),
        ("MULTIPOINT EMPTY", True),
        ("MULTIPOINT (EMPTY, EMPTY)", True),
        ("MULTIPOINT (EMPTY, (1 1))", False),
        ("MULTILINESTRING (EMPTY)", True),
        ("MULTIPOLYGON (EMPTY)", True),
        ("GEOMETRYCOLLECTION EMPTY", True),
        ("GEOMETRYCOLLECTION (POINT EMPTY, LINESTRING EMPTY)", True),
        ("GEOMETRYCOLLECTION (POINT EMPTY, POINT (0 0))", False),
    ],
)
def test_is_empty(wkt, empty):
    assert read_wkt(wkt).is_empty is empty


@pytest.mark.parametrize(
    ("wkt", "dim", "real"),
    [
        ("POINT EMPTY", DIM_P, DIM_FALSE),
        ("POINT (1 1)", DIM_P, DIM_P),
        ("MULTIPOINT ((1 1), (2 2))", DIM_P, DIM_P),
        ("LINESTRING EMPTY", DIM_L, DIM_FALSE),
        ("LINESTRING (0 0, 1 1)", DIM_L, DIM_L),
        ("LINESTRING (1 1, 1 1)", DIM_L, DIM_P),  # zero length: real dimension 0
        ("LINESTRING (1 1, 1 1, 1 1)", DIM_L, DIM_P),
        ("MULTILINESTRING ((1 1, 1 1), (2 2, 2 2))", DIM_L, DIM_P),
        ("MULTILINESTRING ((1 1, 1 1), (2 2, 3 3))", DIM_L, DIM_L),
        ("MULTILINESTRING ((1 1, 1 1), EMPTY)", DIM_L, DIM_P),
        ("POLYGON EMPTY", DIM_A, DIM_FALSE),
        ("POLYGON ((0 0, 1 0, 1 1, 0 0))", DIM_A, DIM_A),
        ("MULTIPOLYGON (EMPTY, ((0 0, 1 0, 1 1, 0 0)))", DIM_A, DIM_A),
        ("GEOMETRYCOLLECTION EMPTY", DIM_FALSE, DIM_FALSE),
        ("GEOMETRYCOLLECTION (POLYGON EMPTY)", DIM_A, DIM_FALSE),
        ("GEOMETRYCOLLECTION (POLYGON EMPTY, POINT (1 1))", DIM_A, DIM_P),
        ("GEOMETRYCOLLECTION (POINT (1 1), LINESTRING (0 0, 1 0))", DIM_L, DIM_L),
        ("GEOMETRYCOLLECTION (POINT (1 1), LINESTRING (0 0, 0 0))", DIM_L, DIM_P),
        (
            "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 1 1, 0 0)), LINESTRING (5 5, 5 5))",
            DIM_A,
            DIM_A,
        ),
        # RelateNG quirk: type dimension 2 (from an empty polygon) disables the
        # zero-length rule, so the zero-length line keeps real dimension 1
        ("GEOMETRYCOLLECTION (POLYGON EMPTY, LINESTRING (1 1, 1 1))", DIM_A, DIM_L),
        ("GEOMETRYCOLLECTION (GEOMETRYCOLLECTION (MULTIPOINT ((1 1))))", DIM_P, DIM_P),
    ],
)
def test_dimension_and_real_dimension(wkt, dim, real):
    g = read_wkt(wkt)
    assert g.dimension == dim
    assert g.real_dimension == real


def test_zero_length_uses_float_equality():
    assert LineString([(0.0, 0.0), (-0.0, 0.0)]).is_zero_length  # -0.0 == 0.0
    assert not LineString([(math.nan, 0.0), (math.nan, 0.0)]).is_zero_length
    assert LineString([(1, 1)]).is_zero_length and LineString().is_zero_length
    assert read_wkt("LINESTRING (1 1, 1 1)").is_zero_length_linear
    assert not read_wkt("LINESTRING EMPTY").is_zero_length_linear
    assert not read_wkt("POINT (1 1)").is_zero_length_linear


def test_has_flags():
    g = read_wkt("GEOMETRYCOLLECTION (POINT EMPTY, LINESTRING (0 0, 1 1), POLYGON EMPTY)")
    assert not g.has_points and g.has_lines and not g.has_areas


def test_elements_are_depth_first_and_keep_empties():
    g = read_wkt(
        "GEOMETRYCOLLECTION (MULTIPOINT ((1 1), EMPTY), "
        "GEOMETRYCOLLECTION (LINESTRING (0 0, 1 1), POLYGON EMPTY), "
        "POLYGON ((0 0, 4 0, 4 4, 0 0)))"
    )
    types = [type(e).__name__ for e in g.elements()]
    assert types == ["Point", "Point", "LineString", "Polygon", "Polygon"]
    idx = [e.index for e in g.iter_elements(skip_empty=True)]
    assert idx == [0, 2, 4]
    assert [type(e).__name__ for e in flatten(g)] == ["Point", "LineString", "Polygon"]
    assert len(flatten(g, skip_empty=False)) == 5
    pts, lns, polys = partition_by_dimension(g)
    assert (len(pts), len(lns), len(polys)) == (1, 1, 1)


def test_rings_with_roles():
    g = MultiPolygon([Polygon([SQUARE, HOLE]), Polygon([SQUARE])])
    rings = list(g.iter_rings(GEOM_B))
    assert [(r.tag.element, r.tag.ring, r.tag.is_hole) for r in rings] == [
        (0, 0, False),
        (0, 1, True),
        (1, 0, False),
    ]
    assert all(r.tag.geom == GEOM_B and r.tag.is_ring for r in rings)
    assert rings[1].coords == tuple(HOLE)
    assert str(rings[1].tag) == "B.e0.r1(hole)"


def test_lines_points_and_endpoints():
    g = read_wkt(
        "GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0, 1 1, 0 0), POINT (5 5), "
        "LINESTRING EMPTY, LINESTRING (2 2, 3 3))"
    )
    lines = list(g.iter_lines())
    assert [t.element for t, _ in lines] == [0, 3]
    assert all(t.ring == LINE and t.is_line and not t.is_hole for t, _ in lines)
    assert str(lines[0][0]) == "A.e0.line"
    assert list(g.iter_points()) == [(1, (5.0, 5.0))]
    # a closed line contributes its endpoint twice (Mod-2: no boundary)
    assert list(g.iter_line_endpoints()) == [(0, 0), (0, 0), (2, 2), (3, 3)]


def test_segments_skip_zero_length_and_keep_indices():
    g = MultiLineString([[(0, 0), (0, 0), (1, 0), (1, 0), (1, 1)]])
    segs = list(g.iter_segments(GEOM_A))
    assert [(s.p, s.q, s.index) for s in segs] == [((0, 0), (1, 0), 1), ((1, 0), (1, 1), 3)]
    assert all(s.tag == SourceTag(GEOM_A, 0, LINE, False) for s in segs)
    poly = Polygon([SQUARE, HOLE])
    segs = list(poly.iter_segments(GEOM_B))
    assert len(segs) == 4 + 3
    assert segs[-1].tag == SourceTag.for_ring(GEOM_B, 0, 1)
    # rings first, then lines, in element order
    gc = GeometryCollection([LineString([(9, 9), (8, 8)]), poly])
    tags = [s.tag for s in gc.iter_segments()]
    assert tags[0].element == 1 and tags[-1].element == 0


def test_coordinates_and_nonfinite_flag():
    g = read_wkt("MULTIPOINT ((1 2), EMPTY, (3 4))")
    assert list(g.iter_coords()) == [(1.0, 2.0), (3.0, 4.0)]
    assert list(g.iter_values()) == [1.0, 2.0, 3.0, 4.0]
    assert g.num_coords == 2 and not g.has_nonfinite
    assert read_wkt("POINT (NaN 1)").has_nonfinite
    assert Polygon([[(0, 0), (math.inf, 0), (0, 1), (0, 0)]]).has_nonfinite


def test_map_coords_preserves_structure():
    g = read_wkt(
        "GEOMETRYCOLLECTION (POINT EMPTY, MULTIPOLYGON (((0 0, 2 0, 0 2, 0 0))), "
        "MULTILINESTRING ((0 0, 1 1)), MULTIPOINT ((1 1)))"
    )
    doubled = g.map_coords(lambda c: (2 * c[0], 2 * c[1]))
    assert type(doubled) is GeometryCollection
    assert [type(x) for x in doubled.geometries] == [type(x) for x in g.geometries]
    assert list(doubled.iter_coords()) == [(2 * x, 2 * y) for x, y in g.iter_coords()]


def test_build_geometry_and_typed_empties():
    p, q = Point((0, 0)), Point((1, 1))
    ln = LineString([(0, 0), (1, 1)])
    poly = Polygon([SQUARE])
    assert build_geometry([]) == GeometryCollection()
    assert build_geometry([p]) is p
    assert build_geometry([p, q]) == MultiPoint([p, q])
    assert build_geometry([ln, ln]) == MultiLineString([ln, ln])
    assert build_geometry([poly, poly]) == MultiPolygon([poly, poly])
    assert build_geometry([poly, p]) == GeometryCollection([poly, p])
    assert empty_of_dimension(0) == Point()
    assert empty_of_dimension(1) == LineString()
    assert empty_of_dimension(2) == Polygon()
    assert empty_of_dimension(-1) == GeometryCollection()
    with pytest.raises(ValueError):
        empty_of_dimension(3)


def test_polygon_accessors_and_types_table():
    poly = Polygon([SQUARE, HOLE])
    assert poly.shell == tuple(SQUARE) and poly.holes == (tuple(HOLE),)
    assert Polygon().shell == () and Polygon().holes == ()
    assert set(TYPES) == {
        "Point",
        "LineString",
        "Polygon",
        "MultiPoint",
        "MultiLineString",
        "MultiPolygon",
        "GeometryCollection",
    }
    assert all(cls.geom_type == name for name, cls in TYPES.items())


def test_source_tag_constructors():
    assert SourceTag.for_ring(GEOM_A, 2, 0) == SourceTag(0, 2, 0, False)
    assert SourceTag.for_ring(GEOM_A, 2, 3).is_hole
    assert SourceTag.for_line(GEOM_B, 1) == SourceTag(1, 1, -1, False)
    assert str(SourceTag.for_ring(GEOM_A, 0, 0)) == "A.e0.r0(shell)"


def test_wkt_property():
    assert Point((1.0, 2.5)).wkt == "POINT (1 2.5)"


def _crosses(matrix: str, da: int, db: int) -> bool:
    """DESIGN §1 crosses dispatch on real dimensions."""
    t = [c != "F" for c in matrix]
    if (da, db) in ((0, 1), (0, 2), (1, 2)):
        return t[0] and t[2]
    if (da, db) in ((1, 0), (2, 0), (2, 1)):
        return t[0] and t[6]
    if (da, db) == (1, 1):
        return matrix[0] == "0"
    return False


@pytest.mark.parametrize(
    "wkt",
    [
        "GEOMETRYCOLLECTION (POLYGON EMPTY, LINESTRING (1 1, 1 1))",  # the quirk: L/L
        "GEOMETRYCOLLECTION (LINESTRING (1 1, 1 1))",
        "LINESTRING (1 1, 1 1)",
        "MULTILINESTRING ((1 1, 1 1), EMPTY)",
        "LINESTRING (0 2, 2 0)",
        "MULTIPOINT ((1 1), (5 5))",
        "GEOMETRYCOLLECTION (POINT (1 1), LINESTRING (1 0, 1 1))",
    ],
)
def test_real_dimension_matches_geos_dispatch(wkt):
    """GEOS's crosses() dispatches on RelateNG's real dimension; ours must agree."""
    shapely = pytest.importorskip("shapely")
    a, b = shapely.from_wkt(wkt), shapely.from_wkt("LINESTRING (0 0, 2 2)")
    ga, gb = read_wkt(wkt), read_wkt("LINESTRING (0 0, 2 2)")
    expected = _crosses(a.relate(b), ga.real_dimension, gb.real_dimension)
    assert bool(a.crosses(b)) == expected
