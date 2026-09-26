"""Exact overlay: intersection, union, difference and symmetric difference (DESIGN §1
"Overlay", §2.5).

:func:`overlay` builds the labelled planar arrangement of the operands
(:func:`geotruth.arrangement.build_arrangement`), selects cells and assembles the exact
result. :func:`overlay_all` reads every operation and variant off one arrangement.

Semantics (OverlayNG)
---------------------
A cell (vertex, edge or face) is *in X* when its location in X is Interior or Boundary
(OverlayNG ``isResultOfOp``). The selected cells are

============== ===============
operation      selected where
============== ===============
intersection   in A and in B
union          in A or in B
difference     in A and not in B
symdifference  in exactly one
============== ===============

and the result is the **closure** of the selected cells, a closed point set R:

- the *polygonal part* is the closure of the selected faces. Faces are merged across every
  edge whose two sides are both selected, whether or not the edge itself is selected
  (a polygon minus a line through it is the polygon);
- the *linear part* is every selected edge with no selected face on either side;
- the *puntal part* is every selected vertex not in the closure of a selected edge or
  face.

Lower-dimensional parts are therefore kept only where they are not covered. The two
variants are:

``"non_strict"``
    OverlayNG's default (``STRICT_MODE_DEFAULT = false``): all three parts, so boundary
    touches survive as lines and points and the result can be a GeometryCollection
    (element order polygons, lines, points, as ``OverlayUtil.createResultGeometry``).
``"areal"``
    the regularized polygonal part only, for polygon-only clippers.

An empty result is typed as ``OverlayUtil.resultDimension`` from the operands' *type*
dimensions (JTS ``getDimension``): intersection ``min``, union and symmetric difference
``max``, difference the dimension of A; ``POINT EMPTY``, ``LINESTRING EMPTY``,
``POLYGON EMPTY``, or ``GEOMETRYCOLLECTION EMPTY`` for -1. Both variants use the rule.

Result assembly
---------------
Everything is exact; nothing samples a point.

1. **Boundary half-edges.** A half-edge whose left face is selected and whose right face
   is not bounds the polygonal part with the interior on its left.
2. **Minimal rings.** At the end vertex of a boundary half-edge ``h`` the walk continues
   with the first boundary half-edge clockwise from ``h``'s twin, turning through
   selected faces only (``next``, then ``next`` of the twin, ...). This links each
   incoming boundary edge to the outgoing one of the *same selected sector*, so faces
   touching only at a vertex are never joined and stay separate polygons. A cycle that
   still visits a vertex twice (a region whose boundary touches itself: a pinch, a hole
   touching the shell, two holes touching) is split there into simple rings, so a pinch
   becomes a shell plus a hole touching it at the vertex, as OGC validity requires.
   Counter-clockwise rings are shells, clockwise rings holes.
3. **Hole assignment by face adjacency.** Selected faces are grouped into components by
   union-find across the edges whose two sides are both selected; each component is the
   interior of one output polygon. Every ring's half-edges have their left faces in one
   component, which has exactly one shell; its clockwise rings are the polygon's holes.
   No point-in-polygon test is needed (islands in holes are components of their own).
4. **Lines** are the maximal chains of linear-part edges between *nodes*, and **points**
   the uncovered selected vertices.
5. **Collinear vertices are removed except at nodes** (and so at every mod-2 boundary
   point: a line end is always a node). A vertex is a *node* unless it is an interior
   vertex of exactly one *visible* input ring or line and nothing else: exactly two
   incident edges with visible sources, both carrying that single source, and not the
   start of a closed line. A source is visible on an edge when it is a line, or a ring
   on the boundary of its operand's polygonal part; the ring edges of a
   GeometryCollection's polygons that lie inside the union of its other polygons are not
   part of the point set's boundary and never make nodes. This is the node set of
   OverlayNG's noder (segment-string ends and every contact between different segment
   strings, while isolated points never node), so ring vertices and line splits follow
   GEOS: e.g. ``difference(LINESTRING (0 0, 2 0), LINESTRING (1 -1, 1 1))`` is
   ``MULTILINESTRING ((0 0, 1 0), (1 0, 2 0))``, the union of a square with a line
   crossing it keeps the crossing points in the square's ring, and ``A u A`` of a line
   is split at every vertex (both copies are segment strings) while ``A u EMPTY`` is not.

Output
------
:class:`OverlayResult` holds the exact canonical geometry (coordinates are rationals of
the active backend, :mod:`geotruth.numbers`): each ring starts at its lexicographically
smallest vertex, shells are counter-clockwise, holes clockwise, holes and parts are
sorted, lines start at their smaller end (:func:`geotruth.io.canonicalize`). It also
gives the rational side-car (``exact``: typed JSON with ``"n/d"`` strings), a display-only
WKT rounded to doubles (``wkt``: never scored, rounding can make it invalid), and the
exact area of the polygonal part. :meth:`OverlayResult.to_json` is the expected-answer
``OverlayResult`` object of ``schemas/expected.v2``.

Checks and statuses
-------------------
Every result is checked internally (ring linking is a permutation, the rings hold every
boundary half-edge exactly once, so their areas add up to the areas of the selected
faces, every component has exactly one shell, and every ring lies in one component).
``certify=True`` also runs the independent certificate of :mod:`geotruth.overlay_certify`
(DESIGN §2.6), which re-nodes A, B and the result from scratch and locates witnesses
with the standalone point locator.

Cost: the arrangement (see :mod:`geotruth.arrangement`), then O(V + E) per result plus
the exact area, whose rational terms are summed pairwise. Two random 3000-vertex stars
(18k vertices, 31k edges in the arrangement) take about 5 s for all eight results.

A result has status ``"ok"``, ``"engine_skipped"`` (over budget:
:class:`~geotruth.arrangement.BudgetExceeded` or ``MemoryError``) or ``"engine_error"``
(an internal assertion or the certificate failed, or the engine raised; ``strict=True``
re-raises). Input outside the engine's contract raises
:class:`~geotruth.arrangement.InvalidInputError` (a ``ValueError``): overlay is defined
for valid input, so the caller checks validity first (:mod:`geotruth.validity`).
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from geotruth.arrangement import (
    DEFAULT_BUDGET,
    Budget,
    BudgetExceeded,
    InvalidInputError,
    build_arrangement,
)
from geotruth.arrangement_api import Arrangement, ArrangementError
from geotruth.exact import HPoint, hp_direction, hpoint_of
from geotruth.geom import (
    Geometry,
    LineString,
    Point,
    Polygon,
    SourceTag,
    build_geometry,
    empty_of_dimension,
)
from geotruth.io import canonical_line, geometry_to_json, to_wkt
from geotruth.numbers import DyadicScale, format_rational, rational

__all__ = [
    "NON_STRICT",
    "OPS",
    "STATUS_ERROR",
    "STATUS_OK",
    "STATUS_SKIPPED",
    "VARIANTS",
    "OverlayAssertionError",
    "OverlayResult",
    "normalize_op",
    "normalize_variant",
    "num_vertices",
    "overlay",
    "overlay_all",
    "overlay_arrangement",
    "result_dimension",
    "select",
]

STATUS_OK = "ok"
STATUS_SKIPPED = "engine_skipped"
STATUS_ERROR = "engine_error"

#: The four operations, in the order of the expected-answer schema.
OPS: tuple[str, ...] = ("intersection", "union", "difference", "symdifference")

NON_STRICT, AREAL = "non_strict", "areal"
#: The two result variants (see the module docstring).
VARIANTS: tuple[str, ...] = (NON_STRICT, AREAL)

_OP_ALIASES = {
    "intersection": "intersection",
    "intersect": "intersection",
    "union": "union",
    "difference": "difference",
    "diff": "difference",
    "symdifference": "symdifference",
    "symdiff": "symdifference",
    "sym_difference": "symdifference",
    "symmetric_difference": "symdifference",
    "symmetricdifference": "symdifference",
    "xor": "symdifference",
}

_VARIANT_ALIASES = {
    "non_strict": NON_STRICT,
    "nonstrict": NON_STRICT,
    "non-strict": NON_STRICT,
    "default": NON_STRICT,
    "areal": AREAL,
    "regularized": AREAL,
    "polygonal": AREAL,
}

_BND, _EXT = 1, 2  # Location.BOUNDARY, Location.EXTERIOR


class OverlayAssertionError(RuntimeError):
    """An internal consistency check of the overlay failed (an engine bug, never a
    library failure); ``problems`` lists what was found."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        super().__init__("overlay assertion failed: " + "; ".join(self.problems))


def normalize_op(op: str) -> str:
    """The canonical name of an operation (``"symmetric_difference"`` -> ``"symdifference"``,
    ...); raises ``ValueError`` for an unknown one."""
    key = str(op).strip().lower().replace("-", "_")
    try:
        return _OP_ALIASES[key]
    except KeyError:
        raise ValueError(f"unknown overlay operation {op!r}; expected one of {OPS}") from None


def normalize_variant(variant: str) -> str:
    """The canonical name of a variant (``"non_strict"`` or ``"areal"``)."""
    key = str(variant).strip().lower()
    try:
        return _VARIANT_ALIASES[key]
    except KeyError:
        raise ValueError(
            f"unknown overlay variant {variant!r}; expected one of {VARIANTS}"
        ) from None


def select(op: str, in_a: bool, in_b: bool) -> bool:
    """Whether a cell that is (``in_a``, ``in_b``) belongs to the selected set of ``op``."""
    if op == "intersection":
        return in_a and in_b
    if op == "union":
        return in_a or in_b
    if op == "difference":
        return in_a and not in_b
    if op == "symdifference":
        return in_a != in_b
    raise ValueError(f"unknown overlay operation {op!r}")


def result_dimension(op: str, dim_a: int, dim_b: int) -> int:
    """``OverlayUtil.resultDimension``: the dimension of an empty result's type, from the
    operands' type dimensions (-1 for an empty collection)."""
    op = normalize_op(op)
    if op == "intersection":
        return min(dim_a, dim_b)
    if op == "difference":
        return dim_a
    return max(dim_a, dim_b)


def num_vertices(g: Geometry) -> int:
    """Vertices of a result: ring vertices without the closing repeat, plus the
    coordinates of every line and point."""
    n = 0
    for e in g.elements():
        if isinstance(e, Polygon):
            n += sum(max(len(r) - 1, 0) for r in e.rings)
        else:
            n += sum(1 for _ in e.iter_coords())
    return n


# ============================================================================ result


@dataclass
class OverlayResult:
    """One exact overlay result.

    ``status`` is ``"ok"``, ``"engine_skipped"`` or ``"engine_error"`` (then ``reason``
    says why and ``geometry``/``area`` are None). ``geometry`` is the canonical exact
    result; ``area`` the exact area of its polygonal part (a rational of the active
    backend). ``type_dim_a``/``type_dim_b`` are the operands' type dimensions (they type
    an empty result). ``certificate`` holds the :class:`~geotruth.overlay_certify.Certificate`
    when one was requested; ``arrangement`` the (A, B) arrangement when kept.
    """

    op: str
    variant: str
    status: str
    geometry: Geometry | None = None
    area: Any = None
    reason: str | None = None
    type_dim_a: int = -1
    type_dim_b: int = -1
    stats: dict[str, Any] = field(default_factory=dict)
    certificate: Any = field(default=None, repr=False)
    arrangement: Arrangement | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    def _geom(self) -> Geometry:
        if self.geometry is None:
            raise ValueError(f"no result: the engine status is {self.status} ({self.reason})")
        return self.geometry

    @property
    def exact(self) -> dict[str, Any]:
        """The rational side-car: typed JSON with every ordinate an ``"n/d"`` string."""
        return geometry_to_json(self._geom(), exact=True)

    @property
    def wkt(self) -> str:
        """Display-only WKT, every ordinate rounded to the nearest double. Never score
        against it: rounding can make the result invalid."""
        return to_wkt(self._geom())

    @property
    def num_vertices(self) -> int:
        return num_vertices(self._geom())

    @property
    def is_empty(self) -> bool:
        return self._geom().is_empty

    @property
    def geom_type(self) -> str:
        return self._geom().geom_type

    def to_json(self) -> dict[str, Any]:
        """The expected-answer ``OverlayResult`` object (``schemas/expected.v2``):
        ``exact``, ``wkt``, ``area`` and ``num_vertices``."""
        g = self._geom()
        return {
            "exact": geometry_to_json(g, exact=True),
            "wkt": to_wkt(g),
            "area": format_rational(self.area),
            "num_vertices": num_vertices(g),
        }


# ============================================================================ builder


def _exact_sum(terms: list[Any], start: Any) -> Any:
    """The exact sum of rationals, added pairwise (a balanced tree): a running sum of
    many terms with distinct large denominators carries the growing common denominator
    through every step, which is quadratic."""
    while len(terms) > 1:
        pairs = [terms[i] + terms[i + 1] for i in range(0, len(terms) - 1, 2)]
        if len(terms) & 1:
            pairs.append(terms[-1])
        terms = pairs
    return start + terms[0] if terms else start


def _bools(locs: Sequence[int], what: str) -> list[bool]:
    """``in X`` (Interior or Boundary) for each label; refuses unlabelled cells."""
    out = []
    for i, x in enumerate(locs):
        if x == 0 or x == 1:
            out.append(True)
        elif x == _EXT:
            out.append(False)
        else:
            raise ArrangementError([f"{what} {i} is not labelled ({x})"])
    return out


class _Overlay:
    """The per-arrangement state shared by every operation and variant."""

    def __init__(self, arr: Arrangement) -> None:
        self.arr = arr
        V, E = arr.num_vertices, arr.num_edges
        self.V, self.E = V, E
        self.fa = _bools(arr.face_loc_a, "face")
        self.fb = _bools(arr.face_loc_b, "face")
        self.ea = _bools(arr.edge_loc_a, "edge")
        self.eb = _bools(arr.edge_loc_b, "edge")
        self.va = _bools(arr.vertex_loc_a, "vertex")
        self.vb = _bools(arr.vertex_loc_b, "vertex")
        self.out: list[list[int]] = [[] for _ in range(V)]
        for h, v in enumerate(arr.he_origin):
            self.out[v].append(h)
        self.iso_face = [-1] * V
        for f, vs in enumerate(arr.face_isolated):
            for v in vs:
                self.iso_face[v] = f
        self.scale = DyadicScale(arr.scale_exp)
        self._xy: list[tuple[Any, Any] | None] = [None] * V
        self.vsrc = self._visible_sources()
        self.node = self._nodes()
        self.dim_a = -1 if arr.a is None else arr.a.dimension
        self.dim_b = -1 if arr.b is None else arr.b.dimension

    # -- vertices -------------------------------------------------------------------

    def _line_ends(self) -> dict[SourceTag, set[HPoint]]:
        """First and last coordinate of every input line element, as canonical
        homogeneous points of the arrangement's scaled space."""
        arr = self.arr
        e = arr.scale_exp
        ends: dict[SourceTag, set[HPoint]] = {}

        def scaled(c: Any) -> Fraction:
            if isinstance(c, (int, float)):
                q = Fraction(c)
            else:
                q = Fraction(int(c.numerator), int(c.denominator))
            return q / (1 << e) if e >= 0 else q * (1 << -e)

        for gid, g in ((0, arr.a), (1, arr.b)):
            if g is None:
                continue
            for tag, coords in g.iter_lines(gid):
                pts = set()
                for c in (coords[0], coords[-1]):
                    pts.add(hpoint_of((scaled(c[0]), scaled(c[1]))))
                ends[tag] = pts
        return ends

    def _visible_sources(self) -> list[tuple[SourceTag, ...]]:
        """The *visible* source tags of every edge: its lines, and its rings that lie on
        the boundary of their operand's polygonal part. A ring edge interior to the union
        of a GeometryCollection's polygons (overlapping or adjacent elements) is not part
        of the point set's boundary, so it never makes a node."""
        arr = self.arr
        loc = (arr.edge_loc_a, arr.edge_loc_b)
        out = []
        for e, srcs in enumerate(arr.edge_sources):
            out.append(tuple(s.tag for s in srcs if s.tag.is_line or loc[s.tag.geom][e] == _BND))
        return out

    def _nodes(self) -> list[bool]:
        """Node flags (see the module docstring), from visible sources only: False only
        for a vertex with exactly two incident edges that have visible sources, each
        carrying one and the same single visible source, which is not the start of a
        closed line."""
        arr = self.arr
        vsrc = self.vsrc
        node = [True] * self.V
        ends: dict[SourceTag, set[HPoint]] | None = None
        for v, hs in enumerate(self.out):
            vis = [vsrc[h >> 1] for h in hs if vsrc[h >> 1]]
            if len(vis) != 2:
                continue
            s1, s2 = vis
            if len(s1) != 1 or len(s2) != 1 or s1[0] != s2[0]:
                continue
            tag = s1[0]
            if tag.is_line:
                if ends is None:
                    ends = self._line_ends()
                if arr.vertex(v) in ends.get(tag, ()):
                    continue  # the start (and end) of a closed line
            node[v] = False
        return node

    def xy(self, v: int) -> tuple[Any, Any]:
        """Real coordinates of vertex ``v`` as exact rationals (active backend)."""
        p = self._xy[v]
        if p is None:
            p = self._xy[v] = self.scale.hpoint_to_rationals(self.arr.vertex(v))
        return p

    def direction(self, h: int) -> tuple[int, int]:
        arr = self.arr
        return hp_direction(arr.vertex(arr.he_origin[h]), arr.vertex(arr.he_origin[h ^ 1]))

    def straight(self, h_in: int, h_out: int) -> bool:
        """True if the path ``h_in`` then ``h_out`` goes straight on at their vertex."""
        ux, uy = self.direction(h_in)
        vx, vy = self.direction(h_out)
        return ux * vy == uy * vx and ux * vx + uy * vy > 0

    # -- areas ----------------------------------------------------------------------

    def _area2(self, hs: Iterable[int]) -> Any:
        """Twice the signed area swept by half-edges ``hs`` (scaled space, exact)."""
        arr = self.arr
        org = arr.he_origin
        vx, vy, vw = arr.vx, arr.vy, arr.vw
        whole = 0
        terms = []
        for h in hs:
            u, v = org[h], org[h ^ 1]
            t = vx[u] * vy[v] - vx[v] * vy[u]
            w = vw[u] * vw[v]
            if w == 1:
                whole += t
            elif t:
                terms.append(rational(t, w))
        return _exact_sum(terms, rational(whole))

    def real_area(self, area2: Any) -> Any:
        """The real area of a scaled twice-area."""
        e2 = 2 * self.arr.scale_exp
        n, d = int(area2.numerator), int(area2.denominator)
        if e2 >= 0:
            return rational(n << e2, 2 * d)
        return rational(n, d << (1 - e2))

    # -- polygonal part -------------------------------------------------------------

    def _split(self, cyc: list[int]) -> list[list[int]]:
        """Split a closed cycle of half-edges into simple rings at repeated vertices."""
        org = self.arr.he_origin
        out: list[list[int]] = []
        stack: list[int] = []
        pos: dict[int, int] = {}
        for h in cyc:
            v = org[h]
            i = pos.get(v)
            if i is not None:
                loop = stack[i:]
                del stack[i:]
                for g in loop:
                    del pos[org[g]]
                out.append(loop)
            pos[v] = len(stack)
            stack.append(h)
        if stack:
            out.append(stack)
        return out

    def polygons(self, fsel: list[bool]) -> tuple[list[Polygon], Any]:
        """The polygons of the closure of the selected faces, and twice their total area
        (scaled space)."""
        arr = self.arr
        he_face, nxt = arr.he_face, arr.he_next
        H = len(he_face)
        bnd = [fsel[he_face[h]] and not fsel[he_face[h ^ 1]] for h in range(H)]
        link = [-1] * H
        for h in range(H):
            if not bnd[h]:
                continue
            g = nxt[h]
            steps = 0
            while not bnd[g]:
                g = nxt[g ^ 1]
                steps += 1
                if steps > H:
                    raise OverlayAssertionError([f"no boundary successor for half-edge {h}"])
            link[h] = g
        seen = [False] * H
        rings: list[list[int]] = []
        for h in range(H):
            if not bnd[h] or seen[h]:
                continue
            cyc = []
            g = h
            while not seen[g]:
                seen[g] = True
                cyc.append(g)
                g = link[g]
            if g != h:
                raise OverlayAssertionError(
                    [f"boundary linking is not a permutation (cycle from {h} enters at {g})"]
                )
            rings.extend(self._split(cyc))
        # components of selected faces, across edges with both sides selected
        parent = list(range(arr.num_faces))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for e in range(self.E):
            fl, fr = he_face[2 * e], he_face[2 * e + 1]
            if fl != fr and fsel[fl] and fsel[fr]:
                rl, rr = find(fl), find(fr)
                if rl != rr:
                    parent[rl] = rr
        shells: dict[int, list[int]] = {}
        holes: dict[int, list[list[int]]] = {}
        areas = []
        problems = []
        for ring in rings:
            comp = find(he_face[ring[0]])
            if any(find(he_face[g]) != comp for g in ring):
                problems.append(f"the ring through half-edge {ring[0]} spans two components")
            a2 = self._area2(ring)
            areas.append(a2)
            if a2 > 0:
                if comp in shells:
                    problems.append(f"component of face {comp} has two shells")
                shells[comp] = ring
            elif a2 < 0:
                holes.setdefault(comp, []).append(ring)
            else:
                problems.append(f"the ring through half-edge {ring[0]} has zero area")
        for comp in holes:
            if comp not in shells:
                problems.append(f"component of face {comp} has holes but no shell")
        # the rings partition the boundary half-edges, so their areas add up to the area of
        # the selected faces (interior edges cancel)
        in_rings = [g for ring in rings for g in ring]
        if len(in_rings) != sum(bnd) or len(set(in_rings)) != len(in_rings):
            problems.append(
                f"the rings hold {len(in_rings)} half-edges ({len(set(in_rings))} distinct), "
                f"the boundary has {sum(bnd)}: the area of the selected faces is not kept"
            )
        if problems:
            raise OverlayAssertionError(problems)
        total = _exact_sum(areas, rational(0))
        polys = []
        for comp, shell in shells.items():
            rs = [self._ring_coords(shell)]
            rs += [self._ring_coords(r) for r in holes.get(comp, ())]
            polys.append(Polygon(rs))
        return polys, total

    def _ring_coords(self, ring: list[int]) -> tuple[tuple[Any, Any], ...]:
        """Closed ring coordinates, collinear vertices removed except at nodes."""
        org, node = self.arr.he_origin, self.node
        pts = []
        n = len(ring)
        for i in range(n):
            g = ring[i]
            v = org[g]
            if not node[v] and self.straight(ring[i - 1], g):
                continue
            pts.append(self.xy(v))
        if len(pts) < 3:
            raise OverlayAssertionError([f"a ring collapsed to {len(pts)} vertices"])
        pts.append(pts[0])
        return tuple(pts)

    # -- linear and puntal parts ---------------------------------------------------------

    def lines(self, fsel: list[bool], esel: list[bool]) -> list[LineString]:
        """Maximal chains of linear-part edges between nodes."""
        arr = self.arr
        he_face = arr.he_face
        line = [
            esel[e] and not fsel[he_face[2 * e]] and not fsel[he_face[2 * e + 1]]
            for e in range(self.E)
        ]
        visited = [False] * self.E
        chains: list[tuple[list[int], bool]] = []
        for v in range(self.V):
            if not self.node[v]:
                continue
            for h in self.out[v]:
                if line[h >> 1] and not visited[h >> 1]:
                    chains.append((self._walk(h, line, visited), False))
        for e in range(self.E):
            if line[e] and not visited[e]:  # a cycle without a node
                chains.append((self._walk(2 * e, line, visited), True))
        return [LineString(self._line_coords(hs, closed)) for hs, closed in chains]

    def _walk(self, h: int, line: list[bool], visited: list[bool]) -> list[int]:
        org, node, out, vsrc = self.arr.he_origin, self.node, self.out, self.vsrc
        start = org[h]
        hs = [h]
        visited[h >> 1] = True
        g = h
        while True:
            w = org[g ^ 1]
            if node[w] or w == start:
                return hs
            o = [x for x in out[w] if x != g ^ 1 and vsrc[x >> 1]]
            if len(o) != 1:
                raise OverlayAssertionError(
                    [f"non-node vertex {w} has visible degree {len(o) + 1}"]
                )
            g2 = o[0]
            e2 = g2 >> 1
            if not line[e2] or visited[e2]:
                raise OverlayAssertionError(
                    [f"a line chain breaks at the non-node vertex {w} (edge {e2})"]
                )
            visited[e2] = True
            hs.append(g2)
            g = g2

    def _line_coords(self, hs: list[int], closed: bool) -> tuple[tuple[Any, Any], ...]:
        org, node = self.arr.he_origin, self.node
        n = len(hs)
        if closed:  # every vertex is a non-node: drop straight ones cyclically
            keep = [i for i in range(n) if not self.straight(hs[i - 1], hs[i])]
            if len(keep) < 2:
                raise OverlayAssertionError(["a closed line chain collapsed"])
            pts = [self.xy(org[hs[i]]) for i in keep]
            return (*pts, pts[0])
        pts = [self.xy(org[hs[0]])]
        for i in range(1, n):
            v = org[hs[i]]
            if node[v] or not self.straight(hs[i - 1], hs[i]):
                pts.append(self.xy(v))
        pts.append(self.xy(org[hs[-1] ^ 1]))
        return tuple(pts)

    def points(self, fsel: list[bool], esel: list[bool], vsel: list[bool]) -> list[Point]:
        """Selected vertices not covered by a selected edge or face."""
        he_face = self.arr.he_face
        pts = []
        for v in range(self.V):
            if not vsel[v]:
                continue
            hs = self.out[v]
            if hs:
                if any(fsel[he_face[h]] or esel[h >> 1] for h in hs):
                    continue
            elif fsel[self.iso_face[v]]:
                continue
            pts.append(Point(self.xy(v)))
        return pts

    # -- results --------------------------------------------------------------------------

    def result(self, op: str, variant: str) -> tuple[Geometry, Any]:
        """The canonical result geometry and its exact area."""
        fsel = [select(op, a, b) for a, b in zip(self.fa, self.fb, strict=True)]
        if fsel and fsel[0]:
            raise OverlayAssertionError(["the unbounded face is selected"])
        polys, area2 = self.polygons(fsel)
        elements: list[Geometry] = list(polys)
        if variant == NON_STRICT:
            esel = [select(op, a, b) for a, b in zip(self.ea, self.eb, strict=True)]
            vsel = [select(op, a, b) for a, b in zip(self.va, self.vb, strict=True)]
            elements += self.lines(fsel, esel)
            elements += self.points(fsel, esel, vsel)
        if elements:
            geom = _assemble(elements)
        else:
            geom = empty_of_dimension(result_dimension(op, self.dim_a, self.dim_b))
        return geom, self.real_area(area2)


def _ring_key(ring: tuple[tuple[Any, Any], ...]) -> tuple:
    return tuple(ring)


def _canonical_ring(ring: tuple[tuple[Any, Any], ...]) -> tuple[tuple[Any, Any], ...]:
    """A closed ring (already oriented) rotated to start at its smallest vertex. The
    vertices of a simple ring are distinct, so the smallest one is unique."""
    pts = ring[:-1]
    k = min(range(len(pts)), key=pts.__getitem__)
    out = pts[k:] + pts[:k]
    return (*out, out[0])


def _assemble(elements: list[Geometry]) -> Geometry:
    """The canonical geometry of the result's parts, exactly as
    :func:`geotruth.io.canonicalize` orders it (rings start at their smallest vertex,
    holes and parts sorted, polygons before lines before points, lines starting at their
    smaller end), without recomputing ring orientations: shells are already
    counter-clockwise and holes clockwise. Coordinates compare exactly (rationals)."""
    polys, lines, points = [], [], []
    for e in elements:
        if isinstance(e, Polygon):
            shell, *holes = (_canonical_ring(r) for r in e.rings)
            polys.append(Polygon((shell, *sorted(holes, key=_ring_key))))
        elif isinstance(e, LineString):
            lines.append(LineString(canonical_line(e.coords)))
        else:
            points.append(e)
    polys.sort(key=lambda p: tuple(_ring_key(r) for r in p.rings))
    lines.sort(key=lambda ln: tuple(ln.coords))
    points.sort(key=lambda pt: pt.coord)
    return build_geometry([*polys, *lines, *points])


# ============================================================================ API


def overlay_arrangement(arr: Arrangement, op: str, variant: str = NON_STRICT) -> Geometry:
    """The canonical result geometry of ``op`` read off a labelled arrangement (for
    callers that already hold one; the typed empty uses ``arr.a``/``arr.b``)."""
    return _Overlay(arr).result(normalize_op(op), normalize_variant(variant))[0]


def _left(budget: Budget, t0: float, phase: str) -> None:
    if budget.max_seconds is None:
        return
    used = time.perf_counter() - t0
    if used > budget.max_seconds:
        raise BudgetExceeded("time", budget.max_seconds, round(used, 3), phase)


def overlay_all(
    a: Geometry,
    b: Geometry,
    *,
    ops: Iterable[str] = OPS,
    variants: Iterable[str] = VARIANTS,
    budget: Budget | None = DEFAULT_BUDGET,
    check: bool = True,
    certify: bool = False,
    strict: bool = False,
    keep_arrangement: bool = False,
) -> dict[str, dict[str, OverlayResult]]:
    """``{op: {variant: OverlayResult}}`` for the requested operations and variants,
    all read off one arrangement of ``(a, b)``.

    ``budget`` bounds the arrangement build (``None``: unlimited) and the wall-clock
    time of the whole call; over budget gives ``"engine_skipped"``. ``check`` runs the
    arrangement's topology and label invariants. ``certify`` runs the independent
    certificate (:mod:`geotruth.overlay_certify`) on every result; a failed certificate
    gives ``"engine_error"``. ``strict=True`` re-raises engine errors and failed
    assertions or certificates. ``keep_arrangement`` keeps the arrangement in each result.

    Raises :class:`~geotruth.arrangement.InvalidInputError` for input outside the
    engine's contract, ``ValueError`` for an unknown operation or variant.
    """
    op_list = list(dict.fromkeys(normalize_op(o) for o in ops))
    var_list = list(dict.fromkeys(normalize_variant(v) for v in variants))
    bud = budget if budget is not None else Budget(None, None, None)
    base = {"type_dim_a": a.dimension, "type_dim_b": b.dimension}

    def fill(status: str, reason: str, stats: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            op: {
                v: OverlayResult(op, v, status, reason=reason, stats=dict(stats), **base)
                for v in var_list
            }
            for op in op_list
        }

    t0 = time.perf_counter()
    stats: dict[str, Any] = {}
    try:
        arr = build_arrangement(a, b, budget=bud, check=check, stats=stats)
        builder = _Overlay(arr)
    except InvalidInputError:
        raise
    except BudgetExceeded as exc:
        return fill(STATUS_SKIPPED, str(exc), stats)
    except MemoryError:
        return fill(STATUS_SKIPPED, "out of memory", stats)
    except Exception as exc:
        if strict:
            raise
        return fill(STATUS_ERROR, f"{type(exc).__name__}: {exc}", stats)

    results: dict[str, dict[str, OverlayResult]] = {}
    for op in op_list:
        results[op] = {}
        for v in var_list:
            t1 = time.perf_counter()
            try:
                _left(bud, t0, f"overlay {op}")
                geom, area = builder.result(op, v)
            except BudgetExceeded as exc:
                res = OverlayResult(op, v, STATUS_SKIPPED, reason=str(exc), stats=stats, **base)
            except MemoryError:
                res = OverlayResult(op, v, STATUS_SKIPPED, reason="out of memory", **base)
            except Exception as exc:
                if strict:
                    raise
                reason = f"{type(exc).__name__}: {exc}"
                res = OverlayResult(op, v, STATUS_ERROR, reason=reason, stats=stats, **base)
            else:
                st = dict(stats)
                st["t_overlay"] = round(time.perf_counter() - t1, 6)
                res = OverlayResult(op, v, STATUS_OK, geom, area, stats=st, **base)
            if keep_arrangement:
                res.arrangement = arr
            results[op][v] = res

    if certify:
        _certify(a, b, results, strict)
    return results


def _certify(
    a: Geometry, b: Geometry, results: dict[str, dict[str, OverlayResult]], strict: bool
) -> None:
    from geotruth.overlay_certify import CertificateError, certify_many

    todo = [r for per_op in results.values() for r in per_op.values() if r.ok]
    if not todo:
        return
    try:
        certs = certify_many(a, b, [(r.op, r.variant, r.geometry) for r in todo])
    except Exception as exc:
        if strict:
            raise
        for r in todo:
            r.status, r.reason = STATUS_ERROR, f"certificate: {type(exc).__name__}: {exc}"
        return
    from geotruth.measures import area as shoelace_area

    for r, cert in zip(todo, certs, strict=True):
        r.certificate = cert
        if not cert.ok:
            if strict:
                raise CertificateError(cert)
            r.status = STATUS_ERROR
            r.reason = f"certificate failed: {cert.summary()}"
        # the certificate checks the point set, not the reported area; output polygons never
        # overlap, so the shoelace area of the result must equal it exactly
        elif shoelace_area(r.geometry) != r.area:
            if strict:
                raise CertificateError(cert)
            r.status = STATUS_ERROR
            r.reason = "certificate: area differs from the shoelace area of the result"


def overlay(
    a: Geometry,
    b: Geometry,
    op: str,
    variant: str = NON_STRICT,
    *,
    budget: Budget | None = DEFAULT_BUDGET,
    check: bool = True,
    certify: bool = False,
    strict: bool = False,
    keep_arrangement: bool = False,
) -> OverlayResult:
    """The exact result of ``op`` (``"intersection"``, ``"union"``, ``"difference"``,
    ``"symdifference"``) on ``(a, b)`` in the given variant (``"non_strict"``, the
    default, or ``"areal"``). See :func:`overlay_all` for the keyword arguments."""
    op, variant = normalize_op(op), normalize_variant(variant)
    res = overlay_all(
        a,
        b,
        ops=(op,),
        variants=(variant,),
        budget=budget,
        check=check,
        certify=certify,
        strict=strict,
        keep_arrangement=keep_arrangement,
    )
    return res[op][variant]
