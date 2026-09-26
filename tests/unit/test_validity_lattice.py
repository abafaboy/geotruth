"""Random small-integer-lattice geometries of every type, valid and invalid, and the
unit-level checks that use them.

:func:`random_geometry` is shared with ``tests/crosscheck/test_validity_geos.py`` (import
it as ``from unit.test_validity_lattice import random_geometry``). It mixes every type and
every GEOS defect class: bowties, self-touching (inverted) rings, spikes, repeated and
collinear points, holes touching / crossing / sharing edges with shells, nested holes and
shells, hole cycles (disconnected interiors), zero-length and one-point lines, empty
elements, non-finite coordinates, and exact affine maps (power-of-two scales, dyadic
offsets, axis swaps) of all of these.
"""

from __future__ import annotations

import math
import random
import sys
from pathlib import Path

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
from geotruth.validity import CODES, validate

NAN, INF = math.nan, math.inf

# ------------------------------------------------------------------------ generator


def _pt(rng: random.Random, g: int) -> tuple[float, float]:
    return (float(rng.randint(0, g)), float(rng.randint(0, g)))


def _close(pts) -> list:
    pts = list(pts)
    return [*pts, pts[0]]


def _ring_random(rng: random.Random, g: int) -> list:
    return _close(_pt(rng, g) for _ in range(rng.randint(3, 6)))


def _ring_rect(rng: random.Random, x0: int, y0: int, x1: int, y1: int) -> list:
    a, b = sorted(rng.sample(range(x0, x1 + 1), 2)) if x1 > x0 else (x0, x0 + 1)
    c, d = sorted(rng.sample(range(y0, y1 + 1), 2)) if y1 > y0 else (y0, y0 + 1)
    return [(a, c), (b, c), (b, d), (a, d), (a, c)]


def _ring_small(rng: random.Random, x0: int, y0: int, x1: int, y1: int) -> list:
    k = rng.randrange(4)
    if k == 0:
        return _ring_rect(rng, x0, y0, x1, y1)
    if k == 1:
        return _close((rng.randint(x0, x1), rng.randint(y0, y1)) for _ in range(3))
    if k == 2:
        cx, cy, r = rng.randint(x0, x1), rng.randint(y0, y1), rng.randint(1, 2)
        return _close([(cx - r, cy), (cx, cy - r), (cx + r, cy), (cx, cy + r)])
    return _close((rng.randint(x0, x1), rng.randint(y0, y1)) for _ in range(rng.randint(3, 5)))


#: Shells that are invalid (or borderline) on their own.
SPECIAL_RINGS = [
    [(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)],  # bowtie
    [(0, 0), (4, 0), (4, 4), (2, 0), (0, 4), (0, 0)],  # inverted: vertex on an edge
    [(0, 0), (2, 0), (1, 1), (2, 2), (0, 2), (1, 1), (0, 0)],  # self-touch at a vertex
    [(0, 0), (1, 1), (2, 2), (2, 0), (1, 1), (0, 2), (0, 0)],  # crossing through a vertex
    [(0, 0), (2, 0), (2, 2), (2, 3), (2, 2), (0, 2), (0, 0)],  # spike
    [(0, 0), (2, 0), (2, 0), (2, 2), (0, 2), (0, 0)],  # repeated point
    [(0, 0), (1, 0), (2, 0), (2, 2), (0, 2), (0, 0)],  # collinear vertex
    [(0, 0), (3, 0), (1, 0), (0, 0)],  # flat
    [(0, 0), (1, 1), (0, 0)],  # three points, closed
    [(0, 0), (1, 1), (1, 1), (0, 0)],  # too few distinct points
    [(0, 0), (4, 0), (4, 2), (2, 2), (2, 0), (2, -1), (0, -1), (0, 0)],  # overlap on a line
]

#: Holes of a 6x6 shell that touch the shell and each other at points.
TOUCHING_HOLES = [
    [(0, 3), (3, 1), (3, 3), (0, 3)],
    [(0, 3), (3, 0), (3, 3), (0, 3)],  # touches the shell twice
    [(3, 3), (6, 3), (3, 5), (3, 3)],
    [(3, 3), (5, 1), (5, 3), (3, 3)],
    [(1, 1), (3, 1), (3, 3), (1, 3), (1, 1)],
    [(3, 3), (5, 3), (5, 5), (3, 5), (3, 3)],
    [(3, 1), (5, 1), (5, 3), (3, 3), (3, 1)],
    [(2, 2), (4, 2), (4, 4), (2, 4), (2, 2)],
    [(1, 1), (5, 1), (5, 5), (1, 5), (1, 1)],  # big: nests others
    [(0, 0), (2, 1), (1, 2), (0, 0)],  # touches the shell's corner
    [(6, 6), (7, 4), (8, 8), (6, 6)],  # outside, touching
]


def _poly_structured(rng: random.Random, g: int, ox: int = 0, oy: int = 0) -> Polygon:
    shell = [(ox, oy), (ox + g, oy), (ox + g, oy + g), (ox, oy + g), (ox, oy)]
    if rng.random() < 0.3:
        shell = [(ox, oy), (ox + g, oy), (ox + g // 2, oy + g), (ox, oy)]
    holes = [
        _ring_small(rng, ox, oy, ox + g, oy + g) for _ in range(rng.choice([0, 1, 1, 2, 2, 3]))
    ]
    return Polygon([shell, *holes])


def _poly_random(rng: random.Random, g: int) -> Polygon:
    rings = [_ring_random(rng, g)]
    for _ in range(rng.choice([0, 0, 1, 2])):
        rings.append(_ring_random(rng, g))
    return Polygon(rings)


def _poly_special(rng: random.Random) -> Polygon:
    shell = rng.choice(SPECIAL_RINGS)
    if rng.random() < 0.3:
        return Polygon([shell, _ring_small(rng, 0, 0, 4, 4)])
    return Polygon([shell])


def _poly_touching_holes(rng: random.Random) -> Polygon:
    shell = [(0, 0), (6, 0), (6, 6), (0, 6), (0, 0)]
    return Polygon([shell, *rng.sample(TOUCHING_HOLES, rng.randint(1, 4))])


def _multipolygon(rng: random.Random) -> MultiPolygon:
    parts = []
    g = rng.choice([2, 3, 4])
    for _ in range(rng.randint(2, 3)):
        ox, oy = rng.randint(-1, g), rng.randint(-1, g)
        r = rng.random()
        if r < 0.4:
            parts.append(Polygon([_ring_small(rng, ox, oy, ox + g, oy + g)]))
        elif r < 0.8:
            parts.append(_poly_structured(rng, max(2, g // 2 + 1), ox, oy))
        else:
            parts.append(Polygon([]))
    return MultiPolygon(parts)


def _line(rng: random.Random, g: int) -> LineString:
    k = rng.random()
    if k < 0.1:
        return LineString([_pt(rng, g)] * rng.randint(1, 3))  # zero length, or one point
    if k < 0.15:
        return LineString([])
    pts = [_pt(rng, g) for _ in range(rng.randint(2, 5))]
    if rng.random() < 0.2:
        i = rng.randrange(len(pts))
        pts.insert(i, pts[i])
    return LineString(pts)


def _points(rng: random.Random, g: int) -> Geometry:
    if rng.random() < 0.3:
        return Point(_pt(rng, g)) if rng.random() < 0.9 else Point()
    return MultiPoint(
        [(Point(_pt(rng, g)) if rng.random() < 0.9 else Point()) for _ in range(rng.randint(0, 4))]
    )


def with_bad_coordinate(rng: random.Random, geom: Geometry) -> Geometry:
    """``geom`` with one ordinate replaced by NaN or +-inf."""
    n = geom.num_coords
    if not n:
        return geom
    target, axis = rng.randrange(n), rng.randrange(3)
    bad = rng.choice([NAN, INF, -INF])
    counter = [0]

    def fn(c):
        i = counter[0]
        counter[0] += 1
        if i != target:
            return c
        return ((bad, c[1]), (c[0], bad), (bad, bad))[axis]

    return geom.map_coords(fn)


def exact_map(rng: random.Random, geom: Geometry) -> Geometry:
    """An exact affine map: a power-of-two scale, a dyadic offset, an axis swap and sign
    flips. Every result is exactly representable, so validity cannot change."""
    s = math.ldexp(1.0, rng.randint(-6, 6))
    ox, oy = rng.randint(-8, 8) * 0.25, rng.randint(-8, 8) * 0.25
    swap = rng.random() < 0.5
    nx, ny = rng.choice([1.0, -1.0]), rng.choice([1.0, -1.0])

    def fn(c):
        x, y = (c[1], c[0]) if swap else (c[0], c[1])
        return (nx * x * s + ox, ny * y * s + oy)

    return geom.map_coords(fn)


def _atomic(rng: random.Random) -> Geometry:
    g = rng.choice([2, 3, 4])
    r = rng.random()
    if r < 0.10:
        return _points(rng, g)
    if r < 0.22:
        return _line(rng, g)
    if r < 0.27:
        return MultiLineString([_line(rng, g) for _ in range(rng.randint(1, 3))])
    if r < 0.45:
        return _poly_random(rng, g)
    if r < 0.62:
        return _poly_structured(rng, rng.choice([2, 3, 4, 6]))
    if r < 0.72:
        return _poly_special(rng)
    if r < 0.82:
        return _poly_touching_holes(rng)
    return _multipolygon(rng)


def random_geometry(rng: random.Random) -> Geometry:
    """One random geometry of any type (doubles), valid or not."""
    if rng.random() < 0.08:
        kids = [_atomic(rng) for _ in range(rng.randint(0, 3))]
        if rng.random() < 0.3:
            kids.append(GeometryCollection([_atomic(rng)]))
        geom: Geometry = GeometryCollection(kids)
    else:
        geom = _atomic(rng)
    geom = geom.map_coords(lambda c: (float(c[0]), float(c[1])))
    if rng.random() < 0.03:
        geom = with_bad_coordinate(rng, geom)
    if rng.random() < 0.3:
        geom = exact_map(rng, geom)
    return geom


# ------------------------------------------------------------------------ unit checks


def test_generator_covers_every_defect_kind():
    rng = random.Random(1)
    seen = set()
    types = set()
    for _ in range(3000):
        g = random_geometry(rng)
        types.add(g.geom_type)
        seen.update(validate(g).reasons)
    assert seen == set(CODES) - {"ring_not_closed"}  # generated rings are always closed
    assert types == {
        "Point",
        "MultiPoint",
        "LineString",
        "MultiLineString",
        "Polygon",
        "MultiPolygon",
        "GeometryCollection",
    }


def test_exact_maps_preserve_validity():
    rng = random.Random(2)
    for _ in range(600):
        g = random_geometry(rng)
        if g.has_nonfinite:
            continue
        r = validate(g)
        h = exact_map(rng, g)
        rh = validate(h)
        assert rh.valid == r.valid
        assert rh.reasons == r.reasons
        assert len(rh.defects) == len(r.defects)


def _reference_validity():
    ref = Path(__file__).resolve().parents[1] / "reference"
    if str(ref) not in sys.path:
        sys.path.insert(0, str(ref))
    import validity as reference

    return reference


def _v1(geom: Geometry):
    polys = [geom] if isinstance(geom, Polygon) else list(geom.polygons)
    return [[[list(c) for c in r] for r in p.rings] for p in polys]


def test_agrees_with_the_vendored_reference():
    """``tests/reference/validity.py`` (R0-R6, independent code) on polygonal input."""
    reference = _reference_validity()
    rng = random.Random(3)
    checked = 0
    for _ in range(4000):
        g = random_geometry(rng)
        if not isinstance(g, (Polygon, MultiPolygon)) or g.has_nonfinite:
            continue
        polys = [g] if isinstance(g, Polygon) else list(g.polygons)
        if any(not p.rings or any(not r for r in p.rings) for p in polys):
            continue  # the reference does not take empty parts or rings
        assert reference.valid_geometry(_v1(g)) == validate(g).valid, g.wkt
        checked += 1
    assert checked > 2000


def test_geos_order_emulation_is_consistent():
    """Whenever a polygonal unit has area intersections, the emulated GEOS noder must
    find one of them (or stop at a double touch): it never falls back to a guess."""
    rng = random.Random(5)
    n = 0
    for _ in range(3000):
        g = random_geometry(rng)
        r = validate(g)
        if r.first_basis == "precedence" and r.first_reason not in (
            "self_intersection",
            "ring_self_intersection",
        ):
            continue  # decided by an order-free check
        if any(c in r.reasons for c in ("self_intersection", "ring_self_intersection")):
            assert r.first_basis == "geos-order", g.wkt
            assert r.first_reason in r.first_alternatives
            n += 1
    assert n > 500
