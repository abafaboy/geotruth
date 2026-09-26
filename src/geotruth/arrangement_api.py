"""The FROZEN interface of the planar arrangement of two geometries (DESIGN §2.2).

The arrangement (``arrangement.py``, built in Phase 1) nodes the segments of operands A
and B, merges coincident sub-segments, and stores the resulting planar subdivision as a
doubly connected edge list (DCEL) in parallel integer arrays. Relate (§2.3), overlay
(§2.5) and every consumer read it only through this module; changes go through the
Phase 0 owner.

Coordinates
-----------
Vertex coordinates are exact, in the case's *scaled* integer space
(:class:`geotruth.numbers.DyadicScale`): vertex ``v`` is the canonical homogeneous
point ``(vx[v], vy[v], vw[v])`` (``vw > 0``, ``gcd == 1``, see :mod:`geotruth.exact`),
i.e. the real point ``(vx/vw, vy/vw) * 2**scale_exp``. Input vertices have ``vw == 1``;
intersection points may not.

Cells and ids
-------------
- **Vertices** ``0 .. V-1`` (0-cells). A vertex with no incident edge is *isolated*
  (``vertex_edge[v] == -1``) and is listed in exactly one face's ``face_isolated``.
- **Edges** ``0 .. E-1`` (1-cells, open segments between two distinct vertices). Edge
  ``e`` consists of the half-edges ``2e`` and ``2e + 1``; ``he_twin[h] == h ^ 1``
  always. The *primary* half-edge ``2e`` is the direction that ``edge_sources[e]`` is
  relative to.
- **Faces** ``0 .. F-1`` (2-cells, open connected regions). Face ``0`` is the unbounded
  face and always exists, even with no edges at all (so EE = 2 always).

Half-edge conventions
---------------------
Every half-edge ``h`` runs from ``he_origin[h]`` to ``dest(h) == he_origin[h ^ 1]``,
and its incident face ``he_face[h]`` lies to its **left**. ``he_next[h]`` is the next
half-edge along the boundary of that face (starting at ``dest(h)``), ``he_prev`` is the
inverse permutation. Consequently the outer boundary of a bounded face is a
counter-clockwise cycle, and every inner boundary component (a hole in the face, i.e.
the outside of a nested connected component) is a clockwise cycle (or a cycle of zero
area when the component is a tree).

Around a vertex, ``he_next[he_twin[g]]`` is the clockwise successor of the outgoing
half-edge ``g`` and ``he_twin[he_prev[g]]`` its counter-clockwise successor. At a
*degree-1* vertex (the free end of a dangling edge) the single outgoing half-edge ``g``
satisfies ``he_next[he_twin[g]] == g``: the boundary walk turns around ("next = twin").

Faces store one half-edge per boundary component: ``face_outer[f]`` (``-1`` only for
face 0) and ``face_inner[f]`` (one half-edge per inner component, e.g. the islands of an
annulus face and every component lying in the unbounded face).

Sources and labels
------------------
``edge_sources[e]`` is the tuple of :class:`EdgeSource` -- one per input segment
covering the edge -- after coincident sub-segments were merged. ``forward`` says
whether half-edge ``2e`` has the direction of the ring/line traversal; half-edge
``2e + 1`` sees it negated (:meth:`Arrangement.sources`). A tag may appear more than
once (a valid LineString may retrace itself, possibly in the opposite direction), so
consumers must not assume uniqueness; :meth:`Arrangement.tags` gives the set.
``ring_orientation[tag]`` is the exact orientation (+1 counter-clockwise, -1 clockwise)
of every input ring appearing in a tag, which gives the areal side of an edge without
any sample point (:meth:`Arrangement.interior_is_left`). Arrangements are built for
valid polygonal elements, whose rings have non-zero area.

Every cell carries its location in A and in B (:class:`Location`: I, B, E; ``NONE``
until labelled) in ``vertex_loc_a/b``, ``edge_loc_a/b`` and ``face_loc_a/b``, computed
with the point-location rules of DESIGN §1. The DE-9IM entry ``M[a][b]`` is the maximum
cell dimension over cells labelled ``(a, b)`` (:meth:`Arrangement.cells`).

Invariants (checked by :meth:`Arrangement.validate`)
----------------------------------------------------
Topology (always checked):

- T1 array lengths agree: V vertex entries, 2E half-edge entries, E edge entries,
  F >= 1 face entries; all indices are in range.
- T2 vertices are canonical (``vw > 0``, ``gcd(vx, vy, vw) == 1``) and pairwise distinct.
- T3 ``he_twin[h] == h ^ 1``; ``he_origin[h] != he_origin[h ^ 1]`` (no loops); no two
  edges join the same pair of vertices (coincident sub-segments are merged).
- T4 ``he_prev[he_next[h]] == h`` and ``he_next[he_prev[h]] == h``.
- T5 ``he_origin[he_next[h]] == dest(h)``, ``he_face[he_next[h]] == he_face[h]``.
- T6 ``vertex_edge[v]`` is -1 exactly for isolated vertices, otherwise an outgoing
  half-edge of ``v``; the counter-clockwise rotation from it visits every outgoing
  half-edge of ``v`` exactly once (degree-1: ``he_next[he_twin[g]] == g``).
- T7 ``face_outer[0] == -1``; ``face_outer[f] >= 0`` for ``f >= 1``; every listed
  half-edge has ``he_face`` equal to its face; every boundary cycle is listed exactly
  once (as an outer or an inner component).
- T8 Euler, per connected component ``c`` with edges: ``V_c - E_c + C_c == 2`` where
  ``C_c`` counts its boundary cycles, and exactly one of those cycles is listed as an
  inner component. Hence globally ``V - E + F == 1 + (number of components)``, counting
  every isolated vertex as a component.
- T9 isolated vertices are listed in exactly one ``face_isolated``; others in none.
- T10 every ring tag in ``edge_sources`` has ``ring_orientation`` +1 or -1; when the
  operands are attached, every tag names an existing ring or line element.

Geometry (``geometry=True``; exact):

- G1 outer cycles have positive signed area, inner cycles non-positive.
- G2 the rotation at every vertex is strictly counter-clockwise sorted by angle.
- G3 every inner component and isolated vertex of face ``f`` lies strictly inside
  ``f``'s outer cycle (``f >= 1``) and outside the other inner components of ``f``.
- G4 (``planarity=True``, O(E^2)) edges meet only at common endpoints; no vertex lies
  in the relative interior of an edge.

Labels (``labels=True``):

- L1 every cell is labelled I, B or E; faces are never B; face 0 is (E, E).
- L2 for each operand X: an edge with no source from X has the X label of both
  adjacent faces, and it is I or E; an edge with an X source is I or B; the two faces
  of an edge whose X sources are all lines have the same X label.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from enum import IntEnum
from fractions import Fraction
from itertools import islice
from math import gcd
from typing import NamedTuple

from geotruth.exact import (
    INSIDE,
    OUTSIDE,
    HPoint,
    angle_cmp,
    hp_direction,
    hp_orient,
    hpoint,
    point_in_ring,
    signed_area2,
)
from geotruth.geom import GEOM_A, GEOM_B, Geometry, LineString, Polygon, SourceTag

__all__ = [
    "Arrangement",
    "ArrangementError",
    "Cell",
    "EdgeSource",
    "Location",
]


class Location(IntEnum):
    """Location of a cell relative to one operand (values as JTS ``Location``).

    The integer values double as DE-9IM row/column indices (I = 0, B = 1, E = 2).
    """

    INTERIOR = 0
    BOUNDARY = 1
    EXTERIOR = 2
    NONE = -1

    @property
    def char(self) -> str:
        """``"I"``, ``"B"``, ``"E"`` or ``"-"`` (unlabelled)."""
        return "IBE"[self] if self >= 0 else "-"

    @classmethod
    def from_char(cls, c: str) -> Location:
        """Inverse of :attr:`char`."""
        try:
            return {"I": cls.INTERIOR, "B": cls.BOUNDARY, "E": cls.EXTERIOR, "-": cls.NONE}[c]
        except KeyError:
            raise ValueError(f"not a location character: {c!r}") from None

    def __str__(self) -> str:
        return self.char


class EdgeSource(NamedTuple):
    """One input ring or line an edge lies on.

    ``forward`` is relative to the edge's primary half-edge ``2e``: True when ``2e``
    runs in the direction of the ring/line traversal.
    """

    tag: SourceTag
    forward: bool


class Cell(NamedTuple):
    """A labelled cell: dimension (0 vertex, 1 edge, 2 face), id, and its locations."""

    dim: int
    index: int
    loc_a: Location
    loc_b: Location


class ArrangementError(ValueError):
    """An arrangement violates an invariant; ``problems`` lists what was found."""

    def __init__(self, problems: Sequence[str]) -> None:
        self.problems = list(problems)
        head = "; ".join(self.problems[:5])
        more = f" (+{len(self.problems) - 5} more)" if len(self.problems) > 5 else ""
        super().__init__(f"invalid arrangement: {head}{more}")


_NONE = int(Location.NONE)


@dataclass(eq=False)
class Arrangement:
    """A planar subdivision (DCEL) of two operands, in parallel arrays.

    Build one with :meth:`new` and the ``add_*`` helpers (they keep the arrays in
    step); ``he_next``, ``he_prev`` and ``he_face`` and the face records are then
    filled in by the builder. The arrays are lists, but a builder may substitute
    ``array.array('q')`` for the integer ones to save memory, so consumers should only
    index, iterate and take ``len``.
    """

    #: Real coordinates are scaled coordinates times ``2**scale_exp``.
    scale_exp: int = 0
    #: The operands the arrangement was built from (optional, for checks and labelling).
    a: Geometry | None = None
    b: Geometry | None = None

    # vertices
    vx: list[int] = field(default_factory=list)
    vy: list[int] = field(default_factory=list)
    vw: list[int] = field(default_factory=list)
    vertex_edge: list[int] = field(default_factory=list)
    vertex_loc_a: list[int] = field(default_factory=list)
    vertex_loc_b: list[int] = field(default_factory=list)

    # half-edges (2 per edge)
    he_origin: list[int] = field(default_factory=list)
    he_twin: list[int] = field(default_factory=list)
    he_next: list[int] = field(default_factory=list)
    he_prev: list[int] = field(default_factory=list)
    he_face: list[int] = field(default_factory=list)

    # edges
    edge_sources: list[tuple[EdgeSource, ...]] = field(default_factory=list)
    edge_loc_a: list[int] = field(default_factory=list)
    edge_loc_b: list[int] = field(default_factory=list)

    # faces (face 0 = unbounded)
    face_outer: list[int] = field(default_factory=list)
    face_inner: list[list[int]] = field(default_factory=list)
    face_isolated: list[list[int]] = field(default_factory=list)
    face_loc_a: list[int] = field(default_factory=list)
    face_loc_b: list[int] = field(default_factory=list)

    #: Exact orientation (+1 CCW, -1 CW) of every input ring named by an edge source.
    ring_orientation: dict[SourceTag, int] = field(default_factory=dict)

    # ------------------------------------------------------------------ construction

    @classmethod
    def new(
        cls, scale_exp: int = 0, a: Geometry | None = None, b: Geometry | None = None
    ) -> Arrangement:
        """An arrangement with no vertices or edges and the unbounded face 0, which is
        labelled (E, E) -- bounded operands never reach it."""
        arr = cls(scale_exp=scale_exp, a=a, b=b)
        f = arr.add_face()
        arr.set_label(2, f, Location.EXTERIOR, Location.EXTERIOR)
        return arr

    def add_vertex(self, x: int, y: int, w: int = 1) -> int:
        """Append a vertex (canonicalised) and return its id. No deduplication."""
        x, y, w = hpoint(x, y, w)
        self.vx.append(x)
        self.vy.append(y)
        self.vw.append(w)
        self.vertex_edge.append(-1)
        self.vertex_loc_a.append(_NONE)
        self.vertex_loc_b.append(_NONE)
        return len(self.vx) - 1

    def add_edge(self, u: int, v: int, sources: Sequence[EdgeSource] = ()) -> int:
        """Append edge ``u -> v`` (half-edges ``2e``: u->v and ``2e+1``: v->u).

        ``next``, ``prev`` and ``face`` are set to -1 for the builder to fill in.
        ``vertex_edge`` of ``u`` and ``v`` is set if it was -1. Returns ``e``.
        """
        e = len(self.edge_sources)
        h = 2 * e
        self.he_origin += [u, v]
        self.he_twin += [h + 1, h]
        self.he_next += [-1, -1]
        self.he_prev += [-1, -1]
        self.he_face += [-1, -1]
        self.edge_sources.append(tuple(sources))
        self.edge_loc_a.append(_NONE)
        self.edge_loc_b.append(_NONE)
        if self.vertex_edge[u] == -1:
            self.vertex_edge[u] = h
        if self.vertex_edge[v] == -1:
            self.vertex_edge[v] = h + 1
        return e

    def add_face(self, outer: int = -1) -> int:
        """Append a face with the given outer half-edge; return its id."""
        self.face_outer.append(outer)
        self.face_inner.append([])
        self.face_isolated.append([])
        self.face_loc_a.append(_NONE)
        self.face_loc_b.append(_NONE)
        return len(self.face_outer) - 1

    # ------------------------------------------------------------------------ sizes

    @property
    def num_vertices(self) -> int:
        return len(self.vx)

    @property
    def num_edges(self) -> int:
        return len(self.edge_sources)

    @property
    def num_half_edges(self) -> int:
        return len(self.he_origin)

    @property
    def num_faces(self) -> int:
        return len(self.face_outer)

    # ------------------------------------------------------------------- navigation

    def vertex(self, v: int) -> HPoint:
        """Canonical homogeneous coordinates of vertex ``v`` (scaled space)."""
        return self.vx[v], self.vy[v], self.vw[v]

    def vertex_fractions(self, v: int) -> tuple[Fraction, Fraction]:
        """Real coordinates of vertex ``v`` (scale applied) as Fractions."""
        e = self.scale_exp
        num_x, num_y, den = self.vx[v], self.vy[v], self.vw[v]
        if e >= 0:
            return Fraction(num_x << e, den), Fraction(num_y << e, den)
        return Fraction(num_x, den << -e), Fraction(num_y, den << -e)

    def dest(self, h: int) -> int:
        """Destination vertex of half-edge ``h``."""
        return self.he_origin[h ^ 1]

    @staticmethod
    def edge_of(h: int) -> int:
        """The edge a half-edge belongs to."""
        return h >> 1

    def sources(self, h: int) -> tuple[EdgeSource, ...]:
        """Edge sources as seen from half-edge ``h`` (``forward`` relative to ``h``)."""
        srcs = self.edge_sources[h >> 1]
        if h & 1:
            return tuple(EdgeSource(s.tag, not s.forward) for s in srcs)
        return srcs

    def tags(self, e: int) -> frozenset[SourceTag]:
        """The set of input rings/lines edge ``e`` lies on."""
        return frozenset(s.tag for s in self.edge_sources[e])

    def interior_is_left(self, h: int, source: EdgeSource) -> bool:
        """For a *ring* source as seen from half-edge ``h`` (see :meth:`sources`): True if
        the polygon element's interior lies to the left of ``h``.

        Interior is left of the traversal of a counter-clockwise shell or a clockwise
        hole, and right of a clockwise shell or a counter-clockwise hole.
        """
        tag = source.tag
        if tag.is_line:
            raise ValueError("a line has no interior side")
        left_of_traversal = (self.ring_orientation[tag] > 0) != tag.is_hole
        return left_of_traversal == source.forward

    def cycle(self, h: int) -> Iterator[int]:
        """The half-edges of the boundary cycle through ``h`` (following ``he_next``)."""
        g = h
        while True:
            yield g
            g = self.he_next[g]
            if g == h:
                return

    def outgoing(self, v: int) -> Iterator[int]:
        """Outgoing half-edges of ``v`` in counter-clockwise order (none if isolated)."""
        start = self.vertex_edge[v]
        if start < 0:
            return
        g = start
        while True:
            yield g
            g = self.he_twin[self.he_prev[g]]
            if g == start:
                return

    def degree(self, v: int) -> int:
        return sum(1 for _ in self.outgoing(v))

    def is_isolated(self, v: int) -> bool:
        return self.vertex_edge[v] < 0

    def boundary_components(self, f: int) -> list[int]:
        """One half-edge per boundary cycle of face ``f``: the outer one first."""
        out = [] if self.face_outer[f] < 0 else [self.face_outer[f]]
        return out + list(self.face_inner[f])

    def face_half_edges(self, f: int) -> Iterator[int]:
        """Every half-edge whose left face is ``f``."""
        for h in self.boundary_components(f):
            yield from self.cycle(h)

    # ------------------------------------------------------------------------ cells

    def vertex_cells(self) -> Iterator[Cell]:
        L = Location
        for v in range(self.num_vertices):
            yield Cell(0, v, L(self.vertex_loc_a[v]), L(self.vertex_loc_b[v]))

    def edge_cells(self) -> Iterator[Cell]:
        L = Location
        for e in range(self.num_edges):
            yield Cell(1, e, L(self.edge_loc_a[e]), L(self.edge_loc_b[e]))

    def face_cells(self) -> Iterator[Cell]:
        L = Location
        for f in range(self.num_faces):
            yield Cell(2, f, L(self.face_loc_a[f]), L(self.face_loc_b[f]))

    def cells(self) -> Iterator[Cell]:
        """Every cell with its dimension and labels: vertices, then edges, then faces."""
        yield from self.vertex_cells()
        yield from self.edge_cells()
        yield from self.face_cells()

    def set_label(self, dim: int, index: int, loc_a: int, loc_b: int) -> None:
        """Set the (A, B) locations of a cell of dimension ``dim``."""
        arr_a, arr_b = {
            0: (self.vertex_loc_a, self.vertex_loc_b),
            1: (self.edge_loc_a, self.edge_loc_b),
            2: (self.face_loc_a, self.face_loc_b),
        }[dim]
        arr_a[index] = int(loc_a)
        arr_b[index] = int(loc_b)

    # --------------------------------------------------------------------- display

    def dump(self) -> str:
        """A human-readable listing of every cell (for debugging and test failures).

        Safe on corrupted arrangements: it neither raises on bad labels nor loops on
        broken pointers.
        """

        def lab(a: int, b: int) -> str:
            return "".join(Location(x).char if x in (-1, 0, 1, 2) else "?" for x in (a, b))

        lines = [
            f"Arrangement V={self.num_vertices} E={self.num_edges} F={self.num_faces} "
            f"scale=2**{self.scale_exp}"
        ]
        for v in range(self.num_vertices):
            x, y, w = self.vertex(v)
            pt = f"({x}, {y})" if w == 1 else f"({x}/{w}, {y}/{w})"
            try:
                out = list(islice(self.outgoing(v), self.num_half_edges + 1))
            except (IndexError, TypeError):
                out = ["?"]
            lines.append(f"  v{v} {pt} {lab(self.vertex_loc_a[v], self.vertex_loc_b[v])} out={out}")
        for e in range(self.num_edges):
            h = 2 * e
            srcs = ",".join(f"{s.tag}{'+' if s.forward else '-'}" for s in self.edge_sources[e])
            lines.append(
                f"  e{e} v{self.he_origin[h]}->v{self.he_origin[h + 1]} "
                f"{lab(self.edge_loc_a[e], self.edge_loc_b[e])} [{srcs}] "
                f"h{h}: next={self.he_next[h]} face={self.he_face[h]}; "
                f"h{h + 1}: next={self.he_next[h + 1]} face={self.he_face[h + 1]}"
            )
        for f in range(self.num_faces):
            lines.append(
                f"  f{f} {lab(self.face_loc_a[f], self.face_loc_b[f])} "
                f"outer={self.face_outer[f]} inner={self.face_inner[f]} "
                f"isolated={self.face_isolated[f]}"
            )
        return "\n".join(lines)

    # -------------------------------------------------------------------- validation

    def validate(
        self, *, geometry: bool = True, planarity: bool = False, labels: bool = True
    ) -> None:
        """Check the invariants listed in the module docstring.

        Topology (T1-T10) is always checked, in O(V + E) apart from the tag checks.
        ``geometry`` adds the exact G1-G3 checks (G3 costs up to
        O(components x cycle length) per face); ``planarity`` adds the O(E^2) G4 check;
        ``labels`` adds L1-L2 (use False before labelling). Raises
        :class:`ArrangementError` listing the problems found.
        """
        _Validator(self).run(geometry=geometry, planarity=planarity, labels=labels)


class _Stop(Exception):
    pass


class _Validator:
    """Implementation of :meth:`Arrangement.validate` (kept out of the data class)."""

    MAX_PROBLEMS = 25

    def __init__(self, arr: Arrangement) -> None:
        self.arr = arr
        self.problems: list[str] = []

    def bad(self, msg: str) -> None:
        self.problems.append(msg)
        if len(self.problems) >= self.MAX_PROBLEMS:
            raise _Stop

    def run(self, *, geometry: bool, planarity: bool, labels: bool) -> None:
        try:
            if self.lengths() and self.topology():
                if geometry:
                    self.geometry()
                if planarity:
                    self.planarity()
                if labels:
                    self.labels()
        except _Stop:
            pass
        if self.problems:
            raise ArrangementError(self.problems)

    # -- T1 ------------------------------------------------------------------------

    def lengths(self) -> bool:
        a = self.arr
        V, H, E, F = len(a.vx), len(a.he_origin), len(a.edge_sources), len(a.face_outer)
        for name, n in (
            ("vy", V),
            ("vw", V),
            ("vertex_edge", V),
            ("vertex_loc_a", V),
            ("vertex_loc_b", V),
            ("he_twin", H),
            ("he_next", H),
            ("he_prev", H),
            ("he_face", H),
            ("edge_loc_a", E),
            ("edge_loc_b", E),
            ("face_inner", F),
            ("face_isolated", F),
            ("face_loc_a", F),
            ("face_loc_b", F),
        ):
            if len(getattr(a, name)) != n:
                self.bad(f"T1: len({name}) = {len(getattr(a, name))}, expected {n}")
        if H != 2 * E:
            self.bad(f"T1: {H} half-edges for {E} edges")
        if F < 1:
            self.bad("T1: face 0 (unbounded) is missing")
        if self.problems:
            return False
        for name, arr, hi in (
            ("he_origin", a.he_origin, V),
            ("he_twin", a.he_twin, H),
            ("he_next", a.he_next, H),
            ("he_prev", a.he_prev, H),
            ("he_face", a.he_face, F),
        ):
            for h, x in enumerate(arr):
                if not 0 <= x < hi:
                    self.bad(f"T1: {name}[{h}] = {x} out of range [0, {hi})")
        for v, h in enumerate(a.vertex_edge):
            if not -1 <= h < H:
                self.bad(f"T1: vertex_edge[{v}] = {h} out of range")
        for f in range(F):
            for h in ([a.face_outer[f]] if a.face_outer[f] != -1 else []) + a.face_inner[f]:
                if not 0 <= h < H:
                    self.bad(f"T1: face {f} lists half-edge {h} out of range")
            for v in a.face_isolated[f]:
                if not 0 <= v < V:
                    self.bad(f"T1: face {f} lists isolated vertex {v} out of range")
        return not self.problems

    # -- T2-T10 --------------------------------------------------------------------

    def topology(self) -> bool:
        a = self.arr
        V, H, F = a.num_vertices, a.num_half_edges, a.num_faces
        seen: dict[HPoint, int] = {}
        for v in range(V):
            x, y, w = a.vertex(v)
            if w <= 0 or gcd(x, y, w) != 1:
                self.bad(f"T2: vertex {v} = {(x, y, w)} is not canonical")
            if (x, y, w) in seen:
                self.bad(f"T2: vertices {seen[(x, y, w)]} and {v} coincide")
            seen[(x, y, w)] = v
        pairs: dict[tuple[int, int], int] = {}
        nxt, prv, org, face = a.he_next, a.he_prev, a.he_origin, a.he_face
        for h in range(H):
            if a.he_twin[h] != h ^ 1:
                self.bad(f"T3: he_twin[{h}] = {a.he_twin[h]}, expected {h ^ 1}")
        for e in range(a.num_edges):
            u, v = org[2 * e], org[2 * e + 1]
            if u == v:
                self.bad(f"T3: edge {e} is a loop at vertex {u}")
            key = (min(u, v), max(u, v))
            if key in pairs:
                self.bad(f"T3: edges {pairs[key]} and {e} both join vertices {key}")
            pairs[key] = e
        for h in range(H):
            if prv[nxt[h]] != h:
                self.bad(f"T4: he_prev[he_next[{h}]] = {prv[nxt[h]]}, expected {h}")
            if nxt[prv[h]] != h:
                self.bad(f"T4: he_next[he_prev[{h}]] = {nxt[prv[h]]}, expected {h}")
            if org[nxt[h]] != org[h ^ 1]:
                self.bad(
                    f"T5: half-edge {h} ends at {org[h ^ 1]} but next {nxt[h]} "
                    f"starts at {org[nxt[h]]}"
                )
            if face[nxt[h]] != face[h]:
                self.bad(
                    f"T5: half-edges {h} and next {nxt[h]} have faces {face[h]} and {face[nxt[h]]}"
                )
        if self.problems:
            return False

        # T6 rotation systems
        out: list[list[int]] = [[] for _ in range(V)]
        for h in range(H):
            out[org[h]].append(h)
        for v in range(V):
            start = a.vertex_edge[v]
            if not out[v]:
                if start != -1:
                    self.bad(f"T6: isolated vertex {v} has vertex_edge {start}")
                continue
            if start == -1 or org[start] != v:
                self.bad(f"T6: vertex_edge[{v}] = {start} is not an outgoing half-edge")
                continue
            orbit, g = [], start
            for _ in range(len(out[v]) + 1):
                orbit.append(g)
                g = a.he_twin[prv[g]]
                if g == start:
                    break
            if g != start or sorted(orbit) != sorted(out[v]):
                self.bad(f"T6: rotation at vertex {v} visits {orbit}, expected {out[v]}")
        if self.problems:
            return False

        # boundary cycles
        cyc = [-1] * H
        self.cycle_starts: list[int] = []
        for h in range(H):
            if cyc[h] != -1:
                continue
            cid = len(self.cycle_starts)
            self.cycle_starts.append(h)
            g = h
            while cyc[g] == -1:
                cyc[g] = cid
                g = nxt[g]
        self.cyc = cyc

        # T7 face records
        if a.face_outer[0] != -1:
            self.bad(f"T7: the unbounded face 0 has outer half-edge {a.face_outer[0]}")
        listed: dict[int, str] = {}
        self.inner_cycles: set[int] = set()
        for f in range(F):
            if f > 0 and a.face_outer[f] == -1:
                self.bad(f"T7: bounded face {f} has no outer half-edge")
            comps = [(a.face_outer[f], "outer")] if a.face_outer[f] != -1 else []
            comps += [(h, "inner") for h in a.face_inner[f]]
            for h, role in comps:
                if face[h] != f:
                    self.bad(f"T7: face {f} lists {role} half-edge {h} whose face is {face[h]}")
                cid = cyc[h]
                if cid in listed:
                    self.bad(
                        f"T7: cycle of half-edge {h} listed twice ({listed[cid]} and "
                        f"face {f} {role})"
                    )
                listed[cid] = f"face {f} {role}"
                if role == "inner":
                    self.inner_cycles.add(cid)
        for cid, h in enumerate(self.cycle_starts):
            if cid not in listed:
                self.bad(
                    f"T7: the cycle of half-edge {h} (face {face[h]}) is not listed by its face"
                )

        # T8 Euler per component
        parent = list(range(V))

        def find(x: int) -> int:
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        for e in range(a.num_edges):
            ru, rv = find(org[2 * e]), find(org[2 * e + 1])
            if ru != rv:
                parent[ru] = rv
        comp_v: dict[int, int] = {}
        comp_e: dict[int, int] = {}
        comp_c: dict[int, int] = {}
        comp_inner: dict[int, int] = {}
        for v in range(V):
            if out[v]:
                r = find(v)
                comp_v[r] = comp_v.get(r, 0) + 1
        for e in range(a.num_edges):
            r = find(org[2 * e])
            comp_e[r] = comp_e.get(r, 0) + 1
        for cid, h in enumerate(self.cycle_starts):
            r = find(org[h])
            comp_c[r] = comp_c.get(r, 0) + 1
            if cid in self.inner_cycles:
                comp_inner[r] = comp_inner.get(r, 0) + 1
        self.component_of = find
        for r in comp_v:
            chi = comp_v[r] - comp_e.get(r, 0) + comp_c.get(r, 0)
            if chi != 2:
                self.bad(
                    f"T8: component of vertex {r}: V - E + cycles = {comp_v[r]} - "
                    f"{comp_e.get(r, 0)} + {comp_c.get(r, 0)} = {chi}, expected 2"
                )
            if comp_inner.get(r, 0) != 1:
                self.bad(
                    f"T8: component of vertex {r} is listed as an inner component "
                    f"{comp_inner.get(r, 0)} times, expected once"
                )

        # T9 isolated vertices
        where: dict[int, int] = {}
        for f in range(F):
            for v in a.face_isolated[f]:
                if out[v]:
                    self.bad(f"T9: face {f} lists vertex {v} as isolated but it has edges")
                if v in where:
                    self.bad(f"T9: isolated vertex {v} listed by faces {where[v]} and {f}")
                where[v] = f
        for v in range(V):
            if not out[v] and v not in where:
                self.bad(f"T9: isolated vertex {v} is not listed by any face")

        # T10 sources
        self.check_sources()
        return not self.problems

    def check_sources(self) -> None:
        a = self.arr
        elements = {
            GEOM_A: None if a.a is None else list(a.a.elements()),
            GEOM_B: None if a.b is None else list(a.b.elements()),
        }
        for e, srcs in enumerate(a.edge_sources):
            for s in srcs:
                if not isinstance(s, EdgeSource):
                    self.bad(f"T10: edge {e} has a source that is not an EdgeSource: {s!r}")
                    continue
                t = s.tag
                if t.geom not in (GEOM_A, GEOM_B):
                    self.bad(f"T10: edge {e} source {t} names operand {t.geom}")
                    continue
                if t.is_ring and a.ring_orientation.get(t) not in (1, -1):
                    self.bad(f"T10: ring {t} of edge {e} has no orientation")
                els = elements[t.geom]
                if els is None:
                    continue
                if not 0 <= t.element < len(els):
                    self.bad(f"T10: edge {e} source {t} names a missing element")
                    continue
                el = els[t.element]
                if t.is_line and not isinstance(el, LineString):
                    self.bad(f"T10: edge {e} source {t} is not a line element")
                if t.is_ring and not (isinstance(el, Polygon) and t.ring < len(el.rings)):
                    self.bad(f"T10: edge {e} source {t} is not a polygon ring")
                if t.is_ring and t.is_hole != (t.ring >= 1):
                    self.bad(f"T10: edge {e} source {t} has an inconsistent hole flag")

    # -- G1-G3 ---------------------------------------------------------------------

    def cycle_points(self, h: int) -> list[tuple]:
        a = self.arr
        pts = []
        for g in a.cycle(h):
            x, y, w = a.vertex(a.he_origin[g])
            pts.append((x, y) if w == 1 else (Fraction(x, w), Fraction(y, w)))
        return pts

    def point(self, v: int) -> tuple:
        x, y, w = self.arr.vertex(v)
        return (x, y) if w == 1 else (Fraction(x, w), Fraction(y, w))

    def geometry(self) -> None:
        a = self.arr
        rings = {cid: self.cycle_points(h) for cid, h in enumerate(self.cycle_starts)}
        # G1
        for cid, h in enumerate(self.cycle_starts):
            area2 = signed_area2(rings[cid])
            if cid in self.inner_cycles:
                if area2 > 0:
                    self.bad(
                        f"G1: inner cycle of half-edge {h} (face {a.he_face[h]}) is "
                        f"counter-clockwise (2*area = {area2})"
                    )
            elif area2 <= 0:
                self.bad(
                    f"G1: outer cycle of half-edge {h} (face {a.he_face[h]}) has "
                    f"2*area = {area2}, expected > 0"
                )
        # G2
        for v in range(a.num_vertices):
            rot = list(a.outgoing(v))
            if len(rot) < 2:
                continue
            p = a.vertex(v)
            dirs = [hp_direction(p, a.vertex(a.dest(g))) for g in rot]
            descents = 0
            for i in range(len(dirs)):
                c = angle_cmp(dirs[i], dirs[(i + 1) % len(dirs)])
                if c == 0:
                    self.bad(
                        f"G2: half-edges {rot[i]} and {rot[(i + 1) % len(rot)]} leave "
                        f"vertex {v} in the same direction"
                    )
                descents += c > 0
            if descents != 1:
                self.bad(f"G2: rotation {rot} at vertex {v} is not counter-clockwise sorted")
        # G3
        for f in range(a.num_faces):
            inner = list(a.face_inner[f])
            probes = [
                (f"inner component of half-edge {h}", self.cyc[h], self.point(a.he_origin[h]))
                for h in inner
            ]
            probes += [(f"isolated vertex {v}", None, self.point(v)) for v in a.face_isolated[f]]
            outer_ring = rings[self.cyc[a.face_outer[f]]] if a.face_outer[f] >= 0 else None
            for what, own, p in probes:
                if outer_ring is not None and point_in_ring(p, outer_ring) != INSIDE:
                    self.bad(f"G3: {what} of face {f} is not inside the face's outer boundary")
                for h in inner:
                    cid = self.cyc[h]
                    if cid != own and point_in_ring(p, rings[cid]) != OUTSIDE:
                        self.bad(
                            f"G3: {what} of face {f} lies inside or on the inner "
                            f"component of half-edge {h}"
                        )

    # -- G4 ------------------------------------------------------------------------

    def planarity(self) -> None:
        a = self.arr
        E = a.num_edges
        segs = [(a.vertex(a.he_origin[2 * e]), a.vertex(a.he_origin[2 * e + 1])) for e in range(E)]
        for i in range(E):
            p, q = segs[i]
            for j in range(i + 1, E):
                r, s = segs[j]
                if _segments_improperly_meet(p, q, r, s):
                    self.bad(f"G4: edges {i} and {j} intersect other than at a shared endpoint")
            for v in range(a.num_vertices):
                pt = a.vertex(v)
                if pt != p and pt != q and _hp_in_open_segment(pt, p, q):
                    self.bad(f"G4: vertex {v} lies in the interior of edge {i}")

    # -- L1-L2 ---------------------------------------------------------------------

    def labels(self) -> None:
        a = self.arr
        valid = (0, 1, 2)
        for dim, name, la, lb in (
            (0, "vertex", a.vertex_loc_a, a.vertex_loc_b),
            (1, "edge", a.edge_loc_a, a.edge_loc_b),
            (2, "face", a.face_loc_a, a.face_loc_b),
        ):
            for i in range(len(la)):
                if la[i] not in valid or lb[i] not in valid:
                    self.bad(f"L1: {name} {i} is not labelled: ({la[i]}, {lb[i]})")
                elif dim == 2 and (la[i] == Location.BOUNDARY or lb[i] == Location.BOUNDARY):
                    self.bad(f"L1: face {i} is labelled Boundary")
        if self.problems:
            return
        if (a.face_loc_a[0], a.face_loc_b[0]) != (Location.EXTERIOR, Location.EXTERIOR):
            self.bad("L1: the unbounded face is not (E, E)")
        for e in range(a.num_edges):
            fl, fr = a.he_face[2 * e], a.he_face[2 * e + 1]
            for g, name, el, fls in (
                (GEOM_A, "A", a.edge_loc_a, a.face_loc_a),
                (GEOM_B, "B", a.edge_loc_b, a.face_loc_b),
            ):
                srcs = [s for s in a.edge_sources[e] if s.tag.geom == g]
                loc = el[e]
                if not srcs:
                    if loc == Location.BOUNDARY:
                        self.bad(f"L2: edge {e} has no {name} source but is {name}-Boundary")
                    elif not loc == fls[fl] == fls[fr]:
                        self.bad(
                            f"L2: edge {e} ({Location(loc).char}) lies in a single {name} "
                            f"region but its faces are {Location(fls[fl]).char}, "
                            f"{Location(fls[fr]).char}"
                        )
                else:
                    if loc == Location.EXTERIOR:
                        self.bad(f"L2: edge {e} lies on {name} but is {name}-Exterior")
                    if all(s.tag.is_line for s in srcs) and fls[fl] != fls[fr]:
                        self.bad(
                            f"L2: edge {e} lies only on {name} lines but its faces differ in {name}"
                        )


def _hp_in_open_segment(p: HPoint, a: HPoint, b: HPoint) -> bool:
    """True if ``p`` lies on segment ``ab`` strictly between its endpoints."""
    if hp_orient(a, b, p) != 0:
        return False
    # compare projections on the direction a -> b, scaled by positive weights
    ux, uy = hp_direction(a, b)
    ap = hp_direction(a, p)  # positive multiple of p - a
    pb = hp_direction(p, b)  # positive multiple of b - p
    return ux * ap[0] + uy * ap[1] > 0 and ux * pb[0] + uy * pb[1] > 0


def _segments_improperly_meet(p: HPoint, q: HPoint, r: HPoint, s: HPoint) -> bool:
    """True if closed segments pq and rs share a point that is not a common endpoint."""
    shared = {p, q} & {r, s}
    o1, o2 = hp_orient(p, q, r), hp_orient(p, q, s)
    o3, o4 = hp_orient(r, s, p), hp_orient(r, s, q)
    if o1 == o2 == 0:  # collinear: overlapping beyond a shared endpoint?
        return (
            _hp_in_open_segment(r, p, q)
            or _hp_in_open_segment(s, p, q)
            or _hp_in_open_segment(p, r, s)
            or _hp_in_open_segment(q, r, s)
            or ({p, q} == {r, s})
        )
    if o1 * o2 < 0 and o3 * o4 < 0:
        return True  # proper crossing
    # touching: an endpoint of one in the other's interior (endpoints on endpoints
    # are either shared, which is fine, or distinct vertices, which cannot touch)
    return bool(
        (o1 == 0 and r not in shared and _hp_in_open_segment(r, p, q))
        or (o2 == 0 and s not in shared and _hp_in_open_segment(s, p, q))
        or (o3 == 0 and p not in shared and _hp_in_open_segment(p, r, s))
        or (o4 == 0 and q not in shared and _hp_in_open_segment(q, r, s))
    )
