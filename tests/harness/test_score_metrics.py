"""Exact grading metrics (src/geotruth/harness/metrics.py): surds, even-odd areas, the exact
squared Hausdorff distance, components and the tube bound."""

from __future__ import annotations

import math
import random
from fractions import Fraction
from itertools import pairwise

import pytest

from geotruth.harness import metrics as M
from geotruth.io import geometry_from_json

pytestmark = pytest.mark.unit

F = Fraction


def shape(g: dict) -> M.Shape:
    return M.shape_of(geometry_from_json(g))


def poly(*rings) -> dict:
    return {"type": "Polygon", "coordinates": [list(r) for r in rings]}


SQ = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]]


# ============================================================================ surds


def test_surd_normalises_and_compares_exactly():
    assert M.Surd(1, 2, 9) == 7  # sqrt(9) folds
    assert M.Surd(0, 1, 2) > F(14142, 10000) and M.Surd(0, 1, 2) < F(14143, 10000)
    # 1 + sqrt(2) vs sqrt(5.8284) ~ 2.41421: exact comparison across radicands
    assert M.Surd(1, 1, 2) > M.Surd(0, 1, F(58283, 10000))
    assert M.Surd(1, 1, 2) < M.Surd(0, 1, F(58285, 10000))
    # equal values with different representations
    assert M.Surd(0, 2, 2) == M.Surd(0, 1, 8)
    assert M.Surd(3, -1, 2) < 2 and M.Surd(3, -1, 2) > 1
    assert float(M.Surd(1, 1, 2)) == pytest.approx(1 + math.sqrt(2))


def test_surd_sign_random_against_high_precision():
    from decimal import Decimal, getcontext

    getcontext().prec = 80
    rng = random.Random(7)
    for _ in range(400):
        a, b, c = (F(rng.randint(-50, 50), rng.randint(1, 9)) for _ in range(3))
        d1, d2 = F(rng.randint(0, 40), rng.randint(1, 5)), F(rng.randint(0, 40), rng.randint(1, 5))
        exact = M._sign3(a, b, d1, c, d2)

        def dec(q):
            return Decimal(q.numerator) / Decimal(q.denominator)

        v = dec(a) + dec(b) * dec(d1).sqrt() + dec(c) * dec(d2).sqrt()
        if abs(v) > Decimal("1e-40"):
            assert exact == (1 if v > 0 else -1), (a, b, d1, c, d2)


def test_sqrt_bounds():
    for q in (F(2), F(1, 3), F(10**30 + 7, 3), F(0)):
        lo, hi = M.sqrt_lower(q), M.sqrt_upper(q)
        assert lo * lo <= q <= hi * hi
        assert hi - lo <= max(hi, F(1)) * F(1, 2**60)
    assert M.sqrt_upper(F(9, 4)) == F(3, 2)


# ============================================================================ areas


def test_even_odd_area():
    assert M.even_odd_area(shape(poly(SQ)).rings()) == 16
    hole = [[1, 1], [1, 2], [2, 2], [2, 1], [1, 1]]
    assert M.even_odd_area(shape(poly(SQ, hole)).rings()) == 15
    # two overlapping squares: even-odd removes the overlap
    s2 = [[2, 2], [6, 2], [6, 6], [2, 6], [2, 2]]
    mp = {"type": "MultiPolygon", "coordinates": [[SQ], [s2]]}
    assert M.even_odd_area(shape(mp).rings()) == 16 + 16 - 2 * 4
    # a bow-tie (self-crossing ring): two triangles of area 1 each
    bow = [[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]
    assert M.even_odd_area(shape(poly(bow)).rings()) == 2
    # rational coordinates and the xor of a shape with itself
    tri = {
        "type": "Polygon",
        "coordinates": [[["0", "0"], ["2/3", "1/3"], ["1/7", "5"], ["0", "0"]]],
    }
    t = M.shape_of(geometry_from_json(tri, exact=True))
    a = abs(M.ring_area2(t.polygons[0][0])) / 2
    assert M.even_odd_area(t.rings()) == a
    assert M.even_odd_area(t.rings() + t.rings()) == 0


def test_overlap_area_and_components_with_islands():
    hole = [[1, 1], [1, 3], [3, 3], [3, 1], [1, 1]]
    island = [[F(3, 2), F(3, 2)], [F(5, 2), F(3, 2)], [F(5, 2), F(5, 2)], [F(3, 2), F(5, 2)]]
    g = {
        "type": "MultiPolygon",
        "coordinates": [[SQ, hole], [[[float(x), float(y)] for x, y in [*island, island[0]]]]],
    }
    s = shape(g)
    polys, holes = M.components(s)
    assert [c.key for c in polys] == [("poly", 0), ("poly", 1)]
    assert polys[0].area == 12 and polys[1].area == 1
    (h,) = holes
    assert h.key == ("hole", 0, 1)
    assert h.area == 4 - 1  # the gap between the hole ring and the island
    assert h.excuse == {("hole", 0, 1), ("shell", 1)}
    other = shape(poly([[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]])).rings()
    assert M.overlap_area(polys[0].rings, polys[0].area, other, 4) == 4 - 1


# ============================================================================ Hausdorff


def test_hausdorff_translated_square():
    a = shape(poly(SQ))
    b = shape(poly([[x + 0.5, y] for x, y in SQ]))
    h2, h_ab, h_ba = M.hausdorff2(a, b)
    assert h2 == F(1, 4) and h_ab == F(1, 4) and h_ba == F(1, 4)


def test_hausdorff_identical_and_collinear_vertices():
    a = shape(poly(SQ))
    b = shape(poly([[0, 0], [2, 0], [4, 0], [4, 4], [0, 4], [0, 0]]))  # an extra collinear vertex
    assert M.hausdorff2(a, b)[0] == 0


def test_hausdorff_interior_maximum_is_found():
    """The farthest point of a segment from two points is its midpoint, not a vertex."""
    s = M.Shape(lines=[[(F(0), F(0)), (F(2), F(0))]])
    t = M.Shape(points=[(F(0), F(0)), (F(2), F(0))])
    assert M.directed_hausdorff2(M.features_of(s), M.features_of(t)) == 1
    assert M.directed_hausdorff2(M.features_of(t), M.features_of(s)) == 0


def test_hausdorff_irrational_value_is_exact():
    """Segment (0,0)-(3,0) against the point (0,1) and the segment (2,1)-(2,5): the
    envelope maximum is where the two squared distances cross, at an irrational t."""
    s = M.Shape(lines=[[(F(0), F(0)), (F(3), F(0))]])
    t = M.Shape(points=[(F(0), F(1))], lines=[[(F(2), F(1)), (F(2), F(5))]])
    h = M.directed_hausdorff2(M.features_of(s), M.features_of(t))
    # brute force on a fine grid: the exact value is an upper bound within 1e-6
    best = 0.0
    for k in range(30001):
        x = 3 * k / 30000
        d1 = x * x + 1
        d2 = (x - 2) ** 2 + 1
        best = max(best, min(d1, d2))
    assert float(h) == pytest.approx(best, abs=1e-6)
    assert h >= F(best) - F(1, 10**6)


def test_hausdorff_random_polylines_against_sampling():
    rng = random.Random(3)
    for _ in range(25):
        pts_s = [(F(rng.randint(0, 20)), F(rng.randint(0, 20))) for _ in range(4)]
        pts_t = [(F(rng.randint(0, 20)), F(rng.randint(0, 20))) for _ in range(4)]
        s, t = M.Shape(lines=[pts_s]), M.Shape(lines=[pts_t])
        h = float(M.directed_hausdorff2(M.features_of(s), M.features_of(t)))
        tf = [(float(x), float(y)) for x, y in pts_t]

        def d2(px, py, tf=tf):
            best = math.inf
            for (ax, ay), (bx, by) in pairwise(tf):
                ux, uy = bx - ax, by - ay
                ll = ux * ux + uy * uy
                t_ = 0.0 if ll == 0 else max(0.0, min(1.0, ((px - ax) * ux + (py - ay) * uy) / ll))
                best = min(best, (px - ax - t_ * ux) ** 2 + (py - ay - t_ * uy) ** 2)
            return best

        sampled = 0.0
        for (ax, ay), (bx, by) in pairwise(pts_s):
            for k in range(801):
                x = float(ax) + (float(bx) - float(ax)) * k / 800
                y = float(ay) + (float(by) - float(ay)) * k / 800
                sampled = max(sampled, d2(x, y))
        assert h >= sampled - 1e-9
        assert h <= sampled + 0.05 * max(1.0, h)  # the grid is fine enough


def test_hausdorff_empty_sides():
    a = shape(poly(SQ))
    empty = M.Shape()
    assert M.hausdorff2(a, empty)[0] is None
    assert M.hausdorff2(empty, a)[0] is None
    assert M.hausdorff2(empty, empty)[0] == 0


def test_excuse_and_collapse():
    """A thin exact component may vanish (excused); a gap between two exact rings may
    collapse (collapse excusal), a big one may not."""
    big = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    sliver = [[20, 0], [30, 0], [30, 0.001], [20, 0.001], [20, 0]]
    e = shape({"type": "MultiPolygon", "coordinates": [[big], [sliver]]})
    lib = shape(poly(big))
    assert M.hausdorff2(e, lib)[0] > 1
    polys, _ = M.components(e)
    thin = {c.key for c in polys if M.is_thin(c.area, c.perimeter_up, c.n_vertices, F(1, 10**6))}
    assert thin == {("poly", 1)}
    assert M.hausdorff2(e, lib, excuse=thin)[0] == 0
    # two squares 1e-3 apart; the library merged them across the gap
    left = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]
    right = [[1.001, 0], [2, 0], [2, 1], [1.001, 1], [1.001, 0]]
    e2 = shape({"type": "MultiPolygon", "coordinates": [[left], [right]]})
    merged = shape(poly([[0, 0], [2, 0], [2, 1], [0, 1], [0, 0]]))
    fe, fl = M.features_of(e2), M.features_of(merged)
    assert M.directed_hausdorff2(fe, fl) > F(1, 10**6)
    d2 = F(1, 10**6)  # delta = 1e-3: a 1e-3 gap may collapse (collapse radius 2 delta)
    assert M.directed_hausdorff2_collapse(fe, fl, d2, 4 * d2) <= d2
    d2 = F(1, 10**8)  # delta = 1e-4: it may not
    assert not M.directed_hausdorff2_collapse(fe, fl, d2, 4 * d2) <= d2


def test_tube_bound_and_rounding_delta():
    assert M.tube_bound(F(1, 4), 10, 4) >= 2 * F(1, 2) * 10 + F(314159, 100000) * F(1, 4) * 4
    assert M.tube_bound(0, 10, 4) == 0
    d2 = M.rounding_delta2(1.0)
    assert d2 == F(math.ulp(1.0)) ** 2 / 2
