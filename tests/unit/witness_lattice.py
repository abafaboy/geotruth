"""Seeded generator of small-integer-lattice geometry pairs, for the witness relate tests.

Every geometry has integer coordinates in ``[0, n]`` (as doubles) and is valid in the
GEOS sense, so GEOS's answers are meaningful third opinions:

- polygons and multipolygons are filtered with the exact reference validity
  (``tests/reference/validity.py``, rules R0-R6);
- lines have at least two distinct points (they may self-cross, retrace or close);
- a GeometryCollection is valid when each element is (DESIGN §1), so its polygons may
  overlap or share edges -- exactly the union-semantics cases.

Zero-length lines are GEOS-invalid; :func:`zero_length_line` makes them separately.

Use from any test directory (``tests/`` is on ``sys.path``)::

    from unit.witness_lattice import TYPES, random_pair
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable

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
from reference import validity

__all__ = [
    "GENERATORS",
    "TYPES",
    "is_valid",
    "random_geometry",
    "random_pair",
    "type_pairs",
    "zero_length_line",
]

Coord = tuple[float, float]


def _pt(rng: random.Random, n: int) -> Coord:
    return float(rng.randint(0, n)), float(rng.randint(0, n))


def point(rng: random.Random, n: int = 4) -> Point:
    return Point(_pt(rng, n))


def multipoint(rng: random.Random, n: int = 4) -> MultiPoint:
    return MultiPoint([_pt(rng, n) for _ in range(rng.randint(2, 3))])


def line(rng: random.Random, n: int = 4) -> LineString:
    while True:
        pts = [_pt(rng, n) for _ in range(rng.randint(2, 4))]
        r = rng.random()
        if r < 0.15:
            pts.append(pts[0])  # closed
        elif r < 0.25:
            pts.insert(1, pts[1])  # a repeated point
        if len(set(pts)) >= 2:
            return LineString(pts)


def multiline(rng: random.Random, n: int = 4) -> MultiLineString:
    return MultiLineString([line(rng, n) for _ in range(rng.randint(2, 3))])


def is_valid(g: Geometry) -> bool:
    """GEOS-default validity of a lattice geometry (exact)."""
    if isinstance(g, GeometryCollection):
        return all(is_valid(e) for e in g.geometries)
    if isinstance(g, MultiPolygon | Polygon):
        polys = [g] if isinstance(g, Polygon) else list(g.polygons)
        return validity.valid_geometry([[list(r) for r in p.rings] for p in polys])
    if isinstance(g, LineString):
        return len(set(g.coords)) >= 2
    if isinstance(g, MultiLineString):
        return all(is_valid(x) for x in g.lines)
    return True


def _ring(rng: random.Random, n: int) -> list[Coord] | None:
    if rng.random() < 0.35:
        x0, x1 = sorted(rng.sample(range(n + 1), 2))
        y0, y1 = sorted(rng.sample(range(n + 1), 2))
        ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    else:
        pts = list({_pt(rng, n) for _ in range(rng.randint(3, 6))})
        if len(pts) < 3:
            return None
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))  # float only orders a
        ring = pts  # candidate; exact validity decides
    if rng.random() < 0.5:
        ring = ring[::-1]
    ring = [(float(x), float(y)) for x, y in ring]
    k = rng.randrange(len(ring))  # any start vertex
    ring = ring[k:] + ring[:k]
    return [*ring, ring[0]]


def polygon(rng: random.Random, n: int = 4) -> Polygon:
    while True:
        shell = _ring(rng, n)
        if shell is None:
            continue
        rings = [shell]
        if rng.random() < 0.3:
            hole = _ring(rng, n)
            if hole is not None:
                rings.append(hole)
        p = Polygon(rings)
        if is_valid(p):
            return p


def multipolygon(rng: random.Random, n: int = 4) -> MultiPolygon:
    for _ in range(500):
        mp = MultiPolygon([polygon(rng, n) for _ in range(2)])
        if is_valid(mp):
            return mp
    return MultiPolygon([polygon(rng, n)])  # pragma: no cover - vanishingly rare


def collection(rng: random.Random, n: int = 4) -> GeometryCollection:
    gens: list[Callable[[random.Random, int], Geometry]] = [
        point,
        multipoint,
        line,
        multiline,
        polygon,
        polygon,
    ]
    return GeometryCollection([rng.choice(gens)(rng, n) for _ in range(rng.randint(2, 3))])


def tiled(rng: random.Random, n: int = 4) -> GeometryCollection:
    """A GC of 2-3 axis-parallel rectangles that often share edges or overlap."""
    rects = []
    for _ in range(rng.randint(2, 3)):
        x0, x1 = sorted(rng.sample(range(n + 1), 2))
        y0, y1 = sorted(rng.sample(range(n + 1), 2))
        ring = [(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]
        rects.append(Polygon([[(float(x), float(y)) for x, y in ring]]))
    return GeometryCollection(rects)


#: Generators by type code: P, MP, L, ML, A, MA, GC (mixed), GCA (tiled rectangles).
GENERATORS: dict[str, Callable[[random.Random, int], Geometry]] = {
    "P": point,
    "MP": multipoint,
    "L": line,
    "ML": multiline,
    "A": polygon,
    "MA": multipolygon,
    "GC": collection,
    "GCA": tiled,
}
TYPES: tuple[str, ...] = tuple(GENERATORS)


def random_geometry(rng: random.Random, kind: str, n: int = 4) -> Geometry:
    return GENERATORS[kind](rng, n)


def type_pairs() -> list[tuple[str, str]]:
    return [(a, b) for a in TYPES for b in TYPES]


def random_pair(rng: random.Random, i: int, n: int = 4) -> tuple[str, str, Geometry, Geometry]:
    """The ``i``-th case of a sweep over every ordered type pair."""
    pairs = type_pairs()
    ta, tb = pairs[i % len(pairs)]
    return ta, tb, random_geometry(rng, ta, n), random_geometry(rng, tb, n)


def zero_length_line(rng: random.Random, n: int = 4) -> LineString:
    """A LineString whose points all coincide (real dimension 0; GEOS calls it invalid)."""
    p = _pt(rng, n)
    return LineString([p] * rng.randint(2, 3))
