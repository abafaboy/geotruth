"""Exact measures against Shapely/GEOS, within GEOS's floating-point rounding.

Marked ``crosscheck`` (it needs Shapely and compares with a library, so it is not part of
the fast ``unit`` selection even though it lives here). GEOS computes every measure in
double arithmetic, so each comparison uses an explicit rounding bound derived from the
operation count and the magnitudes involved; the engine's values are exact (areas,
squared distances, hulls) or correctly rounded (lengths, line centroids).

Inputs: the seed corpus, the floating-point oracle-review families and random lattice
geometries of every type (finite coordinates).
"""

from __future__ import annotations

import math
import random
import subprocess
import sys
import warnings
from fractions import Fraction as F
from itertools import pairwise
from pathlib import Path

import pytest

shapely = pytest.importorskip("shapely")

from geotruth import measures as M  # noqa: E402
from geotruth.geom import Geometry, LineString, Point, Polygon  # noqa: E402
from geotruth.io import geometry_from_json, to_wkt  # noqa: E402
from geotruth.numbers import json_loads  # noqa: E402
from unit.test_validity_lattice import random_geometry  # noqa: E402

pytestmark = pytest.mark.crosscheck

ROOT = Path(__file__).resolve().parents[2]
EPS = 2.0**-52


def _shp(geom: Geometry):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return shapely.from_wkt(to_wkt(geom))


def _magnitude(*geoms: Geometry) -> float:
    return max((abs(v) for g in geoms for v in g.iter_values()), default=0.0)


def _inputs() -> list[Geometry]:
    out: list[Geometry] = []
    for line in (ROOT / "corpus" / "cases" / "seed.jsonl").read_text().splitlines()[::4]:
        case = json_loads(line)
        out += [geometry_from_json(case["a"]), geometry_from_json(case["b"])]
    gen = ROOT / "tools" / "oracle_review" / "gen_review.py"
    for family in ("general-float", "convex-float", "convex-grid-rot", "general-grid"):
        text = subprocess.run(
            [sys.executable, str(gen), family, "60", "2"],
            capture_output=True,
            text=True,
            check=True,
            cwd=ROOT,
        ).stdout
        for line in text.splitlines():
            case = json_loads(line)
            out += [geometry_from_json(case["a"]), geometry_from_json(case["b"])]
    rng = random.Random(99)
    while len(out) < 3500:
        g = random_geometry(rng)
        if not g.has_nonfinite:
            try:
                _shp(g)
            except shapely.errors.GEOSException:
                continue  # GEOS cannot build it
            out.append(g)
    return out


@pytest.fixture(scope="module")
def inputs() -> list[Geometry]:
    return _inputs()


def _rings_and_lines(g: Geometry):
    for e in g.elements():
        if isinstance(e, Polygon):
            yield from (r for r in e.rings if r)
        elif isinstance(e, LineString) and e.coords:
            yield e.coords


def test_area(inputs):
    for g in inputs:
        exact = M.area(g)
        geos = _shp(g).area
        # GEOS: shoelace in doubles, relative to the first vertex of each ring
        bound = 0.0
        for ring in _rings_and_lines(g):
            x0 = ring[0][0]
            s = sum(
                abs(ring[i][0] - x0) * (abs(ring[i + 1][1]) + abs(ring[i - 1][1]))
                for i in range(1, len(ring) - 1)
            )
            bound += 4 * (len(ring) + 2) * EPS * s
        assert abs(F(geos) - F(exact)) <= F(bound) + F(5e-324), (to_wkt(g)[:200], geos, exact)


def test_length(inputs):
    for g in inputs:
        c = M.length(g)
        geos = _shp(g).length
        n = sum(len(r) for r in _rings_and_lines(g)) + 1
        assert abs(geos - c.rounded) <= (n + 6) * EPS * c.rounded, (to_wkt(g)[:200], geos, c)
        assert c.lo <= F(c.rounded) * (1 + F(EPS)) and F(c.rounded) * (1 - F(EPS)) <= c.hi


def test_distance(inputs):
    rng = random.Random(5)
    for _ in range(3000):
        a, b = rng.choice(inputs), rng.choice(inputs)
        if a.is_empty or b.is_empty:
            assert M.distance2(a, b) is None
            continue
        d2 = M.distance2(a, b)
        geos = shapely.distance(_shp(a), _shp(b))
        d = math.sqrt(float(d2))
        bound = 32 * EPS * _magnitude(a, b) + 4 * EPS * d
        assert abs(geos - d) <= bound, (to_wkt(a)[:150], to_wkt(b)[:150], geos, d2)
        if d2 == 0:
            assert geos == 0.0  # GEOS decides intersection with exact orientation


def test_centroid(inputs):
    for g in inputs:
        c = M.centroid(g)
        geos = _shp(g).centroid
        if c is None:
            assert geos.is_empty
            continue
        gx, gy = geos.x, geos.y
        mag = _magnitude(g)
        n = sum(len(r) for r in _rings_and_lines(g)) + 1
        # areal centroids divide by the area: scale the bound by sum|c_i| / |sum c_i|
        amp = 1.0
        if M.area(g) > 0:
            pos = sum(
                abs(p[0] * q[1] - q[0] * p[1]) for r in _rings_and_lines(g) for p, q in pairwise(r)
            )
            amp = max(1.0, pos / float(M.area(g)))
        bound = 16 * n * EPS * mag * amp
        assert abs(gx - c[0].rounded) <= bound and abs(gy - c[1].rounded) <= bound, (
            to_wkt(g)[:200],
            (gx, gy),
            c,
        )


def test_convex_hull(inputs):
    for g in inputs:
        ours = M.convex_hull(g)
        geos = _shp(g).convex_hull
        assert geos.geom_type == ours.geom_type or (ours.is_empty and geos.is_empty), to_wkt(g)
        if ours.is_empty:
            continue
        mine = {(float(x), float(y)) for x, y in ours.iter_coords()}
        theirs = {(float(x), float(y)) for x, y in shapely.get_coordinates(geos)}
        assert mine == theirs, (to_wkt(g)[:200], ours.wkt[:200], geos.wkt[:200])
        if isinstance(ours, Polygon):
            assert M.area(ours) == F(geos.area) or abs(F(geos.area) - M.area(ours)) <= F(
                1e-12
            ) * M.area(ours)


def test_point_and_empty_measures():
    p = Point((1.5, -2.0))
    assert M.area(p) == 0 and M.length(p).exact == 0
    cx, cy = M.centroid(p)
    assert (cx.rounded, cy.rounded) == (_shp(p).centroid.x, _shp(p).centroid.y)
    assert math.isnan(shapely.distance(_shp(Point()), _shp(p)))
    assert M.distance2(Point(), p) is None
