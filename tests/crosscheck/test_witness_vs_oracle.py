"""Cross-check of the witness relate against the audited polygon references.

``tests/reference/oracle.py`` (vertical slabs, gmpy2) and ``indep.py`` (winding numbers,
Green's theorem, Fractions) decide the polygon/polygon predicates from exact areas and
boundary-piece classification. The witness relate decides them from a DE-9IM matrix of
point locations. The three share no code. On every valid polygon case of the seed corpus
(``corpus/cases/seed.jsonl``, 1000 cases of ulp-level near-degeneracy: tiny rotations,
rotated neighbours, shared sloped edges, offsets near 1e7) all predicates must agree,
and so must the legacy expected answers (``corpus/expected-v1/seed.jsonl``, produced by
the oracle).
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path

import pytest

from geotruth.io import case_from_json
from geotruth.numbers import json_loads
from geotruth.predicates import matrix_problems
from geotruth.relate_witness import relate_witness
from reference import indep, oracle

ROOT = Path(__file__).resolve().parents[2]
SEED = ROOT / "corpus" / "cases" / "seed.jsonl"
EXPECTED = ROOT / "corpus" / "expected-v1" / "seed.jsonl"

#: Predicates the references define for polygon/polygon.
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


@cache
def seed_cases() -> list[dict]:
    with open(SEED, encoding="utf-8") as fh:
        return [json_loads(line) for line in fh if line.strip()]


@cache
def expected_answers() -> dict[str, dict]:
    with open(EXPECTED, encoding="utf-8") as fh:
        return {r["id"]: r for r in (json.loads(line) for line in fh if line.strip())}


def _ours(raw: dict) -> tuple[str, dict[str, bool]]:
    case = case_from_json(raw)
    res = relate_witness(case.a, case.b)
    assert matrix_problems(res.matrix, res.dim_a, res.dim_b) == [], (raw["id"], res.matrix)
    return res.matrix, {k: v.value for k, v in res.predicates().items()}


def _chunks(n: int) -> list[tuple[int, int]]:
    total = len(seed_cases())
    size = (total + n - 1) // n
    return [(i, min(i + size, total)) for i in range(0, total, size)]


@pytest.mark.parametrize(("lo", "hi"), _chunks(4))
def test_seed_predicates_vs_oracle_and_indep(lo, hi):
    compared = 0
    for raw in seed_cases()[lo:hi]:
        ref = oracle.evaluate(raw)
        if not (ref["valid_a"] and ref["valid_b"]):
            continue  # relate and predicates are defined for valid input only
        matrix, ours = _ours(raw)
        for name in AREAL_PREDICATES:
            assert ours[name] == ref[name], (raw["id"], name, matrix)
        ind = indep.evaluate_geoms(raw["a"], raw["b"])
        for name in AREAL_PREDICATES:
            assert ours[name] == ind[name], (raw["id"], name, matrix, "indep")
        # crosses is false for A/A by the dispatch table
        assert ours["crosses"] is False
        # the areas must be consistent with the matrix: II = 2 iff the intersection has area
        assert (matrix[0] == "2") == (ind["inter"] > 0), raw["id"]
        compared += 1
    assert compared > 0


def test_seed_predicates_vs_legacy_expected_answers():
    expected = expected_answers()
    mismatches = []
    compared = 0
    for raw in seed_cases():
        exp = expected[raw["id"]]
        if not (exp.get("valid_a") and exp.get("valid_b")):
            continue
        _, ours = _ours(raw)
        compared += 1
        for name in AREAL_PREDICATES:
            if ours[name] != exp[name]:
                mismatches.append((raw["id"], name, ours[name], exp[name]))
    assert mismatches == []
    assert compared >= 900


def test_seed_matrices_vs_geos():
    """A third opinion on the seed: GEOS 3.13.1's relate agrees with the witness matrix
    on every valid seed case (observed; GEOS is not exact in general on such ulp-level
    near-degenerate inputs, so other GEOS versions are only reported)."""
    shapely = pytest.importorskip("shapely")
    from geotruth.io import to_wkt

    disagreements = []
    for raw in seed_cases():
        ref = oracle.evaluate(raw)
        if not (ref["valid_a"] and ref["valid_b"]):
            continue
        case = case_from_json(raw)
        matrix, _ = _ours(raw)
        sa, sb = shapely.from_wkt(to_wkt(case.a)), shapely.from_wkt(to_wkt(case.b))
        theirs = shapely.relate(sa, sb)
        if theirs != matrix:
            disagreements.append((raw["id"], matrix, theirs))
    print(f"\nseed: {len(disagreements)} GEOS relate disagreements", disagreements[:10])
    if tuple(shapely.geos_version) == (3, 13, 1):
        assert disagreements == []


def test_witness_route_matches_arrangement_route():
    """DESIGN §0.2: the arrangement route (§2.3, E1) and the witness route (§2.4) must
    give the same matrix. Skipped until ``geotruth.arrangement`` exists; uses only the
    frozen Arrangement API (cell labels) and the fixture helper that reads them."""
    arrangement = pytest.importorskip("geotruth.arrangement")
    import random

    from geotruth.relate_witness import relate
    from unit.fixtures_arrangement import labels_matrix
    from unit.witness_lattice import random_pair

    cases = [case_from_json(raw) for raw in seed_cases()[::5]]
    pairs = [(c.a, c.b) for c in cases]
    rng = random.Random(3)
    pairs += [random_pair(rng, i)[2:] for i in range(640)]
    for a, b in pairs:
        arr = arrangement.build_arrangement(a, b)
        assert labels_matrix(arr) == relate(a, b), (a.wkt, b.wkt)
