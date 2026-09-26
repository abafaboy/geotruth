"""Exact measures: area, squared distance, length, centroid, convex hull (DESIGN §1
"Measures", §2.7).

Every function takes :mod:`geotruth.geom` geometries whose coordinates are doubles (input)
or exact rationals (engine output) and follows the JTS/GEOS definition of the measure:

- :func:`area` -- exact rational. JTS ``getArea``: for every Polygon element,
  ``|shell| - sum |hole|`` (shoelace, orientation ignored), summed over all elements, so
  overlapping elements of a GeometryCollection count twice. For a valid (Multi)Polygon this
  is the area of the point set. Lines and points have area 0.
- :func:`distance2` / :func:`nearest_points` -- exact rational squared distance (JTS
  ``DistanceOp``): 0 when the geometries intersect (including containment in a polygon),
  otherwise the minimum over point/point, point/segment and segment/segment pairs, with
  exact orthogonal projection. ``None`` when either geometry is empty (GEOS: NaN).
- :func:`length` -- JTS ``getLength``: line lengths plus polygon perimeters (shell and
  holes). A sum of square roots, returned as a :class:`Certified` interval refined until
  the correctly rounded double is decided (exact when every segment length is rational).
- :func:`centroid` -- JTS ``Centroid``: from the highest-dimension components only. The
  areal and puntal centroids are exact rationals; the line centroid (length-weighted
  segment midpoints) is certified like the length.
- :func:`convex_hull` -- exact monotone chain; hull vertices are input points, so the
  result holds the input coordinate objects unchanged.
- :func:`overlay_area` / :func:`relate_predicates` -- a small shim over the exact engine
  (``geotruth.overlay`` / ``geotruth.relate``, DESIGN §2.3/§2.5) that falls back to the
  vendored ``tests/reference/oracle.py`` for polygon/polygon inputs while the engine is not
  available.

Certified values
----------------
A square root ``sqrt(N)`` (``N`` an integer after scaling) is enclosed by integer square
roots: ``s = isqrt(N * 4**k)`` gives ``s <= 2**k sqrt(N) < s + 1``. Sums and ratios of such
terms are enclosed by interval arithmetic, and ``k`` doubles until both ends of the
interval round to the same double. The loop terminates because the only values that could
straddle a rounding boundary forever are exact ties; those are rational, and a sum
``sum q_i sqrt(N_i)`` is compared with a rational exactly by grouping the ``N_i`` into
classes with the same square-free part (square roots of distinct square-free integers are
linearly independent over the rationals), which needs perfect-square tests only.
"""

from __future__ import annotations

import importlib
import importlib.util
import math
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from functools import reduce
from itertools import pairwise
from pathlib import Path
from typing import Any

from geotruth import exact as X
from geotruth.geom import (
    Geometry,
    GeometryCollection,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
)
from geotruth.numbers import NonFiniteError, format_rational, rational, rational_to_float

__all__ = [
    "OVERLAY_OPS",
    "Certified",
    "CoordScale",
    "EngineUnavailable",
    "SqrtSum",
    "area",
    "case_measures",
    "centroid",
    "convex_hull",
    "distance2",
    "engine_backends",
    "length",
    "nearest_points",
    "overlay_area",
    "relate_predicates",
]


# ============================================================================ scaling


def _ratio(v: Any) -> tuple[int, int]:
    """Exact ``(numerator, denominator)`` of a coordinate value (double, int, Fraction,
    mpq)."""
    if isinstance(v, bool):
        raise TypeError("a boolean is not a coordinate")
    if isinstance(v, int):
        return v, 1
    if isinstance(v, float):
        if not math.isfinite(v):
            raise NonFiniteError(f"non-finite coordinate {v!r} has no exact value")
        return v.as_integer_ratio()
    try:
        return int(v.numerator), int(v.denominator)
    except AttributeError:
        raise TypeError(f"not a coordinate value: {v!r}") from None


def _is_finite_value(v: Any) -> bool:
    return not isinstance(v, float) or math.isfinite(v)


class CoordScale:
    """Exact scaling of coordinates to integers by a common denominator ``den``.

    For doubles ``den`` is a power of two (so this is the per-case dyadic scaling of
    DESIGN §2.1); exact rational coordinates (engine output) get the least common
    denominator. A real value ``v`` corresponds to the integer ``v * den``; lengths
    scale by ``den`` and areas and squared distances by ``den**2``.
    """

    __slots__ = ("den",)

    def __init__(self, den: int = 1):
        if den < 1:
            raise ValueError("the common denominator must be positive")
        self.den = den

    def __repr__(self) -> str:
        return f"CoordScale(den={self.den})"

    @classmethod
    def for_values(cls, values: Iterable[Any]) -> CoordScale:
        """The scale for a collection of coordinate values (non-finite ones ignored)."""
        den = 1
        for v in values:
            if not _is_finite_value(v):
                continue
            d = _ratio(v)[1]
            if den % d:
                den = den * d // math.gcd(den, d)
        return cls(den)

    @classmethod
    def for_geometry(cls, *geoms: Geometry) -> CoordScale:
        """The scale for every coordinate of the given geometries."""
        return cls.for_values(v for g in geoms for v in g.iter_values())

    # -- values -> integers ------------------------------------------------------------

    def to_int(self, v: Any) -> int:
        """The exact integer ``v * den`` (raises NonFiniteError for NaN/inf)."""
        n, d = _ratio(v)
        q, r = divmod(n * self.den, d)
        if r:
            raise ValueError(f"{v!r} is not a multiple of 1/{self.den}")
        return q

    def point(self, c: Sequence) -> tuple[int, int]:
        """A coordinate as an integer point."""
        return self.to_int(c[0]), self.to_int(c[1])

    # -- integers -> exact values --------------------------------------------------------

    def value(self, n: int, d: int = 1) -> Any:
        """The real value ``n / (d * den)`` (a length or a coordinate)."""
        return rational(int(n), int(d) * self.den)

    def area(self, n: int, d: int = 1) -> Any:
        """The real value ``n / (d * den**2)`` (an area or a squared distance)."""
        return rational(int(n), int(d) * self.den * self.den)

    def rational_hpoint(self, p: X.HPoint) -> tuple[Any, Any]:
        """A homogeneous integer point as exact real coordinates."""
        x, y, w = p
        return rational(x, w * self.den), rational(y, w * self.den)

    @staticmethod
    def rational_point(c: Sequence) -> tuple[Any, Any]:
        """The exact value of an input coordinate (no scaling involved)."""
        (xn, xd), (yn, yd) = _ratio(c[0]), _ratio(c[1])
        return rational(xn, xd), rational(yn, yd)


# ============================================================================ area


def _polygon_elements(geom: Geometry) -> list[Polygon]:
    return [e for e in geom.elements() if isinstance(e, Polygon) and not e.is_empty]


def area(geom: Geometry) -> Any:
    """Exact area, JTS ``getArea`` semantics (see the module docstring)."""
    polys = _polygon_elements(geom)
    if not polys:
        return rational(0)
    scale = CoordScale.for_geometry(geom)
    twice = 0
    for p in polys:
        for k, ring in enumerate(p.rings):
            if not ring:
                continue
            a2 = abs(X.signed_area2([scale.point(c) for c in ring]))
            twice += a2 if k == 0 else -a2
    return scale.area(twice, 2)


# ============================================================================ distance


class _Parts:
    """Points, segments and polygons of a geometry in scaled integer coordinates."""

    __slots__ = ("points", "polygons", "reps", "segments")

    def __init__(self, geom: Geometry, scale: CoordScale):
        self.points: list[tuple[int, int]] = []
        self.segments: list[tuple[tuple[int, int], tuple[int, int]]] = []
        self.polygons: list[tuple[list[tuple[int, int]], list[list[tuple[int, int]]]]] = []
        self.reps: list[tuple[int, int]] = []  # one point per connected component
        for e in geom.elements():
            if e.is_empty:
                continue
            if isinstance(e, Point):
                p = scale.point(e.coord)
                self.points.append(p)
                self.reps.append(p)
            elif isinstance(e, LineString):
                self._chain([scale.point(c) for c in e.coords])
            else:
                rings = [[scale.point(c) for c in r] for r in e.rings if r]
                for r in rings:
                    self._chain(r)
                self.polygons.append((rings[0], rings[1:]))

    def _chain(self, pts: list[tuple[int, int]]) -> None:
        self.reps.append(pts[0])
        n0 = len(self.segments)
        for p, q in pairwise(pts):
            if p != q:
                self.segments.append((p, q))
        if len(self.segments) == n0:  # zero length: a point
            self.points.append(pts[0])


def _in_polygon(p: Sequence[int], shell, holes) -> bool:
    """Closed point-in-polygon (interior or boundary)."""
    loc = X.point_in_ring(p, shell)
    if loc == X.OUTSIDE:
        return False
    if loc == X.ON_BOUNDARY:
        return True
    return all(X.point_in_ring(p, h) != X.INSIDE for h in holes)


def _foot(p, a, b) -> X.HPoint:
    """The point of segment ``ab`` nearest to ``p`` (exact, homogeneous)."""
    ux, uy = b[0] - a[0], b[1] - a[1]
    t = ux * (p[0] - a[0]) + uy * (p[1] - a[1])
    if t <= 0:
        return (a[0], a[1], 1)
    len2 = ux * ux + uy * uy
    if t >= len2:
        return (b[0], b[1], 1)
    return X.hpoint(a[0] * len2 + t * ux, a[1] * len2 + t * uy, len2)


def _bbox_of(item) -> tuple[int, int, int, int]:
    if len(item) == 2 and isinstance(item[0], int):
        return item[0], item[1], item[0], item[1]
    (ax, ay), (bx, by) = item
    return min(ax, bx), min(ay, by), max(ax, bx), max(ay, by)


def _pair_distance(u, v) -> tuple[tuple[int, int], X.HPoint, X.HPoint]:
    """Exact squared distance ``(num, den)`` between two items (a point ``(x, y)`` or a
    segment ``((x, y), (x, y))``) and a pair of nearest points."""
    upt = isinstance(u[0], int)
    vpt = isinstance(v[0], int)
    if upt and vpt:
        return (X.sqdist(u, v), 1), (u[0], u[1], 1), (v[0], v[1], 1)
    if upt:
        return X.sqdist_point_segment(u, v[0], v[1]), (u[0], u[1], 1), _foot(u, v[0], v[1])
    if vpt:
        return X.sqdist_point_segment(v, u[0], u[1]), _foot(v, u[0], u[1]), (v[0], v[1], 1)
    (a, b), (c, d) = u, v
    hit = X.intersect_segments(a, b, c, d)
    if hit:
        p = hit.points[0]
        return (0, 1), p, p
    cands = [
        (X.sqdist_point_segment(a, c, d), (a[0], a[1], 1), _foot(a, c, d)),
        (X.sqdist_point_segment(b, c, d), (b[0], b[1], 1), _foot(b, c, d)),
        (X.sqdist_point_segment(c, a, b), _foot(c, a, b), (c[0], c[1], 1)),
        (X.sqdist_point_segment(d, a, b), _foot(d, a, b), (d[0], d[1], 1)),
    ]
    best = cands[0]
    for cand in cands[1:]:
        if X.ratio_cmp(cand[0], best[0]) < 0:
            best = cand
    return best


def _nearest(a: Geometry, b: Geometry):
    if a.is_empty or b.is_empty:
        return None
    scale = CoordScale.for_geometry(a, b)
    pa, pb = _Parts(a, scale), _Parts(b, scale)
    # containment of a component in a polygon of the other geometry
    for reps, polys in ((pa.reps, pb.polygons), (pb.reps, pa.polygons)):
        for r in reps:
            for shell, holes in polys:
                if _in_polygon(r, shell, holes):
                    hp = (r[0], r[1], 1)
                    return scale, (0, 1), hp, hp
    items_a = pa.points + pa.segments
    items_b = sorted(pb.points + pb.segments, key=lambda it: _bbox_of(it)[0])
    boxes_b = [_bbox_of(it) for it in items_b]
    best = None
    for u in items_a:
        ux0, uy0, ux1, uy1 = _bbox_of(u)
        for v, (vx0, vy0, vx1, vy1) in zip(items_b, boxes_b, strict=True):
            gx = max(0, vx0 - ux1, ux0 - vx1)
            gy = max(0, vy0 - uy1, uy0 - vy1)
            if best is not None:
                bn, bd = best[0]
                if vx0 > ux1 and (vx0 - ux1) ** 2 * bd >= bn:
                    break  # every later item starts further right
                if (gx * gx + gy * gy) * bd >= bn:
                    continue
            cand = _pair_distance(u, v)
            if best is None or X.ratio_cmp(cand[0], best[0]) < 0:
                best = cand
                if cand[0][0] == 0:
                    return scale, *best
    return scale, *best


def distance2(a: Geometry, b: Geometry) -> Any:
    """Exact squared distance between two geometries (None if either is empty)."""
    res = _nearest(a, b)
    if res is None:
        return None
    scale, (n, d), _, _ = res
    return scale.area(n, d)


def nearest_points(a: Geometry, b: Geometry) -> tuple[tuple[Any, Any], tuple[Any, Any]] | None:
    """A pair of points, one on each geometry, at the exact minimum distance (exact
    rational coordinates); None if either geometry is empty."""
    res = _nearest(a, b)
    if res is None:
        return None
    scale, _, p, q = res
    return scale.rational_hpoint(p), scale.rational_hpoint(q)


# ============================================================================ certified


class SqrtSum:
    """An exact real ``sum(q_i * sqrt(N_i))`` with rational ``q_i`` and integer ``N_i >= 0``.

    Supports certified enclosures (:meth:`enclose`) and exact comparison with a rational
    (:meth:`equals`).
    """

    __slots__ = ("_coef", "_den", "terms")

    def __init__(self, terms: Iterable[tuple[Any, int]]):
        self.terms = [(Fraction(q), int(n)) for q, n in terms if q != 0 and n != 0]
        for _, n in self.terms:
            if n < 0:
                raise ValueError("square root of a negative integer")
        den = reduce(
            lambda x, y: x * y // math.gcd(x, y), (q.denominator for q, _ in self.terms), 1
        )
        self._den = den
        self._coef = [(q.numerator * (den // q.denominator), n) for q, n in self.terms]

    def enclose(self, k: int) -> tuple[Fraction, Fraction]:
        """``(lo, hi)`` with ``lo <= value <= hi`` and ``hi - lo <= sum |q_i| 2**-k``."""
        lo = hi = 0
        for c, n in self._coef:
            m = n << (2 * k)
            s = math.isqrt(m)
            t = s if s * s == m else s + 1
            if c >= 0:
                lo += c * s
                hi += c * t
            else:
                lo += c * t
                hi += c * s
        d = self._den << k
        return Fraction(lo, d), Fraction(hi, d)

    def rational_value(self) -> Fraction | None:
        """The exact value when it is rational (every class but that of 1 cancels)."""
        classes = self._classes()
        if any(v != 0 for rep, v in classes.items() if rep != 1):
            return None
        return classes.get(1, Fraction(0))

    def equals(self, t: Any) -> bool:
        """Exactly whether the value equals the rational ``t``."""
        v = self.rational_value()
        return v is not None and v == Fraction(t)

    def _classes(self) -> dict[int, Fraction]:
        """Coefficient of ``sqrt(rep)`` per square-free class (``rep`` is the first
        ``N_i`` seen in the class, or 1 for perfect squares)."""
        out: dict[int, Fraction] = {}
        for q, n in self.terms:
            r = math.isqrt(n)
            if r * r == n:
                out[1] = out.get(1, Fraction(0)) + q * r
                continue
            for rep in out:
                if rep == 1:
                    continue
                m = n * rep
                s = math.isqrt(m)
                if s * s == m:  # sqrt(n) = (s / rep) sqrt(rep)
                    out[rep] += q * Fraction(s, rep)
                    break
            else:
                out[n] = q
        return out


@dataclass(frozen=True)
class Certified:
    """A certified enclosure ``lo <= value <= hi`` and the correctly rounded double of
    the value (round to nearest, ties to even). ``exact`` is the value itself, with
    ``lo == hi == exact``, when it is known to be rational: when every square root is
    rational, when it is a tie between two doubles, or when it equals ``rounded``; it is
    None for an irrational value (or a rational one that is none of these)."""

    lo: Any
    hi: Any
    rounded: float
    exact: Any = None

    def to_json(self) -> dict[str, Any]:
        """Schema ``Interval``: ``lo``/``hi`` as ``"n/d"`` strings; ``rounded`` is left
        out when it is not finite (JSON has no infinity)."""
        out: dict[str, Any] = {"lo": format_rational(self.lo), "hi": format_rational(self.hi)}
        if math.isfinite(self.rounded):
            out["rounded"] = self.rounded
        return out


_DBL_MAX = Fraction(sys.float_info.max)
_OVERFLOW = _DBL_MAX + Fraction(2) ** 970  # values at or above it round to inf


def _tie_between(f0: float, f1: float) -> Fraction | None:
    """The exact midpoint of two adjacent doubles ``f0 < f1`` (the rounding boundary)."""
    if math.isinf(f1) and f1 > 0:
        return _OVERFLOW
    if math.isinf(f0) and f0 < 0:
        return -_OVERFLOW
    return (Fraction(f0) + Fraction(f1)) / 2


def _certify(
    enclose: Callable[[int], tuple[Fraction, Fraction]],
    equals: Callable[[Fraction], bool],
    to_real: Callable[[Fraction], Any],
    k0: int = 64,
) -> Certified:
    """Refine an enclosure until the correctly rounded double is decided.

    ``equals(t)`` decides exactly whether the value is the rational ``t``; it is only
    asked after a four times finer enclosure still contains ``t`` (for an irrational
    value that cheaply excludes ``t`` in practice).
    """

    def is_value(t: Fraction, k: int) -> bool:
        lo, hi = enclose(4 * k)
        return lo <= t <= hi and equals(t)

    k = k0
    while True:
        lo, hi = enclose(k)
        if lo == hi:
            return Certified(to_real(lo), to_real(hi), rational_to_float(lo), to_real(lo))
        flo, fhi = rational_to_float(lo), rational_to_float(hi)
        if flo == fhi:
            if flo != 0 or lo > 0 or hi < 0:
                val = flo if flo != 0 else math.copysign(0.0, lo if lo != 0 else hi)
                if math.isfinite(val) and is_value(Fraction(val), k):  # exactly this double
                    q = to_real(Fraction(val))
                    return Certified(q, q, val, q)
                return Certified(to_real(lo), to_real(hi), val)
            if is_value(Fraction(0), k):
                z = Fraction(0)
                return Certified(to_real(z), to_real(z), 0.0, to_real(z))
        elif math.nextafter(flo, math.inf) == fhi:
            t = _tie_between(flo, fhi)
            if t is not None and lo <= t <= hi and is_value(t, k):
                return Certified(to_real(t), to_real(t), rational_to_float(t), to_real(t))
        k *= 2


def _as_real(q: Fraction) -> Any:
    return rational(q.numerator, q.denominator)


def _segments_of_rings_and_lines(geom: Geometry):
    """Coordinate sequences of every line and polygon ring, in element order."""
    for e in geom.elements():
        if e.is_empty:
            continue
        if isinstance(e, LineString):
            yield e.coords
        elif isinstance(e, Polygon):
            yield from (r for r in e.rings if r)


def length(geom: Geometry) -> Certified:
    """Certified length (JTS ``getLength``: lines plus polygon perimeters)."""
    scale = CoordScale.for_geometry(geom)
    terms = []
    for seq in _segments_of_rings_and_lines(geom):
        pts = [scale.point(c) for c in seq]
        for p, q in pairwise(pts):
            n = X.sqdist(p, q)
            if n:
                terms.append((1, n))
    s = SqrtSum(terms)
    den = scale.den
    return _certify(
        lambda k: tuple(v / den for v in s.enclose(k)),
        lambda t: s.equals(t * den),
        _as_real,
    )


# ============================================================================ centroid


def _is_ccw(ring: Sequence[tuple[int, int]]) -> bool:
    """JTS/GEOS ``Orientation.isCCW`` (exact on integer coordinates), including its
    answers for flat and non-simple rings. Rings with fewer than 4 points (on which JTS
    throws) give False."""
    n = len(ring) - 1
    if n < 3:
        return False
    up_hi = ring[0]
    prev_y = up_hi[1]
    up_low = None
    i_up_hi = 0
    for i in range(1, n + 1):
        py = ring[i][1]
        if py > prev_y and py >= up_hi[1]:
            up_hi = ring[i]
            i_up_hi = i
            up_low = ring[i - 1]
        prev_y = py
    if i_up_hi == 0:
        return False
    i_down_low = i_up_hi
    while True:
        i_down_low = (i_down_low + 1) % n
        if not (i_down_low != i_up_hi and ring[i_down_low][1] == up_hi[1]):
            break
    down_low = ring[i_down_low]
    down_hi = ring[i_down_low - 1 if i_down_low > 0 else n - 1]
    if up_hi == down_hi:
        if up_hi in (up_low, down_low) or up_low == down_low:
            return False
        return X.orient(up_low, up_hi, down_low) > 0
    return down_hi[0] - up_hi[0] < 0


def centroid(geom: Geometry) -> tuple[Certified, Certified] | None:
    """JTS ``Centroid`` of any geometry, as certified coordinates; None if empty.

    Areal part present with non-zero total area: the exact area centroid. Otherwise, with
    positive total length: the line centroid (lines and polygon rings). Otherwise the mean
    of the points (Point elements and the start points of zero-length lines/rings).
    """
    if geom.is_empty:
        return None
    scale = CoordScale.for_geometry(geom)
    den = scale.den
    # --- areal (exact)
    area6 = 0  # sum of signed twice-areas
    mx = my = 0  # moments * 2 * 3
    for p in _polygon_elements(geom):
        for k, ring in enumerate(p.rings):
            if not ring:
                continue
            pts = [scale.point(c) for c in ring]
            ccw = _is_ccw(pts)
            sign = (1 if ccw else -1) if k == 0 else (-1 if ccw else 1)
            for (x0, y0), (x1, y1) in pairwise(pts):
                c = x0 * y1 - x1 * y0
                area6 += sign * c
                mx += sign * c * (x0 + x1)
                my += sign * c * (y0 + y1)
    if area6 != 0:
        cx = rational(mx, 3 * area6 * den)
        cy = rational(my, 3 * area6 * den)
        return _exact_certified(cx), _exact_certified(cy)
    # --- lineal (certified)
    wx, wy, wl = [], [], []
    pts_sum = [0, 0, 0]
    for seq in _segments_of_rings_and_lines(geom):
        pts = [scale.point(c) for c in seq]
        seg_len = False
        for (x0, y0), (x1, y1) in pairwise(pts):
            n = (x1 - x0) ** 2 + (y1 - y0) ** 2
            if n == 0:
                continue
            seg_len = True
            wl.append((1, n))
            wx.append((x0 + x1, n))
            wy.append((y0 + y1, n))
        if not seg_len:
            pts_sum[0] += pts[0][0]
            pts_sum[1] += pts[0][1]
            pts_sum[2] += 1
    if wl:
        return _ratio_certified(SqrtSum(wx), SqrtSum(wl), 2 * den), _ratio_certified(
            SqrtSum(wy), SqrtSum(wl), 2 * den
        )
    # --- puntal (exact)
    for e in geom.elements():
        if isinstance(e, Point) and not e.is_empty:
            p = scale.point(e.coord)
            pts_sum[0] += p[0]
            pts_sum[1] += p[1]
            pts_sum[2] += 1
    if pts_sum[2] == 0:
        return None
    return (
        _exact_certified(rational(pts_sum[0], pts_sum[2] * den)),
        _exact_certified(rational(pts_sum[1], pts_sum[2] * den)),
    )


def _exact_certified(q: Any) -> Certified:
    return Certified(q, q, rational_to_float(q), q)


def _ratio_certified(num: SqrtSum, dnm: SqrtSum, div: int) -> Certified:
    """Certified ``num / (dnm * div)`` for a positive ``dnm`` and positive integer
    ``div``."""

    def enclose(k: int) -> tuple[Fraction, Fraction]:
        nlo, nhi = num.enclose(k)
        dlo, dhi = dnm.enclose(k)
        while dlo <= 0:  # cannot happen for k >= 1 with N_i >= 1, kept for safety
            k *= 2
            nlo, nhi = num.enclose(k)
            dlo, dhi = dnm.enclose(k)
        if nlo >= 0:
            lo, hi = nlo / dhi, nhi / dlo
        elif nhi <= 0:
            lo, hi = nlo / dlo, nhi / dhi
        else:
            lo, hi = nlo / dlo, nhi / dlo
        return lo / div, hi / div

    def equals(t: Fraction) -> bool:
        # num / (dnm div) == t  <=>  sum (c_i - t div) sqrt(N_i) == 0
        terms = [(q, n) for q, n in num.terms] + [(-t * div * q, n) for q, n in dnm.terms]
        return SqrtSum(terms).equals(0)

    return _certify(enclose, equals, _as_real)


# ============================================================================ hull


def convex_hull(geom: Geometry) -> Geometry:
    """Exact convex hull (JTS ``ConvexHull`` shapes): ``GEOMETRYCOLLECTION EMPTY`` for
    no points, a Point, a two-point LineString when all points are collinear, else a
    Polygon. Collinear boundary points are dropped. The polygon's shell is
    counter-clockwise and starts at its lexicographically smallest vertex (GEOS returns
    the same point set clockwise). Coordinates are the input coordinate objects.

    As JTS/GEOS ``Polygon.convexHull()``, a Polygon's hull is that of its shell alone
    (the same for a valid polygon; GEOS 3.13-3.16 give ``LINESTRING (0 0, 3 0)`` for
    ``POLYGON ((0 0, 3 0, 1 0, 0 0), (2 3, 0 1, 4 1, 2 3))``). Other types use every
    coordinate."""
    coords = geom.shell if isinstance(geom, Polygon) else tuple(geom.iter_coords())
    scale = CoordScale.for_values(v for c in coords for v in c)
    original: dict[tuple[int, int], Any] = {}
    for c in coords:
        original.setdefault(scale.point(c), c)
    pts = sorted(original)
    if not pts:
        return GeometryCollection()
    if len(pts) == 1:
        return Point(original[pts[0]])

    def half(seq):
        out: list[tuple[int, int]] = []
        for p in seq:
            while len(out) >= 2 and X.orient(out[-2], out[-1], p) <= 0:
                out.pop()
            out.append(p)
        return out

    lower = half(pts)
    upper = half(reversed(pts))
    hull = lower[:-1] + upper[:-1]
    if len(hull) < 3:
        return LineString((original[pts[0]], original[pts[-1]]))
    ring = [original[p] for p in hull]
    return Polygon(((*ring, ring[0]),))


# ============================================================================ engine shim

#: Overlay operation names (as in schemas/expected.v2.schema.json).
OVERLAY_OPS = ("intersection", "union", "difference", "symdifference")


class EngineUnavailable(RuntimeError):
    """Neither the exact engine nor a reference fallback can answer this input."""


_reference_pkg: Any = None


def _reference() -> Any:
    """The vendored references ``tests/reference`` as a private package, or None (an
    installed geotruth has no tests directory)."""
    global _reference_pkg
    if _reference_pkg is not None:
        return _reference_pkg or None
    ref = Path(__file__).resolve().parents[2] / "tests" / "reference"
    name = "_geotruth_reference"
    if not (ref / "oracle.py").is_file():
        _reference_pkg = False
        return None
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, ref / "__init__.py", submodule_search_locations=[str(ref)]
        )
        if spec is None or spec.loader is None:  # pragma: no cover
            _reference_pkg = False
            return None
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    _reference_pkg = importlib.import_module(f"{name}.oracle")
    return _reference_pkg


def _engine_function(module: str, func: str) -> Callable | None:
    """``geotruth.<module>.<func>`` if the engine provides it."""
    try:
        mod = importlib.import_module(f"geotruth.{module}")
    except ImportError:
        return None
    fn = getattr(mod, func, None)
    return fn if callable(fn) else None


def engine_backends() -> dict[str, str]:
    """Which implementation :func:`relate_predicates` and :func:`overlay_area` use by
    default (``backend="auto"``) for valid polygon/polygon input."""
    ref = "tests/reference/oracle.py" if _reference() is not None else "unavailable"
    return {
        "relate": "geotruth.relate" if _engine_function("relate", "relate") else ref,
        "overlay": "geotruth.overlay" if _engine_function("overlay", "overlay") else ref,
    }


def _field(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj[name]
    return getattr(obj, name)


def _v1_coords(geom: Geometry) -> list:
    """A Polygon/MultiPolygon as FORMAT-v1 MultiPolygon coordinates (oracle input)."""
    if isinstance(geom, Polygon):
        polys = [geom]
    elif isinstance(geom, MultiPolygon):
        polys = [p for p in geom.polygons if not p.is_empty]
    else:
        raise EngineUnavailable(f"the reference oracle handles polygons only, not {geom.geom_type}")
    if not polys or any(p.is_empty for p in polys):
        raise EngineUnavailable("the reference oracle does not handle empty geometries")
    return [[[[float(x), float(y)] for x, y in ring] for ring in p.rings] for p in polys]


def _oracle_evaluate(a: Geometry, b: Geometry) -> dict[str, Any]:
    oracle = _reference()
    if oracle is None:
        raise EngineUnavailable("the exact engine is not available and tests/reference is absent")
    res = oracle.evaluate({"id": "shim", "a": _v1_coords(a), "b": _v1_coords(b)})
    if not (res.get("valid_a") and res.get("valid_b")):
        raise EngineUnavailable("the reference oracle is defined for valid inputs only")
    return res


def _is_polygonal(g: Geometry) -> bool:
    return isinstance(g, (Polygon, MultiPolygon)) and not g.is_empty


def relate_predicates(a: Geometry, b: Geometry, backend: str = "auto") -> dict[str, bool]:
    """The named predicates of ``a`` and ``b``.

    ``backend``: ``"engine"`` (``geotruth.relate.relate``, DESIGN §2.3), ``"oracle"``
    (``tests/reference/oracle.py``, valid polygon/polygon only), ``"witness"``
    (``geotruth.relate_witness`` with ``geotruth.predicates``, §2.4), or ``"auto"``: the
    engine when it exists, else the oracle for polygon/polygon input, else the witness
    route.
    """
    if backend not in ("auto", "engine", "oracle", "witness"):
        raise ValueError(f"unknown backend {backend!r}")
    fn = _engine_function("relate", "relate") if backend in ("auto", "engine") else None
    if fn is not None:
        res = fn(a, b)
        preds = _field(res, "predicates")
        if preds is not None:
            return {k: bool(getattr(v, "value", v)) for k, v in dict(preds).items()}
        status = res.get("status") if isinstance(res, dict) else getattr(res, "status", None)
        reason = res.get("reason") if isinstance(res, dict) else getattr(res, "reason", None)
        if backend == "engine":
            raise EngineUnavailable(f"geotruth.relate gave no answer ({status}: {reason})")
    elif backend == "engine":
        raise EngineUnavailable("geotruth.relate is not available")
    if backend == "oracle" or (backend == "auto" and _is_polygonal(a) and _is_polygonal(b)):
        res = _oracle_evaluate(a, b)
        keys = (
            "intersects",
            "disjoint",
            "touches",
            "overlaps",
            "contains",
            "covers",
            "within",
            "covered_by",
            "equals",
        )
        return {k: bool(res[k]) for k in keys}
    witness = _engine_function("relate_witness", "relate")
    evaluate = _engine_function("predicates", "predicates")
    if witness is None or evaluate is None:
        raise EngineUnavailable("no relate implementation is available for this input")
    return dict(evaluate(witness(a, b), a.real_dimension, b.real_dimension))


def overlay_area(a: Geometry, b: Geometry, op: str) -> Any:
    """Exact area of ``op(a, b)`` from ``geotruth.overlay.overlay`` (DESIGN §2.5), or
    from the reference oracle for valid polygon/polygon inputs. ``op`` is one of
    :data:`OVERLAY_OPS`."""
    if op not in OVERLAY_OPS:
        raise ValueError(f"unknown overlay operation {op!r}; expected one of {OVERLAY_OPS}")
    fn = _engine_function("overlay", "overlay")
    if fn is not None:
        result = fn(a, b, op, "areal")
        try:
            return _field(result, "area")
        except (KeyError, AttributeError):
            return area(_field(result, "geometry"))
    res = _oracle_evaluate(a, b)
    from geotruth.numbers import parse_rational

    inter, da, db = (parse_rational(res["exact"][k]) for k in ("inter", "diff_ab", "diff_ba"))
    return {
        "intersection": inter,
        "union": inter + da + db,
        "difference": da,
        "symdifference": da + db,
    }[op]


# ============================================================================ records


def case_measures(a: Geometry, b: Geometry | None = None) -> dict[str, Any]:
    """The ``measures`` object of an expected answer (schemas/expected.v2): exact areas,
    certified lengths and centroids of each operand, and the exact squared distance.
    Rationals are ``"n/d"`` strings, intervals ``{"lo", "hi", "rounded"}``."""
    out: dict[str, Any] = {}
    for tag, g in (("a", a), ("b", b)):
        if g is None:
            continue
        out[f"area_{tag}"] = format_rational(area(g))
        out[f"length_{tag}"] = length(g).to_json()
        c = centroid(g)
        if c is not None:
            out[f"centroid_{tag}_x"] = c[0].to_json()
            out[f"centroid_{tag}_y"] = c[1].to_json()
    if b is not None:
        d2 = distance2(a, b)
        if d2 is not None:
            out["distance2"] = format_rational(d2)
    return out
