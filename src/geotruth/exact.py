"""Exact geometric primitives on scaled integer coordinates (DESIGN §2.1).

After per-case dyadic scaling (:class:`geotruth.numbers.DyadicScale`) every input
coordinate is a Python :class:`int`, so the tests below are exact and need no rational
arithmetic. Intersection points are *homogeneous integer triples*.

Conventions
-----------
``Point``
    ``(x, y)``, a pair of ints (the scaled input coordinates). The functions documented
    as *generic* also accept any exact number type (``Fraction``, ``mpq``); they only
    add, subtract, multiply and compare. Never pass floats: float arithmetic rounds.

``HPoint``
    ``(X, Y, W)`` with ``W > 0``: the rational point ``(X/W, Y/W)``. It is *canonical*
    when ``gcd(X, Y, W) == 1``; every rational point has exactly one canonical triple, so
    canonical triples can be hashed and compared with ``==``. Everything that returns an
    ``HPoint`` returns it canonical; functions that accept one also accept non-reduced
    triples (with ``W > 0``) unless noted.

Orientation
    ``orient(a, b, c)`` is the sign of the cross product ``(b - a) x (c - a)``:
    ``+1`` when ``c`` is left of the directed line ``a -> b`` (counter-clockwise turn),
    ``-1`` when right, ``0`` when collinear.

Locations returned by :func:`point_in_ring`
    ``INSIDE = 1``, ``ON_BOUNDARY = 0``, ``OUTSIDE = -1``.

Squared distances
    Returned as ``(num, den)`` pairs of ints with ``den > 0`` (not necessarily reduced),
    because the foot of a perpendicular is rational. Compare them with :func:`ratio_cmp`,
    or convert with ``numbers.rational(num, den)``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from fractions import Fraction
from functools import cmp_to_key
from math import gcd
from typing import Any, NamedTuple

__all__ = [
    "INSIDE",
    "NONE",
    "NO_INTERSECTION",
    "ON_BOUNDARY",
    "OUTSIDE",
    "OVERLAP",
    "POINT",
    "HPoint",
    "Point",
    "SegmentIntersection",
    "angle_cmp",
    "angle_key",
    "cmp_along",
    "cross",
    "hp_cmp",
    "hp_direction",
    "hp_eq",
    "hp_in_ring",
    "hp_is_integer",
    "hp_key",
    "hp_midpoint",
    "hp_on_segment",
    "hp_orient",
    "hp_sqdist",
    "hp_to_fractions",
    "hpoint",
    "hpoint_of",
    "in_segment_interior",
    "intersect_segments",
    "on_segment",
    "orient",
    "orient_value",
    "point_in_ring",
    "quadrant",
    "ratio_cmp",
    "segments_intersect",
    "signed_area2",
    "sort_along",
    "sort_by_angle",
    "sqdist",
    "sqdist_point_segment",
    "sqdist_segment_segment",
]

Point = tuple[int, int]
HPoint = tuple[int, int, int]

INSIDE, ON_BOUNDARY, OUTSIDE = 1, 0, -1

# ------------------------------------------------------------------------ orientation


def cross(ux: Any, uy: Any, vx: Any, vy: Any) -> Any:
    """The cross product ``u x v = ux*vy - uy*vx`` (generic)."""
    return ux * vy - uy * vx


def orient_value(a: Sequence, b: Sequence, c: Sequence) -> Any:
    """``(b - a) x (c - a)``: twice the signed area of triangle ``abc`` (generic)."""
    ax, ay = a[0], a[1]
    return (b[0] - ax) * (c[1] - ay) - (b[1] - ay) * (c[0] - ax)


def orient(a: Sequence, b: Sequence, c: Sequence) -> int:
    """Sign of ``(b - a) x (c - a)``: 1 left turn, -1 right turn, 0 collinear (generic)."""
    ax, ay = a[0], a[1]
    v = (b[0] - ax) * (c[1] - ay) - (b[1] - ay) * (c[0] - ax)
    return (v > 0) - (v < 0)


def signed_area2(ring: Sequence[Sequence]) -> Any:
    """Twice the signed area of a ring (positive when counter-clockwise; generic).

    The ring may be closed (last point repeating the first) or open.
    """
    total = 0
    n = len(ring)
    for i in range(n):
        p, q = ring[i - 1], ring[i]
        total += p[0] * q[1] - q[0] * p[1]
    return total


# -------------------------------------------------------------------- point on segment


def on_segment(p: Sequence, a: Sequence, b: Sequence) -> bool:
    """True if ``p`` lies on the closed segment ``ab`` (generic; ``a == b`` allowed)."""
    px, py = p[0], p[1]
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    if not ((ax <= px <= bx or bx <= px <= ax) and (ay <= py <= by or by <= py <= ay)):
        return False
    return (bx - ax) * (py - ay) == (by - ay) * (px - ax)


def in_segment_interior(p: Sequence, a: Sequence, b: Sequence) -> bool:
    """True if ``p`` lies on segment ``ab`` and is neither endpoint (generic)."""
    return p[0:2] != a[0:2] and p[0:2] != b[0:2] and on_segment(p, a, b)


# --------------------------------------------------------------- homogeneous points


def hpoint(x: int, y: int, w: int = 1) -> HPoint:
    """The canonical homogeneous triple of the rational point ``(x/w, y/w)``."""
    if w == 0:
        raise ZeroDivisionError("homogeneous weight W must be non-zero")
    if w < 0:
        x, y, w = -x, -y, -w
    g = gcd(x, y, w)
    if g != 1:
        x, y, w = x // g, y // g, w // g
    return x, y, w


def hpoint_of(p: Sequence) -> HPoint:
    """An integer point ``(x, y)`` as the homogeneous triple ``(x, y, 1)``.

    Also accepts a pair of rationals (``Fraction``/``mpq``) and returns the canonical
    triple over their common denominator.
    """
    x, y = p[0], p[1]
    if isinstance(x, int) and isinstance(y, int):
        return x, y, 1
    xn, xd = int(x.numerator), int(x.denominator)
    yn, yd = int(y.numerator), int(y.denominator)
    w = xd * yd // gcd(xd, yd)  # lcm of the denominators
    return hpoint(xn * (w // xd), yn * (w // yd), w)


def hp_is_integer(p: HPoint) -> bool:
    """True if the (canonical) homogeneous point has integer coordinates."""
    return p[2] == 1


def hp_eq(p: HPoint, q: HPoint) -> bool:
    """Exact equality of two homogeneous points (canonical or not)."""
    return p[0] * q[2] == q[0] * p[2] and p[1] * q[2] == q[1] * p[2]


def hp_cmp(p: HPoint, q: HPoint) -> int:
    """Lexicographic comparison (x first, then y) of two homogeneous points: -1, 0, 1."""
    pw, qw = p[2], q[2]
    a, b = p[0] * qw, q[0] * pw
    if a != b:
        return -1 if a < b else 1
    a, b = p[1] * qw, q[1] * pw
    if a != b:
        return -1 if a < b else 1
    return 0


#: Sort key for lexicographic order of homogeneous points: ``sorted(pts, key=hp_key)``.
hp_key = cmp_to_key(hp_cmp)


def hp_to_fractions(p: HPoint) -> tuple[Fraction, Fraction]:
    """The rational coordinates of a homogeneous point."""
    return Fraction(p[0], p[2]), Fraction(p[1], p[2])


def hp_orient(p: HPoint, q: HPoint, r: HPoint) -> int:
    """Orientation of three homogeneous points (same sign convention as :func:`orient`).

    With all weights positive, the sign of the 3x3 determinant ``|p; q; r|`` equals the
    sign of the Euclidean orientation.
    """
    px, py, pw = p
    qx, qy, qw = q
    rx, ry, rw = r
    v = px * (qy * rw - ry * qw) - py * (qx * rw - rx * qw) + pw * (qx * ry - rx * qy)
    return (v > 0) - (v < 0)


def hp_direction(p: HPoint, q: HPoint) -> Point:
    """An integer vector with the direction of ``q - p`` (a positive multiple of it)."""
    return q[0] * p[2] - p[0] * q[2], q[1] * p[2] - p[1] * q[2]


def hp_midpoint(p: HPoint, q: HPoint) -> HPoint:
    """The canonical midpoint of two homogeneous points."""
    pw, qw = p[2], q[2]
    return hpoint(p[0] * qw + q[0] * pw, p[1] * qw + q[1] * pw, 2 * pw * qw)


def hp_on_segment(p: HPoint, a: Sequence[int], b: Sequence[int]) -> bool:
    """True if homogeneous point ``p`` lies on the closed integer segment ``ab``."""
    x, y, w = p
    ax, ay, bx, by = a[0], a[1], b[0], b[1]
    axw, ayw, bxw, byw = ax * w, ay * w, bx * w, by * w
    if not ((axw <= x <= bxw or bxw <= x <= axw) and (ayw <= y <= byw or byw <= y <= ayw)):
        return False
    return (bx - ax) * (y - ayw) == (by - ay) * (x - axw)


def cmp_along(a: Sequence, b: Sequence, p: HPoint, q: HPoint) -> int:
    """Compare the positions of homogeneous points ``p`` and ``q`` along the direction
    ``a -> b`` (their projections onto it): -1 if ``p`` comes first, 0 if level, 1 after.
    """
    ux, uy = b[0] - a[0], b[1] - a[1]
    v = (ux * p[0] + uy * p[1]) * q[2] - (ux * q[0] + uy * q[1]) * p[2]
    return (v > 0) - (v < 0)


def sort_along(a: Sequence, b: Sequence, points: Iterable[HPoint]) -> list[HPoint]:
    """Distinct canonical points sorted by position along ``a -> b``.

    The points are assumed to lie on the line ``ab`` (e.g. the split points of a
    segment); duplicates are removed by canonical equality.
    """
    unique = {hpoint(*p) for p in points}
    return sorted(unique, key=cmp_to_key(lambda p, q: cmp_along(a, b, p, q)))


# ------------------------------------------------------------ segment intersection

NONE, POINT, OVERLAP = 0, 1, 2


class SegmentIntersection(NamedTuple):
    """Result of :func:`intersect_segments`.

    ``kind`` is :data:`NONE` (``points == ()``), :data:`POINT` (one canonical
    homogeneous point, possibly an endpoint of either segment -- a touch or a
    T-junction) or :data:`OVERLAP` (a collinear overlap of positive length; its two
    endpoints, ordered along the first segment's direction ``a -> b``). Overlap endpoints
    are always input endpoints, so they have ``W == 1``.
    """

    kind: int
    points: tuple[HPoint, ...]

    def __bool__(self) -> bool:
        return self.kind != NONE


NO_INTERSECTION = SegmentIntersection(NONE, ())


def _pt(p: Sequence[int]) -> SegmentIntersection:
    return SegmentIntersection(POINT, ((p[0], p[1], 1),))


def intersect_segments(
    a: Sequence[int], b: Sequence[int], c: Sequence[int], d: Sequence[int]
) -> SegmentIntersection:
    """Exact intersection of the closed integer segments ``ab`` and ``cd``.

    Handles every case: disjoint, proper crossing (a rational point), touching at an
    endpoint, T-junctions (an endpoint in the other segment's interior), collinear
    overlaps (returns both overlap endpoints), collinear segments touching at one point,
    and zero-length segments (treated as points).
    """
    ax, ay = a[0], a[1]
    bx, by = b[0], b[1]
    cx, cy = c[0], c[1]
    dx, dy = d[0], d[1]
    # bounding-box rejection
    if ax < bx:
        if (cx < ax and dx < ax) or (cx > bx and dx > bx):
            return NO_INTERSECTION
    elif (cx < bx and dx < bx) or (cx > ax and dx > ax):
        return NO_INTERSECTION
    if ay < by:
        if (cy < ay and dy < ay) or (cy > by and dy > by):
            return NO_INTERSECTION
    elif (cy < by and dy < by) or (cy > ay and dy > ay):
        return NO_INTERSECTION

    ux, uy = bx - ax, by - ay
    vx, vy = dx - cx, dy - cy
    if ux == 0 and uy == 0:  # ab is a point
        if vx == 0 and vy == 0:
            return _pt(a) if (ax == cx and ay == cy) else NO_INTERSECTION
        return _pt(a) if on_segment(a, c, d) else NO_INTERSECTION
    if vx == 0 and vy == 0:  # cd is a point
        return _pt(c) if on_segment(c, a, b) else NO_INTERSECTION

    d1 = ux * (cy - ay) - uy * (cx - ax)  # orient(a, b, c)
    d2 = ux * (dy - ay) - uy * (dx - ax)  # orient(a, b, d)
    if (d1 > 0 and d2 > 0) or (d1 < 0 and d2 < 0):
        return NO_INTERSECTION
    if d1 == 0 and d2 == 0:
        return _collinear(a, b, c, d, ux, uy)
    d3 = vx * (ay - cy) - vy * (ax - cx)  # orient(c, d, a)
    d4 = vx * (by - cy) - vy * (bx - cx)  # orient(c, d, b)
    if (d3 > 0 and d4 > 0) or (d3 < 0 and d4 < 0):
        return NO_INTERSECTION
    # The lines are distinct and meet in one point, which lies on both segments.
    # If an endpoint is on the other line, it is that point (T-junction or touch).
    if d1 == 0:
        return _pt(c)
    if d2 == 0:
        return _pt(d)
    if d3 == 0:
        return _pt(a)
    if d4 == 0:
        return _pt(b)
    # Proper crossing: p = a + t (b - a) with t = d3 / (d3 - d4).
    w = d3 - d4
    x = ax * w + d3 * ux
    y = ay * w + d3 * uy
    if w < 0:
        x, y, w = -x, -y, -w
    g = gcd(x, y, w)
    if g != 1:
        x, y, w = x // g, y // g, w // g
    return SegmentIntersection(POINT, ((x, y, w),))


def _collinear(a, b, c, d, ux, uy) -> SegmentIntersection:
    """Both segments lie on one line; intersect their projections on the major axis."""
    k = 0 if abs(ux) >= abs(uy) else 1
    s1, e1 = (a, b) if a[k] <= b[k] else (b, a)
    s2, e2 = (c, d) if c[k] <= d[k] else (d, c)
    lo = s1 if s1[k] >= s2[k] else s2
    hi = e1 if e1[k] <= e2[k] else e2
    if lo[k] > hi[k]:
        return NO_INTERSECTION
    if lo[k] == hi[k]:
        return _pt(lo)
    p, q = (lo[0], lo[1], 1), (hi[0], hi[1], 1)
    if a[k] > b[k]:  # report in the direction a -> b
        p, q = q, p
    return SegmentIntersection(OVERLAP, (p, q))


def segments_intersect(
    a: Sequence[int], b: Sequence[int], c: Sequence[int], d: Sequence[int]
) -> bool:
    """True if the closed segments ``ab`` and ``cd`` share at least one point (generic)."""
    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True
    return (
        (o1 == 0 and on_segment(c, a, b))
        or (o2 == 0 and on_segment(d, a, b))
        or (o3 == 0 and on_segment(a, c, d))
        or (o4 == 0 and on_segment(b, c, d))
    )


# ------------------------------------------------------------------ angular order


def quadrant(dx: Any, dy: Any) -> int:
    """Quadrant of a non-zero direction vector, counter-clockwise from +x:
    0 for angles in [0, pi/2), 1 for [pi/2, pi), 2 for [pi, 3pi/2), 3 for [3pi/2, 2pi).
    """
    if dx > 0 and dy >= 0:
        return 0
    if dx <= 0 and dy > 0:
        return 1
    if dx < 0 and dy <= 0:
        return 2
    if dx >= 0 and dy < 0:
        return 3
    raise ValueError("the zero vector has no direction")


def angle_cmp(u: Sequence, v: Sequence) -> int:
    """Compare direction vectors by angle, counter-clockwise from the +x axis in
    [0, 2pi): quadrant first, then the sign of the cross product. Returns 0 only for
    vectors with the same direction. Generic."""
    qu, qv = quadrant(u[0], u[1]), quadrant(v[0], v[1])
    if qu != qv:
        return -1 if qu < qv else 1
    c = u[0] * v[1] - u[1] * v[0]
    return (c < 0) - (c > 0)


#: Sort key for direction vectors by angle: ``sorted(vectors, key=angle_key)``.
angle_key = cmp_to_key(angle_cmp)


def sort_by_angle(vectors: Sequence[Sequence]) -> list[int]:
    """Indices of ``vectors`` in counter-clockwise angular order from the +x axis
    (stable for equal directions)."""
    return sorted(range(len(vectors)), key=lambda i: angle_key(vectors[i]))


# ------------------------------------------------------------------ squared distances


def sqdist(p: Sequence, q: Sequence) -> Any:
    """Squared Euclidean distance between two points (generic)."""
    dx, dy = p[0] - q[0], p[1] - q[1]
    return dx * dx + dy * dy


def sqdist_point_segment(p: Sequence[int], a: Sequence[int], b: Sequence[int]) -> tuple[int, int]:
    """Exact squared distance from point ``p`` to the closed segment ``ab`` as
    ``(num, den)``."""
    ux, uy = b[0] - a[0], b[1] - a[1]
    wx, wy = p[0] - a[0], p[1] - a[1]
    t = ux * wx + uy * wy
    if t <= 0:
        return wx * wx + wy * wy, 1
    len2 = ux * ux + uy * uy
    if t >= len2:
        return sqdist(p, b), 1
    c = ux * wy - uy * wx
    return c * c, len2


def sqdist_segment_segment(
    a: Sequence[int], b: Sequence[int], c: Sequence[int], d: Sequence[int]
) -> tuple[int, int]:
    """Exact squared distance between the closed segments ``ab`` and ``cd``."""
    if segments_intersect(a, b, c, d):
        return 0, 1
    best = sqdist_point_segment(a, c, d)
    for cand in (
        sqdist_point_segment(b, c, d),
        sqdist_point_segment(c, a, b),
        sqdist_point_segment(d, a, b),
    ):
        if ratio_cmp(cand, best) < 0:
            best = cand
    return best


def hp_sqdist(p: HPoint, q: HPoint) -> tuple[int, int]:
    """Exact squared distance between two homogeneous points as ``(num, den)``."""
    pw, qw = p[2], q[2]
    dx = p[0] * qw - q[0] * pw
    dy = p[1] * qw - q[1] * pw
    w = pw * qw
    return dx * dx + dy * dy, w * w


def ratio_cmp(r: tuple[int, int], s: tuple[int, int]) -> int:
    """Compare two ``(num, den)`` ratios with positive denominators: -1, 0 or 1."""
    a, b = r[0] * s[1], s[0] * r[1]
    return (a > b) - (a < b)


# ------------------------------------------------------------------- point in ring


def point_in_ring(p: Sequence, ring: Sequence[Sequence]) -> int:
    """Locate ``p`` against the region bounded by ``ring`` (generic).

    Returns :data:`INSIDE` (1), :data:`ON_BOUNDARY` (0) or :data:`OUTSIDE` (-1). The
    ring may be closed or open (the closing edge is implied) and need not be simple;
    the inside is decided by the even-odd (crossing-number) rule, with any point on
    an edge reported as on the boundary.
    """
    px, py = p[0], p[1]
    inside = False
    n = len(ring)
    for i in range(n):
        a, b = ring[i - 1], ring[i]
        ax, ay, bx, by = a[0], a[1], b[0], b[1]
        if (ay > py) != (by > py):
            # the edge straddles the horizontal line through p
            o = (bx - ax) * (py - ay) - (by - ay) * (px - ax)
            if o == 0:
                return ON_BOUNDARY
            if (o > 0) == (by > ay):
                inside = not inside
        elif ay == py and by == py:
            # horizontal edge on p's line
            if ax <= px <= bx or bx <= px <= ax:
                return ON_BOUNDARY
        elif (ax == px and ay == py) or (bx == px and by == py):
            return ON_BOUNDARY
    return INSIDE if inside else OUTSIDE


def hp_in_ring(p: HPoint, ring: Sequence[Sequence[int]]) -> int:
    """:func:`point_in_ring` for a homogeneous point against an integer ring."""
    x, y, w = p
    if w == 1:
        return point_in_ring((x, y), ring)
    inside = False
    n = len(ring)
    for i in range(n):
        a, b = ring[i - 1], ring[i]
        ayw, byw = a[1] * w, b[1] * w
        if (ayw > y) != (byw > y):
            o = (b[0] - a[0]) * (y - ayw) - (b[1] - a[1]) * (x - a[0] * w)
            if o == 0:
                return ON_BOUNDARY
            if (o > 0) == (byw > ayw):
                inside = not inside
        elif ayw == y and byw == y:
            axw, bxw = a[0] * w, b[0] * w
            if axw <= x <= bxw or bxw <= x <= axw:
                return ON_BOUNDARY
        elif (ayw == y and a[0] * w == x) or (byw == y and b[0] * w == x):
            return ON_BOUNDARY  # p is a vertex (possible only for a non-reduced triple)
    return INSIDE if inside else OUTSIDE
