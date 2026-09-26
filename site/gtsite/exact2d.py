"""Exact 2-D helpers for the site's figures, on Python ``Fraction`` coordinates.

The figures zoom to where a library's answer departs from the exact one, sometimes by a
single ulp at coordinates of 1e300, so the view window, the clipping to it and the
positions of the marks are computed in exact rational arithmetic; only the final position
on the 400-unit canvas is rounded to a float. None of this decides a verdict: it only
chooses and draws a view.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

P = tuple[Fraction, Fraction]


def frac(v: Any) -> Fraction | None:
    """An exact Fraction of a coordinate value (float, int, Fraction, gmpy2 mpq), or None
    for NaN and infinities."""
    if isinstance(v, Fraction):
        return v
    if isinstance(v, float):
        if not math.isfinite(v):
            return None
        return Fraction(v)
    if isinstance(v, int) and not isinstance(v, bool):
        return Fraction(v)
    if hasattr(v, "numerator") and hasattr(v, "denominator"):
        return Fraction(int(v.numerator), int(v.denominator))
    raise TypeError(f"not a coordinate value: {v!r}")


def _pt(c: Any) -> P | None:
    x, y = frac(c[0]), frac(c[1])
    if x is None or y is None:
        return None
    return (x, y)


@dataclass
class Parts:
    """The drawable parts of a geometry: points, polylines, and polygons (lists of closed
    rings, shell first). Non-finite coordinates are dropped and counted."""

    points: list[P] = field(default_factory=list)
    lines: list[list[P]] = field(default_factory=list)
    polygons: list[list[list[P]]] = field(default_factory=list)
    dropped: int = 0

    @property
    def empty(self) -> bool:
        return not (self.points or self.lines or self.polygons)

    def vertices(self) -> list[P]:
        out = list(self.points)
        for ln in self.lines:
            out += ln
        for poly in self.polygons:
            for ring in poly:
                out += ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
        return out

    def segments(self) -> list[tuple[P, P]]:
        out = []
        for ln in self.lines:
            out += [(ln[i], ln[i + 1]) for i in range(len(ln) - 1) if ln[i] != ln[i + 1]]
        for poly in self.polygons:
            for ring in poly:
                out += [
                    (ring[i], ring[i + 1]) for i in range(len(ring) - 1) if ring[i] != ring[i + 1]
                ]
        return out

    def ring_segments(self) -> list[tuple[int, int, int, tuple[P, P]]]:
        """``(polygon, ring, index, segment)`` of every ring edge, plus lines as
        ``(-1 - line, 0, index, segment)``: identifies adjacency for self-approach."""
        out = []
        for li, ln in enumerate(self.lines):
            for i in range(len(ln) - 1):
                if ln[i] != ln[i + 1]:
                    out.append((-1 - li, 0, i, (ln[i], ln[i + 1])))
        for pi, poly in enumerate(self.polygons):
            for ri, ring in enumerate(poly):
                for i in range(len(ring) - 1):
                    if ring[i] != ring[i + 1]:
                        out.append((pi, ri, i, (ring[i], ring[i + 1])))
        return out


def parts_of(geom: Any) -> Parts:
    """The :class:`Parts` of a ``geotruth.geom`` geometry (doubles or exact rationals)."""
    from geotruth.geom import LineString, Point, Polygon

    out = Parts()
    for el in geom.elements():
        if isinstance(el, Point):
            if el.coord is None:
                continue
            p = _pt(el.coord)
            if p is None:
                out.dropped += 1
            else:
                out.points.append(p)
        elif isinstance(el, LineString):
            pts = [_pt(c) for c in el.coords]
            out.dropped += sum(1 for p in pts if p is None)
            pts = [p for p in pts if p is not None]
            if len(pts) == 1 or (pts and all(p == pts[0] for p in pts)):
                out.points.append(pts[0])  # a zero-length line is drawn as a point
            elif pts:
                out.lines.append(pts)
        elif isinstance(el, Polygon):
            rings = []
            for ring in el.rings:
                pts = [_pt(c) for c in ring]
                out.dropped += sum(1 for p in pts if p is None)
                pts = [p for p in pts if p is not None]
                if len(pts) >= 2:
                    if pts[0] != pts[-1]:
                        pts.append(pts[0])
                    rings.append(pts)
            if rings:
                out.polygons.append(rings)
    return out


# ============================================================================ measures


def bbox(parts_list: list[Parts]) -> tuple[Fraction, Fraction, Fraction, Fraction] | None:
    vs = [v for p in parts_list for v in p.vertices()]
    if not vs:
        return None
    xs, ys = [v[0] for v in vs], [v[1] for v in vs]
    return min(xs), min(ys), max(xs), max(ys)


def orient(a: P, b: P, c: P) -> int:
    d = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (d > 0) - (d < 0)


def dist2(p: P, q: P) -> Fraction:
    dx, dy = p[0] - q[0], p[1] - q[1]
    return dx * dx + dy * dy


def closest_on_segment(p: P, a: P, b: P) -> P:
    """The point of segment ab nearest to p (exact)."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    den = dx * dx + dy * dy
    if den == 0:
        return a
    t = ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / den
    if t <= 0:
        return a
    if t >= 1:
        return b
    return (a[0] + t * dx, a[1] + t * dy)


def segments_cross(a: P, b: P, c: P, d: P) -> bool:
    """Do closed segments ab and cd meet (exact)?"""
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True

    def on(p: P, q: P, r: P) -> bool:
        return min(p[0], q[0]) <= r[0] <= max(p[0], q[0]) and min(p[1], q[1]) <= r[1] <= max(
            p[1], q[1]
        )

    return (
        (o1 == 0 and on(a, b, c))
        or (o2 == 0 and on(a, b, d))
        or (o3 == 0 and on(c, d, a))
        or (o4 == 0 and on(c, d, b))
    )


def _in_ring(p: P, ring: list[P]) -> int:
    """1 inside, 0 on the boundary, -1 outside (crossing number, exact)."""
    inside = False
    n = len(ring) - 1
    for i in range(n):
        a, b = ring[i], ring[i + 1]
        if (
            orient(a, b, p) == 0
            and min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
            and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
        ):
            return 0
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x > p[0]:
                inside = not inside
    return 1 if inside else -1


def in_polygons(p: P, parts: Parts) -> bool:
    """Is p in the closed areal part (inside or on the boundary of some polygon)?"""
    for poly in parts.polygons:
        s = _in_ring(p, poly[0])
        if s == 0:
            return True
        if s < 0:
            continue
        hole = False
        for h in poly[1:]:
            t = _in_ring(p, h)
            if t == 0:
                return True
            if t > 0:
                hole = True
                break
        if not hole:
            return True
    return False


def nearest_in(p: P, parts: Parts) -> tuple[Fraction, P] | None:
    """(squared distance, nearest point) from p to the point set of ``parts`` (0 inside a
    polygon), or None if it is empty."""
    if parts.empty:
        return None
    if parts.polygons and in_polygons(p, parts):
        return Fraction(0), p
    best: tuple[Fraction, P] | None = None
    for q in parts.points:
        d = dist2(p, q)
        if best is None or d < best[0]:
            best = (d, q)
    for a, b in parts.segments():
        q = closest_on_segment(p, a, b)
        d = dist2(p, q)
        if best is None or d < best[0]:
            best = (d, q)
    return best


def sqrt_frac(q: Fraction, bits: int = 24) -> Fraction:
    """A dyadic approximation of sqrt(q) with about ``bits`` significant bits (q >= 0)."""
    if q <= 0:
        return Fraction(0)
    n, d = q.numerator, q.denominator
    k = max(0, (d.bit_length() - n.bit_length()) // 2 + bits)
    r = math.isqrt((n << (2 * k)) // d)
    return Fraction(r, 1 << k) if r else Fraction(1, 1 << (k + 1))


# ============================================================================ clipping

Box = tuple[Fraction, Fraction, Fraction, Fraction]


def clip_segment(a: P, b: P, box: Box) -> tuple[P, P] | None:
    """The part of segment ab inside the box (Liang-Barsky, exact), or None."""
    x0, y0, x1, y1 = box
    dx, dy = b[0] - a[0], b[1] - a[1]
    t0, t1 = Fraction(0), Fraction(1)
    for p, q in ((-dx, a[0] - x0), (dx, x1 - a[0]), (-dy, a[1] - y0), (dy, y1 - a[1])):
        if p == 0:
            if q < 0:
                return None
            continue
        r = q / p
        if p < 0:
            if r > t1:
                return None
            if r > t0:
                t0 = r
        else:
            if r < t0:
                return None
            if r < t1:
                t1 = r
    return (a[0] + t0 * dx, a[1] + t0 * dy), (a[0] + t1 * dx, a[1] + t1 * dy)


def clip_ring(ring: list[P], box: Box) -> list[P]:
    """A closed ring clipped to the box (Sutherland-Hodgman, exact); the result is open
    (first point not repeated), empty when nothing is inside."""
    x0, y0, x1, y1 = box
    pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else list(ring)

    def cut(pts: list[P], inside: Any, inter: Any) -> list[P]:
        out: list[P] = []
        n = len(pts)
        for i in range(n):
            cur, prev = pts[i], pts[i - 1]
            ci, pi = inside(cur), inside(prev)
            if ci:
                if not pi:
                    out.append(inter(prev, cur))
                out.append(cur)
            elif pi:
                out.append(inter(prev, cur))
        return out

    def at_x(x: Fraction) -> Any:
        def f(p: P, q: P) -> P:
            t = (x - p[0]) / (q[0] - p[0])
            return (x, p[1] + t * (q[1] - p[1]))

        return f

    def at_y(y: Fraction) -> Any:
        def f(p: P, q: P) -> P:
            t = (y - p[1]) / (q[1] - p[1])
            return (p[0] + t * (q[0] - p[0]), y)

        return f

    for inside, inter in (
        (lambda p: p[0] >= x0, at_x(x0)),
        (lambda p: p[0] <= x1, at_x(x1)),
        (lambda p: p[1] >= y0, at_y(y0)),
        (lambda p: p[1] <= y1, at_y(y1)),
    ):
        if not pts:
            break
        pts = cut(pts, inside, inter)
    return pts


def in_box(p: P, box: Box) -> bool:
    return box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3]
