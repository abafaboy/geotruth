"""Hand-built arrangement fixtures for the frozen Arrangement API.

Each fixture is a small planar subdivision of two operands, written out by hand: the
already-noded vertices, the edges with their source tags, and the (A, B) location of
every vertex, edge and face. Relate and overlay (Phase 1, E2) are developed against these
before the real arrangement (E1) exists, and the real arrangement must reproduce them.

A fixture names each face by a *witness* point strictly inside it, never by a sample
point computed from the face's outer boundary: the annulus of ``nested_squares`` is the
classic trap where the centroid of the outer cycle falls inside the island.

:func:`build` turns a :class:`FixtureSpec` into an :class:`Arrangement`: it sorts the
outgoing half-edges of each vertex by exact angle, links ``next``/``prev``, walks the
boundary cycles, makes one bounded face per counter-clockwise cycle, and assigns every
clockwise (component-outer) cycle and isolated vertex to the innermost face that strictly
contains it -- all in exact arithmetic. Labels come verbatim from the spec.

``relate`` is the DE-9IM matrix of (A, B); the tests check it against the labels and,
when Shapely is installed, against GEOS 3.13 (every vertex, edge point and face witness
is located by GEOS too).

Fixtures: two_disjoint_squares, nested_squares (the annulus trap), shared_edge,
corner_touch, t_junction, crossing_lines (a non-dyadic vertex), dangling_line (degree-1
vertices, next = twin), point_in_polygon (an isolated vertex), hole_touching_shell,
points_only (no edges), both_empty (only face 0), overlapping_squares.

Use from any test directory (``tests/`` is on ``sys.path`` via ``tests/conftest.py``)::

    from unit.fixtures_arrangement import FIXTURES, fixture
    arr = fixture("nested_squares")          # a fresh, validated-shape Arrangement
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction
from functools import cmp_to_key

from geotruth.arrangement_api import Arrangement, EdgeSource, Location
from geotruth.exact import (
    INSIDE,
    ON_BOUNDARY,
    angle_cmp,
    hp_direction,
    point_in_ring,
    signed_area2,
)
from geotruth.geom import GEOM_A, GEOM_B, SourceTag
from geotruth.io import read_wkt

__all__ = ["FIXTURES", "FixtureSpec", "build", "fixture", "labels_matrix", "line", "ring"]

A, B = GEOM_A, GEOM_B


def ring(geom: int, element: int = 0, ring_index: int = 0, forward: bool = True) -> EdgeSource:
    """Source: ring ``ring_index`` (0 = shell) of polygon element ``element``."""
    return EdgeSource(SourceTag.for_ring(geom, element, ring_index), forward)


def line(geom: int, element: int = 0, forward: bool = True) -> EdgeSource:
    """Source: line element ``element``."""
    return EdgeSource(SourceTag.for_line(geom, element), forward)


@dataclass
class FixtureSpec:
    """A hand-written arrangement.

    ``vertices``: ``(x, y)`` integer points or ``(X, Y, W)`` homogeneous points.
    ``vertex_labels``: one two-letter label per vertex, location in A then in B.
    ``edges``: ``(u, v, sources, label)``; the sources' ``forward`` is relative to u->v.
    ``faces``: ``(witness point, label)``, one per face; witnesses may be Fractions.
    """

    name: str
    description: str
    a: str
    b: str
    relate: str
    vertices: list[tuple]
    vertex_labels: list[str]
    edges: list[tuple[int, int, list[EdgeSource], str]]
    faces: list[tuple[tuple, str]]
    notes: list[str] = field(default_factory=list)


def _pt(v: tuple[int, int, int]) -> tuple:
    x, y, w = v
    return (x, y) if w == 1 else (Fraction(x, w), Fraction(y, w))


def _ring_orientations(arr: Arrangement) -> None:
    for gid, g in ((A, arr.a), (B, arr.b)):
        if g is None:
            continue
        for r in g.iter_rings(gid):
            area = signed_area2([(Fraction(x), Fraction(y)) for x, y in r.coords])
            arr.ring_orientation[r.tag] = 1 if area > 0 else -1


def build(spec: FixtureSpec) -> Arrangement:
    """Build the arrangement described by ``spec`` (see the module docstring)."""
    arr = Arrangement.new(scale_exp=0, a=read_wkt(spec.a), b=read_wkt(spec.b))
    for v in spec.vertices:
        arr.add_vertex(*v)
    for u, v, sources, _ in spec.edges:
        arr.add_edge(u, v, sources)
    _ring_orientations(arr)

    # rotation system: next[twin[h_i]] = h_{i-1} for outgoing h sorted counter-clockwise
    out: list[list[int]] = [[] for _ in range(arr.num_vertices)]
    for h in range(arr.num_half_edges):
        out[arr.he_origin[h]].append(h)
    for v, hs in enumerate(out):
        if not hs:
            continue
        p = arr.vertex(v)
        dirs = {h: hp_direction(p, arr.vertex(arr.dest(h))) for h in hs}
        hs.sort(key=_angle_key(dirs))
        for i, h in enumerate(hs):
            prev_out = hs[i - 1]
            arr.he_next[h ^ 1] = prev_out
            arr.he_prev[prev_out] = h ^ 1
        arr.vertex_edge[v] = hs[0]

    # boundary cycles -> bounded faces (CCW) and component-outer cycles (CW / zero area)
    seen = [False] * arr.num_half_edges
    bounded: list[tuple[int, list[tuple], Fraction]] = []  # (face, ring, area2)
    outer_cycles: list[int] = []
    for h in range(arr.num_half_edges):
        if seen[h]:
            continue
        cyc = list(arr.cycle(h))
        for g in cyc:
            seen[g] = True
        pts = [_pt(arr.vertex(arr.he_origin[g])) for g in cyc]
        area2 = signed_area2(pts)
        if area2 > 0:
            f = arr.add_face(outer=h)
            for g in cyc:
                arr.he_face[g] = f
            bounded.append((f, pts, area2))
        else:
            outer_cycles.append(h)

    def containing_face(p: tuple, *, witness: bool = False) -> int:
        """Innermost bounded face whose outer cycle strictly contains ``p`` (else 0).

        A vertex of a component lies on the boundary of that component's own faces,
        which therefore never contain it; a face witness must avoid every boundary.
        """
        best, best_area = 0, None
        for f, pts, area2 in bounded:
            loc = point_in_ring(p, pts)
            if loc == ON_BOUNDARY and witness:
                raise ValueError(f"{spec.name}: witness {p} lies on the boundary of face {f}")
            if loc == INSIDE and (best_area is None or area2 < best_area):
                best, best_area = f, area2
        return best

    for h in outer_cycles:
        f = containing_face(_pt(arr.vertex(arr.he_origin[h])))
        for g in arr.cycle(h):
            arr.he_face[g] = f
        arr.face_inner[f].append(h)
    for v in range(arr.num_vertices):
        if not out[v]:
            arr.face_isolated[containing_face(_pt(arr.vertex(v)))].append(v)

    # labels
    if len(spec.vertex_labels) != arr.num_vertices:
        raise ValueError(
            f"{spec.name}: {len(spec.vertex_labels)} vertex labels for {arr.num_vertices} vertices"
        )
    for v, lab in enumerate(spec.vertex_labels):
        arr.set_label(0, v, *_loc2(lab))
    for e, (_, _, _, lab) in enumerate(spec.edges):
        arr.set_label(1, e, *_loc2(lab))
    labelled: set[int] = set()
    for witness, lab in spec.faces:
        for v in range(arr.num_vertices):
            if _pt(arr.vertex(v)) == tuple(witness):
                raise ValueError(f"{spec.name}: face witness {witness} is a vertex")
        f = containing_face(tuple(witness), witness=True)
        if f in labelled:
            raise ValueError(f"{spec.name}: two witnesses in face {f}")
        labelled.add(f)
        arr.set_label(2, f, *_loc2(lab))
    if len(labelled) != arr.num_faces:
        raise ValueError(f"{spec.name}: {arr.num_faces} faces but {len(labelled)} witnesses")
    return arr


def _angle_key(dirs: dict[int, tuple[int, int]]):
    return cmp_to_key(lambda g, h: angle_cmp(dirs[g], dirs[h]))


def _loc2(lab: str) -> tuple[Location, Location]:
    if len(lab) != 2:
        raise ValueError(f"a label is two letters (A then B): {lab!r}")
    return Location.from_char(lab[0]), Location.from_char(lab[1])


def labels_matrix(arr: Arrangement) -> str:
    """The DE-9IM matrix implied by the cell labels: M[a][b] = max cell dimension."""
    m = [[-1] * 3 for _ in range(3)]
    for c in arr.cells():
        if c.loc_a >= 0 and c.loc_b >= 0:
            m[c.loc_a][c.loc_b] = max(m[c.loc_a][c.loc_b], c.dim)
    return "".join("F" if d < 0 else str(d) for row in m for d in row)


# ============================================================================ fixtures

H = Fraction(1, 2)

FIXTURES: dict[str, FixtureSpec] = {}

# fmt: off


def _add(spec: FixtureSpec) -> None:
    FIXTURES[spec.name] = spec


_add(FixtureSpec(
    name="two_disjoint_squares",
    description="Two disjoint squares: two components, both inner components of face 0.",
    a="POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))",
    b="POLYGON ((4 0, 6 0, 6 2, 4 2, 4 0))",
    relate="FF2FF1212",
    vertices=[(0, 0), (2, 0), (2, 2), (0, 2), (4, 0), (6, 0), (6, 2), (4, 2)],
    vertex_labels=["BE"] * 4 + ["EB"] * 4,
    edges=[
        (0, 1, [ring(A)], "BE"), (1, 2, [ring(A)], "BE"),
        (2, 3, [ring(A)], "BE"), (3, 0, [ring(A)], "BE"),
        (4, 5, [ring(B)], "EB"), (5, 6, [ring(B)], "EB"),
        (6, 7, [ring(B)], "EB"), (7, 4, [ring(B)], "EB"),
    ],
    faces=[((1, 1), "IE"), ((5, 1), "EI"), ((3, 5), "EE")],
))

_add(FixtureSpec(
    name="nested_squares",
    description="B strictly inside A: the annulus face has an inner component (B's "
                "boundary). A sample point taken from the annulus's outer cycle alone "
                "(its centroid (5, 5)) would fall inside B and mislabel it (I, I).",
    a="POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0))",
    b="POLYGON ((4 4, 6 4, 6 6, 4 6, 4 4))",
    relate="212FF1FF2",
    vertices=[(0, 0), (10, 0), (10, 10), (0, 10), (4, 4), (6, 4), (6, 6), (4, 6)],
    vertex_labels=["BE"] * 4 + ["IB"] * 4,
    edges=[
        (0, 1, [ring(A)], "BE"), (1, 2, [ring(A)], "BE"),
        (2, 3, [ring(A)], "BE"), (3, 0, [ring(A)], "BE"),
        (4, 5, [ring(B)], "IB"), (5, 6, [ring(B)], "IB"),
        (6, 7, [ring(B)], "IB"), (7, 4, [ring(B)], "IB"),
    ],
    faces=[((5, 5), "II"), ((1, 1), "IE"), ((20, 20), "EE")],
))

_add(FixtureSpec(
    name="shared_edge",
    description="Squares sharing a full edge; the merged edge carries both rings, in "
                "opposite directions.",
    a="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
    b="POLYGON ((1 0, 2 0, 2 1, 1 1, 1 0))",
    relate="FF2F11212",
    vertices=[(0, 0), (1, 0), (1, 1), (0, 1), (2, 0), (2, 1)],
    vertex_labels=["BE", "BB", "BB", "BE", "EB", "EB"],
    edges=[
        (0, 1, [ring(A)], "BE"),
        (1, 2, [ring(A), ring(B, forward=False)], "BB"),
        (2, 3, [ring(A)], "BE"), (3, 0, [ring(A)], "BE"),
        (1, 4, [ring(B)], "EB"), (4, 5, [ring(B)], "EB"), (5, 2, [ring(B)], "EB"),
    ],
    faces=[((H, H), "IE"), ((3 * H, H), "EI"), ((5, 5), "EE")],
))

_add(FixtureSpec(
    name="corner_touch",
    description="Squares touching at one corner: one component with a degree-4 vertex.",
    a="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
    b="POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))",
    relate="FF2F01212",
    vertices=[(0, 0), (1, 0), (1, 1), (0, 1), (2, 1), (2, 2), (1, 2)],
    vertex_labels=["BE", "BE", "BB", "BE", "EB", "EB", "EB"],
    edges=[
        (0, 1, [ring(A)], "BE"), (1, 2, [ring(A)], "BE"),
        (2, 3, [ring(A)], "BE"), (3, 0, [ring(A)], "BE"),
        (2, 4, [ring(B)], "EB"), (4, 5, [ring(B)], "EB"),
        (5, 6, [ring(B)], "EB"), (6, 2, [ring(B)], "EB"),
    ],
    faces=[((H, H), "IE"), ((3 * H, 3 * H), "EI"), ((5, 5), "EE")],
))

_add(FixtureSpec(
    name="t_junction",
    description="B's apex lies in the interior of A's top edge, which is split there "
                "(a T-junction).",
    a="POLYGON ((0 0, 4 0, 4 2, 0 2, 0 0))",
    b="POLYGON ((2 2, 3 4, 1 4, 2 2))",
    relate="FF2F01212",
    vertices=[(0, 0), (4, 0), (4, 2), (0, 2), (2, 2), (3, 4), (1, 4)],
    vertex_labels=["BE", "BE", "BE", "BE", "BB", "EB", "EB"],
    edges=[
        (0, 1, [ring(A)], "BE"), (1, 2, [ring(A)], "BE"),
        (2, 4, [ring(A)], "BE"), (4, 3, [ring(A)], "BE"), (3, 0, [ring(A)], "BE"),
        (4, 5, [ring(B)], "EB"), (5, 6, [ring(B)], "EB"), (6, 4, [ring(B)], "EB"),
    ],
    faces=[((1, 1), "IE"), ((2, 3), "EI"), ((10, 10), "EE")],
))

_add(FixtureSpec(
    name="crossing_lines",
    description="Two lines crossing at the non-dyadic point (6/5, 2/5), a homogeneous "
                "vertex (6, 2, 5); only the unbounded face exists.",
    a="LINESTRING (0 0, 3 1)",
    b="LINESTRING (0 1, 2 0)",
    relate="0F1FF0102",
    vertices=[(0, 0), (3, 1), (0, 1), (2, 0), (6, 2, 5)],
    vertex_labels=["BE", "BE", "EB", "EB", "II"],
    edges=[
        (0, 4, [line(A)], "IE"), (4, 1, [line(A)], "IE"),
        (2, 4, [line(B)], "EI"), (4, 3, [line(B)], "EI"),
    ],
    faces=[((5, 5), "EE")],
))

_add(FixtureSpec(
    name="dangling_line",
    description="A line from inside A to outside: degree-1 vertices at both ends, one "
                "dangling into the bounded face; A's right edge is split at (4, 2).",
    a="POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))",
    b="LINESTRING (2 2, 6 2)",
    relate="1020F1102",
    vertices=[(0, 0), (4, 0), (4, 4), (0, 4), (4, 2), (2, 2), (6, 2)],
    vertex_labels=["BE", "BE", "BE", "BE", "BI", "IB", "EB"],
    edges=[
        (0, 1, [ring(A)], "BE"), (1, 4, [ring(A)], "BE"), (4, 2, [ring(A)], "BE"),
        (2, 3, [ring(A)], "BE"), (3, 0, [ring(A)], "BE"),
        (5, 4, [line(B)], "II"), (4, 6, [line(B)], "EI"),
    ],
    faces=[((1, 1), "IE"), ((10, 10), "EE")],
))

_add(FixtureSpec(
    name="point_in_polygon",
    description="An isolated vertex (B) inside A's bounded face.",
    a="POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))",
    b="POINT (1 1)",
    relate="0F2FF1FF2",
    vertices=[(0, 0), (4, 0), (4, 4), (0, 4), (1, 1)],
    vertex_labels=["BE"] * 4 + ["II"],
    edges=[
        (0, 1, [ring(A)], "BE"), (1, 2, [ring(A)], "BE"),
        (2, 3, [ring(A)], "BE"), (3, 0, [ring(A)], "BE"),
    ],
    faces=[((3, 3), "IE"), ((10, 10), "EE")],
))

_add(FixtureSpec(
    name="hole_touching_shell",
    description="A valid polygon whose hole touches the shell at (0, 2) (splitting the "
                "shell edge there; the interior face's outer cycle is pinched), and a "
                "point of B isolated inside the hole face.",
    a="POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (0 2, 2 1, 2 3, 0 2))",
    b="POINT (1 2)",
    relate="FF2FF10F2",
    vertices=[(0, 0), (4, 0), (4, 4), (0, 4), (0, 2), (2, 1), (2, 3), (1, 2)],
    vertex_labels=["BE"] * 7 + ["EI"],
    edges=[
        (0, 1, [ring(A)], "BE"), (1, 2, [ring(A)], "BE"), (2, 3, [ring(A)], "BE"),
        (3, 4, [ring(A)], "BE"), (4, 0, [ring(A)], "BE"),
        (4, 5, [ring(A, 0, 1)], "BE"), (5, 6, [ring(A, 0, 1)], "BE"),
        (6, 4, [ring(A, 0, 1)], "BE"),
    ],
    faces=[((3, 3), "IE"), ((3 * H, 2), "EE"), ((10, 10), "EE")],
))

_add(FixtureSpec(
    name="points_only",
    description="No edges at all: only isolated vertices in the unbounded face.",
    a="MULTIPOINT ((0 0), (1 1))",
    b="POINT (1 1)",
    relate="0F0FFFFF2",
    vertices=[(0, 0), (1, 1)],
    vertex_labels=["IE", "II"],
    edges=[],
    faces=[((5, 5), "EE")],
))

_add(FixtureSpec(
    name="both_empty",
    description="Two empty operands: no vertices, no edges, only the unbounded face "
                "(EE = 2 still holds).",
    a="POLYGON EMPTY",
    b="LINESTRING EMPTY",
    relate="FFFFFFFF2",
    vertices=[],
    vertex_labels=[],
    edges=[],
    faces=[((0, 0), "EE")],
))

_add(FixtureSpec(
    name="overlapping_squares",
    description="Squares overlapping in a lens: proper crossings split both boundaries; "
                "faces A-only, A and B, B-only.",
    a="POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))",
    b="POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))",
    relate="212101212",
    vertices=[(0, 0), (2, 0), (2, 2), (0, 2), (1, 1), (3, 1), (3, 3), (1, 3), (2, 1), (1, 2)],
    vertex_labels=["BE", "BE", "BI", "BE", "IB", "EB", "EB", "EB", "BB", "BB"],
    edges=[
        (0, 1, [ring(A)], "BE"), (1, 8, [ring(A)], "BE"), (8, 2, [ring(A)], "BI"),
        (2, 9, [ring(A)], "BI"), (9, 3, [ring(A)], "BE"), (3, 0, [ring(A)], "BE"),
        (4, 8, [ring(B)], "IB"), (8, 5, [ring(B)], "EB"), (5, 6, [ring(B)], "EB"),
        (6, 7, [ring(B)], "EB"), (7, 9, [ring(B)], "EB"), (9, 4, [ring(B)], "IB"),
    ],
    faces=[((H, H), "IE"), ((3 * H, 3 * H), "II"), ((5 * H, 5 * H), "EI"), ((10, 10), "EE")],
))
# fmt: on


def fixture(name: str) -> Arrangement:
    """A freshly built arrangement for the named fixture."""
    return build(FIXTURES[name])
