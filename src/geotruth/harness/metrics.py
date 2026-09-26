"""Exact grading metrics of a library's overlay output (DESIGN §4.3).

Everything here is exact: coordinates are rationals (library doubles converted exactly,
engine results as they are), and every comparison that decides a tier is an exact sign
test. The metrics are:

- **Even-odd area** (:func:`even_odd_area`) of any set of rings, by a vertical slab
  decomposition. It measures a library's output as DESIGN §4.3 prescribes, even when the
  output is invalid (the point set of an invalid output is defined by even-odd).
- **Symmetric-difference area** of the exact result E and the library output L: even-odd
  parity is additive, so ``|E xor L| = even_odd_area(rings(E) + rings(L))``.
- **Exact squared Hausdorff distance** (:func:`hausdorff2`) between the boundaries and
  lower-dimensional parts of E and L: the polygon rings, the lines and the points. Along a
  segment s the squared distance to a segment or point f is a convex piecewise quadratic
  in the segment parameter, with rational coefficients and rational breakpoints; the
  maximum over s of the lower envelope ``min_f d^2(s(t), f)`` is attained at an end of s or
  where two of those quadratics cross. A crossing is a root of a quadratic, ``p + r sqrt(D)``,
  so the squared Hausdorff distance is a quadratic surd ``a + b sqrt(D)``
  (:class:`Surd`), compared exactly with rationals and with other surds.
- **The tube bound** (:func:`tube_bound`): ``2 delta (P_E + P_L) + pi delta^2 n``, the area
  of a delta-tube around both boundaries, with a rational *upper* bound for every
  irrational quantity (perimeters, pi, delta), so a library is never called gross because
  of the bound's own rounding.

Components: every feature of E carries the polygon it belongs to and, for a hole, the
hole, so that thin exact components or holes ("that fit inside the delta-tube of their
own boundary", :func:`is_thin`) can be excused when they vanish (DESIGN §4.3, tier 3).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from math import isqrt
from typing import Any

from geotruth.geom import (
    Geometry,
    LineString,
    Point,
    Polygon,
)
from geotruth.numbers import NonFiniteError, rational, rational_type

__all__ = [
    "PI_UPPER",
    "Component",
    "Feature",
    "Shape",
    "Surd",
    "directed_hausdorff2",
    "even_odd_area",
    "hausdorff2",
    "is_thin",
    "q",
    "shape_of",
    "sqrt_lower",
    "sqrt_upper",
    "tube_bound",
]

Pt = tuple[Any, Any]

#: A rational upper bound of pi (355/113 exceeds pi by 2.7e-7).
PI_UPPER = rational(355, 113)


# ============================================================================ numbers


def q(v: Any) -> Any:
    """The exact rational value of a coordinate (float, int, Fraction or mpq)."""
    if isinstance(v, float):
        if not math.isfinite(v):
            raise NonFiniteError(f"non-finite coordinate {v!r}")
        n, d = v.as_integer_ratio()
        return rational(n, d)
    if isinstance(v, int) and not isinstance(v, bool):
        return rational(v)
    if isinstance(v, rational_type()):
        return v
    return rational(int(v.numerator), int(v.denominator))


def _sign(x: Any) -> int:
    return (x > 0) - (x < 0)


def _nd(x: Any) -> tuple[int, int]:
    return int(x.numerator), int(x.denominator)


def _is_square(x: Any) -> Any | None:
    """The exact square root of a non-negative rational, or None if it is irrational."""
    n, d = _nd(x)
    rn, rd = isqrt(n), isqrt(d)
    if rn * rn == n and rd * rd == d:
        return rational(rn, rd)
    return None


def _sqrt_bounds(x: Any, bits: int = 64) -> tuple[Any, Any]:
    n, d = _nd(x)
    if n <= 0:
        return rational(0), rational(0)
    nd = n * d
    k = max(0, (2 * bits + 4 - nd.bit_length()) // 2 + 1)
    s = isqrt(nd << (2 * k))
    den = d << k
    if s * s == nd << (2 * k):
        return rational(s, den), rational(s, den)
    return rational(s, den), rational(s + 1, den)


def sqrt_upper(x: Any) -> Any:
    """A rational upper bound of ``sqrt(x)`` (relative error below 2^-64)."""
    return _sqrt_bounds(q(x))[1]


def sqrt_lower(x: Any) -> Any:
    """A rational lower bound of ``sqrt(x)`` (relative error below 2^-64)."""
    return _sqrt_bounds(q(x))[0]


def _sign_ab(a: Any, b: Any, d: Any) -> int:
    """Sign of ``a + b sqrt(d)`` (``d >= 0``)."""
    if b == 0 or d == 0:
        return _sign(a)
    sb = _sign(b)
    sa = _sign(a)
    if sa == 0 or sa == sb:
        return sb if sa == 0 else sa
    return sa * _sign(a * a - b * b * d)


def _sign3(a: Any, b: Any, d1: Any, c: Any, d2: Any) -> int:
    """Sign of ``a + b sqrt(d1) + c sqrt(d2)`` (``d1, d2 >= 0``), exactly."""
    if c == 0 or d2 == 0:
        return _sign_ab(a, b, d1)
    if b == 0 or d1 == 0:
        return _sign_ab(a, c, d2)
    if d1 == d2:
        return _sign_ab(a, b + c, d1)
    s1 = _sign_ab(a, b, d1)  # u = a + b sqrt(d1)
    s2 = _sign(c)  # v = c sqrt(d2)
    if s1 == 0:
        return s2
    if s1 == s2:
        return s1
    # opposite signs: sign(u + v) = sign(u) * sign(u^2 - v^2)
    return s1 * _sign_ab(a * a + b * b * d1 - c * c * d2, 2 * a * b, d1)


class Surd:
    """An exact real number ``a + b sqrt(d)`` with rational ``a``, ``b`` and ``d >= 0``.

    Normalised so that ``b == d == 0`` whenever the value is rational. Surds compare
    exactly with each other and with rationals (ints, Fractions, mpq).
    """

    __slots__ = ("a", "b", "d")

    def __init__(self, a: Any, b: Any = 0, d: Any = 0) -> None:
        a, b, d = q(a), q(b), q(d)
        if d < 0:
            raise ValueError("negative radicand")
        if b != 0 and d != 0:
            r = _is_square(d)
            if r is not None:
                a, b, d = a + b * r, rational(0), rational(0)
        else:
            b, d = rational(0), rational(0)
        self.a, self.b, self.d = a, b, d

    @property
    def is_rational(self) -> bool:
        return self.b == 0

    def _cmp(self, other: Any) -> int:
        o = other if isinstance(other, Surd) else Surd(other)
        return _sign3(self.a - o.a, self.b, self.d, -o.b, o.d)

    def __lt__(self, other: Any) -> bool:
        return self._cmp(other) < 0

    def __le__(self, other: Any) -> bool:
        return self._cmp(other) <= 0

    def __gt__(self, other: Any) -> bool:
        return self._cmp(other) > 0

    def __ge__(self, other: Any) -> bool:
        return self._cmp(other) >= 0

    def __eq__(self, other: object) -> bool:
        try:
            return self._cmp(other) == 0
        except (TypeError, AttributeError):
            return NotImplemented

    def __hash__(self) -> int:
        return hash((self.a, self.b, self.d))

    def __float__(self) -> float:
        return float(self.a) + float(self.b) * math.sqrt(float(self.d))

    def __repr__(self) -> str:
        if self.is_rational:
            return f"Surd({self.a})"
        return f"Surd({self.a} + {self.b}*sqrt({self.d}))"

    def upper(self) -> Any:
        """A rational upper bound of the value (the value itself when rational)."""
        if self.is_rational:
            return self.a
        lo, hi = _sqrt_bounds(self.d)
        return self.a + (self.b * hi if self.b > 0 else self.b * lo)

    def to_json(self) -> dict[str, str]:
        from geotruth.numbers import format_rational

        return {
            "a": format_rational(self.a),
            "b": format_rational(self.b),
            "d": format_rational(self.d),
        }


ZERO_SURD = Surd(0)


# ============================================================================ shapes


@dataclass
class Shape:
    """A geometry's parts with exact rational coordinates.

    ``polygons``: each polygon is a list of rings (open lists: the closing point is
    dropped), ring 0 the shell. ``lines``: coordinate lists. ``points``: coordinates.
    Empty elements are skipped.
    """

    polygons: list[list[list[Pt]]] = field(default_factory=list)
    lines: list[list[Pt]] = field(default_factory=list)
    points: list[Pt] = field(default_factory=list)

    def rings(self) -> list[list[Pt]]:
        return [r for p in self.polygons for r in p]

    @property
    def num_vertices(self) -> int:
        return (
            sum(len(r) for r in self.rings()) + sum(len(x) for x in self.lines) + len(self.points)
        )

    @property
    def is_empty(self) -> bool:
        return not (self.polygons or self.lines or self.points)


def _open_ring(coords: Sequence) -> list[Pt]:
    pts = [(q(c[0]), q(c[1])) for c in coords]
    out: list[Pt] = []
    for p in pts:
        if not out or out[-1] != p:
            out.append(p)
    if len(out) > 1 and out[0] == out[-1]:
        out.pop()
    return out


def shape_of(geom: Geometry) -> Shape:
    """The exact :class:`Shape` of a geometry (raises NonFiniteError for NaN/inf)."""
    s = Shape()
    for e in geom.elements():
        if e.is_empty:
            continue
        if isinstance(e, Polygon):
            rings = [_open_ring(r) for r in e.rings]
            rings = [r for r in rings if r]
            if rings:
                s.polygons.append(rings)
        elif isinstance(e, LineString):
            pts = [(q(c[0]), q(c[1])) for c in e.coords]
            s.lines.append(pts)
        elif isinstance(e, Point):
            assert e.coord is not None
            s.points.append((q(e.coord[0]), q(e.coord[1])))
    return s


def ring_area2(ring: Sequence[Pt]) -> Any:
    """Twice the signed area of an open ring (positive counter-clockwise)."""
    total = rational(0)
    n = len(ring)
    for i in range(n):
        (x0, y0), (x1, y1) = ring[i - 1], ring[i]
        total += x0 * y1 - x1 * y0
    return total


def _edges(rings: Iterable[Sequence[Pt]]) -> list[tuple[Pt, Pt]]:
    out = []
    for r in rings:
        n = len(r)
        for i in range(n):
            p, s = r[i], r[(i + 1) % n]
            if p != s:
                out.append((p, s))
    return out


# ============================================================================ even-odd area


def _proper_crossing_x(a: Pt, b: Pt, c: Pt, d: Pt) -> Any | None:
    """The x of the proper crossing of segments ab and cd, or None."""
    d1 = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d2 = (b[0] - a[0]) * (d[1] - a[1]) - (b[1] - a[1]) * (d[0] - a[0])
    if d1 == 0 or d2 == 0 or (d1 > 0) == (d2 > 0):
        return None
    d3 = (d[0] - c[0]) * (a[1] - c[1]) - (d[1] - c[1]) * (a[0] - c[0])
    d4 = (d[0] - c[0]) * (b[1] - c[1]) - (d[1] - c[1]) * (b[0] - c[0])
    if d3 == 0 or d4 == 0 or (d3 > 0) == (d4 > 0):
        return None
    t = d3 / (d3 - d4)
    return a[0] + t * (b[0] - a[0])


def even_odd_area(rings: Iterable[Sequence[Pt]]) -> Any:
    """Exact area of the even-odd point set of a set of open rings (any orientation,
    self-intersections and overlaps allowed): a vertical slab decomposition in which the
    edges crossing each open slab are totally ordered."""
    edges = [(p, s) if p[0] < s[0] else (s, p) for p, s in _edges(rings) if p[0] != s[0]]
    if not edges:
        return rational(0)
    xs = {e[0][0] for e in edges} | {e[1][0] for e in edges}
    # proper crossings, with an x-sorted sweep so only x-overlapping pairs are tested
    order = sorted(range(len(edges)), key=lambda i: edges[i][0][0])
    active: list[int] = []
    for i in order:
        a, b = edges[i]
        ylo, yhi = min(a[1], b[1]), max(a[1], b[1])
        active = [j for j in active if edges[j][1][0] > a[0]]
        for j in active:
            c, d = edges[j]
            if max(c[1], d[1]) < ylo or min(c[1], d[1]) > yhi:
                continue
            x = _proper_crossing_x(a, b, c, d)
            if x is not None:
                xs.add(x)
        active.append(i)
    xs_sorted = sorted(xs)
    total = rational(0)
    half = rational(1, 2)
    k = 0
    live: list[tuple[Pt, Pt]] = []
    for xl, xr in pairwise(xs_sorted):
        while k < len(order) and edges[order[k]][0][0] <= xl:
            live.append(edges[order[k]])
            k += 1
        live = [e for e in live if e[1][0] > xl]
        span = []
        for a, b in live:
            if a[0] <= xl and b[0] >= xr:
                slope = (b[1] - a[1]) / (b[0] - a[0])
                span.append((a[1] + slope * (xl - a[0]), a[1] + slope * (xr - a[0])))
        if len(span) < 2:
            continue
        span.sort(key=lambda t: t[0] + t[1])
        w = (xr - xl) * half
        inside = False
        for (yl0, yr0), (yl1, yr1) in pairwise(span):
            inside = not inside
            if inside:
                total += w * ((yl1 - yl0) + (yr1 - yr0))
    return total


def perimeter_upper(rings: Iterable[Sequence[Pt]], lines: Iterable[Sequence[Pt]] = ()) -> Any:
    """A rational upper bound of the total length of the rings and lines."""
    total = rational(0)
    for p, s in _edges(rings):
        total += sqrt_upper((s[0] - p[0]) ** 2 + (s[1] - p[1]) ** 2)
    for line in lines:
        for p, s in pairwise(line):
            total += sqrt_upper((s[0] - p[0]) ** 2 + (s[1] - p[1]) ** 2)
    return total


def tube_bound(delta2: Any, perimeter: Any, n_vertices: int) -> Any:
    """A rational upper bound of ``2 delta P + pi delta^2 n`` for ``delta = sqrt(delta2)``."""
    d2 = q(delta2)
    return 2 * sqrt_upper(d2) * q(perimeter) + PI_UPPER * d2 * n_vertices


def is_thin(area: Any, perimeter_up: Any, n_vertices: int, delta2: Any) -> bool:
    """True if a region of this area fits inside the delta-tube of its own boundary, by
    area: ``area <= 2 delta P + pi delta^2 n`` (DESIGN §4.3: such exact components or
    holes may vanish or collapse). Every region whose points all lie within delta of its
    boundary passes; the test is lenient by up to a factor of about two in width."""
    return q(area) <= tube_bound(delta2, perimeter_up, n_vertices)


# ============================================================================ Hausdorff


@dataclass(frozen=True)
class Component:
    """Which part of a shape a feature belongs to: ``("poly", i)``, ``("hole", i, k)``,
    ``("line", j)`` or ``("point", j)``."""

    key: tuple


@dataclass
class Feature:
    """A segment ``p -> s`` (or a point, ``s is None``) of a shape's boundary or
    lower-dimensional parts, with its polygon and hole keys."""

    p: Pt
    s: Pt | None
    poly: int | None = None
    hole: tuple[int, int] | None = None
    line: int | None = None
    point: int | None = None
    bbox: tuple[Any, Any, Any, Any] = field(init=False)

    def __post_init__(self) -> None:
        if self.s is None:
            self.bbox = (self.p[0], self.p[0], self.p[1], self.p[1])
        else:
            self.bbox = (
                min(self.p[0], self.s[0]),
                max(self.p[0], self.s[0]),
                min(self.p[1], self.s[1]),
                max(self.p[1], self.s[1]),
            )


def features_of(shape: Shape) -> list[Feature]:
    """Every boundary segment, line segment and point of a shape."""
    out: list[Feature] = []
    for i, poly in enumerate(shape.polygons):
        for k, ring in enumerate(poly):
            hole = (i, k) if k > 0 else None
            n = len(ring)
            if n == 1:
                out.append(Feature(ring[0], None, poly=i, hole=hole))
            for j in range(n if n > 1 else 0):
                p, s = ring[j], ring[(j + 1) % n]
                if p != s:
                    out.append(Feature(p, s, poly=i, hole=hole))
    for j, line in enumerate(shape.lines):
        segs = [(p, s) for p, s in pairwise(line) if p != s]
        if not segs:
            out.append(Feature(line[0], None, line=j))
        out += [Feature(p, s, line=j) for p, s in segs]
    for j, pt in enumerate(shape.points):
        out.append(Feature(pt, None, point=j))
    return out


def _pt_dist2(v: Pt, f: Feature) -> Any:
    """Exact squared distance from point v to feature f."""
    a = f.p
    if f.s is None:
        return (v[0] - a[0]) ** 2 + (v[1] - a[1]) ** 2
    b = f.s
    ux, uy = b[0] - a[0], b[1] - a[1]
    wx, wy = v[0] - a[0], v[1] - a[1]
    t = ux * wx + uy * wy
    if t <= 0:
        return wx * wx + wy * wy
    len2 = ux * ux + uy * uy
    if t >= len2:
        return (v[0] - b[0]) ** 2 + (v[1] - b[1]) ** 2
    c = ux * wy - uy * wx
    return c * c / len2


def _bbox_dist2(bb1: tuple, bb2: tuple) -> Any:
    dx = max(bb2[0] - bb1[1], bb1[0] - bb2[1], 0)
    dy = max(bb2[2] - bb1[3], bb1[2] - bb2[3], 0)
    return dx * dx + dy * dy


def _orient(a: Pt, b: Pt, c: Pt) -> int:
    return _sign((b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]))


def _on_seg(p: Pt, a: Pt, b: Pt) -> bool:
    return (
        min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
        and _orient(a, b, p) == 0
    )


def _seg_dist2(f: Feature, g: Feature) -> Any:
    """Exact squared distance between two features."""
    if f.s is None:
        return _pt_dist2(f.p, g)
    if g.s is None:
        return _pt_dist2(g.p, f)
    a, b, c, d = f.p, f.s, g.p, g.s
    o1, o2, o3, o4 = _orient(a, b, c), _orient(a, b, d), _orient(c, d, a), _orient(c, d, b)
    if (o1 * o2 < 0 and o3 * o4 < 0) or (
        (o1 == 0 and _on_seg(c, a, b))
        or (o2 == 0 and _on_seg(d, a, b))
        or (o3 == 0 and _on_seg(a, c, d))
        or (o4 == 0 and _on_seg(b, c, d))
    ):
        return rational(0)
    return min(_pt_dist2(a, g), _pt_dist2(b, g), _pt_dist2(c, f), _pt_dist2(d, f))


# A quadratic alpha t^2 + beta t + gamma, and the pieces of a feature's squared distance
# along a segment P + t u: (lo, hi, quadratic) with lo/hi None for -inf/+inf.
Quad = tuple[Any, Any, Any]


def _pieces(P: Pt, u: Pt, f: Feature) -> list[tuple[Any, Any, Quad]]:
    def to_point(A: Pt) -> Quad:
        wx, wy = P[0] - A[0], P[1] - A[1]
        return (u[0] * u[0] + u[1] * u[1], 2 * (u[0] * wx + u[1] * wy), wx * wx + wy * wy)

    if f.s is None:
        return [(None, None, to_point(f.p))]
    A, B = f.p, f.s
    ex, ey = B[0] - A[0], B[1] - A[1]
    L2 = ex * ex + ey * ey
    wx, wy = P[0] - A[0], P[1] - A[1]
    lam0 = (wx * ex + wy * ey) / L2
    lam1 = (u[0] * ex + u[1] * ey) / L2
    c0 = ex * wy - ey * wx
    c1 = ex * u[1] - ey * u[0]
    perp: Quad = (c1 * c1 / L2, 2 * c0 * c1 / L2, c0 * c0 / L2)
    qa, qb = to_point(A), to_point(B)
    if lam1 == 0:
        return [(None, None, qa if lam0 <= 0 else qb if lam0 >= 1 else perp)]
    t0 = -lam0 / lam1
    t1 = (1 - lam0) / lam1
    if lam1 > 0:
        return [(None, t0, qa), (t0, t1, perp), (t1, None, qb)]
    return [(None, t1, qb), (t1, t0, perp), (t0, None, qa)]


# A parameter value: (p, r, D) meaning p + r sqrt(D).
Param = tuple[Any, Any, Any]


def _cmp_param(t: Param, c: Any) -> int:
    """Sign of ``t - c`` for a rational c."""
    return _sign_ab(t[0] - c, t[1], t[2])


def _in_range(t: Param, lo: Any, hi: Any) -> bool:
    return (lo is None or _cmp_param(t, lo) >= 0) and (hi is None or _cmp_param(t, hi) <= 0)


def _roots(a: Any, b: Any, c: Any) -> list[Param]:
    zero = rational(0)
    if a == 0:
        if b == 0:
            return []
        return [(-c / b, zero, zero)]
    disc = b * b - 4 * a * c
    if disc < 0:
        return []
    p = -b / (2 * a)
    if disc == 0:
        return [(p, zero, zero)]
    r = _is_square(disc)
    if r is not None:
        return [(p - r / (2 * a), zero, zero), (p + r / (2 * a), zero, zero)]
    s = 1 / (2 * a)
    return [(p, s, disc), (p, -s, disc)]


def _eval(quad: Quad, t: Param) -> tuple[Any, Any]:
    """``quad(t) = A + B sqrt(D)`` as (A, B)."""
    al, be, ga = quad
    p, r, d = t
    return (al * (p * p + r * r * d) + be * p + ga, (2 * al * p + be) * r)


def _piece_at(pieces: list[tuple[Any, Any, Quad]], t: Param) -> Quad:
    for lo, hi, quad in pieces:
        if (hi is None or _cmp_param(t, hi) <= 0) and (lo is None or _cmp_param(t, lo) >= 0):
            return quad
    return pieces[-1][2]


def _segment_max(f: Feature, targets: list[Feature], best: Surd) -> Surd:
    """The exact maximum over the segment f of the squared distance to the union of
    ``targets`` (all features that can be nearest anywhere on f), or ``best`` if that is
    larger."""
    P, S = f.p, f.s
    assert S is not None
    u = (S[0] - P[0], S[1] - P[1])
    zero = rational(0)
    pieces = [_pieces(P, u, g) for g in targets]
    cands: list[Param] = []
    for i in range(len(targets)):
        for j in range(i + 1, len(targets)):
            for lo1, hi1, q1 in pieces[i]:
                for lo2, hi2, q2 in pieces[j]:
                    lo = max(x for x in (lo1, lo2, zero) if x is not None)
                    hi = min(x for x in (hi1, hi2, rational(1)) if x is not None)
                    if lo > hi:
                        continue
                    da, db, dc = q1[0] - q2[0], q1[1] - q2[1], q1[2] - q2[2]
                    if da == 0 and db == 0 and dc == 0:
                        continue
                    cands += [t for t in _roots(da, db, dc) if _in_range(t, lo, hi)]
    for t in cands:
        # the envelope at t: the smallest of every target's squared distance there
        vals = [_eval(_piece_at(pc, t), t) for pc in pieces]
        a0, b0 = vals[0]
        for a1, b1 in vals[1:]:
            if _sign_ab(a1 - a0, b1 - b0, t[2]) < 0:
                a0, b0 = a1, b1
        v = Surd(a0, b0, t[2])
        if v > best:
            best = v
    return best


def directed_hausdorff2(
    source: list[Feature], target: list[Feature], *, per_feature: bool = False
) -> Any:
    """The exact squared directed Hausdorff distance ``max_{x in source} d^2(x, target)``
    as a :class:`Surd` (``per_feature=True``: a list with one value per source feature).
    An empty target gives None (infinite distance) unless the source is empty too."""
    if not source:
        return [] if per_feature else ZERO_SURD
    if not target:
        return [None] * len(source) if per_feature else None
    # nearest distance of every source vertex, with the previous best target first
    vert: dict[Pt, Any] = {}
    hint = 0

    def nearest(v: Pt) -> Any:
        nonlocal hint
        if v in vert:
            return vert[v]
        best = _pt_dist2(v, target[hint])
        vb = (v[0], v[0], v[1], v[1])
        for k, g in enumerate(target):
            if k == hint or _bbox_dist2(vb, g.bbox) >= best:
                continue
            d = _pt_dist2(v, g)
            if d < best:
                best, hint = d, k
        vert[v] = best
        return best

    out: list[Surd] = []
    for f in source:
        if f.s is None:
            out.append(Surd(nearest(f.p)))
            continue
        lb = max(nearest(f.p), nearest(f.s))
        # an upper bound: the farther end's distance to any single target (convexity)
        ub = min(max(_pt_dist2(f.p, g), _pt_dist2(f.s, g)) for g in target)
        if ub == lb:
            out.append(Surd(lb))
            continue
        near = [g for g in target if _bbox_dist2(f.bbox, g.bbox) <= ub and _seg_dist2(f, g) <= ub]
        out.append(_segment_max(f, near, Surd(lb)))
    if per_feature:
        return out
    best = out[0]
    for v in out[1:]:
        if v > best:
            best = v
    return best


# ------------------------------------------------------------------ collapse excusal


def _ring_id(f: Feature) -> tuple:
    if f.poly is not None:
        return ("ring", f.poly, f.hole[1] if f.hole else 0)
    if f.line is not None:
        return ("line", f.line)
    return ("point", f.point)


def _cmp_params(t1: Param, t2: Param) -> int:
    return _sign3(t1[0] - t2[0], t1[1], t1[2], -t2[1], t2[2])


def _param_key(t: Param) -> Any:
    from functools import cmp_to_key

    return cmp_to_key(_cmp_params)(t)


def _value_at(pieces: list[tuple[Any, Any, Quad]], t: Param) -> tuple[Any, Any]:
    return _eval(_piece_at(pieces, t), t)


def _sublevel(pieces: list[tuple[Any, Any, Quad]], T: Any) -> tuple[Param, Param] | None:
    """The interval of t in [0, 1] where a convex piecewise quadratic is <= T, or None."""
    zero, one = rational(0), rational(1)
    cands: list[Param] = [(zero, zero, zero), (one, zero, zero)]
    for lo, hi, quad in pieces:
        for r in _roots(quad[0], quad[1], quad[2] - T):
            if _in_range(r, lo, hi) and _in_range(r, zero, one):
                cands.append(r)
    ok = []
    for c in cands:
        a, b = _value_at(pieces, c)
        if _sign_ab(a - T, b, c[2]) <= 0:
            ok.append(c)
    if not ok:
        return None
    return min(ok, key=_param_key), max(ok, key=_param_key)


def _collapse_max(f: Feature, targets: list[Feature], others: list[Feature], T: Any) -> Surd | None:
    """The maximum over the points of segment f that are farther than sqrt(T) from every
    feature of ``others`` of the squared distance to ``targets`` (ZERO_SURD if there are
    none; None if some remain and there is no target)."""
    P, S = f.p, f.s
    assert S is not None
    u = (S[0] - P[0], S[1] - P[1])
    zero, one = rational(0), rational(1)
    intervals = []
    for o in others:
        iv = _sublevel(_pieces(P, u, o), T)
        if iv is not None:
            intervals.append(iv)
    intervals.sort(key=lambda iv: _param_key(iv[0]))
    gaps: list[tuple[Param, Param]] = []
    cur: Param = (zero, zero, zero)
    for lo, hi in intervals:
        if _cmp_params(lo, cur) > 0:
            gaps.append((cur, lo))
        if _cmp_params(hi, cur) > 0:
            cur = hi
    end: Param = (one, zero, zero)
    if _cmp_params(cur, end) < 0:
        gaps.append((cur, end))
    if not gaps:
        return ZERO_SURD
    if not targets:
        return None
    ub = min(max(_pt_dist2(P, g), _pt_dist2(S, g)) for g in targets)
    near = [g for g in targets if _bbox_dist2(f.bbox, g.bbox) <= ub and _seg_dist2(f, g) <= ub]
    pieces = [_pieces(P, u, g) for g in near]
    cands: list[Param] = [t for gap in gaps for t in gap]
    for i in range(len(near)):
        for j in range(i + 1, len(near)):
            for lo1, hi1, q1 in pieces[i]:
                for lo2, hi2, q2 in pieces[j]:
                    lo = max(x for x in (lo1, lo2, zero) if x is not None)
                    hi = min(x for x in (hi1, hi2, one) if x is not None)
                    if lo > hi:
                        continue
                    da, db, dc = q1[0] - q2[0], q1[1] - q2[1], q1[2] - q2[2]
                    if da == 0 and db == 0 and dc == 0:
                        continue
                    cands += [t for t in _roots(da, db, dc) if _in_range(t, lo, hi)]
    best = ZERO_SURD
    for t in cands:
        if not any(_cmp_params(a, t) <= 0 <= _cmp_params(b, t) for a, b in gaps):
            continue
        vals = [_value_at(pc, t) for pc in pieces]
        a0, b0 = vals[0]
        for a1, b1 in vals[1:]:
            if _sign_ab(a1 - a0, b1 - b0, t[2]) < 0:
                a0, b0 = a1, b1
        v = Surd(a0, b0, t[2])
        if v > best:
            best = v
    return best


def directed_hausdorff2_collapse(
    source: list[Feature], target: list[Feature], threshold: Any, collapse2: Any
) -> Surd | None:
    """:func:`directed_hausdorff2` where the points of a source feature within
    ``sqrt(collapse2)`` of a *different* source ring, line or point are excused: a gap
    between two exact rings (a thin part of the exterior, or of a hole) may collapse and
    merge them, so that boundary may vanish (DESIGN §4.3). Only features whose plain value
    exceeds ``threshold`` are re-measured, so the result is exact for the comparison
    ``<= threshold`` (not as a metric)."""
    plain = directed_hausdorff2(source, target, per_feature=True) if target else None
    out: list[Surd | None] = []
    T = q(collapse2)
    for k, f in enumerate(source):
        v = plain[k] if plain is not None else None
        if v is not None and v <= threshold:
            out.append(v)
            continue
        rid = _ring_id(f)
        span = (f.bbox[0], f.bbox[1], f.bbox[2], f.bbox[3])
        others = [o for o in source if _ring_id(o) != rid and _bbox_dist2(span, o.bbox) <= T]
        if f.s is None:
            if any(_pt_dist2(f.p, o) <= T for o in others):
                out.append(ZERO_SURD)
            else:
                out.append(v)
            continue
        out.append(_collapse_max(f, target, others, T) if others else v)
    return _max(out)


def _max(values: Iterable[Surd | None]) -> Surd | None:
    best: Surd | None = ZERO_SURD
    for v in values:
        if v is None:
            return None
        if best is not None and v > best:
            best = v
    return best


def excuse_features(features: list[Feature], excuse: set[tuple]) -> list[Feature]:
    """The features not excused by the keys (see :func:`hausdorff2`)."""
    return [
        f
        for f in features
        if ("poly", f.poly) not in excuse
        and (f.hole is not None or ("shell", f.poly) not in excuse)
        and (f.hole is None or ("hole", *f.hole) not in excuse)
    ]


def hausdorff2(
    exact: Shape, lib: Shape, *, excuse: set[tuple] | None = None
) -> tuple[Surd | None, Surd | None, Surd | None]:
    """The exact squared Hausdorff distance between ``exact`` and ``lib``, as
    ``(H^2, h^2(exact -> lib), h^2(lib -> exact))``; None means infinite (one side empty,
    the other not).

    ``excuse``: keys of exact rings left out of the ``exact -> lib`` direction (thin
    components that may vanish): ``("poly", i)`` every ring of polygon i, ``("shell", i)``
    its shell, ``("hole", i, k)`` its hole k.
    """
    fe, fl = features_of(exact), features_of(lib)
    fe_dir = excuse_features(fe, excuse) if excuse else fe
    if not fe_dir and not fl:
        return ZERO_SURD, ZERO_SURD, ZERO_SURD
    h_el = directed_hausdorff2(fe_dir, fl) if fe_dir else ZERO_SURD
    h_le = directed_hausdorff2(fl, fe) if fl else ZERO_SURD
    if not fe and fl:
        h_le = None
    return _max([h_el, h_le]), h_el, h_le


# ============================================================================ components


@dataclass
class ComponentInfo:
    """A polygon component or a hole region of a shape: its even-odd ``rings``, exact
    ``area``, perimeter upper bound, vertex count, and the Hausdorff ``excuse`` keys that
    leave its boundary out when it is thin (it may vanish)."""

    key: tuple
    rings: list[list[Pt]]
    area: Any
    perimeter_up: Any
    n_vertices: int
    excuse: set[tuple] = field(default_factory=set)


def _inside_ring(ring: list[Pt], other: list[Pt]) -> bool:
    """Is the simple ring ``other`` inside ``ring`` (they may touch at points)?"""
    from geotruth.exact import INSIDE, ON_BOUNDARY, point_in_ring

    closed = [*ring, ring[0]]
    n = len(other)
    for j in range(n):
        for p in (
            other[j],
            ((other[j][0] + other[(j + 1) % n][0]) / 2, (other[j][1] + other[(j + 1) % n][1]) / 2),
        ):
            loc = point_in_ring(p, closed)
            if loc != ON_BOUNDARY:
                return loc == INSIDE
    return False


def components(shape: Shape) -> tuple[list[ComponentInfo], list[ComponentInfo]]:
    """The polygon components (key ``("poly", i)``: shell minus holes) and the hole
    regions (key ``("hole", i, k)``: the hole minus the polygons lying in it, the islands)
    of a shape. A thin polygon excuses its own rings; a thin hole region excuses the hole
    ring and its islands' shells (``("shell", j)``), which merge with the surrounding
    polygon when the gap between them vanishes."""
    polys, holes = [], []
    areas = [even_odd_area(poly) for poly in shape.polygons]
    for i, poly in enumerate(shape.polygons):
        polys.append(
            ComponentInfo(
                ("poly", i),
                poly,
                areas[i],
                perimeter_upper(poly),
                sum(len(r) for r in poly),
                {("poly", i)},
            )
        )
        for k, ring in enumerate(poly[1:], start=1):
            islands = [
                j
                for j, other in enumerate(shape.polygons)
                if j != i and _inside_ring(ring, other[0])
            ]
            rings = [ring] + [shape.polygons[j][0] for j in islands]
            area = abs(ring_area2(ring)) / 2 - sum((areas[j] for j in islands), rational(0))
            holes.append(
                ComponentInfo(
                    ("hole", i, k),
                    rings,
                    area,
                    perimeter_upper(rings),
                    sum(len(r) for r in rings),
                    {("hole", i, k), *(("shell", j) for j in islands)},
                )
            )
    return polys, holes


def overlap_area(rings_a: list[list[Pt]], area_a: Any, rings_b: list[list[Pt]], area_b: Any) -> Any:
    """Exact area of the intersection of two even-odd point sets, from
    ``|A and B| = (|A| + |B| - |A xor B|) / 2``."""
    return (area_a + area_b - even_odd_area(rings_a + rings_b)) / 2


# ============================================================================ helpers


def max_abs_ordinate(*geoms: Geometry) -> float:
    """The largest finite |ordinate| of the geometries (M of the manifests' delta)."""
    m = 0.0
    for g in geoms:
        for v in g.iter_values():
            if isinstance(v, float) and not math.isfinite(v):
                continue
            m = max(m, abs(float(v)))
    return m


def rounding_delta2(m: float) -> Any:
    """delta^2 of the correctly rounded floor for coordinates up to M: every coordinate
    is within half an ulp of M of the exact one, so a vertex moves by at most
    ``ulp(M) / sqrt(2)``: ``delta^2 = ulp(M)^2 / 2``."""
    u = q(math.ulp(m if m > 0 else 0.0))
    return u * u / 2
