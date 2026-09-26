#!/usr/bin/env python3
"""Dual-route relate cross-check (DESIGN §0.2, §2.3, §2.4).

Every case is answered by up to five implementations:

``arrangement``
    :func:`geotruth.relate.relate`: DE-9IM from the labelled DCEL (§2.3), with its own
    assertions (EE = 2, transpose from a second, swapped arrangement, dimension sanity).
``witness``
    :func:`geotruth.relate_witness.relate_witness`: witness points located in the original
    operands by the standalone RelateNG-style locator (§2.4). It shares only the §2.1
    primitives with the arrangement route.
``oracle`` / ``indep``
    the audited polygon references ``tests/reference/oracle.py`` (vertical slabs) and
    ``indep.py`` (Green's theorem on boundary pieces): the nine areal predicates, for valid
    polygon/polygon cases only.
``geos``
    GEOS through Shapely -- a third opinion only, and only on small-integer lattice cases
    (every ordinate an integer below 2**20 in magnitude, both operands GEOS-valid), where
    every orientation test GEOS makes is exact. When GEOS's matrix differs, GEOS's *own*
    point locator is asked about every witness point of the case (coordinates scaled to
    integers); if that reproduces the exact matrix, GEOS's relate contradicts GEOS's point
    location, and the case is counted as a GEOS defect, classified by signature
    (``line-end-skip``, ``gc-overlapping-polygons``, ``mixed-gc``, ``ring-touch-node``,
    ``inexact-node``, see ``tests/crosscheck/test_witness_vs_geos.py``; and
    ``empty-element-dimension``: an empty element raising the type dimension). When a
    case is too large to scale every witness, each entry GEOS reports empty is confirmed
    on one small witness of ours that GEOS itself locates there (``... (partial)``). When
    GEOS's point locator itself disagrees with ours, a third exact locator decides: the
    brute-force DESIGN §1 locator of ``tests/unit/arrangement_testlib.py``; if it agrees
    with ours on every disputed witness the verdict is ``geos-point-location (...)``
    (``gc-adjacent-edge`` when the point lies on two or more polygon boundaries of a
    GC). GEOS runs in a separate, restartable process, so a GEOS segfault is recorded
    as ``geos-crash``. Anything else is ``unexplained``.

The two exact routes must agree on every case; any disagreement, engine error, oracle or
indep mismatch or unexplained GEOS difference makes the exit status 1.

Case sources (``--sources``, comma-separated; default all)
----------------------------------------------------------
``fixtures``     the hand-built arrangement fixtures (their stated matrix must match too)
``exhaustive``   every (triangle, point | segment | triangle) pair on the 3x3 grid, GCs
                 of two triangles against points and segments, and two-segment paths
                 against segments and triangles (``--cases`` > 0 takes an even stride)
``seed``         ``corpus/cases/seed.jsonl`` (1000 polygon/polygon cases, ulp-level)
``review``       the oracle-review families: ``tools/oracle_review/gen_review.py all N 1``
``lattice``      random small-integer lattice pairs of every ordered type pair (Point,
                 MultiPoint, LineString, MultiLineString, Polygon, MultiPolygon, mixed GC,
                 GC of rectangles) from ``tests/unit/witness_lattice.py``, plus random
                 operands of ``tests/unit/arrangement_testlib.py``
``adversarial``  new degenerate lattice pairs (this module): B derived from A (A's
                 boundary as closed or open lines, A's vertices and edge midpoints, A
                 re-expressed with rotated/reversed rings and extra collinear vertices, A
                 shifted by a lattice step, A's hole as a polygon, lines along A's edges
                 beyond their ends), nested and mixed GeometryCollections, empties,
                 zero-length and single-point lines, retracing and closed lines
``transformed``  exact images of lattice and adversarial cases under invertible affine
                 maps with rational coefficients, scalings by 2**k (subnormal to 2**1000)
                 and axis swaps: relate is affine invariant, so both routes must also
                 reproduce the untransformed matrix
``ulp``          near-degenerate images of lattice and adversarial cases (float rotations,
                 one-ulp nudges of coordinate values): exact degeneracies become ulp-level
                 near-misses; the two exact routes must still agree
``dense``        8x8 lattice pairs, larger random operands, and GeometryCollections of 3-5
                 stacked polygons (coverage up to 5, identical copies, filled holes)

usage::

    python3 tools/crosscheck_relate.py                        # everything, default sizes
    python3 tools/crosscheck_relate.py --sources lattice,adversarial --cases 5000 --jobs 2
    python3 tools/crosscheck_relate.py --json report.json     # machine-readable report
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import random
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src", REPO / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from geotruth.arrangement import InvalidInputError  # noqa: E402
from geotruth.geom import (  # noqa: E402
    Geometry,
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from geotruth.io import case_from_json, read_wkt, to_wkt  # noqa: E402
from geotruth.locate import Frame  # noqa: E402
from geotruth.numbers import json_loads  # noqa: E402
from geotruth.predicates import evaluate  # noqa: E402
from geotruth.relate import relate  # noqa: E402
from geotruth.relate_witness import WitnessRelate, relate_witness  # noqa: E402

SOURCES = (
    "fixtures",
    "exhaustive",
    "seed",
    "review",
    "lattice",
    "adversarial",
    "transformed",
    "ulp",
    "dense",
)
SEED_FILE = REPO / "corpus" / "cases" / "seed.jsonl"
GEN_REVIEW = REPO / "tools" / "oracle_review" / "gen_review.py"

#: Predicates the polygon references define (crosses is false for A/A by dispatch).
AREAL_PREDICATES = (
    "intersects",
    "disjoint",
    "touches",
    "overlaps",
    "contains",
    "covers",
    "within",
    "covered_by",
    "equals",
)
ENTRIES = tuple(r + c for r in "IBE" for c in "IBE")

#: GEOS is consulted only when every ordinate is an integer below this in magnitude.
GEOS_LATTICE_LIMIT = 2**20
#: GEOS locates a scaled witness exactly while coordinates stay below this.
GEOS_EXACT_LIMIT = 2**25


# ============================================================================ cases


@dataclass
class XCase:
    """One cross-check case. ``expected`` is a stated matrix (fixtures); ``base`` is the
    matrix the case must reproduce because it is an exact affine image of another case."""

    id: str
    source: str
    family: str
    a: Geometry
    b: Geometry
    expected: str | None = None
    base: tuple[Geometry, Geometry] | None = None
    note: str = ""


def fixture_cases() -> Iterator[XCase]:
    from unit.fixtures_arrangement import FIXTURES

    for name, spec in FIXTURES.items():
        yield XCase(
            f"fixture-{name}",
            "fixtures",
            name,
            read_wkt(spec.a),
            read_wkt(spec.b),
            expected=spec.relate,
        )


def seed_cases(path: Path = SEED_FILE, step: int = 1) -> Iterator[XCase]:
    with open(path, encoding="utf-8") as fh:
        lines = [ln for ln in fh if ln.strip()]
    for line in lines[::step]:
        c = case_from_json(json_loads(line))
        yield XCase(c.id, "seed", c.family or c.id.rsplit("-", 1)[0], c.a, c.b)


def review_cases(n: int = 50, seed: int = 1) -> Iterator[XCase]:
    """The oracle-review families (needs Shapely, which the generator uses)."""
    out = subprocess.run(
        [sys.executable, str(GEN_REVIEW), "all", str(n), str(seed)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    for line in out.splitlines():
        if line.strip():
            c = case_from_json(json_loads(line))
            fam = c.id.rsplit("-", 2)[0]
            yield XCase(f"review-{c.id}", "review", fam, c.a, c.b)


def lattice_cases(count: int, seed: int = 1, n: int = 4) -> Iterator[XCase]:
    """Every ordered pair of the eight lattice types, round robin (witness_lattice),
    and every fifth case a pair of arrangement_testlib operands."""
    from unit.arrangement_testlib import random_operand
    from unit.witness_lattice import random_pair

    rng = random.Random(seed)
    for i in range(count):
        if i % 5 == 4:
            a, b = random_operand(rng, 6), random_operand(rng, 6)
            yield XCase(f"lattice-{seed}-{i}", "lattice", "testlib", a, b)
        else:
            ta, tb, a, b = random_pair(rng, i, n)
            yield XCase(f"lattice-{seed}-{i}", "lattice", f"{ta}/{tb}", a, b)


# ------------------------------------------------------------- adversarial generator

Coord = tuple[float, float]


def _pt(rng: random.Random, n: int) -> Coord:
    """A point of the even lattice 2*[0, n] (so every edge midpoint is an integer)."""
    return float(2 * rng.randint(0, n)), float(2 * rng.randint(0, n))


def _closed(ring: list[Coord]) -> list[Coord]:
    return [*ring, ring[0]]


def _rect(rng: random.Random, n: int) -> list[Coord]:
    x0, x1 = sorted(rng.sample(range(n + 1), 2))
    y0, y1 = sorted(rng.sample(range(n + 1), 2))
    return [(2.0 * x0, 2.0 * y0), (2.0 * x1, 2.0 * y0), (2.0 * x1, 2.0 * y1), (2.0 * x0, 2.0 * y1)]


def _star(rng: random.Random, n: int) -> list[Coord] | None:
    pts = list({_pt(rng, n) for _ in range(rng.randint(3, 6))})
    if len(pts) < 3:
        return None
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))  # float only orders a candidate
    return pts


def _ring(rng: random.Random, n: int) -> list[Coord] | None:
    ring = _rect(rng, n) if rng.random() < 0.4 else _star(rng, n)
    if ring is None:
        return None
    if rng.random() < 0.5:
        ring = ring[::-1]
    k = rng.randrange(len(ring))
    return _closed(ring[k:] + ring[:k])


def in_contract(g: Geometry) -> bool:
    """Input the exact routes are defined on: every polygonal unit valid (reference
    validity R0-R6), lines and points anything (zero-length lines included, DESIGN §1)."""
    from reference import validity

    if isinstance(g, GeometryCollection):
        return all(in_contract(e) for e in g.geometries)
    if isinstance(g, Polygon | MultiPolygon):
        polys = [g] if isinstance(g, Polygon) else [p for p in g.polygons if not p.is_empty]
        polys = [p for p in polys if not p.is_empty]
        if not polys:
            return True
        return bool(validity.valid_geometry([[list(r) for r in p.rings] for p in polys]))
    return True


def geos_valid(g: Geometry) -> bool:
    """GEOS-default validity (exact): in contract, and no zero-length lines."""
    if not in_contract(g):
        return False
    return all(
        e.is_empty or not e.is_zero_length for e in g.elements() if isinstance(e, LineString)
    )


def adv_polygon(rng: random.Random, n: int) -> Polygon:
    while True:
        shell = _ring(rng, n)
        if shell is None:
            continue
        rings = [shell]
        r = rng.random()
        if r < 0.3:
            hole = _ring(rng, n)
            if hole is not None:
                rings.append(hole)
        elif r < 0.45:  # a hole touching the shell at a vertex
            v = shell[rng.randrange(len(shell) - 1)]
            q1, q2 = _pt(rng, n), _pt(rng, n)
            rings.append(_closed([v, q1, q2]))
        p = Polygon(rings)
        if in_contract(p):
            return p


def adv_multipolygon(rng: random.Random, n: int) -> MultiPolygon:
    for _ in range(200):
        first = adv_polygon(rng, n)
        if rng.random() < 0.5:  # a second part touching the first at a vertex
            v = first.shell[rng.randrange(len(first.shell) - 1)]
            second = Polygon([_closed([v, _pt(rng, n), _pt(rng, n)])])
        else:
            second = adv_polygon(rng, n)
        mp = MultiPolygon([first, second])
        if in_contract(mp):
            return mp
    return MultiPolygon([adv_polygon(rng, n)])


def adv_line(rng: random.Random, n: int) -> LineString:
    while True:
        pts = [_pt(rng, n) for _ in range(rng.randint(2, 4))]
        r = rng.random()
        if r < 0.15:
            pts.append(pts[0])  # closed
        elif r < 0.25:
            pts.append(pts[-2])  # retraces its last segment
        elif r < 0.35 and len(pts) >= 3:  # ends on its own interior (a "6")
            a, b = pts[0], pts[1]
            pts.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
        elif r < 0.45:
            pts.insert(1, pts[0])  # a repeated point
        if len(set(pts)) >= 2:
            return LineString(pts)


def adv_multiline(rng: random.Random, n: int) -> MultiLineString:
    lines = [adv_line(rng, n) for _ in range(rng.randint(2, 3))]
    if rng.random() < 0.4:  # share an endpoint between elements (degree 2 or 3)
        end = lines[0].coords[-1]
        lines[1] = LineString([end, *lines[1].coords[1:]])
    if rng.random() < 0.2:  # a zero-length element (the line keeps real dimension 1)
        lines.append(LineString([_pt(rng, n)] * 2))
    return MultiLineString(lines)


def adv_points(rng: random.Random, n: int) -> Geometry:
    pts = [_pt(rng, n) for _ in range(rng.randint(1, 4))]
    if len(pts) == 1:
        return Point(pts[0])
    if rng.random() < 0.2:
        pts.append(pts[0])  # a repeated point
    return MultiPoint(pts)


def adv_zero_length(rng: random.Random, n: int) -> Geometry:
    p = _pt(rng, n)
    r = rng.random()
    if r < 0.4:
        return LineString([p, p])
    if r < 0.6:
        return LineString([p])  # a single-point line
    if r < 0.8:
        return MultiLineString([LineString([p, p]), LineString([_pt(rng, n)] * 3)])
    return GeometryCollection([LineString([p, p]), Point(_pt(rng, n))])


EMPTIES = (
    "POINT EMPTY",
    "LINESTRING EMPTY",
    "POLYGON EMPTY",
    "MULTIPOLYGON EMPTY",
    "GEOMETRYCOLLECTION EMPTY",
    "GEOMETRYCOLLECTION (POINT EMPTY, LINESTRING EMPTY)",
)


def adv_basic(rng: random.Random, n: int) -> Geometry:
    kind = rng.choice(("P", "P", "L", "ML", "A", "A", "MA", "GC", "GC", "ZL"))
    return ADV_KINDS[kind](rng, n)


def adv_collection(rng: random.Random, n: int) -> GeometryCollection:
    parts: list[Geometry] = []
    for _ in range(rng.randint(2, 3)):
        r = rng.random()
        if r < 0.15:
            parts.append(GeometryCollection([adv_basic(rng, n), adv_points(rng, n)]))  # nested
        elif r < 0.25:
            parts.append(adv_multipolygon(rng, n))
        elif r < 0.3:
            parts.append(read_wkt(rng.choice(EMPTIES)))
        else:
            parts.append(rng.choice((adv_polygon, adv_line, adv_points, adv_multiline))(rng, n))
    return GeometryCollection(parts)


ADV_KINDS: dict[str, Callable[[random.Random, int], Geometry]] = {
    "P": adv_points,
    "L": adv_line,
    "ML": adv_multiline,
    "A": adv_polygon,
    "MA": adv_multipolygon,
    "GC": adv_collection,
    "ZL": adv_zero_length,
}


def _rings(g: Geometry) -> list[list[Coord]]:
    return [list(r.coords) for r in g.iter_rings() if r.coords]


def _paths(g: Geometry) -> list[list[Coord]]:
    """Every ring and line of ``g`` as a coordinate list."""
    return _rings(g) + [list(c) for _, c in g.iter_lines()]


def _mid(p: Coord, q: Coord) -> Coord:
    return ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2)


def _reexpress(g: Geometry, rng: random.Random) -> Geometry:
    """The same point set with rotated or reversed rings, extra collinear vertices
    (edge midpoints) and reversed lines."""

    def ring(r: tuple[Coord, ...]) -> list[Coord]:
        pts = list(r[:-1])
        if rng.random() < 0.5:
            pts = pts[::-1]
        k = rng.randrange(len(pts))
        pts = pts[k:] + pts[:k]
        if rng.random() < 0.5:
            i = rng.randrange(len(pts))
            pts.insert(i + 1, _mid(pts[i], pts[(i + 1) % len(pts)]))
        return _closed(pts)

    def fn(e: Geometry) -> Geometry:
        if isinstance(e, Polygon) and not e.is_empty:
            return Polygon([ring(r) for r in e.rings])
        if isinstance(e, LineString) and len(e.coords) >= 2:
            c = list(e.coords)
            if rng.random() < 0.5:
                c = c[::-1]
            if rng.random() < 0.5 and c[0] != c[1]:
                c.insert(1, _mid(c[0], c[1]))
            return LineString(c)
        return e

    return _map_elements(g, fn)


def _map_elements(g: Geometry, fn: Callable[[Geometry], Geometry]) -> Geometry:
    if isinstance(g, GeometryCollection):
        return GeometryCollection([_map_elements(x, fn) for x in g.geometries])
    if isinstance(g, MultiPolygon):
        return MultiPolygon([fn(p) for p in g.polygons])
    if isinstance(g, MultiLineString):
        return MultiLineString([fn(x) for x in g.lines])
    if isinstance(g, MultiPoint):
        return MultiPoint([fn(p) for p in g.points])
    return fn(g)


def derived(rng: random.Random, a: Geometry, n: int) -> Geometry | None:
    """A geometry built from ``a``'s own vertices and edges (maximal degeneracy)."""
    paths = _paths(a)
    verts = [c for p in paths for c in p] + [c for _, c in a.iter_points()]
    how = rng.choice(
        ("boundary", "path", "vertices", "same", "shift", "hole", "extend", "gc", "mirror")
    )
    if how == "boundary" and _rings(a):
        rings = _rings(a)
        if rng.random() < 0.5:
            return LineString(rng.choice(rings))
        return MultiLineString(rings)
    if how == "path" and paths:
        p = rng.choice(paths)
        if len(p) >= 2:
            i = rng.randrange(len(p) - 1)
            j = rng.randrange(i + 1, len(p))
            sub = list(p[i : j + 1])
            if rng.random() < 0.4:
                sub[0] = _mid(p[i], p[i + 1])
            if len(set(sub)) >= 2:
                return LineString(sub)
    if how == "vertices" and verts:
        pts = rng.sample(verts, min(len(verts), rng.randint(1, 4)))
        for p in paths:
            if len(p) >= 2 and rng.random() < 0.5:
                k = rng.randrange(len(p) - 1)
                pts.append(_mid(p[k], p[k + 1]))
        return Point(pts[0]) if len(pts) == 1 else MultiPoint(pts)
    if how == "same":
        return _reexpress(a, rng)
    if how == "shift":
        dx, dy = rng.choice((-2, 0, 2)), rng.choice((-2, 0, 2))
        return a.map_coords(lambda c: (c[0] + dx, c[1] + dy))
    if how == "hole":
        holes = [r.coords for r in a.iter_rings() if r.tag.is_hole and r.coords]
        if holes:
            return Polygon([rng.choice(holes)])
    if how == "extend" and paths:
        p = rng.choice(paths)
        if len(p) >= 2:
            k = rng.randrange(len(p) - 1)
            (x0, y0), (x1, y1) = p[k], p[k + 1]
            if (x0, y0) != (x1, y1):
                s, t = rng.choice((0.5, 1.0, -1.0)), rng.choice((0.5, 2.0, 0.0, 1.0))
                q0 = (x0 + s * (x1 - x0), y0 + s * (y1 - y0))
                q1 = (x0 + t * (x1 - x0), y0 + t * (y1 - y0))
                if q0 != q1:
                    return LineString([q0, q1])
    if how == "gc":
        return GeometryCollection([_reexpress(a, rng), adv_basic(rng, n)])
    if how == "mirror" and verts:
        m = 2 * rng.randint(0, n)
        return a.map_coords(lambda c: (m - c[0], c[1]))
    return None


def adversarial_pair(rng: random.Random, i: int, n: int = 3) -> tuple[str, Geometry, Geometry]:
    """The ``i``-th adversarial case: (family, A, B)."""
    kinds = tuple(ADV_KINDS)
    while True:
        r = rng.random()
        if r < 0.08:
            a = read_wkt(rng.choice(EMPTIES))
            b = ADV_KINDS[rng.choice(kinds)](rng, n)
            fam = "empty"
        elif r < 0.55:
            ka = kinds[i % len(kinds)]
            a = ADV_KINDS[ka](rng, n)
            b = derived(rng, a, n)
            if b is None:
                continue
            fam = f"derived-{ka}"
        else:
            ka, kb = kinds[i % len(kinds)], kinds[(i // len(kinds)) % len(kinds)]
            a, b = ADV_KINDS[ka](rng, n), ADV_KINDS[kb](rng, n)
            fam = f"{ka}/{kb}"
        if rng.random() < 0.5:
            a, b = b, a
        if in_contract(a) and in_contract(b):
            return fam, a, b


def adversarial_cases(count: int, seed: int = 1, n: int = 3) -> Iterator[XCase]:
    rng = random.Random(seed)
    for i in range(count):
        fam, a, b = adversarial_pair(rng, i, n)
        yield XCase(f"adversarial-{seed}-{i}", "adversarial", fam, a, b)


# ---------------------------------------------------------------- exact transforms


def _affine(rng: random.Random) -> tuple[str, Callable[[Any], Any]]:
    """A random invertible affine map with exact coefficients (it preserves relate)."""
    kind = rng.choice(("rational", "scale-small", "scale-large", "swap", "translate"))
    if kind == "rational":
        while True:
            m = [Fraction(rng.randint(-4, 4), rng.choice((1, 3, 5, 7))) for _ in range(4)]
            if m[0] * m[3] - m[1] * m[2] != 0:
                break
        t = (Fraction(rng.randint(-9, 9), 11), Fraction(rng.randint(-9, 9), 13))

        def f(c: Any) -> Any:
            x, y = Fraction(c[0]), Fraction(c[1])
            return (m[0] * x + m[1] * y + t[0], m[2] * x + m[3] * y + t[1])

        return f"rational {m} + {t}", f
    if kind == "scale-small":
        k = rng.randint(1060, 1070)  # subnormal doubles (lattice coordinates <= 16)
        return f"scale 2**-{k}", lambda c: (math.ldexp(c[0], -k), math.ldexp(c[1], -k))
    if kind == "scale-large":
        k = rng.randint(900, 1000)
        return f"scale 2**{k}", lambda c: (math.ldexp(c[0], k), math.ldexp(c[1], k))
    if kind == "swap":
        if rng.random() < 0.5:
            return "swap axes", lambda c: (c[1], c[0])
        return "swap rotate90", lambda c: (-c[1], c[0])
    off = (float(2**52), float(-(2**40)))
    return f"translate {off}", lambda c: (c[0] + off[0], c[1] + off[1])


def _grid_shapes(k: int = 2) -> dict[str, list[Geometry]]:
    """Every point, segment, triangle and two-segment path on the grid {0..k}^2."""
    pts = [(float(x), float(y)) for x in range(k + 1) for y in range(k + 1)]
    segs = [LineString([p, q]) for p, q in itertools.combinations(pts, 2)]
    tris = []
    for p, q, r in itertools.combinations(pts, 3):
        if (q[0] - p[0]) * (r[1] - p[1]) != (q[1] - p[1]) * (r[0] - p[0]):
            tris.append(Polygon([[p, q, r, p]]))
    paths = [
        LineString([p, q, r])
        for p, q, r in itertools.permutations(pts, 3)
        if p < r and len({p, q, r}) == 3
    ]
    return {"P": [Point(p) for p in pts], "L": segs, "A": tris, "L2": paths}


def exhaustive_cases(limit: int = 0) -> Iterator[XCase]:
    """Every pair (triangle, point | segment | triangle) on the 3x3 grid, then GCs of two
    triangles, and two-segment paths against segments and triangles: all the small exact
    degeneracies, systematically. ``limit`` > 0 takes an even stride through the list."""
    sh = _grid_shapes()
    pairs: list[tuple[str, Geometry, Geometry]] = []
    for a in sh["A"]:
        pairs += [("A/P", a, b) for b in sh["P"]]
        pairs += [("A/L", a, b) for b in sh["L"]]
        pairs += [("A/A", a, b) for b in sh["A"]]
    tris = sh["A"]
    for i, t1 in enumerate(tris):
        for t2 in tris[i + 1 :: 7]:
            gc = GeometryCollection([t1, t2])
            pairs += [("GC/P", gc, b) for b in sh["P"]]
            pairs += [("GC/L", gc, b) for b in sh["L"][::5]]
    for path in sh["L2"]:
        pairs += [("L2/L", path, b) for b in sh["L"][::3]]
        pairs += [("L2/A", path, b) for b in tris[::5]]
    step = max(1, len(pairs) // limit) if limit else 1
    for i, (fam, a, b) in enumerate(pairs[::step]):
        yield XCase(f"exhaustive-{i}", "exhaustive", fam, a, b)


def _ulp_map(rng: random.Random, g1: Geometry, g2: Geometry) -> tuple[str, Callable]:
    """A coordinate map that breaks exact degeneracies at the scale of one ulp: a float
    rotation (rounded), or a nudge of chosen coordinate *values* by one ulp (applied to
    every occurrence, so rings stay closed and shared vertices stay shared)."""
    if rng.random() < 0.4:
        t = rng.uniform(0, 2 * math.pi)
        c, s_ = math.cos(t), math.sin(t)
        return f"rotate {t!r}", lambda p: (p[0] * c - p[1] * s_, p[0] * s_ + p[1] * c)
    values = sorted({float(v) for g in (g1, g2) for v in g.iter_values()})
    xs = {
        v: math.nextafter(v, rng.choice((math.inf, -math.inf)))
        for v in values
        if rng.random() < 0.3
    }
    ys = {
        v: math.nextafter(v, rng.choice((math.inf, -math.inf)))
        for v in values
        if rng.random() < 0.3
    }
    return "nudge", lambda p: (xs.get(float(p[0]), float(p[0])), ys.get(float(p[1]), float(p[1])))


def ulp_cases(count: int, seed: int = 1) -> Iterator[XCase]:
    """Near-degenerate images of lattice and adversarial cases: exact degeneracies (a
    point on an edge, collinear overlaps, shared vertices of different elements) turn into
    ulp-level near-misses or crossings. The images are not exact, so only agreement of the
    two exact routes is required (and only in-contract images are kept)."""
    rng = random.Random(seed)
    lat = lattice_cases(4 * count, seed + 3000)
    adv = adversarial_cases(4 * count, seed + 4000)
    made = 0
    for base in _interleave(lat, adv):
        if made >= count:
            return
        name, f = _ulp_map(rng, base.a, base.b)
        a, b = base.a.map_coords(f), base.b.map_coords(f)
        if not (in_contract(a) and in_contract(b)):
            continue
        yield XCase(f"ulp-{seed}-{made}", "ulp", name.split()[0], a, b, note=f"{name} of {base.id}")
        made += 1


def stacked_collection(rng: random.Random, n: int = 4) -> GeometryCollection:
    """A GC of 3-5 polygons stacked on each other (coverage up to 5, holes filled by
    other elements, identical copies) with lines and points on their boundaries."""
    polys = [adv_polygon(rng, n) for _ in range(rng.randint(3, 5))]
    if rng.random() < 0.3:
        polys.append(polys[0])  # an identical copy
    parts: list[Geometry] = list(polys)
    ring = polys[0].shell
    if rng.random() < 0.5:
        parts.append(LineString(ring[: rng.randint(2, len(ring))]))
    if rng.random() < 0.5:
        parts.append(MultiPoint(list(ring[:-1])))
    rng.shuffle(parts)
    return GeometryCollection(parts)


def dense_cases(count: int, seed: int = 1) -> Iterator[XCase]:
    """Bigger inputs: 8x8 lattice pairs of every type pair, larger testlib operands, and
    stacked GCs against anything."""
    from unit.arrangement_testlib import random_operand
    from unit.witness_lattice import random_pair

    rng = random.Random(seed)
    for i in range(count):
        k = i % 3
        if k == 0:
            ta, tb, a, b = random_pair(rng, i // 3, 8)
            fam = f"{ta}/{tb}"
        elif k == 1:
            a, b, fam = random_operand(rng, 12), random_operand(rng, 12), "testlib-12"
        else:
            a = stacked_collection(rng)
            b = rng.choice((stacked_collection, adv_basic, adv_multiline))(rng, 4)
            fam = "stacked"
            if not (in_contract(a) and in_contract(b)):
                continue
        yield XCase(f"dense-{seed}-{i}", "dense", fam, a, b)


def transformed_cases(count: int, seed: int = 1) -> Iterator[XCase]:
    rng = random.Random(seed)
    lat = lattice_cases(count, seed + 1000)
    adv = adversarial_cases(count, seed + 2000)
    for i, base in enumerate(itertools.islice(_interleave(lat, adv), count)):
        name, f = _affine(rng)
        a, b = base.a.map_coords(f), base.b.map_coords(f)
        yield XCase(
            f"transformed-{seed}-{i}",
            "transformed",
            name.split()[0],
            a,
            b,
            base=(base.a, base.b),
            note=f"{name} of {base.id}",
        )


def _interleave(*its: Iterable[XCase]) -> Iterator[XCase]:
    for group in itertools.zip_longest(*its):
        for x in group:
            if x is not None:
                yield x


# ============================================================================ routes


def polygonal(g: Geometry) -> bool:
    return isinstance(g, Polygon | MultiPolygon) and not g.is_empty


def legacy(g: Geometry) -> list:
    """A (Multi)Polygon as FORMAT-v1 nested lists (the references' input)."""
    polys = [g] if isinstance(g, Polygon) else [p for p in g.polygons if not p.is_empty]
    return [[[[float(x), float(y)] for x, y in ring] for ring in p.rings] for p in polys]


def _float_coords(g: Geometry) -> bool:
    return all(isinstance(v, float) for v in g.iter_values())


def geos_eligible(a: Geometry, b: Geometry) -> bool:
    """Small-integer lattice cases of GEOS-valid operands (see the module docstring)."""
    for g in (a, b):
        for v in g.iter_values():
            if not (isinstance(v, float | int) and float(v).is_integer()):
                return False
            if abs(v) >= GEOS_LATTICE_LIMIT:
                return False
        if not geos_valid(g):
            return False
    return True


def _shapely():
    try:
        import shapely
    except ImportError:
        return None
    return shapely


#: The GEOS server: one JSON request per line on stdin, one JSON answer per line.
_GEOS_SERVER = r"""
import json, sys
import shapely

def loc(m):
    return 0 if m[0] != "F" else 1 if m[1] != "F" else 2

for line in sys.stdin:
    req = json.loads(line)
    try:
        if req["op"] == "relate":
            a, b = shapely.from_wkt(req["a"]), shapely.from_wkt(req["b"])
            res = {"m": shapely.relate(a, b)}
        elif req["op"] == "locate":
            gs = [shapely.from_wkt(w) for w in req["geoms"]]
            res = {"locs": [[loc(shapely.relate(shapely.Point(x, y), g)) for g in gs]
                            for x, y in req["points"]]}
        else:
            res = {"v": shapely.geos_version_string}
    except Exception as exc:
        res = {"error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(res) + "\n")
    sys.stdout.flush()
"""


class GeosCrash(RuntimeError):
    """GEOS killed its process (a segfault or abort) or hung on a request."""


class GeosWorker:
    """GEOS (through Shapely) in a separate process, restarted after a crash, so that a
    GEOS segfault is recorded as a finding instead of ending the run."""

    def __init__(self, timeout: float = 60.0) -> None:
        self.timeout = timeout
        self.proc: subprocess.Popen | None = None
        self.crashes = 0

    def _start(self) -> subprocess.Popen:
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen(
                [sys.executable, "-c", _GEOS_SERVER],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        return self.proc

    def call(self, req: dict[str, Any]) -> dict[str, Any]:
        import select

        proc = self._start()
        assert proc.stdin is not None and proc.stdout is not None
        try:
            proc.stdin.write(json.dumps(req) + "\n")
            proc.stdin.flush()
            ready, _, _ = select.select([proc.stdout], [], [], self.timeout)
            line = proc.stdout.readline() if ready else ""
        except (BrokenPipeError, OSError):
            line = ""
        if not line:
            if proc.poll() is None:
                proc.kill()
            proc.wait()
            self.crashes += 1
            self.proc = None
            code = proc.returncode
            what = "hang" if code == -9 else f"signal {-code}" if code < 0 else f"exit {code}"
            raise GeosCrash(what)
        out = json.loads(line)
        if "error" in out:
            raise RuntimeError(out["error"])
        return out

    def relate(self, a: str, b: str) -> str:
        return self.call({"op": "relate", "a": a, "b": b})["m"]

    def locate(self, geoms: list[str], points: list[tuple[float, float]]) -> list[list[int]]:
        return self.call({"op": "locate", "geoms": geoms, "points": points})["locs"]

    def version(self) -> str:
        return self.call({"op": "version"})["v"]

    def close(self) -> None:
        if self.proc is not None and self.proc.poll() is None:
            self.proc.kill()
            self.proc.wait()
        self.proc = None


_GEOS: GeosWorker | None = None


def geos() -> GeosWorker:
    """The process-wide GEOS worker."""
    global _GEOS
    if _GEOS is None:
        _GEOS = GeosWorker()
    return _GEOS


def geos_relate(a: Geometry, b: Geometry) -> str:
    """GEOS's matrix; raises :class:`GeosCrash` when GEOS crashes."""
    return geos().relate(to_wkt(a), to_wkt(b))


def _scaled_wkt(g: Geometry, frame: Frame, k: int) -> str:
    """``g`` in the integer frame, multiplied by ``k`` (doubles holding integers)."""

    def f(c: Any) -> Any:
        x, y = frame.to_int_point(c)
        return float(x * k), float(y * k)

    return to_wkt(g.map_coords(f))


def _fits(res: WitnessRelate, a: Geometry, b: Geometry, k: int, ws: list) -> bool:
    """True when the case scaled by ``k`` and the witnesses ``ws`` (weight ``k``) stay
    below :data:`GEOS_EXACT_LIMIT`, so that GEOS locates them exactly."""
    coords = [res.frame.to_int_point(c) for g in (a, b) for c in g.iter_coords()]
    top = max((max(abs(x), abs(y)) for x, y in coords), default=0) + 1
    biggest = max((max(abs(w.point[0]), abs(w.point[1])) for w in ws), default=0)
    return top * k < GEOS_EXACT_LIMIT and biggest < GEOS_EXACT_LIMIT


def geos_locate_witnesses(
    res: WitnessRelate, a: Geometry, b: Geometry, witnesses: list | None = None
) -> list[tuple[Any, int, int]] | None:
    """``(witness, GEOS location in A, GEOS location in B)`` for the witnesses of ``res``
    (or the given subset), each located by GEOS's point locator with the case scaled by
    the witness weight so that every coordinate is an integer. None when a scaled
    coordinate is too large for GEOS to locate exactly."""
    by_w: dict[int, list] = {}
    for w in res.witnesses if witnesses is None else witnesses:
        by_w.setdefault(w.point[2], []).append(w)
    out = []
    for k, ws in by_w.items():
        if not _fits(res, a, b, k, ws):
            return None
        pts = [(float(w.point[0]), float(w.point[1])) for w in ws]
        geoms = [_scaled_wkt(a, res.frame, k), _scaled_wkt(b, res.frame, k)]
        out += [(w, la, lb) for w, (la, lb) in zip(ws, geos().locate(geoms, pts), strict=True)]
    return out


def geos_located_matrix(res: WitnessRelate, a: Geometry, b: Geometry) -> str | None:
    """The matrix of the witnesses of ``res`` with GEOS's point locations (None when too
    large to locate exactly)."""
    located = geos_locate_witnesses(res, a, b)
    if located is None:
        return None
    return _matrix_of((w.dim, la, lb) for w, la, lb in located)


def _matrix_of(cells: Iterable[tuple[int, int, int]]) -> str:
    dims = [[-1] * 3 for _ in range(3)]
    for d, la, lb in cells:
        dims[la][lb] = max(dims[la][lb], d)
    dims[2][2] = 2
    return "".join("F" if d < 0 else str(d) for row in dims for d in row)


def _partial_confirmation(
    res: WitnessRelate, a: Geometry, b: Geometry, ours: str, theirs: str
) -> bool:
    """For a case too large to locate every witness exactly: True if every entry where
    GEOS differs is one GEOS reports empty (F) while GEOS's own point locator puts one of
    our witnesses there (the smallest-weight witness of that entry that fits)."""
    for i in range(9):
        if ours[i] == theirs[i]:
            continue
        if theirs[i] != "F":
            return False
        label = (i // 3, i % 3)
        cands = sorted(
            (w for w in res.witnesses if (w.loc_a, w.loc_b) == label),
            key=lambda w: (w.point[2], abs(w.point[0]) + abs(w.point[1])),
        )
        cands = [w for w in cands if _fits(res, a, b, w.point[2], [w])][:3]
        located = geos_locate_witnesses(res, a, b, cands) if cands else None
        if not located or not any((la, lb) == label for _, la, lb in located):
            return False
    return True


def _polygon_boundaries_through(g: Geometry, p: tuple[Fraction, Fraction]) -> int:
    """How many polygon elements of ``g`` have ``p`` on their boundary (exact)."""
    from geotruth.exact import on_segment

    n = 0
    for e in g.elements():
        if isinstance(e, Polygon) and not e.is_empty:
            rings = [[(Fraction(x), Fraction(y)) for x, y in r] for r in e.rings if r]
            if any(on_segment(p, u, v) for r in rings for u, v in itertools.pairwise(r)):
                n += 1
    return n


def judge_point_location(
    res: WitnessRelate, a: Geometry, b: Geometry, located: list[tuple[Any, int, int]]
) -> str:
    """GEOS's point locator disagrees with ours on some witnesses. A third exact
    locator decides: the brute-force DESIGN §1 locator of ``tests/unit/arrangement_testlib``
    (E1's, independent of :mod:`geotruth.locate`). If it agrees with ours on every
    disputed witness, GEOS's point location is wrong there; the class says where
    (``gc-adjacent-edge``: the point lies on the boundaries of two or more polygon
    elements of one operand, RelateNG's AdjacentEdgeLocator case)."""
    from unit.arrangement_testlib import BruteLocator

    brute = (BruteLocator(a), BruteLocator(b))
    where = set()
    for w, la, lb in located:
        if (la, lb) == (w.loc_a, w.loc_b):
            continue
        p = res.frame.to_fractions(w.point)
        if (int(brute[0].locate(p)), int(brute[1].locate(p))) != (w.loc_a, w.loc_b):
            return "UNEXPLAINED (GEOS and the brute-force locator both differ from ours)"
        for g, mine, theirs in ((a, w.loc_a, la), (b, w.loc_b, lb)):
            if mine != theirs:
                multi = _polygon_boundaries_through(g, p) >= 2
                where.add("gc-adjacent-edge" if multi else "other")
    return "geos-point-location (" + ", ".join(sorted(where)) + ")"


def _mixed(g: Geometry) -> bool:
    kinds = {e.geom_type for e in g.elements() if not e.is_empty}
    return isinstance(g, GeometryCollection) and len(kinds) > 1


def _num_lines(g: Geometry) -> int:
    return sum(1 for e in g.elements() if isinstance(e, LineString) and not e.is_empty)


def _gc_polygons(g: Geometry) -> int:
    if not isinstance(g, GeometryCollection):
        return 0
    return sum(1 for e in g.elements() if isinstance(e, Polygon) and not e.is_empty)


def _has_ring_touch(g: Geometry) -> bool:
    from geotruth.exact import on_segment

    frame = Frame.for_geometries(g)
    rings = [[frame.to_int_point(c) for c in r.coords] for r in g.iter_rings() if r.coords]
    for i, r in enumerate(rings):
        for j, other in enumerate(rings):
            if i != j and any(
                on_segment(v, p, q) for v in set(r) for p, q in itertools.pairwise(other)
            ):
                return True
    return False


def classify_geos(a: Geometry, b: Geometry, ours: str, theirs: str, res: WitnessRelate) -> str:
    """The GEOS 3.13 RelateNG defect class of a confirmed disagreement, by signature
    (the same classes as tests/crosscheck/test_witness_vs_geos.py)."""
    diff = {ENTRIES[i] for i in range(9) if ours[i] != theirs[i]}
    lost_ends = all(ours[ENTRIES.index(e)] == "0" and theirs[ENTRIES.index(e)] == "F" for e in diff)
    if diff <= {"BE", "EB"} and lost_ends and max(_num_lines(a), _num_lines(b)) >= 2:
        return "line-end-skip"
    if max(_gc_polygons(a), _gc_polygons(b)) >= 2:
        return "gc-overlapping-polygons"
    if _mixed(a) or _mixed(b):
        return "mixed-gc"
    if _has_ring_touch(a) or _has_ring_touch(b):
        return "ring-touch-node"
    if any(w.kind == "intersection" and w.point[2] & (w.point[2] - 1) for w in res.witnesses):
        return "inexact-node"
    if _empty_raises_dimension(a) or _empty_raises_dimension(b):
        return "empty-element-dimension"
    return "other"


def _empty_raises_dimension(g: Geometry) -> bool:
    """An empty element gives ``g`` a type dimension above the dimension of its point
    set (``GC (LINESTRING (...), POLYGON EMPTY)``): GEOS then infers exterior
    interactions from the type dimension (IE = 2 for a line)."""
    from geotruth.relate import effective_dimension

    return g.dimension > effective_dimension(g)


# ============================================================================ checks


@dataclass
class Report:
    """The outcome of one case."""

    id: str
    source: str
    family: str
    types: tuple[str, str]
    arrangement: str | None = None  # matrix, or None
    arrangement_status: str = "ok"
    witness: str | None = None
    witness_error: str | None = None
    invalid_input: str | None = None
    exact_agree: bool | None = None
    predicates_agree: bool | None = None
    expected: str | None = None  # fixture or affine-invariance matrix
    expected_agree: bool | None = None
    oracle_agree: bool | None = None
    indep_agree: bool | None = None
    geos: str | None = None
    geos_verdict: str | None = None  # None (agree / not asked), a defect class, UNEXPLAINED
    problems: list[str] = field(default_factory=list)
    t_arrangement: float = 0.0
    t_witness: float = 0.0
    wkt: tuple[str, str] | None = None

    @property
    def failed(self) -> bool:
        return bool(self.problems)


def check_case(xc: XCase, *, use_geos: bool = True, witness_check: bool = True) -> Report:
    """Run every applicable route on one case and compare."""
    a, b = xc.a, xc.b
    rep = Report(xc.id, xc.source, xc.family, (a.geom_type, b.geom_type))
    t = time.perf_counter()
    try:
        res = relate(a, b, strict=False)
    except InvalidInputError as exc:
        rep.invalid_input = str(exc)
        rep.problems.append(f"arrangement refused the input: {exc}")
        rep.wkt = (_wkt(a), _wkt(b))
        return rep
    rep.t_arrangement = time.perf_counter() - t
    rep.arrangement_status = res.status
    rep.arrangement = res.matrix
    if not res.ok:
        rep.problems.append(f"arrangement route: {res.status}: {res.reason}")
    t = time.perf_counter()
    wres: WitnessRelate | None = None
    try:
        wres = relate_witness(a, b, check=witness_check)
        rep.witness = wres.matrix
    except Exception as exc:  # an engine bug on the witness side
        rep.witness_error = f"{type(exc).__name__}: {exc}"
        rep.problems.append(f"witness route raised {rep.witness_error}")
    rep.t_witness = time.perf_counter() - t

    if rep.arrangement is not None and rep.witness is not None:
        rep.exact_agree = rep.arrangement == rep.witness
        if not rep.exact_agree:
            rep.problems.append(
                f"routes disagree: arrangement {rep.arrangement}, witness {rep.witness}"
            )
        ours = res.predicates
        theirs = {k: v.value for k, v in wres.predicates().items()}
        rep.predicates_agree = ours == theirs
        if not rep.predicates_agree and rep.exact_agree:
            rep.problems.append("predicates differ although the matrices agree")
    matrix = rep.arrangement if rep.arrangement is not None else rep.witness

    # a stated matrix (fixtures) or the matrix of the untransformed case
    if xc.expected is not None:
        rep.expected = xc.expected
    elif xc.base is not None:
        base = relate(*xc.base, strict=False)
        rep.expected = base.matrix
    if rep.expected is not None and matrix is not None:
        rep.expected_agree = rep.arrangement == rep.expected and rep.witness == rep.expected
        if not rep.expected_agree:
            rep.problems.append(
                f"expected {rep.expected} ({xc.note or 'stated'}), got "
                f"{rep.arrangement} / {rep.witness}"
            )

    # the polygon references
    if (
        matrix is not None
        and polygonal(a)
        and polygonal(b)
        and _float_coords(a)
        and _float_coords(b)
    ):
        _check_references(rep, a, b, matrix)

    # GEOS on small-integer lattices
    if use_geos and matrix is not None and _shapely() is not None and geos_eligible(a, b):
        _check_geos(rep, a, b, matrix)
    if rep.problems or rep.geos_verdict:
        rep.wkt = (_wkt(a), _wkt(b))
    return rep


def _check_geos(rep: Report, a: Geometry, b: Geometry, matrix: str) -> None:
    """GEOS as a third opinion; a disagreement is judged by GEOS's own point locator,
    then (if that differs too) by the brute-force exact locator (module docstring)."""
    try:
        rep.geos = geos_relate(a, b)
    except GeosCrash as exc:
        rep.geos, rep.geos_verdict = "CRASH", f"geos-crash ({exc})"
        return
    if rep.geos == matrix:
        return
    w = relate_witness(a, b, keep_witnesses=True)
    try:
        located = geos_locate_witnesses(w, a, b)
        if located is None:
            confirmed = _partial_confirmation(w, a, b, matrix, rep.geos)
            rep.geos_verdict = (
                classify_geos(a, b, matrix, rep.geos, w) + " (partial)"
                if confirmed
                else "UNEXPLAINED (too large to locate exactly)"
            )
        elif _matrix_of((x.dim, la, lb) for x, la, lb in located) != matrix:
            rep.geos_verdict = judge_point_location(w, a, b, located)
        else:
            rep.geos_verdict = classify_geos(a, b, matrix, rep.geos, w)
    except GeosCrash as exc:
        rep.geos_verdict = f"geos-crash ({exc}, locating a witness)"
        return
    if rep.geos_verdict.startswith("UNEXPLAINED"):
        rep.problems.append(f"GEOS {rep.geos} vs exact {matrix}: {rep.geos_verdict}")


def _wkt(g: Geometry) -> str:
    try:
        return to_wkt(g)
    except Exception:  # pragma: no cover - display only
        return repr(g)


def _check_references(rep: Report, a: Geometry, b: Geometry, matrix: str) -> None:
    from reference import indep, oracle

    la, lb = legacy(a), legacy(b)
    ref = oracle.evaluate({"id": rep.id, "a": la, "b": lb})
    if not (ref.get("valid_a") and ref.get("valid_b")):
        return  # the references are defined for valid input only
    ours = {k: v.value for k, v in evaluate(matrix, a.real_dimension, b.real_dimension).items()}
    bad = [k for k in AREAL_PREDICATES if ours[k] != ref[k]]
    area_ok = (matrix[0] == "2") == (Fraction(ref["exact"]["inter"]) > 0)
    rep.oracle_agree = not bad and area_ok and ours["crosses"] is False
    if not rep.oracle_agree:
        rep.problems.append(f"oracle disagrees on {bad or 'II vs intersection area'}")
    ind = indep.evaluate_geoms(la, lb)
    bad = [k for k in AREAL_PREDICATES if ours[k] != ind[k]]
    area_ok = (matrix[0] == "2") == (ind["inter"] > 0)
    rep.indep_agree = not bad and area_ok and bool(ind["selfcheck"])
    if not rep.indep_agree:
        rep.problems.append(f"indep disagrees on {bad or 'II vs intersection area'}")


# ============================================================================ driver


def gather(sources: Iterable[str], args: argparse.Namespace) -> list[XCase]:
    cases: list[XCase] = []
    for src in sources:
        if src == "fixtures":
            cases += fixture_cases()
        elif src == "seed":
            cases += seed_cases(step=args.seed_step)
        elif src == "review":
            cases += review_cases(args.review_n, 1)
        elif src == "lattice":
            cases += lattice_cases(args.cases, args.seed)
        elif src == "adversarial":
            cases += adversarial_cases(args.cases, args.seed)
        elif src == "transformed":
            cases += transformed_cases(max(1, args.cases // 4), args.seed)
        elif src == "exhaustive":
            cases += exhaustive_cases(args.cases)
        elif src == "ulp":
            cases += ulp_cases(max(1, args.cases // 2), args.seed)
        elif src == "dense":
            cases += dense_cases(max(1, args.cases // 4), args.seed)
        else:
            raise SystemExit(f"unknown source {src!r}; choose from {', '.join(SOURCES)}")
    return cases


def _run_chunk(payload: tuple[list[XCase], bool]) -> list[Report]:
    chunk, use_geos = payload
    return [check_case(c, use_geos=use_geos) for c in chunk]


def run(cases: list[XCase], *, jobs: int = 1, use_geos: bool = True) -> list[Report]:
    if jobs <= 1:
        return [check_case(c, use_geos=use_geos) for c in cases]
    from concurrent.futures import ProcessPoolExecutor

    size = max(1, min(200, len(cases) // (jobs * 8) or 1))
    chunks = [(cases[i : i + size], use_geos) for i in range(0, len(cases), size)]
    out: list[Report] = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for reps in pool.map(_run_chunk, chunks):
            out += reps
    return out


def summarize(reports: list[Report]) -> dict[str, Any]:
    """Agreement statistics per source and overall."""
    by_src: dict[str, list[Report]] = {}
    for r in reports:
        by_src.setdefault(r.source, []).append(r)

    def stats(rs: list[Report]) -> dict[str, Any]:
        geos = [r for r in rs if r.geos is not None]
        defects = Counter(
            r.geos_verdict
            for r in geos
            if r.geos_verdict and not r.geos_verdict.startswith("UNEXPLAINED")
        )
        return {
            "cases": len(rs),
            "arrangement_ok": sum(
                r.arrangement_status == "ok" and r.arrangement is not None for r in rs
            ),
            "arrangement_skipped": sum(r.arrangement_status == "engine_skipped" for r in rs),
            "arrangement_error": sum(r.arrangement_status == "engine_error" for r in rs),
            "invalid_input": sum(r.invalid_input is not None for r in rs),
            "witness_error": sum(r.witness_error is not None for r in rs),
            "exact_compared": sum(r.exact_agree is not None for r in rs),
            "exact_agree": sum(bool(r.exact_agree) for r in rs),
            "predicates_agree": sum(bool(r.predicates_agree) for r in rs),
            "expected_compared": sum(r.expected_agree is not None for r in rs),
            "expected_agree": sum(bool(r.expected_agree) for r in rs),
            "oracle_compared": sum(r.oracle_agree is not None for r in rs),
            "oracle_agree": sum(bool(r.oracle_agree) for r in rs),
            "indep_compared": sum(r.indep_agree is not None for r in rs),
            "indep_agree": sum(bool(r.indep_agree) for r in rs),
            "geos_compared": len(geos),
            "geos_agree": sum(r.geos_verdict is None for r in geos),
            "geos_defects": dict(sorted(defects.items())),
            "geos_unexplained": sum(
                bool(r.geos_verdict and r.geos_verdict.startswith("UNEXPLAINED")) for r in geos
            ),
            "failed": sum(r.failed for r in rs),
            "t_arrangement_ms": round(1000 * sum(r.t_arrangement for r in rs) / max(1, len(rs)), 3),
            "t_witness_ms": round(1000 * sum(r.t_witness for r in rs) / max(1, len(rs)), 3),
        }

    types = Counter(f"{r.types[0]}/{r.types[1]}" for r in reports)
    return {
        "sources": {s: stats(rs) for s, rs in by_src.items()},
        "total": stats(reports),
        "type_pairs": len(types),
        "types": dict(sorted(types.items())),
        "failures": [
            {
                "id": r.id,
                "family": r.family,
                "a": r.wkt[0] if r.wkt else None,
                "b": r.wkt[1] if r.wkt else None,
                "arrangement": r.arrangement,
                "witness": r.witness,
                "problems": r.problems,
            }
            for r in reports
            if r.failed
        ],
        "geos_defects": [
            {
                "id": r.id,
                "class": r.geos_verdict,
                "a": r.wkt[0] if r.wkt else None,
                "b": r.wkt[1] if r.wkt else None,
                "exact": r.arrangement,
                "geos": r.geos,
            }
            for r in reports
            if r.geos_verdict and not r.failed
        ],
    }


def print_summary(summary: dict[str, Any], out: Any = None) -> None:
    out = out if out is not None else sys.stdout
    cols = ("cases", "exact", "oracle", "indep", "stated", "GEOS", "GEOS defects", "fail")
    print(f"{'source':12s} " + " ".join(f"{c:>14s}" for c in cols), file=out)
    rows = [*summary["sources"].items(), ("TOTAL", summary["total"])]

    def frac(s: dict[str, Any], k: str) -> str:
        n = s[f"{k}_compared"]
        return f"{s[f'{k}_agree']}/{n}" if n else "-"

    for name, s in rows:
        ndef = sum(s["geos_defects"].values())
        cells = (
            str(s["cases"]),
            *(frac(s, k) for k in ("exact", "oracle", "indep", "expected", "geos")),
            str(ndef),
            str(s["failed"]),
        )
        print(f"{name:12s} " + " ".join(f"{c:>14s}" for c in cells), file=out)
    tot = summary["total"]
    print(f"\ntype pairs covered: {summary['type_pairs']}", file=out)
    print(
        f"GEOS defect classes: {tot['geos_defects'] or 'none'}; unexplained: "
        f"{tot['geos_unexplained']}",
        file=out,
    )
    print(
        f"engine: {tot['arrangement_skipped']} skipped, {tot['arrangement_error']} errors, "
        f"{tot['witness_error']} witness errors, {tot['invalid_input']} refused inputs",
        file=out,
    )
    print(
        f"mean time per case: arrangement route {tot['t_arrangement_ms']} ms (both "
        f"orders), witness route {tot['t_witness_ms']} ms",
        file=out,
    )
    for f in summary["failures"][:20]:
        print(f"\nFAIL {f['id']} ({f['family']})\n  A: {f['a']}\n  B: {f['b']}", file=out)
        for p in f["problems"]:
            print(f"  - {p}", file=out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument(
        "--sources",
        default=",".join(SOURCES),
        help=f"comma-separated subset of {', '.join(SOURCES)}",
    )
    p.add_argument(
        "--cases",
        type=int,
        default=2000,
        help="random cases per random source (transformed: a quarter)",
    )
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--seed-step", type=int, default=1, help="use every k-th seed case")
    p.add_argument("--review-n", type=int, default=50, help="cases per review family")
    p.add_argument("--jobs", type=int, default=1, help="worker processes (at most 2 advised)")
    p.add_argument("--no-geos", action="store_true", help="skip the GEOS third opinion")
    p.add_argument("--json", metavar="PATH", help="write the full report as JSON")
    args = p.parse_args(argv)
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    t0 = time.perf_counter()
    cases = gather(sources, args)
    reports = run(cases, jobs=args.jobs, use_geos=not args.no_geos)
    summary = summarize(reports)
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    summary["geos_version"] = None if _shapely() is None else geos().version()
    print_summary(summary)
    print(f"\n{len(cases)} cases in {summary['seconds']} s (GEOS {summary['geos_version']})")
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=1, default=str) + "\n")
    return 1 if summary["total"]["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
