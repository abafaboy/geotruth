"""Seeded generator of degenerate, GeometryCollection-heavy lattice pairs (adversarial review).

It complements :mod:`unit.witness_lattice` and the ``adversarial`` source of
``tools/crosscheck_relate.py`` with the shapes an adversarial review of the engine found
least covered:

- GeometryCollections of 2-5 elements that nest (depth 2), hold MultiPolygon /
  MultiLineString / MultiPoint members and empty members of every type, so polygons in one
  collection overlap, share edges, fill each other's holes or stack;
- polygons whose holes touch the shell and each other at vertices (valid OGC polygons);
- B derived from A: lines retracing pieces of A's shell (reversed, extended by a
  fold-back), points on A's vertices and on half-lattice edge midpoints.

Every geometry has coordinates on the integer (or half-integer) lattice ``[0, n]``, so
GEOS's orientation tests are exact and GEOS is a meaningful third opinion. Operands are
*not* filtered here: call :func:`valid_pair` (exact GEOS-default validity per element,
:func:`unit.witness_lattice.is_valid`) to keep the ones inside the engine's contract.

Use from any test directory (``tests/`` is on ``sys.path``)::

    from unit.nasty_lattice import valid_pairs
"""

from __future__ import annotations

import random
from collections.abc import Iterator

from geotruth.geom import (
    Geometry,
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from unit.witness_lattice import is_valid
from unit.witness_lattice import polygon as lattice_polygon

__all__ = ["operand", "pair", "valid_pair", "valid_pairs"]

Coord = tuple[float, float]
Ctx = tuple[list[Coord] | None, list[Coord] | None]


def _p(x: float, y: float) -> Coord:
    return float(x), float(y)


def _rect(rng: random.Random, n: int) -> list[Coord]:
    x0, x1 = sorted(rng.sample(range(n + 1), 2))
    y0, y1 = sorted(rng.sample(range(n + 1), 2))
    r = [_p(x0, y0), _p(x1, y0), _p(x1, y1), _p(x0, y1), _p(x0, y0)]
    return r[::-1] if rng.random() < 0.5 else r


def _triangle(rng: random.Random, n: int) -> list[Coord]:
    while True:
        a, b, c = (_p(rng.randint(0, n), rng.randint(0, n)) for _ in range(3))
        if (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) != 0:
            return [a, b, c, a]


def _touching_holes(rng: random.Random, n: int) -> Polygon:
    """The square [0, n]^2 with 1-2 triangular holes; holes may touch the shell and each
    other at vertices (kept only when valid)."""
    shell = [_p(0, 0), _p(n, 0), _p(n, n), _p(0, n), _p(0, 0)]
    for _ in range(50):
        p = Polygon([shell, *(_triangle(rng, n) for _ in range(rng.randint(1, 2)))])
        if is_valid(p):
            return p
    return Polygon([shell])


def _polygon(rng: random.Random, n: int) -> Polygon:
    r = rng.random()
    if r < 0.3:
        return Polygon([_rect(rng, n)])
    if r < 0.55:
        return Polygon([_triangle(rng, n)])
    if r < 0.75:
        return _touching_holes(rng, n)
    return lattice_polygon(rng, n)


def _line(rng: random.Random, n: int, along: list[Coord] | None = None) -> LineString:
    if along is not None and rng.random() < 0.5:
        # a piece of a ring: maybe reversed, maybe folding back on its last segment
        i = rng.randrange(len(along) - 1)
        k = rng.randint(1, len(along) - 1)
        pts = [along[(i + j) % (len(along) - 1)] for j in range(k + 1)]
        if rng.random() < 0.3:
            pts = pts[::-1]
        if rng.random() < 0.2:
            pts.append(pts[-2])
        if len(set(pts)) >= 2:
            return LineString(pts)
    while True:
        pts = [_p(rng.randint(0, n), rng.randint(0, n)) for _ in range(rng.randint(2, 4))]
        if rng.random() < 0.15:
            pts.append(pts[0])  # closed
        if len(set(pts)) >= 2:
            return LineString(pts)


def _point(rng: random.Random, n: int, verts: list[Coord] | None = None) -> Point:
    if verts and rng.random() < 0.6:
        return Point(rng.choice(verts))
    if rng.random() < 0.2:  # half-lattice: edge midpoints
        return Point((rng.randint(0, 2 * n) / 2, rng.randint(0, 2 * n) / 2))
    return Point(_p(rng.randint(0, n), rng.randint(0, n)))


def _element(rng: random.Random, n: int, depth: int, ctx: Ctx) -> Geometry:
    ring, verts = ctx
    r = rng.random()
    if r < 0.35:
        return _polygon(rng, n)
    if r < 0.55:
        return _line(rng, n, ring)
    if r < 0.65:
        return _point(rng, n, verts)
    if r < 0.72:
        for _ in range(20):
            mp = MultiPolygon([_polygon(rng, n) for _ in range(2)])
            if is_valid(mp):
                return mp
        return _polygon(rng, n)
    if r < 0.8:
        return MultiLineString([_line(rng, n, ring) for _ in range(rng.randint(1, 3))])
    if r < 0.86:
        return MultiPoint([_point(rng, n, verts) for _ in range(rng.randint(1, 3))])
    if r < 0.93 and depth < 2:
        return GeometryCollection(
            [_element(rng, n, depth + 1, ctx) for _ in range(rng.randint(1, 3))]
        )
    return rng.choice(
        [
            Point(),
            LineString(),
            Polygon(),
            GeometryCollection(),
            MultiPolygon([Polygon(), Polygon([_rect(rng, n)])]),
        ]
    )


def operand(rng: random.Random, n: int = 4, ctx: Ctx = (None, None)) -> Geometry:
    """One operand: a GeometryCollection of 2-5 elements (45%) or a single element."""
    if rng.random() < 0.45:
        return GeometryCollection([_element(rng, n, 0, ctx) for _ in range(rng.randint(2, 5))])
    return _element(rng, n, 0, ctx)


def _shell_of(g: Geometry) -> list[Coord] | None:
    for e in g.elements():
        if isinstance(e, Polygon) and not e.is_empty:
            return list(e.rings[0])
    return None


def pair(rng: random.Random, n: int = 4) -> tuple[Geometry, Geometry]:
    """A pair; B is usually derived from A (pieces of A's shell, A's vertices)."""
    a = operand(rng, n)
    ctx: Ctx = (_shell_of(a), sorted(set(a.iter_coords())))
    b = operand(rng, n, ctx if rng.random() < 0.7 else (None, None))
    return a, b


def valid_pair(a: Geometry, b: Geometry) -> bool:
    """Both operands GEOS-valid (per element for collections), exactly."""
    return is_valid(a) and is_valid(b)


def valid_pairs(seed: int, count: int, n: int = 4) -> Iterator[tuple[Geometry, Geometry]]:
    """``count`` valid pairs from one seed (invalid draws are skipped, not counted)."""
    rng = random.Random(seed)
    made = 0
    while made < count:
        a, b = pair(rng, n)
        if valid_pair(a, b):
            made += 1
            yield a, b
