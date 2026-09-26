"""Test helpers for :mod:`geotruth.arrangement` (shared by unit, crosscheck and slow tests).

Everything here is exact and deliberately independent of the arrangement's algorithms:

- :func:`brute_locate` locates a point in a geometry directly from its coordinates by the
  rules of DESIGN §1 (polygonal union with an exact AdjacentEdgeLocator-style sector test,
  then the Mod-2 line rule, then points). It never looks at a DCEL.
- :func:`locate_cell` finds the arrangement cell containing a point by brute force
  (vertex equality, point on edge, then point-in-cycle tests on every face).
- :func:`cell_probes` yields one exact probe point per vertex, per edge (its midpoint) and
  per half-edge (a point just to its left, closer to it than to any other edge), so every
  label and every face assignment can be checked.
- :func:`canonical_form` describes an arrangement up to renumbering, to compare a built
  arrangement with a hand-built fixture.
- random generators of valid lattice cases (polygons, lines, points, collections).
"""

from __future__ import annotations

import random
from collections.abc import Iterator
from fractions import Fraction

from geotruth.arrangement_api import Arrangement, Location
from geotruth.exact import (
    INSIDE,
    ON_BOUNDARY,
    OUTSIDE,
    angle_cmp,
    on_segment,
    point_in_ring,
    signed_area2,
    sqdist_point_segment,
)
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

I, B, E = Location.INTERIOR, Location.BOUNDARY, Location.EXTERIOR

FPoint = tuple[Fraction, Fraction]


def fpt(c) -> FPoint:
    return Fraction(c[0]), Fraction(c[1])


# ========================================================= brute-force point location


def _ring(coords) -> list[FPoint]:
    return [fpt(c) for c in coords]


def _polygon_loc(p: FPoint, rings: list[list[FPoint]]) -> Location:
    shell = point_in_ring(p, rings[0])
    if shell == ON_BOUNDARY:
        return B
    if shell == OUTSIDE:
        return E
    for hole in rings[1:]:
        loc = point_in_ring(p, hole)
        if loc == ON_BOUNDARY:
            return B
        if loc == INSIDE:
            return E
    return I


def _segments(ring: list[FPoint]) -> Iterator[tuple[FPoint, FPoint]]:
    for i in range(len(ring) - 1):
        if ring[i] != ring[i + 1]:
            yield ring[i], ring[i + 1]


def _sector_interior(p: FPoint, polys: list[list[list[FPoint]]]) -> bool:
    """True if every sector around ``p`` (a point on some polygon boundary) lies in the
    interior of some polygon: the exact AdjacentEdgeLocator rule.

    The boundary rays at ``p`` split its neighbourhood into wedges; each wedge is probed
    at ``p + eps * w`` for a direction ``w`` strictly inside it and an ``eps`` below the
    distance from ``p`` to every boundary segment not through ``p``.
    """
    dirs: list[FPoint] = []
    far = None
    for rings in polys:
        for ring in rings:
            for a, b in _segments(ring):
                if on_segment(p, a, b):
                    if p != a:
                        dirs.append((a[0] - p[0], a[1] - p[1]))
                    if p != b:
                        dirs.append((b[0] - p[0], b[1] - p[1]))
                else:
                    num, den = sqdist_point_segment(p, a, b)
                    d2 = Fraction(num) / Fraction(den)
                    far = d2 if far is None or d2 < far else far
    dirs.sort(key=_angle_key)
    uniq: list[FPoint] = []
    for d in dirs:
        if not uniq or angle_cmp(uniq[-1], d) != 0:
            uniq.append(d)
    if uniq and angle_cmp(uniq[0], uniq[-1]) == 0 and len(uniq) > 1:
        uniq.pop()
    for i, d0 in enumerate(uniq):
        d1 = uniq[(i + 1) % len(uniq)]
        cross = d0[0] * d1[1] - d0[1] * d1[0]
        if len(uniq) > 1 and cross > 0:
            w = (d0[0] + d1[0], d0[1] + d1[1])
        else:  # the wedge spans at least pi: its left perpendicular is inside
            w = (-d0[1], d0[0])
        n2 = w[0] * w[0] + w[1] * w[1]
        eps = Fraction(1)
        while far is not None and eps * eps * n2 * 4 >= far:
            eps /= 2
        q = (p[0] + eps * w[0], p[1] + eps * w[1])
        if not any(_polygon_loc(q, rings) == I for rings in polys):
            return False
    return True


def _angle_key(d):
    from functools import cmp_to_key

    return cmp_to_key(angle_cmp)(d)


class BruteLocator:
    """DESIGN §1 point location in one operand, directly from its coordinates."""

    def __init__(self, geom: Geometry) -> None:
        self.polys: list[list[list[FPoint]]] = []
        self.lines: list[list[FPoint]] = []
        self.points: set[FPoint] = set()
        self.ends: dict[FPoint, int] = {}
        for el in geom.elements():
            if el.is_empty:
                continue
            if isinstance(el, Polygon):
                self.polys.append([_ring(r) for r in el.rings if r])
            elif isinstance(el, LineString):
                pts = _ring(el.coords)
                self.lines.append(pts)
                for q in (pts[0], pts[-1]):
                    self.ends[q] = self.ends.get(q, 0) + 1
            else:
                self.points.add(fpt(el.coord))

    def locate(self, p: FPoint) -> Location:
        p = (Fraction(p[0]), Fraction(p[1]))
        n_bdy = 0
        for rings in self.polys:
            loc = _polygon_loc(p, rings)
            if loc == I:
                return I
            n_bdy += loc == B
        if n_bdy:
            return I if _sector_interior(p, self.polys) else B
        if self.ends.get(p, 0) % 2 == 1:
            return B
        for pts in self.lines:
            if len(pts) == 1 or all(q == pts[0] for q in pts):
                if p == pts[0]:
                    return I
                continue
            if any(on_segment(p, a, b) for a, b in _segments(pts)):
                return I
        if p in self.points:
            return I
        return E


def brute_locate(geom: Geometry, p) -> Location:
    return BruteLocator(geom).locate(p)


# ============================================================== cells of a DCEL


def cycle_points(arr: Arrangement, h: int) -> list[FPoint]:
    return [arr.vertex_fractions(arr.he_origin[g]) for g in arr.cycle(h)]


def face_area2(arr: Arrangement, f: int) -> Fraction:
    """Twice the (real) area of bounded face ``f``: outer cycle minus inner components."""
    total = Fraction(0)
    for h in arr.boundary_components(f):
        total += signed_area2(cycle_points(arr, h))
    return total


class CellLocator:
    """Which cell of an arrangement contains a point (brute force, exact)."""

    def __init__(self, arr: Arrangement) -> None:
        self.arr = arr
        self.pts = [arr.vertex_fractions(v) for v in range(arr.num_vertices)]
        self.index = {p: v for v, p in enumerate(self.pts)}
        self.segs = [
            (self.pts[arr.he_origin[2 * e]], self.pts[arr.he_origin[2 * e + 1]])
            for e in range(arr.num_edges)
        ]
        self.faces = []
        for f in range(1, arr.num_faces):
            outer = cycle_points(arr, arr.face_outer[f])
            inner = [cycle_points(arr, h) for h in arr.face_inner[f]]
            self.faces.append((f, outer, inner))

    def locate(self, p) -> tuple[int, int]:
        """``(dim, index)`` of the cell containing ``p``."""
        p = (Fraction(p[0]), Fraction(p[1]))
        v = self.index.get(p)
        if v is not None:
            return 0, v
        for e, (a, b) in enumerate(self.segs):
            if on_segment(p, a, b):
                return 1, e
        found = [
            f
            for f, outer, inner in self.faces
            if point_in_ring(p, outer) == INSIDE
            and all(point_in_ring(p, r) == OUTSIDE for r in inner)
        ]
        assert len(found) <= 1, f"point {p} lies in several faces {found}"
        return 2, (found[0] if found else 0)

    def label(self, cell: tuple[int, int]) -> tuple[Location, Location]:
        dim, i = cell
        arr = self.arr
        la, lb = {
            0: (arr.vertex_loc_a, arr.vertex_loc_b),
            1: (arr.edge_loc_a, arr.edge_loc_b),
            2: (arr.face_loc_a, arr.face_loc_b),
        }[dim]
        return Location(la[i]), Location(lb[i])

    def clearance2(self, p: FPoint, skip_edge: int) -> Fraction | None:
        """Squared distance from ``p`` to the nearest edge other than ``skip_edge`` and to
        the nearest isolated vertex other than ``p`` itself (None if there is none)."""
        best = None
        for e, (a, b) in enumerate(self.segs):
            if e == skip_edge:
                continue
            num, den = sqdist_point_segment(p, a, b)
            d2 = Fraction(num) / Fraction(den)
            best = d2 if best is None or d2 < best else best
        for f in range(self.arr.num_faces):
            for v in self.arr.face_isolated[f]:
                q = self.pts[v]
                if q != p:
                    d2 = (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2
                    best = d2 if best is None or d2 < best else best
        return best


def cell_probes(arr: Arrangement) -> Iterator[tuple[str, FPoint, tuple[int, int]]]:
    """``(what, point, expected cell)`` for every vertex, edge midpoint, and a point just
    to the left of every half-edge's midpoint (which must lie in ``he_face[h]``)."""
    loc = CellLocator(arr)
    for v in range(arr.num_vertices):
        yield f"vertex {v}", loc.pts[v], (0, v)
    for e, (a, b) in enumerate(loc.segs):
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        yield f"edge {e}", mid, (1, e)
        for h in (2 * e, 2 * e + 1):
            p, q = (a, b) if h == 2 * e else (b, a)
            n = (-(q[1] - p[1]), q[0] - p[0])  # left normal
            n2 = n[0] * n[0] + n[1] * n[1]
            far = loc.clearance2(mid, e)
            # also stay closer to the edge's midpoint than to its end points
            half2 = ((q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) / 4
            far = half2 if far is None else min(far, half2)
            eps = Fraction(1)
            while eps * eps * n2 * 4 >= far:
                eps /= 2
            yield (
                f"left of half-edge {h}",
                (mid[0] + eps * n[0], mid[1] + eps * n[1]),
                (2, arr.he_face[h]),
            )
    for f in range(arr.num_faces):
        for v in arr.face_isolated[f]:
            # a point next to an isolated vertex lies in its face
            yield f"near isolated vertex {v}", _near(loc, loc.pts[v]), (2, f)


def _near(loc: CellLocator, p: FPoint) -> FPoint:
    far = loc.clearance2(p, -1)
    eps = Fraction(1)
    while far is not None and eps * eps * 4 >= far:
        eps /= 2
    return (p[0] + eps, p[1])


def check_labels(arr: Arrangement, a: Geometry, b: Geometry, extra_points=()) -> int:
    """Every probe lies in its expected cell and the cell's labels equal the brute-force
    locations in A and B. Returns the number of probes."""
    loc = CellLocator(arr)
    la, lb = BruteLocator(a), BruteLocator(b)
    n = 0
    for what, p, cell in cell_probes(arr):
        got = loc.locate(p)
        assert got == cell, f"{what} at {p}: point is in cell {got}, expected {cell}"
        want = (la.locate(p), lb.locate(p))
        assert loc.label(cell) == want, f"{what} at {p}: labels {loc.label(cell)} != {want}"
        n += 1
    for p in extra_points:
        cell = loc.locate(p)
        want = (la.locate(p), lb.locate(p))
        assert loc.label(cell) == want, f"point {p} in cell {cell}: {loc.label(cell)} != {want}"
        n += 1
    return n


def labels_matrix(arr: Arrangement) -> str:
    """The DE-9IM matrix implied by the cell labels (max cell dimension per entry)."""
    m = [[-1] * 3 for _ in range(3)]
    for c in arr.cells():
        m[c.loc_a][c.loc_b] = max(m[c.loc_a][c.loc_b], c.dim)
    return "".join("F" if d < 0 else str(d) for row in m for d in row)


# =================================================================== isomorphism


def canonical_form(arr: Arrangement) -> dict:
    """The arrangement up to renumbering: vertices, edges (with source multisets),
    ``next``, faces (by their half-edge and isolated-vertex sets) and all labels."""
    pts = [arr.vertex_fractions(v) for v in range(arr.num_vertices)]

    def he(h):
        return pts[arr.he_origin[h]], pts[arr.he_origin[h ^ 1]]

    def cyc(h):
        return frozenset(he(g) for g in arr.cycle(h))

    vertices = {pts[v]: (arr.vertex_loc_a[v], arr.vertex_loc_b[v]) for v in range(len(pts))}
    edges = {}
    for e in range(arr.num_edges):
        p, q = he(2 * e)
        key, flip = ((p, q), False) if p < q else ((q, p), True)
        srcs = sorted((tuple(s.tag), s.forward != flip) for s in arr.edge_sources[e])
        edges[key] = (srcs, arr.edge_loc_a[e], arr.edge_loc_b[e])
    nxt = {he(h): he(arr.he_next[h]) for h in range(arr.num_half_edges)}
    faces = {}
    for f in range(arr.num_faces):
        hs = frozenset(he(h) for h in arr.face_half_edges(f))
        iso = frozenset(pts[v] for v in arr.face_isolated[f])
        outer = cyc(arr.face_outer[f]) if arr.face_outer[f] >= 0 else None
        inner = frozenset(cyc(h) for h in arr.face_inner[f])
        faces[(hs, iso)] = (outer, inner, arr.face_loc_a[f], arr.face_loc_b[f], f == 0)
    return {"vertices": vertices, "edges": edges, "next": nxt, "faces": faces}


def components(arr: Arrangement) -> int:
    parent = list(range(arr.num_vertices))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for e in range(arr.num_edges):
        parent[find(arr.he_origin[2 * e])] = find(arr.he_origin[2 * e + 1])
    return len({find(v) for v in range(arr.num_vertices)})


# ==================================================================== generators


def _star(rng: random.Random, cx: int, cy: int, rmax: int, n: int) -> list[tuple[int, int]]:
    """A star-shaped lattice polygon around (cx, cy): vertices sorted by exact angle."""
    pts = set()
    while len(pts) < n:
        x, y = rng.randint(-rmax, rmax), rng.randint(-rmax, rmax)
        if (x, y) != (0, 0):
            pts.add((x, y))
    ordered = sorted(pts, key=_angle_key)
    uniq = []
    for p in ordered:
        if uniq and angle_cmp(uniq[-1], p) == 0:
            if p[0] ** 2 + p[1] ** 2 > uniq[-1][0] ** 2 + uniq[-1][1] ** 2:
                uniq[-1] = p
            continue
        uniq.append(p)
    ring = [(cx + x, cy + y) for x, y in uniq]
    return [*ring, ring[0]]


def _valid_polygon(poly: Polygon) -> bool:
    from reference import validity

    rings = [[list(map(float, c)) for c in r] for r in poly.rings]
    try:
        return bool(validity.valid_geometry([rings]))
    except Exception:
        return False


def _valid_multipolygon(polys: list[Polygon]) -> bool:
    from reference import validity

    geom = [[[list(map(float, c)) for c in r] for r in p.rings] for p in polys]
    try:
        return bool(validity.valid_geometry(geom))
    except Exception:
        return False


def random_polygon(rng: random.Random, size: int = 6, holes: bool = True) -> Polygon:
    """A valid lattice polygon (star-shaped shell, maybe a hole) within [0, 2*size]^2."""
    while True:
        c = (rng.randint(size - 1, size + 1), rng.randint(size - 1, size + 1))
        shell = _star(rng, c[0], c[1], size, rng.randint(3, 7))
        if len(shell) < 4 or signed_area2(shell) == 0:
            continue
        rings = [shell]
        if holes and rng.random() < 0.4:
            hole = _star(rng, c[0], c[1], max(1, size // 3), rng.randint(3, 4))
            if len(hole) >= 4 and signed_area2(hole) != 0:
                rings.append(hole[::-1] if rng.random() < 0.5 else hole)
        if rng.random() < 0.5:
            rings[0] = rings[0][::-1]
        poly = Polygon(rings)
        if _valid_polygon(poly):
            return poly


def random_multipolygon(rng: random.Random, size: int = 6) -> Geometry:
    while True:
        parts = [random_polygon(rng, size) for _ in range(rng.randint(1, 3))]
        if _valid_multipolygon(parts):
            return parts[0] if len(parts) == 1 else MultiPolygon(parts)


def random_line(rng: random.Random, size: int = 6) -> LineString:
    n = rng.randint(2, 5)
    while True:
        pts = [(rng.randint(0, 2 * size), rng.randint(0, 2 * size)) for _ in range(n)]
        if rng.random() < 0.15:
            pts.append(pts[0])  # closed
        if len(set(pts)) >= 2:
            return LineString(pts)


def random_lines(rng: random.Random, size: int = 6) -> Geometry:
    k = rng.randint(1, 3)
    lines = [random_line(rng, size) for _ in range(k)]
    return lines[0] if k == 1 else MultiLineString(lines)


def random_points(rng: random.Random, size: int = 6) -> Geometry:
    k = rng.randint(1, 4)
    pts = [(rng.randint(0, 2 * size), rng.randint(0, 2 * size)) for _ in range(k)]
    return Point(pts[0]) if k == 1 else MultiPoint(pts)


def random_collection(rng: random.Random, size: int = 6) -> GeometryCollection:
    """A GC mixing polygons (which may overlap: GC validity is per element), lines and
    points."""
    parts: list[Geometry] = []
    for _ in range(rng.randint(1, 3)):
        kind = rng.random()
        if kind < 0.45:
            parts.append(random_polygon(rng, size, holes=rng.random() < 0.3))
        elif kind < 0.8:
            parts.append(random_line(rng, size))
        else:
            parts.append(random_points(rng, size))
    return GeometryCollection(parts)


def random_operand(rng: random.Random, size: int = 6) -> Geometry:
    kind = rng.random()
    if kind < 0.35:
        return random_multipolygon(rng, size)
    if kind < 0.6:
        return random_lines(rng, size)
    if kind < 0.75:
        return random_points(rng, size)
    return random_collection(rng, size)


def random_face_points(rng: random.Random, arr: Arrangement, n: int) -> list[FPoint]:
    """Random rational points in the bounding box, with small denominators so that some
    fall on edges and vertices."""
    if arr.num_vertices == 0:
        return [(Fraction(rng.randint(-5, 5)), Fraction(rng.randint(-5, 5))) for _ in range(n)]
    pts = [arr.vertex_fractions(v) for v in range(arr.num_vertices)]
    x0, x1 = min(p[0] for p in pts) - 1, max(p[0] for p in pts) + 1
    y0, y1 = min(p[1] for p in pts) - 1, max(p[1] for p in pts) + 1
    out = []
    for _ in range(n):
        d = rng.choice((1, 2, 3, 4, 7, 1024))
        out.append(
            (
                x0 + Fraction(rng.randint(0, int((x1 - x0) * d)), d),
                y0 + Fraction(rng.randint(0, int((y1 - y0) * d)), d),
            )
        )
    return out
