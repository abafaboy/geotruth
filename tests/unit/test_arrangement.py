"""Unit tests of the arrangement builder (DESIGN §2.2): structure, labels, budget, errors.

The labels are checked against :mod:`unit.arrangement_testlib`'s brute-force locator,
which applies DESIGN §1 directly to the input coordinates (no DCEL), at every vertex,
every edge midpoint and a point just left of every half-edge.
"""

from __future__ import annotations

import random
from fractions import Fraction

import pytest

from geotruth.arrangement import (
    DEFAULT_BUDGET,
    Budget,
    BudgetExceeded,
    InvalidInputError,
    build_arrangement,
)
from geotruth.arrangement_api import Arrangement, Location
from geotruth.geom import (
    GEOM_A,
    GEOM_B,
    GeometryCollection,
    LineString,
    MultiPoint,
    Point,
    Polygon,
    SourceTag,
)
from geotruth.io import read_wkt

from .arrangement_testlib import (
    BruteLocator,
    CellLocator,
    canonical_form,
    check_labels,
    components,
    face_area2,
    labels_matrix,
    random_face_points,
    random_operand,
)
from .fixtures_arrangement import FIXTURES, fixture

I, B, E = Location.INTERIOR, Location.BOUNDARY, Location.EXTERIOR
NAMES = sorted(FIXTURES)


def build(wkt_a: str, wkt_b: str, **kw) -> Arrangement:
    """Build from WKT and run every invariant check, including the O(E^2) planarity."""
    a, b = read_wkt(wkt_a), read_wkt(wkt_b)
    arr = build_arrangement(a, b, **kw)
    arr.validate(geometry=True, planarity=True, labels=True)
    assert arr.num_vertices - arr.num_edges + arr.num_faces == 1 + components(arr)
    check_labels(arr, a, b)
    return arr


def vertex_at(arr: Arrangement, x, y) -> int:
    p = (Fraction(x), Fraction(y))
    (v,) = [v for v in range(arr.num_vertices) if arr.vertex_fractions(v) == p]
    return v


def vlabel(arr: Arrangement, x, y) -> str:
    v = vertex_at(arr, x, y)
    return Location(arr.vertex_loc_a[v]).char + Location(arr.vertex_loc_b[v]).char


# ============================================================ the hand-built fixtures


@pytest.mark.parametrize("name", NAMES)
def test_fixture_reproduced_from_raw_geometries(name):
    """The builder reproduces every hand-built fixture up to renumbering: vertices,
    edges with their source multisets, ``next``, faces (outer and inner components,
    isolated vertices) and every label."""
    spec = FIXTURES[name]
    arr = build(spec.a, spec.b)
    assert canonical_form(arr) == canonical_form(fixture(name))
    assert labels_matrix(arr) == spec.relate


def test_fixture_scale_is_dyadic():
    arr = build(FIXTURES["two_disjoint_squares"].a, FIXTURES["two_disjoint_squares"].b)
    assert arr.scale_exp == 1  # every coordinate is even
    assert max(arr.vx) == 3  # 6 / 2
    assert all(w == 1 for w in arr.vw)


# ===================================================================== semantics


@pytest.mark.parametrize(
    ("a", "b", "relate"),
    [
        # review must-fix 1: GeometryCollections use union semantics (GEOS 3.13.1)
        (
            "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0)), "
            "POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0)))",
            "POLYGON ((0 0, 2 0, 2 1, 0 1, 0 0))",
            "2FFF1FFF2",
        ),
        (
            "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
            "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)))",
            "POINT (1.5 1.5)",
            "0F2FF1FF2",
        ),
        (
            "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (1 1, 3 1))",
            "POINT (1 1)",
            "0F2FF1FF2",
        ),
        # review must-fix 6: the Mod-2 rule counts first/last coordinates of all lines
        ("MULTILINESTRING ((0 0, 2 0), (1 0, 1 1))", "POINT (1 0)", "FF10F0FF2"),
        ("LINESTRING (0 0, 1 0, 0 0)", "LINESTRING (0 0, 1 0)", "10FFFFFF2"),
        # review should-change 8: a zero-length line is a point on a line
        ("LINESTRING (1 1, 1 1)", "POINT (1 1)", "0FFFFFFF2"),
        ("LINESTRING (0 0, 0 0, 2 0)", "POINT (0 0)", "FF10F0FF2"),
        # closed lines have no boundary
        ("LINESTRING (0 0, 2 0, 2 2, 0 0)", "POINT (0 0)", "0F1FFFFF2"),
        # points on polygon boundaries and on lines
        (
            "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))",
            "MULTIPOINT ((2 0), (4 4), (1 1), (9 9))",
            "0F20F10F2",
        ),
        ("LINESTRING (0 0, 4 0)", "MULTIPOINT ((2 0), (4 0), (5 0))", "0F10F00F2"),
        # a line along a polygon edge, then through it
        ("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))", "LINESTRING (1 0, 3 0, 3 2, 6 2)", "1F2101102"),
        # empty operands
        ("POLYGON EMPTY", "POINT (1 1)", "FFFFFF0F2"),
        ("GEOMETRYCOLLECTION EMPTY", "LINESTRING EMPTY", "FFFFFFFF2"),
        ("GEOMETRYCOLLECTION (POINT EMPTY, LINESTRING (0 0, 1 1))", "POINT EMPTY", "FF1FF0FF2"),
    ],
)
def test_relate_implied_by_labels(a, b, relate):
    """The DE-9IM implied by the cell labels (expected values checked with GEOS 3.13.1)."""
    assert labels_matrix(build(a, b)) == relate
    # transposing the operands transposes the matrix
    t = labels_matrix(build(b, a))
    assert t == "".join(relate[3 * c + r] for r in range(3) for c in range(3))


def test_gc_shared_edge_is_interior():
    arr = build(
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0)), "
        "POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0)))",
        "POINT (5 5)",
    )
    (e,) = [e for e in range(arr.num_edges) if len(arr.edge_sources[e]) == 2]
    assert arr.edge_loc_a[e] == I  # both incident faces are interior (AdjacentEdgeLocator)
    assert vlabel(arr, 1, 0) == "BE"  # the ends of the shared edge touch the exterior


def test_gc_overlap_face_is_interior_not_even_odd():
    arr = build(
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
        "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)))",
        "POINT (9 9)",
    )
    assert sorted(arr.face_loc_a) == [I, I, I, E]
    assert vlabel(arr, 2, 1) == "BE" and vlabel(arr, 1, 1) == "IE" and vlabel(arr, 2, 2) == "IE"


def test_mod2_vertex_labels():
    arr = build("MULTILINESTRING ((0 0, 2 0), (1 0, 1 1), (1 1, 2 2))", "POINT (1 0)")
    assert vlabel(arr, 1, 0) == "BI"  # endpoint of one line, interior of another: odd
    assert vlabel(arr, 1, 1) == "IE"  # two endpoints: even
    assert vlabel(arr, 0, 0) == "BE"


def test_vertices_are_located_in_both_operands():
    """Intersection points and isolated points get a full location in each operand."""
    arr = build(
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)), LINESTRING (4 2, 6 2))",
        "MULTILINESTRING ((2 -1, 2 5), (5 0, 5 4))",
    )
    assert vlabel(arr, 2, 0) == "BI"
    assert vlabel(arr, 5, 2) == "II"  # crossing of A's line and B's line
    assert vlabel(arr, 4, 2) == "BE"  # A's polygon boundary first, though a line ends here
    assert vlabel(arr, 2, 5) == "EB"


# ============================================================== DCEL structure


def test_island_in_hole_in_island_nesting():
    arr = build(
        "MULTIPOLYGON (((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 8 2, 8 8, 2 8, 2 2)), "
        "((4 4, 6 4, 6 6, 4 6, 4 4)))",
        "MULTIPOINT ((1 1), (3 3), (5 5), (11 11))",
    )
    loc = CellLocator(arr)
    outer_face = loc.locate((1, 1.5))[1]
    hole_face = loc.locate((3, 3.5))[1]
    island_face = loc.locate((5, 5.5))[1]
    assert len({0, outer_face, hole_face, island_face}) == 4
    assert len(arr.face_inner[0]) == 1
    # the hole ring touches nothing: it is a component nested in the annulus face...
    assert len(arr.face_inner[outer_face]) == 1
    assert len(arr.face_inner[hole_face]) == 1  # ... and the island sits in the hole face
    assert [arr.face_loc_a[f] for f in (outer_face, hole_face, island_face)] == [I, E, I]
    assert vertex_at(arr, 3, 3) in arr.face_isolated[hole_face]
    assert vertex_at(arr, 11, 11) in arr.face_isolated[0]


def test_disconnected_ring_of_a_polygon_is_an_inner_component():
    arr = build(
        "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (4 4, 6 4, 6 6, 4 6, 4 4))", "POINT (20 20)"
    )
    (annulus,) = [f for f in range(arr.num_faces) if arr.face_loc_a[f] == I]
    assert len(arr.face_inner[annulus]) == 1
    assert face_area2(arr, annulus) == 2 * 96


def test_degree_one_vertices_turn_around():
    arr = build("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))", "LINESTRING (1 1, 2 2, 3 1)")
    for x, y in ((1, 1), (3, 1)):
        v = vertex_at(arr, x, y)
        (g,) = arr.outgoing(v)
        assert arr.he_next[g ^ 1] == g
    # the tree is an inner component of the square's interior face (a zero-area cycle)
    f = arr.he_face[next(arr.outgoing(vertex_at(arr, 2, 2)))]
    assert arr.face_loc_a[f] == I and len(arr.face_inner[f]) == 1


@pytest.mark.parametrize(
    "b",
    [
        # the ray from the island's leftmost vertex (3, 2) passes exactly through (0, 2)
        "POLYGON ((3 2, 4 1, 5 2, 4 3, 3 2))",
        # ... along a horizontal edge of another component
        "MULTIPOLYGON (((1 2, 2 2, 2 3, 1 3, 1 2)), ((3 2, 4 1, 5 2, 4 3, 3 2)))",
        # ... through a vertex whose wedges are all of one outer cycle
        "MULTILINESTRING ((1 1, 2 2, 1 3), (3 2, 5 2))",
    ],
)
def test_ray_shooting_through_vertices_and_horizontal_edges(b):
    arr = build("POLYGON ((0 0, 6 0, 6 4, 0 4, 0 2, 0 0))", b)
    assert all(c >= 0 for c in arr.face_loc_b)


def test_components_located_through_other_components():
    """C's ray hits D's outer cycle, so C lies in D's containing face."""
    arr = build(
        "POLYGON ((0 0, 20 0, 20 10, 0 10, 0 0))",
        "MULTIPOLYGON (((2 2, 4 2, 4 8, 2 8, 2 2)), ((6 4, 8 4, 8 6, 6 6, 6 4)), "
        "((10 1, 12 1, 12 9, 10 9, 10 1)))",
    )
    (big,) = [f for f in range(arr.num_faces) if (arr.face_loc_a[f], arr.face_loc_b[f]) == (I, E)]
    assert len(arr.face_inner[big]) == 3


def test_isolated_points_merge_and_split():
    arr = build(
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))",
        "MULTIPOINT ((0 0), (2 0), (2 0), (1 1), (4 1))",
    )
    assert arr.num_vertices == 4 + 3  # (0 0) merged; (2 0), (4 1) split edges; (1 1) isolated
    assert arr.num_edges == 6
    assert arr.is_isolated(vertex_at(arr, 1, 1))
    assert vlabel(arr, 2, 0) == "BI" and vlabel(arr, 0, 0) == "BI"


def test_point_at_a_crossing():
    arr = build("LINESTRING (0 0, 2 2)", "GEOMETRYCOLLECTION (LINESTRING (0 2, 2 0), POINT (1 1))")
    assert vlabel(arr, 1, 1) == "II" and arr.degree(vertex_at(arr, 1, 1)) == 4


def test_collinear_overlaps_merge_sources():
    arr = build("LINESTRING (0 0, 4 0, 2 0, 6 0)", "LINESTRING (1 0, 5 0)")
    e = next(
        e
        for e in range(arr.num_edges)
        if arr.tags(e) == {SourceTag.for_line(GEOM_A, 0), SourceTag.for_line(GEOM_B, 0)}
        and len(arr.edge_sources[e]) == 4
    )
    # the retraced part (2 0)-(4 0) carries A three times, in both directions, and B once
    assert sorted(s.forward for s in arr.edge_sources[e] if s.tag.geom == GEOM_A).count(True) == 2
    assert arr.num_faces == 1


def test_non_dyadic_rational_input():
    third = Fraction(1, 3)
    a = Polygon([[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]])
    b = Polygon([[(third, third), (2, third), (2, 2 * third), (third, 2 * third), (third, third)]])
    arr = build_arrangement(a, b)
    arr.validate(geometry=True, planarity=True, labels=True)
    check_labels(arr, a, b)
    assert labels_matrix(arr) == "212101212"
    assert (Fraction(1), third) in {arr.vertex_fractions(v) for v in range(arr.num_vertices)}


def test_huge_and_tiny_coordinates():
    for s in (2.0**-1070, 2.0**-600, 1.0, 2.0**600, 2.0**1000):
        a = Polygon([[(0.0, 0.0), (3 * s, 0.0), (3 * s, 3 * s), (0.0, 0.0)]])
        b = GeometryCollection([LineString([(s, -s), (s, 5 * s)]), Point((2 * s, s))])
        arr = build_arrangement(a, b)
        arr.validate(geometry=True, planarity=True, labels=True)
        assert labels_matrix(arr) == "1F20F1102", s
    mixed = build_arrangement(
        Polygon([[(0.0, 0.0), (1e300, 0.0), (0.0, 1e300), (0.0, 0.0)]]),
        Point((5e-324, 5e-324)),
    )
    mixed.validate(geometry=True, planarity=True, labels=True)
    assert labels_matrix(mixed) == "0F2FF1FF2"


# ===================================================== invariance under transforms


def _transforms():
    return [
        lambda p: (p[1], p[0]),  # reflection: reverses every orientation
        lambda p: (-p[1], p[0]),  # rotation by 90 degrees
        lambda p: (-p[0], -p[1]),
        lambda p: (p[0] + 7, p[1] - 3),
        lambda p: (p[0] * 0.25, p[1] * 8),
    ]


@pytest.mark.parametrize("seed", range(30))
def test_labels_invariant_under_exact_transforms(seed):
    rng = random.Random(seed)
    a, b = random_operand(rng, 5), random_operand(rng, 5)
    base = build_arrangement(a, b)
    counts = sorted((c.dim, c.loc_a, c.loc_b) for c in base.cells())
    for fn in _transforms():
        ta, tb = a.map_coords(fn), b.map_coords(fn)
        arr = build_arrangement(ta, tb)
        arr.validate(geometry=True, labels=True)
        assert labels_matrix(arr) == labels_matrix(base)
        assert sorted((c.dim, c.loc_a, c.loc_b) for c in arr.cells()) == counts


# ============================================================== random lattice cases


@pytest.mark.parametrize("seed", range(120))
def test_random_lattice_case(seed):
    """Random points, lines, polygons and collections on a small lattice (many exact
    degeneracies): every invariant, Euler, and every label against brute force."""
    rng = random.Random(1000 + seed)
    size = 3 if seed % 3 == 0 else 6
    a, b = random_operand(rng, size), random_operand(rng, size)
    arr = build_arrangement(a, b)
    arr.validate(geometry=True, planarity=True, labels=True)
    assert arr.num_vertices - arr.num_edges + arr.num_faces == 1 + components(arr)
    check_labels(arr, a, b, random_face_points(rng, arr, 25))


def test_bounded_face_areas_sum_to_the_enclosed_area():
    rng = random.Random(7)
    for _ in range(20):
        a, b = random_operand(rng, 6), random_operand(rng, 6)
        arr = build_arrangement(a, b)
        total = sum(face_area2(arr, f) for f in range(1, arr.num_faces))
        outer = sum(-face_area2_of_cycle(arr, h) for h in arr.face_inner[0])  # top-level components
        assert total == outer
        assert all(face_area2(arr, f) > 0 for f in range(1, arr.num_faces))


def face_area2_of_cycle(arr, h):
    from geotruth.exact import signed_area2

    from .arrangement_testlib import cycle_points

    return signed_area2(cycle_points(arr, h))


def test_brute_locator_self_check():
    """The reference locator itself, on hand-checked points."""
    gc = read_wkt(
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0)), "
        "POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0)), LINESTRING (3 0, 4 0), POINT (5 5))"
    )
    loc = BruteLocator(gc)
    assert loc.locate((1, Fraction(1, 2))) == I  # shared edge between two polygons
    assert loc.locate((1, 1)) == B
    assert loc.locate((Fraction(1, 2), Fraction(1, 2))) == I
    assert loc.locate((3, 0)) == B and loc.locate((Fraction(7, 2), 0)) == I
    assert loc.locate((5, 5)) == I and loc.locate((6, 6)) == E


# ================================================================== determinism


def test_builds_are_deterministic():
    rng = random.Random(3)
    a, b = random_operand(rng, 6), random_operand(rng, 6)
    one, two = build_arrangement(a, b), build_arrangement(a, b)
    for attr in (
        "vx",
        "vy",
        "vw",
        "he_origin",
        "he_next",
        "he_face",
        "edge_sources",
        "face_outer",
        "face_inner",
        "face_isolated",
        "vertex_loc_a",
        "edge_loc_b",
    ):
        assert getattr(one, attr) == getattr(two, attr), attr


# ====================================================================== errors


@pytest.mark.parametrize(
    ("a", "why"),
    [
        (Polygon([[(0, 0), (1, 0), (1, 1), (0, 1)]]), "not closed"),
        (Polygon([[(0, 0), (1, 0), (2, 0), (0, 0)]]), "zero area"),
        (Polygon([[(0, 0), (1, 1), (1, 0), (0, 1), (0, 0)]]), "zero area"),  # symmetric bowtie
        (Polygon([[(0, 0), (2, 2), (2, 0), (0, 1), (0, 0)]]), "not valid"),  # asymmetric bowtie
        (
            Polygon([[(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)], [(5, 5), (6, 5), (6, 6), (5, 5)]]),
            "not valid",
        ),  # hole outside the shell
        (
            read_wkt("MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 1, 3 1, 3 3, 1 3, 1 1)))"),
            "not valid",
        ),  # overlapping parts
        (
            read_wkt(
                "POLYGON ((0 0, 9 0, 9 9, 0 9, 0 0), (1 1, 8 1, 8 8, 1 8, 1 1), "
                "(2 2, 3 2, 3 3, 2 2))"
            ),
            "not valid",
        ),  # nested holes
        (Point((float("nan"), 0.0)), "invalid coordinate"),
        (LineString([(0.0, 0.0), (float("inf"), 1.0)]), "invalid coordinate"),
    ],
)
def test_invalid_input_is_rejected(a, why):
    with pytest.raises(InvalidInputError, match=why):
        build_arrangement(a, Point((0, 0)))
    with pytest.raises(InvalidInputError, match=why):
        build_arrangement(Point((0, 0)), a)


def test_gc_with_overlapping_polygons_is_accepted():
    gc = read_wkt(
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
        "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))"
    )
    arr = build_arrangement(gc, Point((1, 1)))
    arr.validate(geometry=True, planarity=True, labels=True)
    assert labels_matrix(arr) == "0F2FF1FF2"


# ====================================================================== budget


def _comb(n: int, vertical: bool) -> Polygon:
    pts = []
    for i in range(n):
        pts += [(float(i), 0.0), (i + 0.5, float(n))]
    pts += [(float(n), -1.0), (0.0, -1.0)]
    if vertical:
        pts = [(y, x) for x, y in pts]
    return Polygon([[*pts, pts[0]]])


def test_budget_size_cap():
    a, b = _comb(30, False), _comb(30, True)
    stats = {}
    arr = build_arrangement(a, b, stats=stats)
    assert stats["n"] + stats["k"] > 1000
    assert stats["V"] == arr.num_vertices and stats["F"] == arr.num_faces
    with pytest.raises(BudgetExceeded) as info:
        build_arrangement(a, b, budget=Budget(max_size=1000))
    assert info.value.resource == "size" and info.value.limit == 1000
    assert info.value.phase == "intersect"
    with pytest.raises(BudgetExceeded):
        build_arrangement(a, b, budget=Budget(max_size=10))  # n alone is over


def test_budget_time_and_memory():
    a, b = _comb(10, False), _comb(10, True)
    with pytest.raises(BudgetExceeded) as info:
        build_arrangement(a, b, budget=Budget(max_seconds=0.0))
    assert info.value.resource == "time"
    with pytest.raises(BudgetExceeded) as info:
        build_arrangement(a, b, budget=Budget(max_memory_mb=1.0))
    assert info.value.resource == "memory"
    build_arrangement(a, b, budget=None)
    assert DEFAULT_BUDGET.max_size == 200_000


def test_budget_exception_is_not_a_value_error():
    """The caller maps BudgetExceeded to engine_skipped; it must not be mistaken for
    invalid input (a ValueError)."""
    assert not issubclass(BudgetExceeded, ValueError)
    assert issubclass(InvalidInputError, ValueError)


def test_stats_and_empty_operands():
    stats = {}
    arr = build_arrangement(MultiPoint([]), GeometryCollection([]), stats=stats)
    assert (arr.num_vertices, arr.num_edges, arr.num_faces) == (0, 0, 1)
    assert stats["n"] == 0 and stats["F"] == 1 and "t_total" in stats
    arr.validate(geometry=True, planarity=True, labels=True)
    assert arr.ring_orientation == {}
    assert arr.a is not None and arr.b is not None
    assert GEOM_A == 0 and GEOM_B == 1


def test_direct_ring_rule_catches_what_coverage_sums_miss():
    """A GC whose two polygons have consistent coverage *sums* but where one element is
    a self-crossing ring: the half-edge-on-ring rule sees the triangle's interior on the
    left of an edge whose face has coverage 0."""
    lobe = "POLYGON ((2 2, 0 3, 0 0, 2 2))"  # the small lobe of the bowtie below
    bowtie = "POLYGON ((0 0, 6 6, 6 0, 0 3, 0 0))"  # clockwise overall; its small lobe is CCW
    gc = read_wkt(f"GEOMETRYCOLLECTION ({lobe}, {bowtie})")
    with pytest.raises(InvalidInputError, match="on its left"):
        build_arrangement(gc, Point((9, 9)))


def test_empty_rings_and_elements_are_skipped():
    a = GeometryCollection(
        [
            Polygon([[(0, 0), (4, 0), (4, 4), (0, 4), (0, 0)], []]),
            Polygon(),
            LineString(),
            Point(),
        ]
    )
    arr = build_arrangement(a, Point((1, 1)))
    arr.validate(geometry=True, planarity=True, labels=True)
    assert labels_matrix(arr) == "0F2FF1FF2"
    assert list(arr.ring_orientation) == [SourceTag.for_ring(GEOM_A, 0, 0)]


@pytest.mark.parametrize("seed", range(12))
def test_random_points_against_oracle_point_in(seed):
    """Random exact points (small denominators, so some fall on edges and vertices): the
    label of the cell containing each equals the audited oracle's point_in."""
    from gmpy2 import mpq

    from reference import oracle

    from .arrangement_testlib import random_multipolygon

    rng = random.Random(4000 + seed)
    a, b = random_multipolygon(rng, 6), random_multipolygon(rng, 6)

    def legacy(g):
        polys = [g] if isinstance(g, Polygon) else list(g.polygons)
        return [[[[float(x), float(y)] for x, y in r] for r in p.rings] for p in polys]

    ea, eb = oracle.edges(legacy(a)), oracle.edges(legacy(b))
    arr = build_arrangement(a, b)
    loc = CellLocator(arr)
    code = {1: I, 0: B, -1: E}
    pts = random_face_points(rng, arr, 60) + [
        arr.vertex_fractions(v) for v in range(arr.num_vertices)
    ]
    for p in pts:
        q = (mpq(p[0].numerator, p[0].denominator), mpq(p[1].numerator, p[1].denominator))
        assert loc.label(loc.locate(p)) == (
            code[oracle.point_in(q, ea)],
            code[oracle.point_in(q, eb)],
        )
