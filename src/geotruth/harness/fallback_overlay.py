"""The exact overlay of two valid polygonal geometries, from boundary pieces.

This is the shim's fallback (:mod:`geotruth.harness.engine`) until ``geotruth.overlay``
(DESIGN §2.5) lands. It reuses the audited piece classification of
``tests/reference/indep.py``: every directed edge of A (shells counter-clockwise, holes
clockwise, so the interior is on the left) is split at every contact with B, and each
piece is classified by its midpoint as ``in`` or ``out`` of B, or on B's boundary with
the same (``same``) or the opposite (``opp``) direction; and vice versa.

The boundary of each regularized result is a set of those pieces (DESIGN §1, "the
closure of the selected cells", faces merged across edges whose sides are both selected):

============== ===================================================
operation      boundary pieces (interior on the left)
============== ===================================================
intersection   A in, B in, A same
union          A out, B out, A same
difference     A out, A opp, B in reversed
symdifference  A out, B out, A in reversed, B in reversed
============== ===================================================

Pieces are chained into rings with the minimal-ring rule of DESIGN §2.5: at a vertex the
next piece is the first one clockwise from the reversed incoming direction (the boundary
walk of one face, so faces that touch at a vertex stay separate polygons), and a walk that
visits a vertex twice is split there into simple rings, so a pinch becomes a shell and a
touching hole. Counter-clockwise rings are shells; each clockwise ring is a hole of the
smallest shell that contains it. Collinear vertices are removed except at nodes.

The non-strict variant (OverlayNG's default, lines and points of boundary touches kept)
differs from the areal one only for the intersection of polygonal operands: it adds the
``opp`` pieces (boundary shared with the interiors on opposite sides) as lines, and every
boundary contact point not on the areal result or on those lines as a point. Union,
difference and symmetric difference of polygons have no lower-dimensional parts.

Every result's area is checked against ``indep.evaluate_geoms``; a mismatch raises
:class:`FallbackOverlayError` (reported as ``engine_error``, never against a library).
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
from fractions import Fraction
from functools import cmp_to_key
from pathlib import Path
from typing import Any

from geotruth.exact import ON_BOUNDARY, angle_cmp, point_in_ring
from geotruth.geom import (
    Geometry,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
    build_geometry,
)
from geotruth.io import canonicalize

__all__ = [
    "OPS",
    "FallbackOverlayError",
    "areal_rings_area",
    "overlay_all",
    "reference_module",
]

OPS = ("intersection", "union", "difference", "symdifference")

Pt = tuple[Fraction, Fraction]


class FallbackOverlayError(RuntimeError):
    """The fallback overlay could not build a consistent result."""


_REF_PKG = "_geotruth_reference"


def reference_module(name: str) -> Any:
    """A module of the vendored references (``tests/reference/<name>.py``), imported as
    part of a private package so its relative imports work. Raises ImportError when the
    references are absent (an installed geotruth has no tests directory)."""
    ref = Path(__file__).resolve().parents[3] / "tests" / "reference"
    if not (ref / f"{name}.py").is_file():
        raise ImportError(f"tests/reference/{name}.py is not available")
    if _REF_PKG not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            _REF_PKG, ref / "__init__.py", submodule_search_locations=[str(ref)]
        )
        if spec is None or spec.loader is None:  # pragma: no cover
            raise ImportError("cannot load tests/reference")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_REF_PKG] = mod
        spec.loader.exec_module(mod)
    return importlib.import_module(f"{_REF_PKG}.{name}")


def _v1(geom: Geometry) -> list:
    """Non-empty polygon elements as FORMAT-v1 coordinates (doubles, as a library sees)."""
    out = []
    for e in geom.elements():
        if isinstance(e, Polygon) and not e.is_empty:
            out.append([[[float(x), float(y)] for x, y in ring] for ring in e.rings])
    return out


def is_polygonal(geom: Geometry) -> bool:
    """Polygon or MultiPolygon (possibly empty): the input the fallback handles."""
    return isinstance(geom, (Polygon, MultiPolygon))


# ============================================================================ chaining


def _angle_key(v: tuple[Any, Any]) -> Any:
    return cmp_to_key(angle_cmp)(v)


def _next_piece(v: Pt, incoming_from: Pt, candidates: list[tuple[Pt, int]]) -> tuple[Pt, int]:
    """The first candidate clockwise from the reversed incoming direction."""
    r = (incoming_from[0] - v[0], incoming_from[1] - v[1])
    kr = _angle_key(r)
    below = [(w, i) for w, i in candidates if _angle_key((w[0] - v[0], w[1] - v[1])) < kr]
    pool = below or candidates
    return max(pool, key=lambda c: _angle_key((c[0][0] - v[0], c[0][1] - v[1])))


def _chain(segments: list[tuple[Pt, Pt]]) -> list[list[Pt]]:
    """Closed rings (open vertex lists) from directed boundary segments."""
    out_of: dict[Pt, list[tuple[Pt, int]]] = {}
    for i, (p, s) in enumerate(segments):
        out_of.setdefault(p, []).append((s, i))
    used = [False] * len(segments)
    rings = []
    for i0, (p0, s0) in enumerate(segments):
        if used[i0]:
            continue
        used[i0] = True
        ring = [p0]
        prev, v = p0, s0
        for _ in range(len(segments) + 1):
            cands = [(w, i) for w, i in out_of.get(v, []) if not used[i] or i == i0]
            if not cands:
                raise FallbackOverlayError(f"open boundary chain at {v}")
            w, i = _next_piece(v, prev, cands)
            if i == i0:
                break
            used[i] = True
            ring.append(v)
            prev, v = v, w
        else:  # pragma: no cover
            raise FallbackOverlayError("ring chaining did not terminate")
        rings.append(ring)
    return rings


def _split_simple(rings: list[list[Pt]]) -> list[list[Pt]]:
    """Split every ring that visits a vertex twice (a face whose boundary touches itself,
    as the boundary walk of a polygon with a hole touching its shell does) into simple
    rings; their orientations then tell shells from holes."""
    out = []
    stack = list(rings)
    while stack:
        r = stack.pop()
        seen: dict[Pt, int] = {}
        for i, p in enumerate(r):
            j = seen.get(p)
            if j is not None:
                stack.append(r[j:i])
                stack.append(r[:j] + r[i:])
                break
            seen[p] = i
        else:
            out.append(r)
    return out


def _area2(ring: list[Pt]) -> Fraction:
    n = len(ring)
    return sum(
        (ring[i - 1][0] * ring[i][1] - ring[i][0] * ring[i - 1][1] for i in range(n)), Fraction(0)
    )


def _collinear(a: Pt, b: Pt, c: Pt) -> bool:
    return (b[0] - a[0]) * (c[1] - a[1]) == (b[1] - a[1]) * (c[0] - a[0])


def _simplify(rings: list[list[Pt]]) -> list[list[Pt]]:
    """Drop collinear vertices that are not nodes (a node occurs more than once among all
    ring vertices)."""
    count: dict[Pt, int] = {}
    for r in rings:
        for p in r:
            count[p] = count.get(p, 0) + 1
    out = []
    for r in rings:
        pts = list(r)
        changed = True
        while changed and len(pts) > 3:
            changed = False
            for k in range(len(pts)):
                a, b, c = pts[k - 1], pts[k], pts[(k + 1) % len(pts)]
                if count[b] == 1 and _collinear(a, b, c):
                    del pts[k]
                    changed = True
                    break
        out.append(pts)
    return out


def _assemble(rings: list[list[Pt]]) -> list[Polygon]:
    shells = [r for r in rings if _area2(r) > 0]
    holes = [r for r in rings if _area2(r) < 0]
    if len(shells) + len(holes) != len(rings):
        raise FallbackOverlayError("a result ring has zero area")
    shells.sort(key=_area2)
    owned: list[list[list[Pt]]] = [[] for _ in shells]
    for h in holes:
        owner = None
        for k, sh in enumerate(shells):
            closed = [*sh, sh[0]]
            loc = ON_BOUNDARY
            for j in range(len(h)):
                a, b = h[j], h[(j + 1) % len(h)]
                m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                loc = point_in_ring(m, closed)
                if loc != ON_BOUNDARY:
                    break
            if loc > 0:
                owner = k
                break
        if owner is None:
            raise FallbackOverlayError("a hole lies in no shell")
        owned[owner].append(h)
    return [
        Polygon(((*sh, sh[0]), *((*h, h[0]) for h in hs)))
        for sh, hs in zip(shells, owned, strict=True)
    ]


# ============================================================================ lines, points


def _merge_lines(segs: list[tuple[Pt, Pt]]) -> list[list[Pt]]:
    """Maximal polylines from undirected segments (joined at vertices of degree 2),
    without collinear interior vertices."""
    if not segs:
        return []
    adj: dict[Pt, list[int]] = {}
    for i, (p, s) in enumerate(segs):
        adj.setdefault(p, []).append(i)
        adj.setdefault(s, []).append(i)
    used = [False] * len(segs)
    lines = []

    def walk(start: Pt, i: int) -> list[Pt]:
        path = [start]
        v = start
        while True:
            used[i] = True
            p, s = segs[i]
            v = s if p == v else p
            path.append(v)
            if len(adj[v]) != 2:
                return path
            nxt = [j for j in adj[v] if not used[j]]
            if not nxt:
                return path
            i = nxt[0]

    for v, idx in adj.items():
        if len(idx) != 2:
            for i in idx:
                if not used[i]:
                    lines.append(walk(v, i))
    for i, (p, _) in enumerate(segs):  # cycles
        if not used[i]:
            lines.append(walk(p, i))
    out = []
    for line in lines:
        pts = [line[0]]
        for k in range(1, len(line) - 1):
            if not _collinear(pts[-1], line[k], line[k + 1]):
                pts.append(line[k])
        pts.append(line[-1])
        out.append(pts)
    return out


def _on_segment(p: Pt, a: Pt, b: Pt) -> bool:
    return (
        min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
        and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
        and _collinear(a, b, p)
    )


# ============================================================================ overlay


def _is_valid(g: Geometry) -> bool:
    from geotruth.validity import validate

    return validate(g).valid


def areal_rings_area(polys: list[Polygon]) -> Fraction:
    """Exact area of valid polygons: each shell minus its holes."""
    total = Fraction(0)
    for p in polys:
        for k, ring in enumerate(p.rings):
            a = abs(_area2(list(ring[:-1]))) / 2
            total += a if k == 0 else -a
    return total


def overlay_all(a: Geometry, b: Geometry) -> dict[str, dict[str, Geometry]]:
    """``{op: {"areal": geometry, "non_strict": geometry}}`` for the four operations, with
    exact (Fraction) coordinates in canonical form. ``a`` and ``b`` must be valid Polygons
    or MultiPolygons (possibly empty); the caller checks."""
    if not (is_polygonal(a) and is_polygonal(b)):
        raise FallbackOverlayError("the fallback overlay handles polygonal operands only")
    indep = reference_module("indep")
    pa, pb = indep.parse(_v1(a)), indep.parse(_v1(b))
    ea, eb = indep.directed_edges(pa), indep.directed_edges(pb)
    pieces_a, _ = indep.pieces(ea, eb)
    pieces_b, _ = indep.pieces(eb, ea)
    sel: dict[str, list[tuple[Pt, Pt]]] = {}
    for tag, pieces in (("A", pieces_a), ("B", pieces_b)):
        for p, s, cls in pieces:
            if p != s:
                sel.setdefault(tag + cls, []).append((p, s))

    def fwd(key: str) -> list[tuple[Pt, Pt]]:
        return sel.get(key, [])

    def rev(key: str) -> list[tuple[Pt, Pt]]:
        return [(s, p) for p, s in sel.get(key, [])]

    boundary = {
        "intersection": fwd("Ain") + fwd("Bin") + fwd("Asame"),
        "union": fwd("Aout") + fwd("Bout") + fwd("Asame"),
        "difference": fwd("Aout") + fwd("Aopp") + rev("Bin"),
        "symdifference": fwd("Aout") + fwd("Bout") + rev("Ain") + rev("Bin"),
    }
    check = indep.evaluate_geoms(_v1(a), _v1(b))
    want = {
        "intersection": check["inter"],
        "union": check["union"],
        "difference": check["diff_ab"],
        "symdifference": check["diff_ab"] + check["diff_ba"],
    }
    out: dict[str, dict[str, Geometry]] = {}
    for op in OPS:
        polys = _assemble(_simplify(_split_simple(_chain(boundary[op]))))
        got = areal_rings_area(polys)
        if got != want[op]:
            raise FallbackOverlayError(f"{op}: area {got} != independent area {want[op]}")
        areal = canonicalize(build_geometry(polys)) if polys else Polygon()
        if not _is_valid(areal):
            raise FallbackOverlayError(f"{op}: the assembled result is not valid")
        non_strict = areal
        if op == "intersection":
            lines = [LineString(tuple(x)) for x in _merge_lines(sel.get("Aopp", []))]
            ring_segs = [
                (r[j], r[j + 1]) for p in polys for r in p.rings for j in range(len(r) - 1)
            ]
            line_segs = [
                (ln.coords[j], ln.coords[j + 1]) for ln in lines for j in range(len(ln.coords) - 1)
            ]
            contacts = set()
            for p, s, _ in pieces_a:
                for v in (p, s):
                    if any(_on_segment(v, c, d) for c, d in eb):
                        contacts.add(v)
            points = [
                Point(v)
                for v in sorted(contacts)
                if not any(_on_segment(v, c, d) for c, d in ring_segs + line_segs)
            ]
            parts = [*polys, *lines, *points]
            if lines or points:
                non_strict = canonicalize(build_geometry(parts))
        out[op] = {"areal": areal, "non_strict": non_strict}
    return out
