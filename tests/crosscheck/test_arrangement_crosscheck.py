"""Cross-checks of the arrangement (DESIGN §2.2) against independent implementations.

- the audited references ``tests/reference/oracle.py`` (vertical slabs, mpq, even-odd)
  and ``indep.py`` (Green's theorem on boundary pieces, Fractions): exact face-area
  identities and the location of random exact points;
- the brute-force DESIGN §1 locator of ``unit.arrangement_testlib`` at every cell;
- GEOS 3.13 through Shapely, as a third opinion only. Where GEOS's ``relate`` differs
  from the labels, the test requires that GEOS's *own* point location agrees with the
  label of every cell probe it can be asked about (double coordinates), i.e. that the
  GEOS matrix contradicts GEOS's own point locator. Such cases are counted, and every
  other disagreement fails.
"""

from __future__ import annotations

import random
from fractions import Fraction
from pathlib import Path

import pytest

from geotruth.arrangement import build_arrangement
from geotruth.arrangement_api import Arrangement, Location
from geotruth.geom import Geometry, MultiPolygon, Polygon
from geotruth.io import case_from_json
from geotruth.numbers import json_loads
from reference import indep, oracle
from unit.arrangement_testlib import (
    CellLocator,
    cell_probes,
    check_labels,
    components,
    face_area2,
    labels_matrix,
    random_face_points,
    random_multipolygon,
    random_operand,
)

pytestmark = pytest.mark.crosscheck

I, B, E = Location.INTERIOR, Location.BOUNDARY, Location.EXTERIOR
REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "corpus" / "cases" / "seed.jsonl"


def seed_cases(step: int = 1) -> list[dict]:
    with open(SEED, encoding="utf-8") as fh:
        lines = [line for line in fh if line.strip()]
    return [json_loads(line) for line in lines[::step]]


def review_cases() -> list[dict]:
    """The oracle-review families (tools/oracle_review/gen_review.py all 20 1); needs
    Shapely, which the generator uses to build valid inputs."""
    pytest.importorskip("shapely")
    import subprocess
    import sys

    out = subprocess.run(
        [sys.executable, str(REPO / "tools" / "oracle_review" / "gen_review.py"), "all", "20", "1"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    return [json_loads(line) for line in out.splitlines() if line.strip()]


def legacy(g: Geometry) -> list:
    """A (Multi)Polygon as FORMAT-v1 nested coordinate lists (the references' input)."""
    polys = [g] if isinstance(g, Polygon) else list(g.polygons)
    return [[[[float(x), float(y)] for x, y in ring] for ring in p.rings] for p in polys]


# ================================================================= area identities


def face_areas(arr: Arrangement) -> dict[tuple[int, int], Fraction]:
    """Real area of the faces of each (A, B) label."""
    out: dict[tuple[int, int], Fraction] = {}
    for f in range(1, arr.num_faces):
        key = (arr.face_loc_a[f], arr.face_loc_b[f])
        out[key] = out.get(key, Fraction(0)) + face_area2(arr, f) / 2
    return out


def check_areas(arr: Arrangement, la: list, lb: list) -> None:
    both, only_a, only_b = oracle.overlay_areas(oracle.edges(la), oracle.edges(lb))
    areas = face_areas(arr)
    zero = Fraction(0)
    got = {
        "both": areas.get((I, I), zero),
        "only_a": areas.get((I, E), zero),
        "only_b": areas.get((E, I), zero),
    }
    want = {"both": both, "only_a": only_a, "only_b": only_b}
    assert {k: Fraction(v) for k, v in got.items()} == {k: Fraction(v) for k, v in want.items()}
    # the union: every bounded face labelled in A or in B
    union = sum((v for k, v in areas.items() if I in k), zero)
    assert union == Fraction(both + only_a + only_b)
    # an independent third route (Green's theorem, Fractions)
    ind = indep.evaluate_geoms(la, lb)
    assert (ind["inter"], ind["diff_ab"], ind["diff_ba"]) == (
        got["both"],
        got["only_a"],
        got["only_b"],
    )
    # bounded faces labelled (E, E) are the holes nobody covers: all bounded area adds up
    assert sum(areas.values(), zero) == -face_area2_of_components(arr) / 2


def face_area2_of_components(arr: Arrangement) -> Fraction:
    from geotruth.exact import signed_area2
    from unit.arrangement_testlib import cycle_points

    return sum((signed_area2(cycle_points(arr, h)) for h in arr.face_inner[0]), Fraction(0))


def check_points_vs_oracle(arr: Arrangement, la: list, lb: list, rng: random.Random, n: int):
    """Random exact points: the label of the cell containing each equals oracle.point_in
    (1 inside, 0 boundary, -1 outside) for A and for B."""
    from gmpy2 import mpq

    ea, eb = oracle.edges(la), oracle.edges(lb)
    code = {1: I, 0: B, -1: E}
    loc = CellLocator(arr)
    pts = random_face_points(rng, arr, n)
    pts += [arr.vertex_fractions(v) for v in range(0, arr.num_vertices, 3)]
    for p in pts:
        q = (mpq(p[0].numerator, p[0].denominator), mpq(p[1].numerator, p[1].denominator))
        want = (code[oracle.point_in(q, ea)], code[oracle.point_in(q, eb)])
        assert loc.label(loc.locate(p)) == want, p


@pytest.mark.parametrize("chunk", range(10))
def test_seed_corpus_against_oracle_and_indep(chunk):
    """Every 5th seed case (200 in all): full validation, exact face-area identities
    against oracle and indep, and random points against oracle.point_in."""
    rng = random.Random(chunk)
    cases = seed_cases(step=5)[chunk::10]
    for obj in cases:
        case = case_from_json(obj)
        arr = build_arrangement(case.a, case.b)
        arr.validate(geometry=True, planarity=arr.num_edges < 300, labels=True)
        assert arr.num_vertices - arr.num_edges + arr.num_faces == 1 + components(arr)
        check_areas(arr, obj["a"], obj["b"])
        check_points_vs_oracle(arr, obj["a"], obj["b"], rng, 15)


def test_seed_corpus_labels_against_brute_force():
    """Every label of 40 seed cases against the brute-force DESIGN §1 locator."""
    for obj in seed_cases(step=25):
        case = case_from_json(obj)
        arr = build_arrangement(case.a, case.b)
        check_labels(arr, case.a, case.b)


def test_review_families_against_oracle_and_indep():
    """The oracle-review families: grids with holes touching shells, collinear edges
    everywhere, ulp-level near-degeneracy, extreme scales (2^-1074 .. 2^600)."""
    rng = random.Random(5)
    n = 0
    for obj in review_cases():
        case = case_from_json(obj)
        arr = build_arrangement(case.a, case.b)
        arr.validate(geometry=True, planarity=arr.num_edges < 300, labels=True)
        check_areas(arr, obj["a"], obj["b"])
        check_points_vs_oracle(arr, obj["a"], obj["b"], rng, 10)
        if arr.num_edges < 120:
            check_labels(arr, case.a, case.b)
        n += 1
    assert n >= 150


@pytest.mark.parametrize("seed", range(40))
def test_random_multipolygons_against_oracle(seed):
    rng = random.Random(7000 + seed)
    a, b = random_multipolygon(rng, 6), random_multipolygon(rng, 6)
    if isinstance(a, Polygon) and rng.random() < 0.3:
        b = MultiPolygon([a])  # identical boundaries
    arr = build_arrangement(a, b)
    arr.validate(geometry=True, planarity=True, labels=True)
    check_areas(arr, legacy(a), legacy(b))
    check_points_vs_oracle(arr, legacy(a), legacy(b), rng, 30)


# ======================================================================= GEOS


def _loc_from_matrix(m: str) -> Location:
    return I if m[0] != "F" else (B if m[1] != "F" else E)


def geos_point_disagreements(arr: Arrangement, a: Geometry, b: Geometry) -> tuple[int, list]:
    """Locate every double-representable cell probe with GEOS; return how many were
    asked and the probes where GEOS's point location differs from the cell label."""
    shapely = pytest.importorskip("shapely")
    ga, gb = shapely.from_wkt(a.wkt), shapely.from_wkt(b.wkt)
    loc = CellLocator(arr)
    asked, bad = 0, []
    for what, p, cell in cell_probes(arr):
        xy = [float(c) for c in p]
        if any(Fraction(f) != c for f, c in zip(xy, p, strict=True)):
            continue
        pt = shapely.Point(*xy)
        got = (_loc_from_matrix(pt.relate(ga)), _loc_from_matrix(pt.relate(gb)))
        asked += 1
        if got != loc.label(cell):
            bad.append((what, p, loc.label(cell), got))
    return asked, bad


@pytest.mark.parametrize("block", range(8))
def test_random_lattice_cases_against_geos(block):
    """Random P/L/A/GC lattice cases: the matrix implied by the labels equals GEOS's
    relate, or GEOS's relate contradicts GEOS's own point location at the cells."""
    shapely = pytest.importorskip("shapely")
    agree = contradicted = 0
    for seed in range(block * 150, (block + 1) * 150):
        rng = random.Random(90_000 + seed)
        size = 3 if seed % 2 else 6
        a, b = random_operand(rng, size), random_operand(rng, size)
        arr = build_arrangement(a, b)
        mine = labels_matrix(arr)
        geos = shapely.from_wkt(a.wkt).relate(shapely.from_wkt(b.wkt))
        if mine == geos:
            agree += 1
            continue
        arr.validate(geometry=True, planarity=True, labels=True)
        check_labels(arr, a, b)
        asked, bad = geos_point_disagreements(arr, a, b)
        assert asked > 0 and not bad, (seed, a.wkt, b.wkt, mine, geos, bad)
        contradicted += 1
    assert agree >= 0.95 * (agree + contradicted)


def test_known_geos_relate_contradictions():
    """Cases where GEOS 3.13.1 relate contradicts GEOS's own answers; the labels match
    the brute-force locator and GEOS's point location at every probe."""
    shapely = pytest.importorskip("shapely")
    from geotruth.io import read_wkt

    cases = [
        # RelateNG skips line ends of elements disjoint from the target's envelope once
        # an exterior line end was seen, even when that one was an Interior (Mod-2 even)
        # end: GEOS's boundary() of B is MULTIPOINT ((0 5), (2 2)), both exterior to A
        (
            "LINESTRING (4 2, 4 6, 3 6)",
            "MULTILINESTRING ((0 4, 1 1), (2 2, 1 1), (0 5, 0 4))",
            "FF1FF0102",
            "FF1FF01F2",
        ),
        # GC union: GEOS's own OverlayNG gives area(A - B) = 0, yet relate says IE = 2
        (
            "POLYGON ((3 2, 5 3, 5 4, 5 5, 2 5, 3 2))",
            "GEOMETRYCOLLECTION (POLYGON ((5 4, 7 3, 4 1, 2 1, 1 4, 1 7, 5 4)), "
            "MULTIPOINT ((3 0), (5 2), (2 1)), POLYGON ((6 2, 5 5, 1 5, 0 1, 5 0, 6 0, 6 2)))",
            "2FF11F212",
            "212111212",
        ),
        # GC with a point element: OverlayNG gives area(B - A) = 0, relate says EI = 2
        (
            "GEOMETRYCOLLECTION (POLYGON ((4 6, 0 0, -1 4, -1 6, 4 6)), POINT (1 0))",
            "POLYGON ((3 5, 0 6, 1 4, 3 5))",
            "212F01FF2",
            "212F01212",
        ),
        # a line along a GC polygon's edge where a GC line crosses it: II = 1 in GEOS
        (
            "MULTILINESTRING ((2 4, 1 5), (1 3, 2 2))",
            "GEOMETRYCOLLECTION (LINESTRING (3 1, 6 5, 3 4, 6 2), "
            "LINESTRING (0 2, 6 5, 1 3, 1 5), POLYGON ((4 5, 1 3, 3 1, 6 2, 4 5)))",
            "F11F00212",
            "111F00212",
        ),
    ]
    for wa, wb, mine, geos in cases:
        a, b = read_wkt(wa), read_wkt(wb)
        arr = build_arrangement(a, b)
        arr.validate(geometry=True, planarity=True, labels=True)
        check_labels(arr, a, b)
        assert labels_matrix(arr) == mine
        got = shapely.from_wkt(wa).relate(shapely.from_wkt(wb))
        if got == mine:  # fixed upstream: nothing left to explain
            continue
        assert got == geos
        asked, bad = geos_point_disagreements(arr, a, b)
        assert asked > 10 and not bad


# ============================================ the independent witness route (E2, §2.4)


@pytest.mark.parametrize("block", range(4))
def test_labels_agree_with_the_standalone_locator(block):
    """Every cell probe's labels equal geotruth.locate (the RelateNG-style locator of
    the witness route, which shares only the §2.1 primitives with the arrangement)."""
    locate = pytest.importorskip("geotruth.locate").locate
    for seed in range(block * 100, (block + 1) * 100):
        rng = random.Random(777_000 + seed)
        size = 3 if seed % 2 else 6
        a, b = random_operand(rng, size), random_operand(rng, size)
        arr = build_arrangement(a, b)
        loc = CellLocator(arr)
        for what, p, cell in cell_probes(arr):
            want = (Location.from_char(locate(p, a)), Location.from_char(locate(p, b)))
            assert loc.label(cell) == want, (seed, what, p, a.wkt, b.wkt)


def test_matrix_agrees_with_witness_relate():
    """DESIGN §0.2: the arrangement route and the witness route give the same DE-9IM on
    random P/L/A/GC lattice cases, the seed corpus and the review families."""
    relate = pytest.importorskip("geotruth.relate_witness").relate
    pairs = []
    for seed in range(600):
        rng = random.Random(888_000 + seed)
        size = 3 if seed % 2 else 6
        pairs.append((random_operand(rng, size), random_operand(rng, size)))
    for obj in seed_cases(step=2):
        case = case_from_json(obj)
        pairs.append((case.a, case.b))
    for obj in review_cases():
        case = case_from_json(obj)
        pairs.append((case.a, case.b))
    for a, b in pairs:
        assert labels_matrix(build_arrangement(a, b)) == relate(a, b), (a.wkt, b.wkt)
