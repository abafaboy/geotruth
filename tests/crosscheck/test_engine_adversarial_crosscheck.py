"""Cross-checks from the adversarial review of the exact engine.

The review fuzzed both relate routes, GEOS and the overlay certificate with the
GeometryCollection-heavy, degenerate lattice pairs of :mod:`unit.nasty_lattice`: 65,011
valid pairs (four seeds, lattices of size 3 to 6), with no disagreement between the
arrangement and witness routes, no predicate disagreement with GEOS where GEOS's matrix
matched, no failed overlay certificate, and no engine exception. These tests keep a
seeded sample of that sweep, and pin the two GEOS 3.13.1 self-contradictions it found:

- **relate:** B's lines cover an edge of A's ring and another line of B *ends inside* that
  edge (not at a vertex of either). GEOS reports BE = 1 although its own point location
  puts every point of A's ring in B.
- **overlay:** ``symdifference(A, B)`` for a GeometryCollection B with lines and points
  outside A returns A alone, although GEOS's own ``difference(B, A)`` returns those parts.

Every other GEOS relate disagreement of the sample must be one that GEOS's own point
location explains (the classification of ``tools/crosscheck_relate.py``).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from geotruth.io import read_wkt
from geotruth.measures import area as shoelace_area
from geotruth.overlay import OPS, VARIANTS, overlay, overlay_all
from geotruth.relate import relate
from geotruth.relate_witness import relate_witness
from unit.nasty_lattice import valid_pairs

pytestmark = pytest.mark.crosscheck

REPO = Path(__file__).resolve().parents[2]


def _load_tool():
    name = "crosscheck_relate"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / "crosscheck_relate.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _doubled(g):
    """Half-lattice coordinates become integers (relate is invariant under scaling), so
    every case is eligible for the GEOS third opinion."""
    return g.map_coords(lambda c: (2 * c[0], 2 * c[1]))


@pytest.mark.parametrize("block", range(4))
def test_nasty_lattice_routes_and_geos(block):
    """Both exact routes agree (with their transposes and assertions); a GEOS
    disagreement must be explained by GEOS's own point location."""
    pytest.importorskip("shapely")
    X = _load_tool()
    cases = [
        X.XCase(f"nasty-{block}-{i}", "nasty", "nasty", _doubled(a), _doubled(b))
        for i, (a, b) in enumerate(valid_pairs(seed=90_000 + block, count=60))
    ]
    reports = X.run(cases, use_geos=True)
    assert [(r.id, r.wkt, r.problems) for r in reports if r.failed] == []
    assert all(r.exact_agree and r.arrangement_status == "ok" for r in reports)
    assert not [r for r in reports if (r.geos_verdict or "").startswith("UNEXPLAINED")]


def test_nasty_lattice_predicates_match_geos():
    """Where GEOS's matrix equals the exact one, every named predicate that is not an
    empty-geometry convention equals GEOS's (the dimension dispatch of DESIGN §1)."""
    shapely = pytest.importorskip("shapely")
    names = ("intersects", "disjoint", "touches", "crosses", "overlaps", "contains",
             "covers", "within", "covered_by", "equals")  # fmt: skip
    compared = 0
    for a, b in valid_pairs(seed=91_000, count=250):
        ga, gb = shapely.from_wkt(a.wkt), shapely.from_wkt(b.wkt)
        res = relate(a, b, strict=True)
        if ga.relate(gb) != res.matrix:
            continue
        compared += 1
        for name in names:
            if not res.predicate_values[name].convention:
                assert res.predicates[name] == getattr(ga, name)(gb), (name, a.wkt, b.wkt)
    assert compared > 200


@pytest.mark.parametrize("block", range(3))
def test_nasty_lattice_overlay_is_certified(block):
    """Every operation in both variants passes the independent certificate, and the
    reported exact area is the shoelace area of the result's own polygons."""
    for a, b in valid_pairs(seed=92_000 + block, count=40):
        res = overlay_all(a, b, certify=True, strict=True)
        ok = {(op, v) for op, per in res.items() for v, r in per.items() if r.ok}
        assert ok == {(op, v) for op in OPS for v in VARIANTS}, (a.wkt, b.wkt)
        for per in res.values():  # the area field is not part of the certificate
            for r in per.values():
                assert r.area == shoelace_area(r.geometry), (a.wkt, b.wkt, r.op)


def test_known_geos_relate_contradiction_covered_ring_line_end():
    """B covers A's ring and another line of B ends inside a ring edge: GEOS 3.13.1
    reports BE = 1 (A's boundary meets B's exterior), but locates every point of A's ring
    in B. A vertex at (1 0) in either ring makes GEOS agree."""
    shapely = pytest.importorskip("shapely")
    a = "POLYGON ((0 0, 2 0, 2 1, 0 1, 0 0))"
    cases = [
        ("MULTILINESTRING ((0 0, 2 0, 2 1, 0 1, 0 0), (1 0, 1 -1))", "FF210F102", "FF2101102"),
        ("MULTILINESTRING ((0 0, 2 0, 2 1, 0 1, 0 0), (1 0, 1 1))", "1F210FFF2", "1F2101FF2"),
        ("MULTILINESTRING ((0 0, 2 0), (2 0, 2 1, 0 1, 0 0), (1 0, 1 0.5))",
         "10210FFF2", "102101FF2"),
    ]  # fmt: skip
    ring_points = ["POINT (1 0)", "POINT (0.5 0)", "POINT (1.5 0)", "POINT (2 0.5)",
                   "POINT (1 1)", "POINT (0 0.5)", "POINT (0 0)", "POINT (2 1)"]  # fmt: skip
    for b, exact, geos in cases:
        ga, gb = read_wkt(a), read_wkt(b)
        assert relate(ga, gb, strict=True).matrix == exact
        assert relate_witness(ga, gb).matrix == exact
        got = shapely.from_wkt(a).relate(shapely.from_wkt(b))
        if got == exact:  # fixed upstream: nothing left to explain
            continue
        assert got == geos
        # GEOS's own point location: no point of A's ring is exterior to B
        sb = shapely.from_wkt(b)
        assert all(shapely.from_wkt(p).relate(sb)[2] == "F" for p in ring_points)
        assert exact[5] == "F"  # BE: the exact A boundary lies in B


def test_known_geos_symdifference_drops_collection_parts():
    """symdifference(A, B) with B a GeometryCollection of a line and points: GEOS 3.13.1
    returns A alone, although its own difference(B, A) holds the line part and the point
    outside A. The exact result (certified) keeps them."""
    shapely = pytest.importorskip("shapely")
    a = "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"
    b = "GEOMETRYCOLLECTION (LINESTRING (1 1, 3 1), POINT (1 1), POINT (5 5))"
    res = overlay(read_wkt(a), read_wkt(b), "symdifference", certify=True, strict=True)
    assert res.wkt == (
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 1, 2 2, 0 2, 0 0)), "
        "LINESTRING (2 1, 3 1), POINT (5 5))"
    )
    sa, sb = shapely.from_wkt(a), shapely.from_wkt(b)
    got = shapely.symmetric_difference(sa, sb)
    if got.equals(shapely.from_wkt(res.wkt)):  # fixed upstream
        return
    assert got.equals(sa)  # the parts of B outside A are lost
    b_minus_a = shapely.difference(sb, sa)
    parts = shapely.from_wkt("GEOMETRYCOLLECTION (LINESTRING (2 1, 3 1), POINT (5 5))")
    assert b_minus_a.equals(parts)
