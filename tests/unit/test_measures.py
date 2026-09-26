"""Unit tests of the exact measures (DESIGN §1 "Measures", §2.7)."""

from __future__ import annotations

import math
import random
from fractions import Fraction as F
from itertools import pairwise
from pathlib import Path

import pytest

from geotruth import measures as M
from geotruth.geom import GeometryCollection, LineString, MultiPoint, Point, Polygon
from geotruth.io import read_wkt
from geotruth.numbers import NonFiniteError, json_loads

gmpy2 = pytest.importorskip("gmpy2")


def W(text):
    return read_wkt(text)


# ------------------------------------------------------------------------ scaling


def test_coord_scale_is_exact():
    s = M.CoordScale.for_values([0.5, 0.25, 3.0, math.nan, F(1, 3)])
    assert s.den == 12
    assert s.to_int(0.25) == 3 and s.to_int(F(1, 3)) == 4 and s.to_int(7) == 84
    assert s.value(3) == F(1, 4) and s.area(12) == F(1, 12)
    assert s.rational_hpoint((1, 2, 3)) == (F(1, 36), F(2, 36))
    assert M.CoordScale.rational_point((0.1, 2)) == (F(0.1), 2)
    with pytest.raises(NonFiniteError):
        s.to_int(math.inf)
    with pytest.raises(ValueError, match="multiple"):
        M.CoordScale(2).to_int(0.25)


# ------------------------------------------------------------------------ area


def test_area_exact():
    assert M.area(W("POLYGON ((0 0, 0 4, 4 4, 4 0, 0 0), (1 1, 2 1, 2 2, 1 2, 1 1))")) == 15
    assert M.area(W("POLYGON ((0 0, 1 0, 0 1, 0 0))")) == F(1, 2)
    assert M.area(W("POLYGON ((0 0, 0.1 0, 0 0.1, 0 0))")) == F(0.1) ** 2 / 2
    assert M.area(W("LINESTRING (0 0, 1 1)")) == 0
    assert M.area(W("POINT EMPTY")) == 0
    # JTS semantics: elements are summed even when they overlap
    gc = (
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
        "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)))"
    )
    assert M.area(W(gc)) == 8
    # beyond the double range: exact rational, no overflow
    big = M.area(W("POLYGON ((0 0, 1e300 0, 1e300 1e300, 0 1e300, 0 0))"))
    assert big == F(1e300) ** 2
    tiny = M.area(W("POLYGON ((0 0, 5e-324 0, 5e-324 5e-324, 0 5e-324, 0 0))"))
    assert tiny == F(5e-324) ** 2
    # rational coordinates (engine output)
    tri = Polygon([[(F(0), F(0)), (F(1, 3), F(0)), (F(0), F(1, 7)), (F(0), F(0))]])
    assert M.area(tri) == F(1, 42)
    with pytest.raises(NonFiniteError):
        M.area(Polygon([[(0.0, 0.0), (math.nan, 0.0), (1.0, 1.0), (0.0, 0.0)]]))


# ------------------------------------------------------------------------ distance


def test_distance2_primitives():
    d = M.distance2
    assert d(W("POINT (0 0)"), W("POINT (3 4)")) == 25
    assert d(W("POINT (0 0)"), W("LINESTRING (1 3, 3 1)")) == 8
    assert d(W("POINT (0 0)"), W("LINESTRING (1 0, 0 2)")) == F(4, 5)  # foot inside
    assert d(W("LINESTRING (0 0, 2 2)"), W("LINESTRING (0 2, 2 0)")) == 0
    assert d(W("LINESTRING (0 0, 1 0)"), W("LINESTRING (0 1, 1 1)")) == 1
    assert d(W("LINESTRING (0 0, 1 0)"), W("LINESTRING (3 0, 5 0)")) == 4
    assert d(W("POINT (0.1 0)"), W("POINT (0 0)")) == F(0.1) ** 2
    assert d(W("POINT EMPTY"), W("POINT (0 0)")) is None
    assert d(W("LINESTRING (1 1, 1 1)"), W("POINT (1 2)")) == 1  # zero-length line


def test_distance2_areas():
    d = M.distance2
    square = W("POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 8 2, 8 8, 2 8, 2 2))")
    assert d(square, W("POINT (1 1)")) == 0  # inside
    assert d(square, W("POINT (5 5)")) == 9  # in the hole
    assert d(square, W("POINT (5 12)")) == 4
    assert d(square, W("POLYGON ((4 4, 6 4, 6 6, 4 6, 4 4))")) == 4  # island in the hole
    assert d(square, W("POLYGON ((-5 -5, 20 -5, 20 20, -5 20, -5 -5))")) == 0  # contains it
    assert d(square, W("LINESTRING (3 3, 4 4)")) == 1
    gc = W("GEOMETRYCOLLECTION (POINT (100 100), LINESTRING (11 0, 11 10))")
    assert d(square, gc) == 1


def test_nearest_points_are_exact():
    rng = random.Random(7)
    for _ in range(200):
        a = LineString([(float(rng.randint(-5, 5)), float(rng.randint(-5, 5))) for _ in range(3)])
        b = Point((float(rng.randint(-5, 5)), float(rng.randint(-5, 5))))
        p, q = M.nearest_points(a, b)
        d2 = M.distance2(a, b)
        assert (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 == d2
        assert q == (F(b.coord[0]), F(b.coord[1]))
    assert M.nearest_points(W("POINT (0 0)"), W("LINESTRING (1 0, 0 2)")) == (
        (0, 0),
        (F(4, 5), F(2, 5)),
    )


def test_distance2_brute_force_agrees():
    """The pruned search against an exhaustive one over all element pairs."""
    rng = random.Random(3)

    def rand_line(n):
        return LineString(
            [(float(rng.randint(-20, 20)), float(rng.randint(-20, 20))) for _ in range(n)]
        )

    for _ in range(100):
        a, b = rand_line(rng.randint(1, 6)), rand_line(rng.randint(2, 6))
        best = None
        pa, pb = a.coords, b.coords
        for i in range(max(1, len(pa) - 1)):
            for j in range(len(pb) - 1):
                u = (pa[i], pa[min(i + 1, len(pa) - 1)])
                v = (pb[j], pb[j + 1])
                cand = _seg_seg_d2(u, v)
                best = cand if best is None or cand < best else best
        assert M.distance2(a, b) == best


def _seg_seg_d2(u, v):
    from geotruth import exact as X

    (a, b), (c, d) = [tuple(tuple(int(t) for t in p) for p in s) for s in (u, v)]
    n, den = X.sqdist_segment_segment(a, b, c, d)
    return F(n, den)


# ------------------------------------------------------------------------ certified


def _mpfr_round(expr_fn, bits=400) -> float:
    with gmpy2.context(gmpy2.get_context(), precision=bits):
        return float(expr_fn())


def test_length_certified():
    c = M.length(W("LINESTRING (0 0, 1 1)"))
    assert c.rounded == math.sqrt(2) and c.exact is None
    assert c.lo * c.lo <= 2 <= c.hi * c.hi and c.hi - c.lo < F(1, 2**60)
    c = M.length(W("LINESTRING (0 0, 3 4, 3 0)"))
    assert c.exact == 9 and c.lo == c.hi == 9 and c.rounded == 9.0
    c = M.length(W("POLYGON ((0 0, 0 4, 4 4, 4 0, 0 0), (1 1, 2 1, 2 2, 1 2, 1 1))"))
    assert c.exact == 20
    c = M.length(W("MULTILINESTRING ((0 0, 1 1), (0 0, 1 2), (0 0, 1 3))"))
    assert c.rounded == _mpfr_round(lambda: gmpy2.sqrt(2) + gmpy2.sqrt(5) + gmpy2.sqrt(10))
    c = M.length(W("MULTILINESTRING ((0 0, 1 1), (5 5, 6 4, 6 6))"))
    assert c.rounded == _mpfr_round(lambda: gmpy2.sqrt(2) * 2 + 2)
    assert M.length(W("POINT (1 1)")).exact == 0


def test_length_tie_rounds_to_even():
    # 2**53 + 1 lies halfway between the doubles 2**53 and 2**53 + 2
    c = M.length(W("LINESTRING (0 0, 9007199254740992 0, 9007199254740992 1)"))
    assert c.exact == 2**53 + 1 and c.rounded == 2.0**53


def test_length_matches_high_precision_on_random_lines():
    rng = random.Random(11)
    for _ in range(100):
        pts = [(rng.uniform(-1, 1), rng.uniform(-1, 1)) for _ in range(rng.randint(2, 6))]
        c = M.length(LineString(pts))

        def exact_sum(pts=pts):
            s = gmpy2.mpfr(0)
            for (x0, y0), (x1, y1) in pairwise(pts):
                dx = gmpy2.mpfr(x1) - gmpy2.mpfr(x0)
                dy = gmpy2.mpfr(y1) - gmpy2.mpfr(y0)
                s += gmpy2.sqrt(dx * dx + dy * dy)
            return s

        assert c.rounded == _mpfr_round(exact_sum, 600)
        assert c.lo <= c.hi


def test_length_huge_and_tiny():
    c = M.length(W("LINESTRING (0 0, 1e308 1e308)"))
    assert c.rounded == _mpfr_round(lambda: gmpy2.sqrt(2) * gmpy2.mpfr(1e308))
    c = M.length(W("LINESTRING (0 0, 1.5e308 1.5e308)"))
    assert c.rounded == math.inf  # sqrt(2) * 1.5e308 is beyond the double range
    c = M.length(W("LINESTRING (0 0, 5e-324 5e-324)"))
    assert c.rounded == 5e-324  # sqrt(2) * 2**-1074 rounds to the smallest subnormal


def test_sqrt_sum_exact_comparison():
    s = M.SqrtSum([(1, 8), (-2, 2)])
    assert s.equals(0) and s.rational_value() == 0
    assert M.SqrtSum([(1, 2), (1, 8)]).rational_value() is None
    assert M.SqrtSum([(F(1, 2), 4), (3, 9)]).rational_value() == 10
    lo, hi = M.SqrtSum([(1, 2)]).enclose(30)
    assert lo * lo <= 2 <= hi * hi and hi - lo <= F(1, 2**30)
    with pytest.raises(ValueError):
        M.SqrtSum([(1, -1)])


def test_centroid():
    c = M.centroid(W("POLYGON ((0 0, 0 4, 4 4, 4 0, 0 0), (1 1, 2 1, 2 2, 1 2, 1 1))"))
    assert (c[0].exact, c[1].exact) == (F(61, 30), F(61, 30))
    c = M.centroid(W("LINESTRING (0 0, 3 4, 3 0)"))
    assert (c[0].exact, c[1].exact) == (F(13, 6), 2)
    # irrational weights; the value is still decided and bracketed
    c = M.centroid(W("LINESTRING (0 0, 1 1, 3 1)"))
    x = (math.sqrt(2) * 0.5 + 2 * 2) / (math.sqrt(2) + 2)
    assert abs(c[0].rounded - x) <= 4e-16 and c[0].lo <= c[0].hi
    exp = _mpfr_round(lambda: (gmpy2.sqrt(2) * gmpy2.mpfr(0.5) + 4) / (gmpy2.sqrt(2) + 2))
    assert c[0].rounded == exp
    # areal dominates lineal dominates puntal
    gc = W("GEOMETRYCOLLECTION (POLYGON ((0 0, 1 0, 1 1, 0 0)), LINESTRING (5 5, 9 9))")
    c = M.centroid(gc)
    assert (c[0].exact, c[1].exact) == (F(2, 3), F(1, 3))
    c = M.centroid(W("MULTIPOINT ((0 0), (1 0), (1 1))"))
    assert (c[0].exact, c[1].exact) == (F(2, 3), F(1, 3))
    c = M.centroid(W("MULTILINESTRING ((1 1, 1 1), (3 3, 3 3))"))  # zero length: points
    assert (c[0].exact, c[1].exact) == (2, 2)
    # a zero-area polygon falls back to its perimeter
    c = M.centroid(W("POLYGON ((0 0, 2 0, 1 0, 0 0))"))
    assert (c[0].rounded, c[1].rounded) == (1.0, 0.0)
    assert M.centroid(W("LINESTRING EMPTY")) is None


def test_centroid_tie_is_detected_exactly():
    # both segments have length sqrt(2); the centroid x is 2**52 + 1/2 exactly, halfway
    # between two doubles, although every enclosure straddles it
    g = W(
        "MULTILINESTRING ((4503599627370496 0, 4503599627370497 1), "
        "(4503599627370496 5, 4503599627370497 6))"
    )
    cx, cy = M.centroid(g)
    assert cx.exact == 2**52 + F(1, 2) and cx.rounded == 2.0**52
    assert cy.exact == 3


def test_convex_hull():
    h = M.convex_hull(W("MULTIPOINT ((0 0), (1 0), (0 1), (1 1), (0.5 0.5), (0.5 0))"))
    assert h.wkt == "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))"
    assert M.convex_hull(W("MULTIPOINT ((0 0), (1 1), (2 2))")).wkt == "LINESTRING (0 0, 2 2)"
    assert M.convex_hull(W("MULTIPOINT ((1 2), (1 2))")).wkt == "POINT (1 2)"
    assert M.convex_hull(W("POLYGON EMPTY")).wkt == "GEOMETRYCOLLECTION EMPTY"
    h = M.convex_hull(MultiPoint([(0.1, 0.0), (0.0, 0.3), (0.2, 0.2), (0.08, 0.1)]))
    assert set(h.shell) == {(0.1, 0.0), (0.2, 0.2), (0.0, 0.3)}  # the input doubles
    h = M.convex_hull(W("POLYGON ((0 0, 4 0, 2 1, 4 4, 0 4, 0 0))"))
    assert h.wkt == "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))"
    # a Polygon's hull is its shell's (JTS/GEOS Polygon.convexHull), even when invalid
    h = M.convex_hull(W("POLYGON ((0 0, 3 0, 1 0, 0 0), (2 3, 0 1, 4 1, 2 3))"))
    assert h.wkt == "LINESTRING (0 0, 3 0)"
    h = M.convex_hull(W("MULTIPOLYGON (((0 0, 3 0, 1 0, 0 0), (2 3, 0 1, 4 1, 2 3)))"))
    assert h.wkt == "POLYGON ((0 0, 3 0, 4 1, 2 3, 0 1, 0 0))"
    rng = random.Random(1)
    for _ in range(50):
        pts = [(float(rng.randint(0, 9)), float(rng.randint(0, 9))) for _ in range(12)]
        h = M.convex_hull(MultiPoint(pts))
        if isinstance(h, Polygon):
            ring = h.shell
            from geotruth.exact import orient

            for p in pts:  # every point inside or on, every turn strictly left
                for u, v in pairwise(ring):
                    assert orient(u, v, p) >= 0
            for u, v, w in zip(ring, ring[1:], [*ring[2:], ring[1]], strict=False):
                assert orient(u, v, w) > 0


def test_certified_json_matches_schema():
    pytest.importorskip("jsonschema")
    from jsonschema import Draft202012Validator

    from geotruth import schemas

    ref = schemas.load_schema("expected")["$id"] + "#/properties/measures"
    check = Draft202012Validator({"$ref": ref}, registry=schemas._registry())
    a = W("POLYGON ((0 0, 3 0, 0 1, 0 0))")
    b = W("LINESTRING (5 5, 6 7, 9 9)")
    obj = M.case_measures(a, b)
    check.validate(obj)
    assert obj["area_a"] == "3/2" and obj["area_b"] == "0"
    assert set(obj) >= {"length_a", "length_b", "centroid_b_x", "distance2"}
    assert "rounded" not in M.Certified(F(1), F(2), math.inf).to_json()


# ------------------------------------------------------------------------ engine shim


def test_overlay_area_and_predicates_shim():
    a = W("POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))")
    b = W("POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))")
    areas = {op: M.overlay_area(a, b, op) for op in M.OVERLAY_OPS}
    assert areas == {"intersection": 1, "union": 7, "difference": 3, "symdifference": 6}
    assert M.relate_predicates(a, b, backend="oracle")["overlaps"] is True
    assert set(M.engine_backends()) == {"relate", "overlay"}
    with pytest.raises(ValueError, match="unknown overlay"):
        M.overlay_area(a, b, "xor")
    with pytest.raises(M.EngineUnavailable):
        M.relate_predicates(W("POINT (0 0)"), a, backend="oracle")
    with pytest.raises(M.EngineUnavailable):  # the oracle needs valid input
        M.relate_predicates(W("POLYGON ((0 0, 2 2, 2 0, 0 2, 0 0))"), a, backend="oracle")


def test_distance_zero_iff_intersects_on_the_seed(repo_root: Path):
    """distance2 == 0 exactly when the reference oracle says the operands intersect."""
    from geotruth.io import geometry_from_json

    lines = (repo_root / "corpus" / "cases" / "seed.jsonl").read_text().splitlines()
    for line in lines[::10]:
        case = json_loads(line)
        a, b = geometry_from_json(case["a"]), geometry_from_json(case["b"])
        preds = M.relate_predicates(a, b, backend="oracle")
        assert (M.distance2(a, b) == 0) == preds["intersects"], case["id"]
        inter = M.overlay_area(a, b, "intersection")
        assert inter + M.overlay_area(a, b, "difference") == M.area(a)
        assert M.overlay_area(a, b, "union") == M.area(a) + M.area(b) - inter


def test_gc_distance_and_empty_elements():
    gc = GeometryCollection([Point(), LineString([]), Point((3.0, 4.0))])
    assert M.distance2(gc, W("POINT (0 0)")) == 25
    assert M.length(gc).exact == 0
    c = M.centroid(gc)
    assert (c[0].exact, c[1].exact) == (3, 4)


def test_relate_shim_prefers_the_engine():
    a = W("POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))")
    b = W("POLYGON ((2 0, 4 0, 4 2, 2 2, 2 0))")
    oracle = M.relate_predicates(a, b, backend="oracle")
    assert oracle["touches"] and not oracle["overlaps"]
    auto = M.relate_predicates(a, b)
    assert all(auto[k] == oracle[k] for k in oracle)
    if M.engine_backends()["relate"] == "geotruth.relate":
        assert M.relate_predicates(a, b, backend="engine") == auto
    else:
        with pytest.raises(M.EngineUnavailable):
            M.relate_predicates(a, b, backend="engine")
    with pytest.raises(ValueError, match="unknown backend"):
        M.relate_predicates(a, b, backend="nope")
