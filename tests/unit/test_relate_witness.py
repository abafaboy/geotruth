"""Unit tests of the witness-point relate (DESIGN §2.4)."""

from __future__ import annotations

import json
import math
import random
from fractions import Fraction

import pytest

from geotruth.exact import hp_on_segment
from geotruth.geom import Geometry, LineString, Point, Polygon
from geotruth.io import read_wkt
from geotruth.numbers import NonFiniteError
from geotruth.predicates import matrix_problems, transpose
from geotruth.relate_witness import (
    ENTRY_NAMES,
    KIND_EDGE,
    KIND_FACE_NORMAL,
    KIND_FACE_RAY,
    KIND_FAR,
    KIND_INTERSECTION,
    KIND_VERTEX,
    relate,
    relate_witness,
)

from .fixtures_arrangement import FIXTURES
from .witness_lattice import random_pair

SQ = "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))"

# (A, B, matrix): every type pair P/L/A x P/L/A, the mod-2 rule, closed and zero-length
# lines, holes, and the GC union semantics of the design review. Each matrix was derived
# by hand; those not involving a GEOS defect (see the crosscheck suite) also agree with
# GEOS 3.13.1.
HAND_CASES = [
    # ---------------------------------------------------------------------- P/P
    ("POINT (0 0)", "POINT (0 0)", "0FFFFFFF2"),
    ("POINT (0 0)", "POINT (1 1)", "FF0FFF0F2"),
    ("MULTIPOINT ((0 0), (1 1))", "POINT (1 1)", "0F0FFFFF2"),
    ("MULTIPOINT ((0 0), (1 1))", "MULTIPOINT ((1 1), (2 2))", "0F0FFF0F2"),
    ("MULTIPOINT ((0 0), (0 0))", "POINT (0 0)", "0FFFFFFF2"),
    # ---------------------------------------------------------------------- P/L
    ("POINT (1 0)", "LINESTRING (0 0, 2 0)", "0FFFFF102"),
    ("POINT (0 0)", "LINESTRING (0 0, 2 0)", "F0FFFF102"),
    ("POINT (5 5)", "LINESTRING (0 0, 2 0)", "FF0FFF102"),
    ("POINT (0 0)", "LINESTRING (0 0, 1 0, 1 1, 0 0)", "0FFFFF1F2"),
    ("MULTIPOINT ((0 0), (1 0), (3 0))", "LINESTRING (0 0, 2 0)", "000FFF102"),
    ("POINT (1 0)", "MULTILINESTRING ((0 0, 2 0), (1 0, 1 1))", "F0FFFF102"),
    # ---------------------------------------------------------------------- P/A
    ("POINT (1 1)", SQ, "0FFFFF212"),
    ("POINT (0 0)", SQ, "F0FFFF212"),
    ("POINT (4 2)", SQ, "F0FFFF212"),
    ("POINT (9 9)", SQ, "FF0FFF212"),
    ("MULTIPOINT ((1 1), (4 2), (9 9))", SQ, "000FFF212"),
    # ---------------------------------------------------------------------- L/P
    ("LINESTRING (0 0, 2 0)", "POINT (1 0)", "0F1FF0FF2"),
    ("LINESTRING (0 0, 2 0)", "POINT (2 0)", "FF10F0FF2"),
    # the design review's mod-2 cases
    ("MULTILINESTRING ((0 0, 2 0), (1 0, 1 1))", "POINT (1 0)", "FF10F0FF2"),
    ("LINESTRING (1 1, 1 1)", "POINT (1 1)", "0FFFFFFF2"),  # zero-length line: a point
    # ---------------------------------------------------------------------- L/L
    ("LINESTRING (0 0, 2 2)", "LINESTRING (0 2, 2 0)", "0F1FF0102"),
    ("LINESTRING (0 0, 3 1)", "LINESTRING (0 1, 2 0)", "0F1FF0102"),  # at (6/5, 2/5)
    ("LINESTRING (0 0, 2 0)", "LINESTRING (1 0, 3 0)", "1010F0102"),
    ("LINESTRING (0 0, 2 0)", "LINESTRING (2 0, 0 0)", "1FFF0FFF2"),
    ("LINESTRING (0 0, 1 0)", "LINESTRING (1 0, 2 0)", "FF1F00102"),
    ("LINESTRING (0 0, 2 0)", "LINESTRING (1 0, 1 1)", "F01FF0102"),
    ("LINESTRING (0 0, 1 0, 0 0)", "LINESTRING (0 0, 1 0)", "10FFFFFF2"),  # review
    ("LINESTRING (0 0, 4 0)", "LINESTRING (1 0, 2 0, 2 1, 3 1, 3 0)", "101FF01F2"),
    ("LINESTRING (0 0, 2 0, 2 2, 0 0)", "LINESTRING (0 0, 2 0, 2 2, 0 0)", "1FFFFFFF2"),
    ("MULTILINESTRING ((0 0, 1 0), (1 0, 2 0))", "LINESTRING (0 0, 2 0)", "1FFF0FFF2"),
    (
        "MULTILINESTRING ((0 0, 1 0), (1 0, 2 0), (1 0, 1 1))",
        "LINESTRING (0 0, 2 0)",
        "1F1000FF2",
    ),  # (1 0) has degree 3: boundary of A, interior of B
    # ---------------------------------------------------------------------- L/A
    ("LINESTRING (1 1, 2 2)", SQ, "1FF0FF212"),
    ("LINESTRING (2 2, 6 2)", SQ, "1010F0212"),
    ("LINESTRING (0 0, 4 0)", SQ, "F1FF0F212"),
    ("LINESTRING (4 2, 6 2)", SQ, "FF1F00212"),
    ("LINESTRING (3 5, 5 3)", SQ, "F01FF0212"),
    ("LINESTRING (-1 0, 5 0)", SQ, "F11FF0212"),
    ("LINESTRING (1 1, 3 1, 3 3, 1 1)", SQ, "1FFFFF212"),  # closed line inside
    # ---------------------------------------------------------------------- A/P, A/L
    (SQ, "POINT (1 1)", "0F2FF1FF2"),
    (SQ, "LINESTRING (2 2, 6 2)", "1020F1102"),
    # ---------------------------------------------------------------------- A/A
    (SQ, "POLYGON ((5 0, 6 0, 6 1, 5 0))", "FF2FF1212"),
    (SQ, "POLYGON ((2 2, 6 2, 6 6, 2 6, 2 2))", "212101212"),
    (SQ, "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))", "212FF1FF2"),
    (SQ, "POLYGON ((4 4, 0 4, 0 0, 4 0, 4 4))", "2FFF1FFF2"),
    (SQ, "POLYGON ((4 0, 6 0, 6 4, 4 4, 4 0))", "FF2F11212"),
    (SQ, "POLYGON ((4 4, 6 4, 6 6, 4 6, 4 4))", "FF2F01212"),
    (SQ, "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))", "212F11FF2"),
    (
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 3 1, 3 3, 1 3, 1 1))",
        "POLYGON ((1.5 1.5, 2.5 1.5, 2.5 2.5, 1.5 2.5, 1.5 1.5))",
        "FF2FF1212",
    ),
    (
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 3 1, 3 3, 1 3, 1 1))",
        "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))",
        "FF2F112F2",
    ),  # the hole is A's exterior
    (
        "MULTIPOLYGON (((0 0, 1 0, 1 1, 0 1, 0 0)), ((1 1, 2 1, 2 2, 1 2, 1 1)))",
        "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))",
        "2FF11F212",
    ),
    # ------------------------------------------------ GC union semantics (review)
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
    (
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0)), "
        "POLYGON ((2 0, 3 -1, 1 -1, 2 0)))",
        "POINT (2 0)",
        "FF20F1FF2",
    ),
    (
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (0 0, 2 2))",
        "LINESTRING (0 0, 2 2)",
        "1F2F01FF2",
    ),
    (
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (-1 0, 3 0))",
        "LINESTRING (0 0, 2 0)",
        "FF2101FF2",
    ),
    # ---------------------- GEOS 3.13.1 answers these wrongly (see the crosscheck suite)
    (
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)), POINT (10 10))",
        "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))",
        "212FF1FF2",
    ),
    ("POINT (10 10)", "MULTILINESTRING ((0 0, 1 0, 1 1, 0 0), (5 5, 6 6))", "FF0FFF102"),
    (
        "LINESTRING (0 0, 1 0)",
        "GEOMETRYCOLLECTION (MULTIPOINT ((1 0), (0 0)), LINESTRING (5 5, 6 6))",
        "FF10FF102",
    ),
    (
        "GEOMETRYCOLLECTION (POLYGON ((3 2, 3 1, 1 0, 3 2)), MULTIPOINT ((3 4)))",
        "LINESTRING (3 4, 4 3, 3 4)",
        "0F2FF11F2",
    ),
    # ------------------------------------------------------------------ empties
    ("POINT EMPTY", SQ, "FFFFFF212"),
    (SQ, "LINESTRING EMPTY", "FF2FF1FF2"),
    ("POLYGON EMPTY", "GEOMETRYCOLLECTION EMPTY", "FFFFFFFF2"),
    ("GEOMETRYCOLLECTION (POINT EMPTY, LINESTRING (0 0, 1 1))", "POINT (0 0)", "FF10F0FF2"),
]


@pytest.mark.parametrize(("a", "b", "expected"), HAND_CASES)
def test_hand_cases(a, b, expected):
    ga, gb = read_wkt(a), read_wkt(b)
    assert relate(ga, gb) == expected
    assert relate(gb, ga) == transpose(expected)


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_fixture_matrices(name):
    spec = FIXTURES[name]
    a, b = read_wkt(spec.a), read_wkt(spec.b)
    assert relate(a, b) == spec.relate
    assert relate(b, a) == transpose(spec.relate)


# ========================================================== result structure


def test_result_structure_and_realizers():
    a = read_wkt("POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))")
    b = read_wkt("POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))")
    res = relate_witness(a, b, keep_witnesses=True)
    assert res.matrix == "212101212"
    assert (res.dim_a, res.dim_b) == (2, 2)
    assert res.num_segments == 8
    assert res.num_intersections == 2  # (2 1) and (1 2)
    assert res.num_subsegments == 12
    kinds = {w.kind for w in res.witnesses}
    assert kinds == {
        KIND_VERTEX,
        KIND_INTERSECTION,
        KIND_EDGE,
        KIND_FACE_NORMAL,
        KIND_FACE_RAY,
        KIND_FAR,
    }
    assert sum(res.counts.values()) == len(res.witnesses)
    for name in ENTRY_NAMES:
        dim = res.entry(name)
        if dim < 0:
            assert name not in res.realizers
            continue
        w = res.realizers[name]
        assert w.label == name and w.dim == dim
    assert res.real_point(res.realizers["BB"]) in {(2, 1), (1, 2)}
    d = res.to_dict()
    json.dumps(d)
    assert d["matrix"] == "212101212" and d["entries"]["BB"]["dim"] == 0
    preds = res.predicates()
    assert preds["overlaps"].value and not preds["touches"].value


def test_witnesses_are_on_their_cells():
    """Face witnesses avoid every segment, edge witnesses lie on one, and every vertex
    witness is an input vertex or an intersection."""
    rng = random.Random(5)
    for i in range(60):
        _, _, a, b = random_pair(rng, i)
        res = relate_witness(a, b, keep_witnesses=True)
        to_pt = res.frame.to_int_point
        segs = []
        for g in (a, b):
            for s in g.iter_segments():
                segs.append((to_pt(s.p), to_pt(s.q)))
            for r in g.iter_rings():  # implicit closing segments of unclosed rings: none
                assert r.coords[0] == r.coords[-1]
        for w in res.witnesses:
            on = [hp_on_segment(w.point, p, q) for p, q in segs]
            if w.kind in (KIND_FACE_NORMAL, KIND_FACE_RAY, KIND_FAR):
                assert not any(on), (a.wkt, b.wkt, w)
            elif w.kind == KIND_EDGE:
                assert any(on)


def test_check_false_gives_the_same_matrix():
    rng = random.Random(11)
    for i in range(80):
        _, _, a, b = random_pair(rng, i)
        full = relate_witness(a, b)
        fast = relate_witness(a, b, check=False)
        assert full.matrix == fast.matrix
        assert KIND_FACE_RAY not in fast.counts


# ============================================================== properties


def _map(g: Geometry, fn) -> Geometry:
    return g.map_coords(fn)


def test_transpose_symmetry_and_dimension_consistency():
    rng = random.Random(1)
    for i in range(300):
        _, _, a, b = random_pair(rng, i)
        m = relate(a, b)
        assert relate(b, a) == transpose(m), (a.wkt, b.wkt)
        assert matrix_problems(m, a.real_dimension, b.real_dimension) == [], (a.wkt, b.wkt, m)


@pytest.mark.parametrize(
    "transform",
    [
        pytest.param(lambda c: (c[0] + 3.0, c[1] - 7.0), id="translate"),
        pytest.param(lambda c: (c[0] * 2.0**-900, c[1] * 2.0**-900), id="scale-2^-900"),
        pytest.param(lambda c: (c[0] * 2.0**700, c[1] * 2.0**700), id="scale-2^700"),
        pytest.param(lambda c: (c[1], c[0]), id="swap-xy"),
        pytest.param(lambda c: (-c[1], c[0]), id="rotate-90"),
        pytest.param(lambda c: (-c[0], c[1]), id="mirror"),
        pytest.param(lambda c: (c[0] + c[1], c[1]), id="shear"),
    ],
)
def test_invariance_under_exact_transforms(transform):
    rng = random.Random(2)
    for i in range(120):
        _, _, a, b = random_pair(rng, i)
        assert relate(_map(a, transform), _map(b, transform)) == relate(a, b), (a.wkt, b.wkt)


def test_subnormal_coordinates():
    tiny = 5e-324  # the smallest subnormal
    a = LineString([(0.0, 0.0), (2 * tiny, 2 * tiny)])
    b = LineString([(0.0, 2 * tiny), (2 * tiny, 0.0)])
    assert relate(a, b) == "0F1FF0102"


def test_ulp_level_near_degeneracy():
    # B's vertex is one ulp above A's top edge (1.0): disjoint vs touching is exact
    up = math.nextafter(1.0, 2.0)
    a = read_wkt("POLYGON ((0 0, 2 0, 2 1, 0 1, 0 0))")
    b_touch = Polygon([[(1.0, 1.0), (2.0, 2.0), (0.0, 2.0), (1.0, 1.0)]])
    b_apart = Polygon([[(1.0, up), (2.0, 2.0), (0.0, 2.0), (1.0, up)]])
    assert relate(a, b_touch) == "FF2F01212"
    assert relate(a, b_apart) == "FF2FF1212"


def test_rational_input_geometries():
    third = Fraction(1, 3)
    a = Polygon([[(0, 0), (1, 0), (1, 1), (0, 1), (0, 0)]])
    b = LineString([(third, third), (third, 2)])
    assert relate(a, b) == "1020F1102"
    c = Point((third, 1))
    assert relate(a, c) == "FF20F1FF2"


def test_nonfinite_coordinates_raise():
    with pytest.raises(NonFiniteError):
        relate(read_wkt("POINT (NaN 1)"), read_wkt("POINT (1 1)"))


def test_split_at_isolated_points_and_zero_length_lines():
    # a Point and a zero-length line in the middle of B's segment must split it
    a = read_wkt("GEOMETRYCOLLECTION (POINT (1 0), LINESTRING (3 0, 3 0))")
    b = read_wkt("LINESTRING (0 0, 4 0)")
    res = relate_witness(a, b, keep_witnesses=True)
    assert res.matrix == "0FFFFF102"
    assert res.num_subsegments == 3


def test_collinear_overlaps_share_subsegments():
    a = read_wkt("LINESTRING (0 0, 4 0)")
    b = read_wkt("MULTILINESTRING ((1 0, 3 0), (2 -1, 2 1))")
    res = relate_witness(a, b)
    # A is split at 1, 2, 3 and B's pieces coincide with A's: 4 + 2 (vertical) sub-segments
    assert res.num_subsegments == 6
    assert res.matrix == "101FF0102"  # B's ends (1 0), (3 0) lie in A's interior


def test_self_intersecting_line_nodes():
    # a self-crossing (valid) line: its crossing point (1 1) is a split point
    a = read_wkt("LINESTRING (0 0, 2 2, 2 0, 0 2)")
    res = relate_witness(a, read_wkt("POINT (5 5)"))
    assert res.num_intersections == 1
    assert res.matrix == "FF1FF00F2"
    # the crossing coinciding with an input point is a vertex, not an intersection
    res = relate_witness(a, read_wkt("POINT (1 1)"))
    assert res.num_intersections == 0
    assert res.matrix == "0F1FF0FF2"


def test_long_chains_are_fine():
    pts = [(float(i), float(i % 2)) for i in range(60)]
    a = LineString(pts)
    b = LineString([(p[0], 1.0 - p[1]) for p in pts])
    res = relate_witness(a, b)
    assert res.matrix == "0F1FF0102"
    assert res.num_intersections == 59
