"""Cross-check of the witness relate, the point locator and the predicates against GEOS.

GEOS 3.13.1 (through Shapely 2.1.2) is a third opinion only: nothing in ``src/geotruth``
imports it. The cases are small-integer lattice geometries (:mod:`unit.witness_lattice`),
all GEOS-valid, of every ordered type pair (Point, MultiPoint, LineString,
MultiLineString, Polygon, MultiPolygon, mixed GeometryCollection, GC of rectangles).

How disagreements are judged
----------------------------
GEOS computes intersection points in floating point, so its *relate* is not exact in
general. Its *point location* is, for integer coordinates of modest size: every test is
an orientation or coordinate comparison on small integers. So when the matrices differ,
the case is scaled by an integer so that each of our witness points is an integer point,
and GEOS locates every witness in the original A and B (``relate(POINT, X)``, first
row). If GEOS's own point locator, applied to our witnesses, reproduces our matrix, then
GEOS's relate contradicts GEOS's point location on a complete set of cell
representatives: the disagreement is in GEOS's matrix assembly, not in the semantics.
Such cases are recorded by class (below); anything else fails the test.

Known GEOS 3.13.1 RelateNG defects found this way (minimal cases in KNOWN_GEOS_DEFECTS),
recognised by their signature in :func:`classify`:

- ``line-end-skip``: ``RelateNG.computeLineEnds`` stops examining line elements whose
  envelope misses the other operand once *any* line end was found in the other's
  exterior -- even when that end was a Mod-2 *interior* point (a closed line's start).
  Boundary endpoints of later elements are then never recorded: EB/BE is F instead of 0.
  The answer depends on element order.
- ``gc-overlapping-polygons``: in a GeometryCollection whose polygons overlap, the node
  topology RelateNG builds where A's boundary crosses one polygon element ignores the
  other elements covering that node, so a sector inside the union is labelled exterior:
  a polygon inside the union of a square and a crossing rectangle gets IE = 2. (GEOS's
  point locator, with its AdjacentEdgeLocator, still locates every point correctly.)
- ``ring-touch-node``: at a node where an areal operand's boundary touches itself (a
  hole touching its shell, MultiPolygon parts touching at a point) and the other operand
  has an edge collinear with that boundary through the node, RelateNG mislabels a sector.
  All-integer, valid input: ``POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))``
  and the rectangle below it sharing the bottom edge get II = 2, so GEOS's ``overlaps``
  is true for two polygons that only touch (its own overlay gives an intersection of
  area 0), and ``relate(A, B)`` is not the transpose of ``relate(B, A)`` for the line
  along that edge.
- ``inexact-node``: a crossing point that is not a double -- (7/3, 2/3) -- lying on a
  collinear overlap of A and B. GEOS rounds the node off the common line, then sees the
  overlapping edges as non-collinear and reports IE = 1. The only class where GEOS is
  inexact by construction; still a wrong answer on exact input.
- ``mixed-gc``: ``TopologyComputer`` infers exterior interactions from the operand's
  real dimension or from the dimension of the element a point hits, as if the operand
  were homogeneous. In a GeometryCollection mixing points with lines or polygons this is
  wrong: a Point element outside B makes GEOS claim B's interior meets A's exterior
  (EI = 2) although A's polygon covers B; a line whose ends sit on Point elements of a
  mixed GC never gets IE/EI = 1.
"""

from __future__ import annotations

import itertools
import random
from collections import Counter

import pytest

from geotruth.exact import on_segment
from geotruth.geom import (
    Geometry,
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
)
from geotruth.io import read_wkt, to_wkt
from geotruth.locate import Frame, PointLocator, locate, location_char
from geotruth.predicates import PREDICATE_NAMES, evaluate, predicates, transpose
from geotruth.relate_witness import WitnessRelate, relate, relate_witness
from unit.test_relate_witness import HAND_CASES
from unit.witness_lattice import (
    GENERATORS,
    is_valid,
    random_geometry,
    random_pair,
    zero_length_line,
)

shapely = pytest.importorskip("shapely")

#: Coordinates below this are exact in every GEOS orientation test (products < 2**52).
_EXACT_LIMIT = 2**25

GEOS_3_13_1 = tuple(shapely.geos_version) == (3, 13, 1)


# ============================================================================ helpers


def geos_relate(a: Geometry, b: Geometry) -> str:
    return shapely.relate(shapely.from_wkt(to_wkt(a)), shapely.from_wkt(to_wkt(b)))


def _scaled(g: Geometry, frame: Frame, k: int) -> object:
    def f(c):
        x, y = frame.to_int_point(c)
        return float(x * k), float(y * k)

    return shapely.from_wkt(to_wkt(g.map_coords(f)))


def _geos_loc(pt: object, g: object) -> int:
    m = shapely.relate(pt, g)
    return 0 if m[0] != "F" else 1 if m[1] != "F" else 2


def geos_located_matrix(res: WitnessRelate, a: Geometry, b: Geometry) -> str | None:
    """Our witnesses, located by GEOS's point locator in exactly scaled coordinates.

    Returns the matrix M[a][b] = max witness dimension with GEOS's labels, or None when
    the scaled coordinates would be too large for GEOS to locate exactly.
    """
    frame = res.frame
    by_w: dict[int, list] = {}
    for w in res.witnesses:
        by_w.setdefault(w.point[2], []).append(w)
    dims = [[-1] * 3 for _ in range(3)]
    coords = [frame.to_int_point(c) for g in (a, b) for c in g.iter_coords()]
    top = max((max(abs(x), abs(y)) for x, y in coords), default=0) + 1
    for k, ws in by_w.items():
        biggest = max(max(abs(w.point[0]), abs(w.point[1])) for w in ws)
        if top * k >= _EXACT_LIMIT or biggest >= _EXACT_LIMIT:
            return None
        sa, sb = _scaled(a, frame, k), _scaled(b, frame, k)
        for w in ws:
            x, y, _ = w.point
            pt = shapely.Point(float(x), float(y))
            la, lb = _geos_loc(pt, sa), _geos_loc(pt, sb)
            dims[la][lb] = max(dims[la][lb], w.dim)
    dims[2][2] = 2
    return "".join("F" if d < 0 else str(d) for row in dims for d in row)


def _reversed(g: Geometry) -> Geometry:
    """The same point set with every collection's children in reverse order."""
    if isinstance(g, GeometryCollection):
        return GeometryCollection(tuple(_reversed(x) for x in reversed(g.geometries)))
    if isinstance(g, MultiPoint | MultiLineString | MultiPolygon):
        return type(g)(tuple(reversed(g.children())))
    return g


def _mixed(g: Geometry) -> bool:
    kinds = {e.geom_type for e in g.elements() if not e.is_empty}
    return isinstance(g, GeometryCollection) and len(kinds) > 1


def _num_lines(g: Geometry) -> int:
    return sum(1 for e in g.elements() if isinstance(e, LineString) and not e.is_empty)


def _gc_polygons(g: Geometry) -> int:
    if not isinstance(g, GeometryCollection):
        return 0
    return sum(1 for e in g.elements() if e.geom_type == "Polygon" and not e.is_empty)


_ENTRIES = ("II", "IB", "IE", "BI", "BB", "BE", "EI", "EB", "EE")


def _has_ring_touch(g: Geometry) -> bool:
    """Some polygon ring vertex lies on another ring: a hole touching its shell or
    another hole, or MultiPolygon/GC parts touching at a point."""
    frame = Frame.for_geometries(g)
    rings = [[frame.to_int_point(c) for c in r.coords] for r in g.iter_rings()]
    for i, r in enumerate(rings):
        for j, other in enumerate(rings):
            if i != j and any(
                on_segment(v, p, q) for v in set(r) for p, q in itertools.pairwise(other)
            ):
                return True
    return False


def _has_inexact_node(res: WitnessRelate) -> bool:
    """Some intersection point is not dyadic, so GEOS cannot even represent it."""
    return any(w.kind == "intersection" and w.point[2] & (w.point[2] - 1) for w in res.witnesses)


def classify(a: Geometry, b: Geometry, ours: str, theirs: str, res: WitnessRelate) -> str:
    """Which GEOS defect mechanism explains a disagreement (module docstring), from its
    signature. Called only after GEOS's own point location has confirmed our matrix, so
    the class is a diagnosis, not the evidence."""
    diff = {_ENTRIES[i] for i in range(9) if ours[i] != theirs[i]}
    lost_ends = all(ours[_ENTRIES.index(e)] == "0" and theirs[_ENTRIES.index(e)] == "F"
                    for e in diff)  # fmt: skip
    if diff <= {"BE", "EB"} and lost_ends and max(_num_lines(a), _num_lines(b)) >= 2:
        return LINE_END_SKIP
    if max(_gc_polygons(a), _gc_polygons(b)) >= 2:
        return GC_OVERLAP
    if _mixed(a) or _mixed(b):
        return MIXED_GC
    if _has_ring_touch(a) or _has_ring_touch(b):
        return RING_TOUCH
    if _has_inexact_node(res):
        return INEXACT_NODE
    return "other"


LINE_END_SKIP = "line-end-skip"
GC_OVERLAP = "gc-overlapping-polygons"
MIXED_GC = "mixed-gc"
RING_TOUCH = "ring-touch-node"
INEXACT_NODE = "inexact-node"
GEOS_DEFECT_CLASSES = frozenset({LINE_END_SKIP, GC_OVERLAP, MIXED_GC, RING_TOUCH, INEXACT_NODE})


def judge(a: Geometry, b: Geometry) -> tuple[str, str, str | None]:
    """(ours, GEOS relate, verdict): verdict None if they agree, else the GEOS defect
    class when GEOS's point location confirms ours, else ``"UNEXPLAINED ..."``."""
    res = relate_witness(a, b, keep_witnesses=True)
    ours, theirs = res.matrix, geos_relate(a, b)
    if ours == theirs:
        return ours, theirs, None
    located = geos_located_matrix(res, a, b)
    if located is None:
        return ours, theirs, "UNEXPLAINED (too large to locate exactly)"
    if located != ours:
        return ours, theirs, f"UNEXPLAINED (GEOS point location gives {located})"
    return ours, theirs, classify(a, b, ours, theirs, res)


# ===================================================================== lattice relate


def _run_lattice(n_cases: int, seed: int, n: int) -> tuple[Counter, list]:
    rng = random.Random(seed)
    verdicts: Counter = Counter()
    unexplained = []
    for i in range(n_cases):
        ta, tb, a, b = random_pair(rng, i, n)
        ours, theirs, verdict = judge(a, b)
        verdicts[verdict or "agree"] += 1
        if verdict and verdict.startswith("UNEXPLAINED"):
            unexplained.append((ta, tb, a.wkt, b.wkt, ours, theirs, verdict))
    return verdicts, unexplained


def test_lattice_relate_vs_geos():
    """3000 lattice cases over all 64 ordered type pairs."""
    verdicts, unexplained = _run_lattice(3000, seed=20260926, n=4)
    print("\nwitness relate vs GEOS 3.13:", dict(verdicts))
    assert unexplained == []
    assert verdicts["agree"] >= 0.97 * 3000
    assert set(verdicts) <= {"agree", *GEOS_DEFECT_CLASSES}


@pytest.mark.slow
@pytest.mark.parametrize(("seed", "n"), [(1, 3), (2, 5), (3, 8)])
def test_lattice_relate_vs_geos_large(seed, n):
    verdicts, unexplained = _run_lattice(10000, seed=seed, n=n)
    print(f"\nseed {seed}, lattice {n}:", dict(verdicts))
    assert unexplained == []
    assert set(verdicts) <= {"agree", *GEOS_DEFECT_CLASSES}


def test_witnesses_located_by_geos_reproduce_our_matrix():
    """GEOS's point locator on our witnesses gives our matrix for every case (thousands
    of exact point locations of vertices, crossings, edge and face points)."""
    rng = random.Random(77)
    checked = 0
    for i in range(640):
        _, _, a, b = random_pair(rng, i)
        res = relate_witness(a, b, keep_witnesses=True)
        located = geos_located_matrix(res, a, b)
        if located is None:
            continue
        assert located == res.matrix, (a.wkt, b.wkt)
        checked += 1
    assert checked >= 600


# ================================================================= point location


def test_locate_vs_geos_on_lattice_points():
    """Every point of the half-integer lattice (scaled by 2 to integers) against random
    geometries of every type, including collections with shared and crossing edges."""
    rng = random.Random(9)
    n = 4
    total = 0
    for i in range(160):
        kind = list(GENERATORS)[i % len(GENERATORS)]
        g = random_geometry(rng, kind, n)
        sg = shapely.from_wkt(to_wkt(g.map_coords(lambda c: (2 * c[0], 2 * c[1]))))
        frame = Frame.for_geometries(g)
        lp = PointLocator(g, frame)
        for x2, y2 in itertools.product(range(-1, 2 * n + 2), repeat=2):
            p = frame.hpoint((x2, y2, 2))
            ours = location_char(lp.locate(p))
            theirs = "IBE"[_geos_loc(shapely.Point(x2, y2), sg)]
            assert ours == theirs, (g.wkt, (x2 / 2, y2 / 2))
            total += 1
    assert total > 10000


def test_locate_matches_module_function():
    g = read_wkt(
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
        "POLYGON ((2 0, 4 0, 4 2, 2 2, 2 0)), LINESTRING (1 1, 5 1), POINT (6 6))"
    )
    sg = shapely.from_wkt(to_wkt(g))
    for x, y in itertools.product(range(-1, 8), repeat=2):
        assert locate((x, y), g) == "IBE"[_geos_loc(shapely.Point(x, y), sg)], (x, y)


# ==================================================================== predicates


def test_predicate_dispatch_vs_geos():
    """Our dimension-dispatched predicates, applied to GEOS's own matrix, give GEOS's
    named predicates (so the dispatch table is RelateNG's)."""
    rng = random.Random(4)
    for i in range(1500):
        _, _, a, b = random_pair(rng, i)
        sa, sb = shapely.from_wkt(to_wkt(a)), shapely.from_wkt(to_wkt(b))
        m = shapely.relate(sa, sb)
        ours = predicates(m, a.real_dimension, b.real_dimension)
        theirs = {k: bool(getattr(shapely, k)(sa, sb)) for k in PREDICATE_NAMES}
        assert ours == theirs, (a.wkt, b.wkt, m)


def test_predicates_from_our_matrix_vs_geos_where_matrices_agree():
    rng = random.Random(6)
    compared = 0
    for i in range(1500):
        _, _, a, b = random_pair(rng, i)
        res = relate_witness(a, b)
        if res.matrix != geos_relate(a, b):
            continue  # a GEOS relate defect; its predicates inherit it
        sa, sb = shapely.from_wkt(to_wkt(a)), shapely.from_wkt(to_wkt(b))
        theirs = {k: bool(getattr(shapely, k)(sa, sb)) for k in PREDICATE_NAMES}
        assert {k: v.value for k, v in res.predicates().items()} == theirs
        compared += 1
    assert compared > 1400


EMPTIES = [
    "POINT EMPTY",
    "LINESTRING EMPTY",
    "POLYGON EMPTY",
    "MULTIPOINT EMPTY",
    "MULTILINESTRING EMPTY",
    "MULTIPOLYGON EMPTY",
    "GEOMETRYCOLLECTION EMPTY",
    "GEOMETRYCOLLECTION (POINT EMPTY, POLYGON EMPTY)",
]
NON_EMPTY = ["POINT (1 1)", "LINESTRING (0 0, 2 2)", "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"]


@pytest.mark.parametrize(
    ("a", "b"),
    [*itertools.product(EMPTIES, EMPTIES + NON_EMPTY), *itertools.product(NON_EMPTY, EMPTIES)],
)
def test_empty_conventions_vs_geos(a, b):
    ga, gb = read_wkt(a), read_wkt(b)
    m = relate(ga, gb)
    assert m == geos_relate(ga, gb)
    res = evaluate(m, ga.real_dimension, gb.real_dimension)
    sa, sb = shapely.from_wkt(a), shapely.from_wkt(b)
    for name in PREDICATE_NAMES:
        assert res[name].value == bool(getattr(shapely, name)(sa, sb)), name
    assert res["equals"].convention == (ga.is_empty and gb.is_empty)


# ================================================================== zero-length lines


def test_zero_length_lines_vs_geos():
    """RelateNG treats a line whose points coincide as a point (GEOS calls it invalid,
    but relates it); geotruth follows RelateNG."""
    rng = random.Random(12)
    for i in range(300):
        a = zero_length_line(rng)
        kind = list(GENERATORS)[i % len(GENERATORS)]
        b = random_geometry(rng, kind)
        if _mixed(b):
            continue  # keep clear of the mixed-GC defect
        _, _, verdict = judge(a, b)
        assert verdict is None or not verdict.startswith("UNEXPLAINED"), (a.wkt, b.wkt)
        assert a.real_dimension == 0


# ================================================================ known GEOS defects


KNOWN_GEOS_DEFECTS = [
    # (class, A, B, exact matrix, GEOS 3.13.1 matrix)
    (
        RING_TOUCH,
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))",
        "POLYGON ((0 0, 4 0, 4 -1, 0 -1, 0 0))",
        "FF2F11212",
        "212F11212",
    ),
    (
        RING_TOUCH,
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))",
        "LINESTRING (0 0, 4 0)",
        "FF2101FF2",
        "1F2101FF2",
    ),
    (
        RING_TOUCH,
        "MULTIPOLYGON (((0 0, 4 0, 4 2, 0 2, 0 0)), ((2 2, 3 3, 1 3, 2 2)))",
        "POLYGON ((1 1, 3 1, 3 2, 1 2, 1 1))",
        "212F11FF2",
        "212F11212",
    ),
    (
        INEXACT_NODE,
        "LINESTRING (1 2, 3 0)",
        "MULTILINESTRING ((3 0, 0 3), (3 2, 2 0))",
        "1FF00F102",
        "1F100F102",
    ),
    (
        GC_OVERLAP,
        "POLYGON ((0 0, 0 3, 3 3, 3 2, 0 0))",
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), "
        "POLYGON ((1 0, 2 0, 2 4, 1 4, 1 0)))",
        "2FF11F212",
        "212111212",
    ),
    (
        MIXED_GC,
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)), POINT (10 10))",
        "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))",
        "212FF1FF2",
        "212FF1212",
    ),
    (
        MIXED_GC,
        "LINESTRING (0 0, 1 0)",
        "GEOMETRYCOLLECTION (MULTIPOINT ((1 0), (0 0)), LINESTRING (5 5, 6 6))",
        "FF10FF102",
        "FFF0FF102",
    ),
    (
        MIXED_GC,
        "GEOMETRYCOLLECTION (POLYGON ((3 2, 3 1, 1 0, 3 2)), MULTIPOINT ((3 4)))",
        "LINESTRING (3 4, 4 3, 3 4)",
        "0F2FF11F2",
        "0F2FF1FF2",
    ),
    (
        LINE_END_SKIP,
        "POINT (10 10)",
        "MULTILINESTRING ((0 0, 1 0, 1 1, 0 0), (5 5, 6 6))",
        "FF0FFF102",
        "FF0FFF1F2",
    ),
    (
        LINE_END_SKIP,
        "POLYGON ((1 2, 4 0, 1 0, 1 2))",
        "MULTILINESTRING ((2 3, 1 1), (2 3, 4 3))",
        "1F2001102",
        "1F20011F2",
    ),
]


@pytest.mark.parametrize(("cls", "a", "b", "exact", "geos"), KNOWN_GEOS_DEFECTS)
def test_known_geos_defects(cls, a, b, exact, geos):
    ga, gb = read_wkt(a), read_wkt(b)
    ours, theirs, verdict = judge(ga, gb)
    assert ours == exact
    assert is_valid(ga) and is_valid(gb)
    if GEOS_3_13_1:
        assert theirs == geos
        assert verdict == cls
    if GEOS_3_13_1 and cls in (LINE_END_SKIP, MIXED_GC, GC_OVERLAP):
        # the point-set-equal reordering fixes GEOS's answer only for line-end-skip
        rev = geos_relate(_reversed(ga), _reversed(gb))
        assert (rev == exact) == (cls == LINE_END_SKIP)


@pytest.mark.parametrize(("a", "b", "expected"), HAND_CASES)
def test_hand_cases_vs_geos(a, b, expected):
    """The hand-derived table agrees with GEOS except on the known GEOS defects."""
    theirs = geos_relate(read_wkt(a), read_wkt(b))
    defect = {(d[1], d[2]): d[4] for d in KNOWN_GEOS_DEFECTS}
    if (a, b) in defect and GEOS_3_13_1:
        assert theirs == defect[(a, b)]
    else:
        assert theirs == expected


def test_line_end_skip_depends_on_element_order():
    """The same MultiLineString with its parts swapped gets the right answer from GEOS."""
    a = read_wkt("POINT (10 10)")
    b1 = read_wkt("MULTILINESTRING ((0 0, 1 0, 1 1, 0 0), (5 5, 6 6))")
    b2 = read_wkt("MULTILINESTRING ((5 5, 6 6), (0 0, 1 0, 1 1, 0 0))")
    assert relate(a, b1) == relate(a, b2) == "FF0FFF102"
    assert geos_relate(a, b2) == "FF0FFF102"
    if GEOS_3_13_1:
        assert geos_relate(a, b1) == "FF0FFF1F2"


def test_mixed_gc_point_changes_containment():
    """GEOS 3.13.1: adding a far-away Point to a GC flips contains() on a polygon it
    covers; the exact answer is unchanged."""
    big = "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))"
    small = read_wkt("POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))")
    for a in (big, f"GEOMETRYCOLLECTION ({big}, POINT (10 10))"):
        res = relate_witness(read_wkt(a), small)
        assert res.predicates()["contains"].value is True
    if GEOS_3_13_1:
        gc = shapely.from_wkt(f"GEOMETRYCOLLECTION ({big}, POINT (10 10))")
        assert not shapely.contains(gc, shapely.from_wkt(to_wkt(small)))


def test_geos_location_helper_refuses_inexact_scales():
    # sanity of the helper: a case whose witnesses need a large scale is refused
    a = LineString([(0.0, 0.0), (3.0, 1.0)])
    b = LineString([(0.0, 1.0), (2.0, 0.0)])
    res = relate_witness(a, b, keep_witnesses=True)
    assert geos_located_matrix(res, a, b) == res.matrix
    big = LineString([(0.0, 0.0), (float(2**40), 1.0)])
    res = relate_witness(big, b, keep_witnesses=True)
    assert geos_located_matrix(res, big, b) is None


def test_ring_touch_defect_breaks_geos_predicates_and_symmetry():
    """GEOS 3.13.1: two valid polygons sharing only an edge 'overlap'; relate is not
    transpose-symmetric. The exact answers: they touch; the matrices are transposes."""
    a = read_wkt("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))")
    below = read_wkt("POLYGON ((0 0, 4 0, 4 -1, 0 -1, 0 0))")
    edge = read_wkt("LINESTRING (0 0, 4 0)")
    res = relate_witness(below, a)
    assert res.predicates()["touches"].value and not res.predicates()["overlaps"].value
    assert relate(a, edge) == transpose(relate(edge, a)) == "FF2101FF2"
    if GEOS_3_13_1:
        sa, sb = shapely.from_wkt(to_wkt(a)), shapely.from_wkt(to_wkt(below))
        assert shapely.overlaps(sb, sa) and not shapely.touches(sb, sa)
        assert shapely.intersection(sa, sb).area == 0
        assert geos_relate(edge, a) == "F1FF0F212"  # right
        assert geos_relate(a, edge) == "1F2101FF2"  # not its transpose
