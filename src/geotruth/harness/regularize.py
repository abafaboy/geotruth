"""Exact even-odd regularization, and valid rounding of exact geometry to doubles.

The engine control (:mod:`geotruth.harness.control`) must return *valid* output with
double coordinates. Rounding an exact overlay result to doubles can make it invalid (a hole
within an ulp of its shell crosses it, a sliver collapses to a zero-area ring), so the
control rounds, and when the rounded geometry is invalid it replaces its polygonal part by
the regularized even-odd point set of its own rings, computed exactly here, and rounds
again (a few rounds at most; every step moves the boundary by ulps only).

:func:`regularize_even_odd`: every ring edge is split at every contact with every other
edge; coincident pieces cancel in pairs (even-odd), so the boundary is the pieces of odd
multiplicity. Each is oriented with the interior on its left: the parity just below a
non-vertical piece is the number of boundary pieces crossing the vertical line through its
midpoint below it (half-open rule; no other piece passes through the midpoint, since every
contact is a split point), and likewise to the left of a vertical one. The pieces are
chained into simple rings and assembled into polygons as the fallback overlay does.
"""

from __future__ import annotations

from fractions import Fraction
from itertools import pairwise
from typing import Any

from geotruth.geom import (
    Geometry,
    LineString,
    Point,
    Polygon,
    build_geometry,
)
from geotruth.io import geometry_from_json, geometry_to_json

__all__ = ["regularize_even_odd", "round_valid"]

Pt = tuple[Fraction, Fraction]


def _fr(v: Any) -> Fraction:
    if isinstance(v, Fraction):
        return v
    if isinstance(v, (int, float)):
        return Fraction(v)
    return Fraction(int(v.numerator), int(v.denominator))


def _cross(ax: Fraction, ay: Fraction, bx: Fraction, by: Fraction) -> Fraction:
    return ax * by - ay * bx


def _on(p: Pt, a: Pt, b: Pt) -> bool:
    return (
        min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
        and _cross(b[0] - a[0], b[1] - a[1], p[0] - a[0], p[1] - a[1]) == 0
    )


def _contacts(a: Pt, b: Pt, c: Pt, d: Pt) -> list[Pt]:
    """Every intersection point of closed segments ab and cd (overlap endpoints too)."""
    if (
        max(a[0], b[0]) < min(c[0], d[0])
        or max(c[0], d[0]) < min(a[0], b[0])
        or max(a[1], b[1]) < min(c[1], d[1])
        or max(c[1], d[1]) < min(a[1], b[1])
    ):
        return []
    rx, ry = b[0] - a[0], b[1] - a[1]
    sx, sy = d[0] - c[0], d[1] - c[1]
    den = _cross(rx, ry, sx, sy)
    qx, qy = c[0] - a[0], c[1] - a[1]
    if den != 0:
        t = _cross(qx, qy, sx, sy) / den
        u = _cross(qx, qy, rx, ry) / den
        if 0 <= t <= 1 and 0 <= u <= 1:
            return [(a[0] + t * rx, a[1] + t * ry)]
        return []
    if _cross(qx, qy, rx, ry) != 0:
        return []
    return [p for p in (a, b, c, d) if _on(p, a, b) and _on(p, c, d)]


def _param(a: Pt, b: Pt, p: Pt) -> Fraction:
    dx, dy = b[0] - a[0], b[1] - a[1]
    return (p[0] - a[0]) / dx if abs(dx) >= abs(dy) else (p[1] - a[1]) / dy


def regularize_even_odd(rings: list[list[Pt]]) -> list[Polygon]:
    """Valid polygons (exact coordinates) covering the even-odd point set of the rings
    (open vertex lists, any orientation, any self-intersections), up to its measure-zero
    parts (the regularized set)."""
    from geotruth.harness.fallback_overlay import _assemble, _chain, _simplify, _split_simple

    edges: list[tuple[Pt, Pt]] = []
    for r in rings:
        n = len(r)
        for i in range(n):
            p, q = r[i], r[(i + 1) % n]
            if p != q:
                edges.append((p, q))
    splits: list[set[Pt]] = [{p, q} for p, q in edges]
    for i in range(len(edges)):
        a, b = edges[i]
        for j in range(i + 1, len(edges)):
            c, d = edges[j]
            for x in _contacts(a, b, c, d):
                splits[i].add(x)
                splits[j].add(x)
    mult: dict[tuple[Pt, Pt], int] = {}
    for (a, b), pts in zip(edges, splits, strict=True):
        seq = sorted(pts, key=lambda p, a=a, b=b: _param(a, b, p))
        for p, q in pairwise(seq):
            key = (p, q) if p < q else (q, p)
            mult[key] = mult.get(key, 0) + 1
    pieces = [k for k, m in mult.items() if m % 2 == 1]
    oriented: list[tuple[Pt, Pt]] = []
    half = Fraction(1, 2)
    for p, q in pieces:  # p < q lexicographically
        mx, my = (p[0] + q[0]) * half, (p[1] + q[1]) * half
        if p[0] != q[0]:
            below = 0
            for c, d in pieces:
                lo, hi = (c, d) if c[0] <= d[0] else (d, c)
                if lo[0] == hi[0] or not (lo[0] <= mx < hi[0]):
                    continue
                y = lo[1] + (mx - lo[0]) * (hi[1] - lo[1]) / (hi[0] - lo[0])
                if y < my:
                    below += 1
            # p -> q heads right (+x): its left side is above
            oriented.append((q, p) if below % 2 == 1 else (p, q))
        else:
            left = 0
            for c, d in pieces:
                lo, hi = (c, d) if c[1] <= d[1] else (d, c)
                if lo[1] == hi[1] or not (lo[1] <= my < hi[1]):
                    continue
                x = lo[0] + (my - lo[1]) * (hi[0] - lo[0]) / (hi[1] - lo[1])
                if x < mx:
                    left += 1
            # p -> q heads up (+y): its left side is at smaller x
            oriented.append((p, q) if left % 2 == 1 else (q, p))
    if not oriented:
        return []
    return _assemble(_simplify(_split_simple(_chain(oriented))))


def regularize_winding(rings: list[list[Pt]]) -> list[Polygon]:
    """Valid polygons (exact coordinates) covering the points of positive winding number
    of the rings (open vertex lists; shells counter-clockwise and holes clockwise, as the
    caller orients them), up to measure-zero parts: overlapping shells merge, and a hole
    poking out of its shell is clipped to it.

    As :func:`regularize_even_odd`, with directed multiplicities: along a piece the winding
    number steps by the net number of copies crossing it, and the winding just below a
    non-vertical piece (left of a vertical one) is the signed count of the pieces crossing
    the vertical (horizontal) line through its midpoint on that side."""
    from geotruth.harness.fallback_overlay import _assemble, _chain, _simplify, _split_simple

    edges: list[tuple[Pt, Pt]] = []
    for r in rings:
        n = len(r)
        for i in range(n):
            p, q = r[i], r[(i + 1) % n]
            if p != q:
                edges.append((p, q))
    splits: list[set[Pt]] = [{p, q} for p, q in edges]
    for i in range(len(edges)):
        a, b = edges[i]
        for j in range(i + 1, len(edges)):
            c, d = edges[j]
            for x in _contacts(a, b, c, d):
                splits[i].add(x)
                splits[j].add(x)
    net: dict[tuple[Pt, Pt], int] = {}
    for (a, b), pts in zip(edges, splits, strict=True):
        seq = sorted(pts, key=lambda p, a=a, b=b: _param(a, b, p))
        for p, q in pairwise(seq):
            key, step = ((p, q), 1) if p < q else ((q, p), -1)
            net[key] = net.get(key, 0) + step
    pieces = [(k, n) for k, n in net.items() if n != 0]
    oriented: list[tuple[Pt, Pt]] = []
    half = Fraction(1, 2)
    for (p, q), n in pieces:  # p < q lexicographically; n copies heading p -> q
        mx, my = (p[0] + q[0]) * half, (p[1] + q[1]) * half
        if p[0] != q[0]:
            w_below = 0
            for (c, d), m in pieces:
                if c[0] == d[0] or not (c[0] <= mx < d[0]):
                    continue
                y = c[1] + (mx - c[0]) * (d[1] - c[1]) / (d[0] - c[0])
                if y < my:
                    w_below += m  # c -> d heads +x
            w_above = w_below + n
            if (w_below > 0) != (w_above > 0):
                oriented.append((p, q) if w_above > 0 else (q, p))
        else:
            w_left = 0
            for (c, d), m in pieces:
                lo, hi = (c, d) if c[1] <= d[1] else (d, c)
                if lo[1] == hi[1] or not (lo[1] <= my < hi[1]):
                    continue
                x = lo[0] + (my - lo[1]) * (hi[0] - lo[0]) / (hi[1] - lo[1])
                if x < mx:
                    w_left += m if c[1] > d[1] else -m  # heading -y counts +1
            w_right = w_left - n  # p -> q heads +y
            if (w_left > 0) != (w_right > 0):
                oriented.append((p, q) if w_left > 0 else (q, p))
    if not oriented:
        return []
    return _assemble(_simplify(_split_simple(_chain(oriented))))


def _oriented_rings(g: Geometry) -> list[list[Pt]]:
    """Every polygon ring with exact coordinates, shells counter-clockwise, holes
    clockwise."""
    out = []
    for e in g.elements():
        if isinstance(e, Polygon) and not e.is_empty:
            for k, ring in enumerate(e.rings):
                pts = [(_fr(x), _fr(y)) for x, y in ring]
                if len(pts) > 1 and pts[0] == pts[-1]:
                    pts = pts[:-1]
                if len(pts) < 3:
                    continue
                a2 = sum(
                    (
                        pts[i - 1][0] * pts[i][1] - pts[i][0] * pts[i - 1][1]
                        for i in range(len(pts))
                    ),
                    Fraction(0),
                )
                if (k == 0 and a2 < 0) or (k > 0 and a2 > 0):
                    pts.reverse()
                out.append(pts)
    return out


def _valid(g: Geometry) -> bool:
    from geotruth.validity import validate

    return validate(g).valid


def _exact_rings(g: Geometry) -> list[list[Pt]]:
    out = []
    for e in g.elements():
        if isinstance(e, Polygon) and not e.is_empty:
            for ring in e.rings:
                pts = [(_fr(x), _fr(y)) for x, y in ring]
                if len(pts) > 1 and pts[0] == pts[-1]:
                    pts = pts[:-1]
                if pts:
                    out.append(pts)
    return out


def round_valid(g: Geometry, max_rounds: int = 4) -> dict[str, Any]:
    """Typed JSON of an exact geometry with every coordinate rounded to the nearest double,
    made valid where rounding broke validity: the polygonal part is replaced by the
    regularized positive-winding point set of its rounded rings (shells merge where they
    overlap, holes are clipped to their shells), re-rounded (up to ``max_rounds`` times);
    lines that collapse to a point become points. If that does not converge the last
    rounding is returned as it is."""
    js = geometry_to_json(g)
    rg = geometry_from_json(js)
    for _ in range(max_rounds):
        if _valid(rg):
            return geometry_to_json(rg)
        polys = regularize_winding(_oriented_rings(rg))
        others: list[Geometry] = []
        for e in rg.elements():
            if e.is_empty or isinstance(e, Polygon):
                continue
            if isinstance(e, LineString) and len({(x, y) for x, y in e.coords}) < 2:
                others.append(Point(e.coords[0]))
            else:
                others.append(e)
        parts: list[Geometry] = [*polys, *others]
        if not parts:
            return geometry_to_json(Polygon() if g.dimension == 2 else rg)
        rg = geometry_from_json(geometry_to_json(build_geometry(parts)))
    return geometry_to_json(rg)
