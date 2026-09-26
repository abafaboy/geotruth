"""The native adapters on the tracked seed corpus (``corpus/cases/seed.jsonl``, 1000
polygon/polygon cases), in both contracts:

- v1 (legacy lines): ``harness/compare.py`` against ``corpus/expected-v1/seed.jsonl`` gives
  the documented baseline of harness/README.md (the v2 upgrade must not change it);
- v2 (``--v2``): the same library calls answer the same way (predicates and validity equal
  their v1 values, overlay output geometry has the v1 area), and the disagreements with the
  exact answer are exactly the v1 ones;
- CGAL, the exact control: its exact areas equal the oracle's for every case, its rounded
  output coordinates are the correctly rounded exact ones, and its derived predicates agree.
"""

from __future__ import annotations

import collections
import itertools
import json
import subprocess
import sys
from fractions import Fraction

import pytest
from test_native_support import (
    OPS,
    REPO,
    TARGETS,
    V1_PREDICATES,
    area,
    by_id,
    positions,
    require,
    run_adapter,
    target,
)

pytestmark = pytest.mark.crosscheck

SEED = REPO / "corpus" / "cases" / "seed.jsonl"
EXPECTED = REPO / "corpus" / "expected-v1" / "seed.jsonl"
V1_AREA = {"intersection": "area_inter", "union": "area_union", "difference": "area_diff",
           "symdifference": "area_symdiff"}
REL_TOL = 1e-6  # compare.py's gross-error threshold, relative to the operands' area

# harness/compare.py on the seed, per target: {kind: records} (harness/README.md "Seed
# baseline" for the pre-v2 targets; geos-release, boost-release and cgal are new)
V1_BASELINE = {
    "geos-main": {},
    "geos-release": {},
    "boost-1.83": {"predicate": 229},
    "boost-develop": {"predicate": 247, "area": 2},
    "boost-release": {"predicate": 247, "area": 2},
    "clipper2": {"error": 15},
    "cgal": {},
}


@pytest.fixture(scope="module")
def expected():
    return by_id([json.loads(line) for line in EXPECTED.read_text().splitlines()])


@pytest.fixture(scope="module")
def cases():
    return by_id([json.loads(line) for line in SEED.read_text().splitlines()])


_cache: dict = {}


def results(t, *flags):
    key = (t.id, flags)
    if key not in _cache:
        _cache[key] = run_adapter(t, SEED, *flags)
    return _cache[key]


@pytest.fixture(params=TARGETS, ids=lambda t: t.id)
def tgt(request):
    require(request.param)
    return request.param


def test_v1_compare_is_the_documented_baseline(tgt, tmp_path):
    out = tmp_path / "v1.jsonl"
    out.write_text("".join(json.dumps(r) + "\n" for r in results(tgt)))
    proc = subprocess.run([sys.executable, str(REPO / "harness" / "compare.py"), str(SEED),
                           str(EXPECTED), str(out), "--json"], capture_output=True, text=True,
                          check=True)
    kinds = collections.Counter(json.loads(line)["kind"] for line in proc.stdout.splitlines())
    assert dict(kinds) == V1_BASELINE[tgt.id]


def test_v2_answers_equal_the_v1_answers(tgt, expected, cases):
    """--v2 on legacy input runs the same library calls: predicates and validity are the v1
    values, and the exact area of each overlay output geometry is the v1 area up to
    rounding. Two roundings separate them: the library's own double area computation (a
    shoelace over n vertices of magnitude M errs by up to about n M^2 2^-52: bg::area is off
    by 4.5e-10 on tiny-rotation-offset-1-000001, whose output geometry has exactly the
    oracle's area), and, for CGAL, the rounding of exact output coordinates to doubles
    (about n M ulp(M))."""
    v1, v2 = by_id(results(tgt)), by_id(results(tgt, "--v2"))
    assert v1.keys() == v2.keys()
    for cid, r2 in v2.items():
        r1 = v1[cid]
        if "unsupported" in r1["errors"]:  # Clipper2: outside the int64 contract
            assert r2["overlay"]["union"] == "unsupported"
            continue
        for p in V1_PREDICATES:
            assert r2["predicates"][p] == r1[p], (tgt.id, cid, p)
        for k in ("valid_a", "valid_b"):
            assert r2[k] == r1[k], (tgt.id, cid, k)
        for op in OPS:
            a1 = r1[V1_AREA[op]]
            if a1 is None:
                assert r2["overlay"][op] is None and f"overlay.{op}" in r2["errors"]
                continue
            a2 = area(r2["overlay"][op])
            scale = max(expected[cid].get("area_a") or 0, expected[cid].get("area_b") or 0, abs(a1))
            m = max(abs(v) for p in positions_of_case(cases[cid]) for v in p)
            n = len(positions(r2["overlay"][op]))
            tol = 1e-12 * scale + n * (m * m + m) * 2.0**-50
            assert abs(float(a2) - a1) <= tol, (tgt.id, cid, op, float(a2), a1)


def test_v2_disagreements_with_the_exact_answer_are_the_v1_ones(tgt, expected, cases):
    """Scored like compare.py (predicates exactly, areas beyond 1e-6 of the operands' area),
    the v2 output has exactly the v1 disagreements."""
    v1, v2 = by_id(results(tgt)), by_id(results(tgt, "--v2"))

    def disagreements(get_pred, get_area, rec):
        out = set()
        for cid, r in rec.items():
            e = expected[cid]
            if not (e["valid_a"] and e["valid_b"]):
                continue
            for p in V1_PREDICATES:
                got = get_pred(r, p)
                if got in (True, False) and got != e[p]:
                    out.add((cid, p))
            scale = max(e["area_a"], e["area_b"], 1e-300)
            for op in OPS:
                got = get_area(r, op)
                if got is not None and abs(got - e[V1_AREA[op]]) > REL_TOL * scale:
                    out.add((cid, op))
        return out

    d1 = disagreements(lambda r, p: r[p], lambda r, op: r[V1_AREA[op]], v1)
    d2 = disagreements(lambda r, p: r["predicates"][p],
                       lambda r, op: (float(area(r["overlay"][op]))
                                      if isinstance(r["overlay"][op], dict) else None), v2)
    assert d2 == d1


def test_cgal_is_exact_on_the_seed(expected, tmp_path):
    """The exact control: CGAL's exact overlay areas equal the oracle's exact areas on every
    seed case; its output doubles are the correctly rounded exact coordinates; its derived
    predicates and its validity equal the oracle's."""
    t = target("cgal")
    require(t)
    side = tmp_path / "exact.jsonl"
    out = by_id(run_adapter(t, SEED, "--v2", "--exact", str(side)))
    exact = by_id([json.loads(line) for line in side.read_text().splitlines()])
    assert len(out) == len(exact) == 1000
    for cid, e in expected.items():
        r, x = out[cid], exact[cid]
        assert r["errors"] == {}, cid
        assert (r["valid_a"], r["valid_b"]) == (e["valid_a"], e["valid_b"]), cid
        ex = e["exact"]
        i, da, db = Fraction(ex["inter"]), Fraction(ex["diff_ab"]), Fraction(ex["diff_ba"])
        want = {"intersection": i, "union": i + da + db, "difference": da, "symdifference": da + db}
        for op in OPS:
            ov = x["overlay"][op]
            assert Fraction(ov["area"]) == want[op], (cid, op)  # exact equality
            assert exact_area(ov["exact"]) == want[op], (cid, op)
            got = positions(r["overlay"][op])
            ring_pts = [(float(Fraction(px)), float(Fraction(py)))
                        for px, py in exact_positions(ov["exact"])]
            assert got == ring_pts, (cid, op)  # Fraction -> float is correctly rounded
            assert ov["num_vertices"] + count_rings(ov["exact"]) == len(ring_pts)
        for p in V1_PREDICATES:
            assert r["predicates"][p] == e[p], (cid, p)
        assert r["predicates"]["crosses"] is False and r["relate"] is None


def positions_of_case(c: dict) -> list[tuple[float, float]]:
    return [(float(x), float(y)) for g in (c["a"], c["b"]) for poly in g for ring in poly
            for x, y, *_ in ring]


def exact_positions(g: dict) -> list[tuple[str, str]]:
    rings = g["coordinates"] if g["type"] == "Polygon" else [r for p in g["coordinates"] for r in p]
    return [tuple(p) for r in rings for p in r]


def count_rings(g: dict) -> int:
    if g["type"] == "Polygon":
        return len(g["coordinates"])
    return sum(len(p) for p in g["coordinates"])


def exact_area(g: dict) -> Fraction:
    """Signed shoelace area of an exact (rational) result: CGAL writes shells
    counter-clockwise and holes clockwise, so the signed sum is the area."""
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    total = Fraction(0)
    for poly in polys:
        for ring in poly:
            pts = [(Fraction(x), Fraction(y)) for x, y in ring]
            total += sum((p[0] * q[1] - q[0] * p[1] for p, q in itertools.pairwise(pts)),
                         Fraction(0)) / 2
    return total
