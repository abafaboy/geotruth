"""Unit tests for geotruth.exact against independent Fraction-based brute force.

The references below deliberately use different algorithms from the module under test:
parametric (Cramer) solving instead of orientation signs, projection parameters instead
of axis-aligned comparisons, a winding number instead of the crossing rule, and a
"diamond angle" pseudo-angle instead of quadrant + cross product.
"""

from __future__ import annotations

import itertools
import math
import random
from fractions import Fraction as F

import pytest

from geotruth import exact as X
from geotruth.numbers import DyadicScale

# ======================================================================= references


def ref_orient(a, b, c) -> int:
    m = [[F(1), F(a[0]), F(a[1])], [F(1), F(b[0]), F(b[1])], [F(1), F(c[0]), F(c[1])]]
    det = (
        m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0])
    )
    return (det > 0) - (det < 0)


def ref_point_on_segment(p, a, b) -> bool:
    """Parametric: p == a + t (b - a) for some t in [0, 1]."""
    p, a, b = [tuple(map(F, q)) for q in (p, a, b)]
    if a == b:
        return p == a
    dx, dy = b[0] - a[0], b[1] - a[1]
    t = (p[0] - a[0]) / dx if dx != 0 else (p[1] - a[1]) / dy
    return 0 <= t <= 1 and a[0] + t * dx == p[0] and a[1] + t * dy == p[1]


def ref_intersection(a, b, c, d):
    """(kind, points) with points as Fraction pairs, overlap ordered along a -> b."""
    a, b, c, d = [tuple(map(F, q)) for q in (a, b, c, d)]
    if a == b and c == d:
        return (X.POINT, [a]) if a == c else (X.NONE, [])
    if a == b:
        return (X.POINT, [a]) if ref_point_on_segment(a, c, d) else (X.NONE, [])
    if c == d:
        return (X.POINT, [c]) if ref_point_on_segment(c, a, b) else (X.NONE, [])
    ux, uy = b[0] - a[0], b[1] - a[1]
    vx, vy = d[0] - c[0], d[1] - c[1]
    wx, wy = c[0] - a[0], c[1] - a[1]
    det = ux * vy - uy * vx
    if det != 0:
        t = (wx * vy - wy * vx) / det
        s = (wx * uy - wy * ux) / det
        if 0 <= t <= 1 and 0 <= s <= 1:
            return X.POINT, [(a[0] + t * ux, a[1] + t * uy)]
        return X.NONE, []
    if wx * uy - wy * ux != 0:  # parallel, distinct lines
        return X.NONE, []
    L = ux * ux + uy * uy
    tc = (wx * ux + wy * uy) / L
    td = ((d[0] - a[0]) * ux + (d[1] - a[1]) * uy) / L
    lo, hi = max(F(0), min(tc, td)), min(F(1), max(tc, td))
    if lo > hi:
        return X.NONE, []
    pl = (a[0] + lo * ux, a[1] + lo * uy)
    if lo == hi:
        return X.POINT, [pl]
    return X.OVERLAP, [pl, (a[0] + hi * ux, a[1] + hi * uy)]


def as_fracs(hp):
    return (F(hp[0], hp[2]), F(hp[1], hp[2]))


def check_intersection(a, b, c, d):
    got = X.intersect_segments(a, b, c, d)
    kind, pts = ref_intersection(a, b, c, d)
    assert got.kind == kind, (a, b, c, d, got)
    assert [as_fracs(p) for p in got.points] == pts, (a, b, c, d, got)
    for p in got.points:
        assert p[2] > 0 and math.gcd(*p) == 1  # canonical
    assert bool(got) == (kind != X.NONE)
    assert X.segments_intersect(a, b, c, d) == (kind != X.NONE)


def rand_pt(rng, lo, hi):
    return (rng.randint(lo, hi), rng.randint(lo, hi))


# ================================================================== orientation


def test_orient_matches_determinant():
    rng = random.Random(10)
    for lo, hi in ((0, 3), (-(10**6), 10**6), (-(2**80), 2**80)):
        for _ in range(3000):
            a, b, c = (rand_pt(rng, lo, hi) for _ in range(3))
            o = X.orient(a, b, c)
            assert o == ref_orient(a, b, c)
            assert X.orient(b, a, c) == -o and X.orient(b, c, a) == o
            v = X.orient_value(a, b, c)
            assert (v > 0) - (v < 0) == o


def test_orient_is_generic():
    a, b, c = (F(0), F(0)), (F(1, 3), F(1, 3)), (F(2, 3), F(2, 3) + F(1, 10**30))
    assert X.orient(a, b, c) == 1
    assert X.orient(a, b, (F(2, 3), F(2, 3))) == 0


def test_signed_area2():
    sq = [(0, 0), (2, 0), (2, 2), (0, 2)]
    assert X.signed_area2(sq) == 8
    assert X.signed_area2([*sq, sq[0]]) == 8  # closed ring, same value
    assert X.signed_area2(sq[::-1]) == -8
    assert X.signed_area2([(0, 0), (1, 1), (2, 2)]) == 0
    assert X.signed_area2([]) == 0


def test_cross():
    assert X.cross(1, 0, 0, 1) == 1 and X.cross(0, 1, 1, 0) == -1


# ============================================================ point on segment


def test_on_segment_against_reference():
    rng = random.Random(11)
    for _ in range(20000):
        a, b, p = (rand_pt(rng, 0, 4) for _ in range(3))
        assert X.on_segment(p, a, b) == ref_point_on_segment(p, a, b), (p, a, b)
        interior = X.in_segment_interior(p, a, b)
        assert interior == (ref_point_on_segment(p, a, b) and p not in (a, b))


def test_hp_on_segment_against_reference():
    rng = random.Random(12)
    for _ in range(5000):
        a, b = rand_pt(rng, -5, 5), rand_pt(rng, -5, 5)
        w = rng.randint(1, 6)
        if rng.random() < 0.5 and a != b:  # a point exactly on the line ab
            t = F(rng.randint(-2, 8), w)
            q = (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1]))
            p = X.hpoint_of(q)
        else:
            p = X.hpoint(rng.randint(-30, 30), rng.randint(-30, 30), w)
        assert X.hp_on_segment(p, a, b) == ref_point_on_segment(as_fracs(p), a, b)
        # non-reduced triples are accepted
        assert X.hp_on_segment((2 * p[0], 2 * p[1], 2 * p[2]), a, b) == X.hp_on_segment(p, a, b)


# ======================================================== segment intersection


@pytest.mark.parametrize(
    ("lo", "hi", "n"), [(0, 3, 30000), (-2, 2, 10000), (-(10**9), 10**9, 5000)]
)
def test_intersection_random_integers(lo, hi, n):
    rng = random.Random(lo * 7 + hi)
    for _ in range(n):
        a, b, c, d = (rand_pt(rng, lo, hi) for _ in range(4))
        check_intersection(a, b, c, d)


def test_intersection_dyadic_inputs():
    """Random doubles at mixed binary scales, mapped to integers by DyadicScale."""
    rng = random.Random(13)
    for _ in range(3000):
        coords = []
        for _ in range(8):
            m = rng.randint(-(2**53) + 1, 2**53 - 1)
            coords.append(math.ldexp(m, rng.randint(-60, -40)))
        scale = DyadicScale.for_values(coords)
        a, b, c, d = (scale.to_point(coords[i], coords[i + 1]) for i in range(0, 8, 2))
        check_intersection(a, b, c, d)


def test_intersection_constructed_degeneracies():
    """Collinear overlaps, T-junctions and shared endpoints, built on purpose."""
    rng = random.Random(14)
    for _ in range(5000):
        a = rand_pt(rng, -50, 50)
        u = (rng.randint(-5, 5), rng.randint(-5, 5))
        if u == (0, 0):
            continue
        b = (a[0] + 4 * u[0], a[1] + 4 * u[1])
        kind = rng.randrange(4)
        if kind == 0:  # collinear, overlapping or not
            s, t = rng.randint(-6, 10), rng.randint(-6, 10)
            c, d = (a[0] + s * u[0], a[1] + s * u[1]), (a[0] + t * u[0], a[1] + t * u[1])
        elif kind == 1:  # T-junction: c on ab, d off the line
            s = rng.randint(0, 4)
            c = (a[0] + s * u[0], a[1] + s * u[1])
            d = (c[0] - u[1] * rng.randint(1, 3), c[1] + u[0] * rng.randint(1, 3))
        elif kind == 2:  # shared endpoint
            c, d = b, rand_pt(rng, -50, 50)
        else:  # crossing through a lattice point of ab
            s = rng.randint(1, 3)
            m = (a[0] + s * u[0], a[1] + s * u[1])
            v = (rng.randint(-5, 5), rng.randint(-5, 5))
            c, d = (m[0] - v[0], m[1] - v[1]), (m[0] + v[0], m[1] + v[1])
        check_intersection(a, b, c, d)
        check_intersection(c, d, a, b)
        check_intersection(b, a, d, c)


def test_intersection_examples():
    # proper crossing at a non-dyadic point
    r = X.intersect_segments((0, 0), (3, 1), (0, 1), (2, 0))
    assert r == X.SegmentIntersection(X.POINT, ((6, 2, 5),))
    # T-junction returns the endpoint itself
    r = X.intersect_segments((0, 0), (4, 0), (2, 0), (2, 5))
    assert r.points == ((2, 0, 1),)
    # collinear overlap, reported along the first segment's direction
    r = X.intersect_segments((4, 0), (0, 0), (1, 0), (6, 0))
    assert r.kind == X.OVERLAP and r.points == ((4, 0, 1), (1, 0, 1))
    # collinear, touching at one endpoint
    assert X.intersect_segments((0, 0), (1, 1), (1, 1), (3, 3)).points == ((1, 1, 1),)
    # collinear, disjoint
    assert X.intersect_segments((0, 0), (1, 1), (2, 2), (3, 3)) is X.NO_INTERSECTION
    # parallel
    assert not X.intersect_segments((0, 0), (2, 0), (0, 1), (2, 1))
    # degenerate segments
    assert X.intersect_segments((1, 1), (1, 1), (0, 0), (2, 2)).points == ((1, 1, 1),)
    assert X.intersect_segments((1, 1), (1, 1), (1, 1), (1, 1)).points == ((1, 1, 1),)
    assert not X.intersect_segments((1, 1), (1, 1), (1, 2), (1, 2))


def test_intersection_symmetry_and_huge_coordinates():
    rng = random.Random(15)
    big = 2**1100  # far beyond any double's integer range after scaling
    for _ in range(2000):
        a, b, c, d = (rand_pt(rng, -big, big) for _ in range(4))
        r1 = X.intersect_segments(a, b, c, d)
        r2 = X.intersect_segments(c, d, a, b)
        assert r1.kind == r2.kind and set(r1.points) == set(r2.points)
    # a crossing with huge coordinates stays exact
    a, b = (-big, -big), (big, big)
    c, d = (-big, big + 1), (big, -big)
    check_intersection(a, b, c, d)


# ============================================================ homogeneous points


def test_hpoint_canonical_form():
    assert X.hpoint(6, 4, 2) == (3, 2, 1)
    assert X.hpoint(-6, 4, -4) == (3, -2, 2)
    assert X.hpoint(0, 0, 5) == (0, 0, 1)
    with pytest.raises(ZeroDivisionError):
        X.hpoint(1, 1, 0)
    assert X.hpoint_of((3, 4)) == (3, 4, 1)
    assert X.hpoint_of((F(1, 2), F(2, 3))) == (3, 4, 6)
    assert X.hp_is_integer((3, 4, 1)) and not X.hp_is_integer((3, 4, 6))


def test_hp_comparisons_against_fractions():
    rng = random.Random(16)
    pts = [
        X.hpoint(rng.randint(-20, 20), rng.randint(-20, 20), rng.randint(1, 5)) for _ in range(300)
    ]
    for _ in range(5000):
        p, q, r = rng.choice(pts), rng.choice(pts), rng.choice(pts)
        fp, fq, fr = as_fracs(p), as_fracs(q), as_fracs(r)
        assert X.hp_eq(p, q) == (fp == fq) == (p == q)  # canonical => tuple equality
        assert X.hp_cmp(p, q) == (fp > fq) - (fp < fq)
        assert X.hp_orient(p, q, r) == ref_orient(fp, fq, fr)
        m = X.hp_midpoint(p, q)
        assert as_fracs(m) == ((fp[0] + fq[0]) / 2, (fp[1] + fq[1]) / 2)
        n, d = X.hp_sqdist(p, q)
        assert F(n, d) == (fp[0] - fq[0]) ** 2 + (fp[1] - fq[1]) ** 2
        dx, dy = X.hp_direction(p, q)
        if fp != fq:
            k = F(dx) / (fq[0] - fp[0]) if fq[0] != fp[0] else F(dy) / (fq[1] - fp[1])
            assert k > 0 and dx == k * (fq[0] - fp[0]) and dy == k * (fq[1] - fp[1])
    assert sorted(pts, key=X.hp_key) == sorted(pts, key=as_fracs)
    assert X.hp_to_fractions((6, 2, 5)) == (F(6, 5), F(2, 5))


def test_sort_along_segment():
    rng = random.Random(17)
    for _ in range(500):
        a = rand_pt(rng, -10, 10)
        u = (rng.randint(-4, 4), rng.randint(-4, 4))
        if u == (0, 0):
            continue
        b = (a[0] + 6 * u[0], a[1] + 6 * u[1])
        ts = [F(rng.randint(0, 36), rng.randint(1, 6)) for _ in range(8)]
        ts = [t for t in ts if t <= 6]
        pts = [X.hpoint_of((a[0] + t * u[0], a[1] + t * u[1])) for t in ts]
        got = X.sort_along(a, b, pts + pts[:2])
        assert [as_fracs(p) for p in got] == sorted(
            {as_fracs(p) for p in pts}, key=lambda q: (q[0] - a[0]) * u[0] + (q[1] - a[1]) * u[1]
        )
        for p, q in itertools.pairwise(got):
            assert X.cmp_along(a, b, p, q) == -1 and X.cmp_along(b, a, p, q) == 1
            assert X.cmp_along(a, b, p, p) == 0


# ================================================================= angular order


def diamond_angle(v) -> F:
    """Monotone rational pseudo-angle in [0, 4) (independent of quadrant + cross)."""
    x, y = F(v[0]), F(v[1])
    s = abs(x) + abs(y)
    if y >= 0:
        return 1 - x / s if x >= 0 or y > 0 else F(2)  # [0, 2)
    return 3 + x / s  # (2, 4)


def test_diamond_reference_sanity():
    order = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
    angles = [diamond_angle(v) for v in order]
    assert angles == sorted(angles) and len(set(angles)) == 8


def test_angle_cmp_against_pseudo_angle():
    rng = random.Random(18)
    for bound in (2, 1000, 2**70):
        for _ in range(5000):
            u = rand_pt(rng, -bound, bound)
            v = rand_pt(rng, -bound, bound)
            if u == (0, 0) or v == (0, 0):
                continue
            du, dv = diamond_angle(u), diamond_angle(v)
            assert X.angle_cmp(u, v) == (du > dv) - (du < dv), (u, v)


def test_sort_by_angle():
    rng = random.Random(19)
    for _ in range(300):
        vs = [rand_pt(rng, -5, 5) for _ in range(rng.randint(1, 12))]
        vs = [v for v in vs if v != (0, 0)]
        order = X.sort_by_angle(vs)
        assert [diamond_angle(vs[i]) for i in order] == sorted(diamond_angle(v) for v in vs)
        assert sorted(vs, key=X.angle_key) == [vs[i] for i in order]


def test_quadrant_boundaries():
    assert [X.quadrant(*v) for v in [(1, 0), (0, 1), (-1, 0), (0, -1)]] == [0, 1, 2, 3]
    assert [X.quadrant(*v) for v in [(1, 1), (-1, 1), (-1, -1), (1, -1)]] == [0, 1, 2, 3]
    with pytest.raises(ValueError):
        X.quadrant(0, 0)
    assert X.angle_cmp((2, 2), (1, 1)) == 0  # same direction


# ============================================================== squared distances


def ref_sqdist_point_segment(p, a, b) -> F:
    p, a, b = [tuple(map(F, q)) for q in (p, a, b)]
    ux, uy = b[0] - a[0], b[1] - a[1]
    L = ux * ux + uy * uy
    t = F(0) if L == 0 else max(F(0), min(F(1), ((p[0] - a[0]) * ux + (p[1] - a[1]) * uy) / L))
    qx, qy = a[0] + t * ux, a[1] + t * uy
    return (p[0] - qx) ** 2 + (p[1] - qy) ** 2


def test_sqdist_point_segment():
    rng = random.Random(20)
    for _ in range(10000):
        p, a, b = (rand_pt(rng, -6, 6) for _ in range(3))
        n, d = X.sqdist_point_segment(p, a, b)
        assert d > 0 and F(n, d) == ref_sqdist_point_segment(p, a, b)
    assert X.sqdist((0, 0), (3, 4)) == 25


def test_sqdist_segment_segment():
    rng = random.Random(21)
    for _ in range(5000):
        a, b, c, d = (rand_pt(rng, -6, 6) for _ in range(4))
        n, den = X.sqdist_segment_segment(a, b, c, d)
        if ref_intersection(a, b, c, d)[0] != X.NONE:
            ref = F(0)
        else:
            ref = min(
                ref_sqdist_point_segment(a, c, d),
                ref_sqdist_point_segment(b, c, d),
                ref_sqdist_point_segment(c, a, b),
                ref_sqdist_point_segment(d, a, b),
            )
        assert F(n, den) == ref


def test_ratio_cmp():
    assert X.ratio_cmp((1, 3), (2, 6)) == 0
    assert X.ratio_cmp((1, 3), (1, 2)) == -1
    assert X.ratio_cmp((5, 2), (2, 1)) == 1


# ================================================================= point in ring


def ref_locate(p, ring) -> int:
    """Winding number (Sunday) + parametric on-edge test, all in Fractions."""
    p = (F(p[0]), F(p[1]))
    pts = [(F(x), F(y)) for x, y in ring]
    n = len(pts)
    for i in range(n):
        if ref_point_on_segment(p, pts[i - 1], pts[i]):
            return X.ON_BOUNDARY
    wn = 0
    for i in range(n):
        a, b = pts[i - 1], pts[i]
        is_left = (b[0] - a[0]) * (p[1] - a[1]) - (p[0] - a[0]) * (b[1] - a[1])
        if a[1] <= p[1] < b[1] and is_left > 0:
            wn += 1
        elif b[1] <= p[1] < a[1] and is_left < 0:
            wn -= 1
    return X.INSIDE if wn != 0 else X.OUTSIDE


def star_polygon(rng, center, k, radius):
    """A simple polygon: distinct directions around ``center`` sorted by angle.

    Vertices in the four axis directions keep every angular gap below pi, so ``center``
    is in the kernel and the polygon is star-shaped, hence simple.
    """
    pts = {}
    for axis in ((1, 0), (0, 1), (-1, 0), (0, -1)):
        r = rng.randint(1, radius)
        pts[axis] = (axis[0] * r, axis[1] * r)
    for _ in range(k):
        v = (rng.randint(-radius, radius), rng.randint(-radius, radius))
        if v == (0, 0):
            continue
        g = math.gcd(*v)
        key = (v[0] // g, v[1] // g)  # one vertex per direction keeps it simple
        pts.setdefault(key, v)
    vs = sorted(pts.values(), key=X.angle_key)
    return [(center[0] + v[0], center[1] + v[1]) for v in vs]


def test_point_in_ring_against_winding_number():
    rng = random.Random(22)
    checked = 0
    for _ in range(400):
        ring = star_polygon(rng, (0, 0), rng.randint(3, 12), 6)
        if len(ring) < 3 or X.signed_area2(ring) == 0:
            continue
        closed = [*ring, ring[0]]
        for _ in range(40):
            p = rand_pt(rng, -7, 7)
            ref = ref_locate(p, ring)
            assert X.point_in_ring(p, ring) == ref
            assert X.point_in_ring(p, closed) == ref
            assert X.point_in_ring(p, ring[::-1]) == ref
            checked += 1
    assert checked > 5000


def test_hp_in_ring_against_winding_number():
    rng = random.Random(23)
    for _ in range(300):
        ring = star_polygon(rng, (1, -1), rng.randint(3, 10), 5)
        if len(ring) < 3 or X.signed_area2(ring) == 0:
            continue
        for _ in range(30):
            w = rng.randint(1, 4)
            p = X.hpoint(rng.randint(-7 * w, 7 * w), rng.randint(-7 * w, 7 * w), w)
            ref = ref_locate(as_fracs(p), ring)
            assert X.hp_in_ring(p, ring) == ref
            # non-reduced triples (including integer points written with W > 1)
            assert X.hp_in_ring((3 * p[0], 3 * p[1], 3 * p[2]), ring) == ref


def test_point_in_ring_generic_and_degenerate():
    ring = [(F(0), F(0)), (F(1, 3), F(0)), (F(1, 3), F(1, 3))]
    assert X.point_in_ring((F(1, 4), F(1, 10)), ring) == X.INSIDE
    assert X.point_in_ring((F(1, 6), F(1, 6)), ring) == X.ON_BOUNDARY
    assert X.point_in_ring((F(1, 2), F(0)), ring) == X.OUTSIDE
    # a notched ring, and one with a dangling spike (a DCEL face cycle can look like it)
    notched = [(0, 0), (4, 0), (4, 4), (2, 2), (0, 4), (0, 0)]
    assert X.point_in_ring((2, 2), notched) == X.ON_BOUNDARY
    assert X.point_in_ring((1, 1), notched) == X.INSIDE
    assert X.point_in_ring((2, 3), notched) == X.OUTSIDE
    spike = [(0, 0), (4, 0), (4, 2), (6, 2), (4, 2), (4, 4), (0, 4)]
    assert X.point_in_ring((5, 2), spike) == X.ON_BOUNDARY
    assert X.point_in_ring((5, 1), spike) == X.OUTSIDE
    assert X.point_in_ring((3, 2), spike) == X.INSIDE
