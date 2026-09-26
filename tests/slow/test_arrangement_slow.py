"""Slow arrangement tests: whole corpora, large inputs, the budget, and timings.

Run with ``python3 -m pytest -m slow tests/slow/test_arrangement_slow.py -s`` to see the
timing report (the assertions on time are deliberately generous).
"""

from __future__ import annotations

import math
import random
import statistics
import time
from collections import defaultdict
from fractions import Fraction
from pathlib import Path

import pytest

from geotruth.arrangement import Budget, BudgetExceeded, build_arrangement
from geotruth.arrangement_api import Location
from geotruth.exact import signed_area2
from geotruth.geom import Polygon
from geotruth.io import case_from_json
from geotruth.numbers import json_loads
from reference import oracle
from unit.arrangement_testlib import (
    check_labels,
    components,
    face_area2,
    random_face_points,
    random_operand,
)

pytestmark = pytest.mark.slow

I, E = Location.INTERIOR, Location.EXTERIOR
REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "corpus" / "cases" / "seed.jsonl"


def _cases(lines):
    return [json_loads(line) for line in lines if line.strip()]


def _review_lines() -> list[str]:
    pytest.importorskip("shapely")
    import subprocess
    import sys

    gen = REPO / "tools" / "oracle_review" / "gen_review.py"
    out = subprocess.run(
        [sys.executable, str(gen), "all", "20", "1"], check=True, capture_output=True, text=True
    ).stdout
    return out.splitlines()


def _timed_corpus(objs, family_of):
    times = defaultdict(list)
    arrs = []
    for obj in objs:
        case = case_from_json(obj)
        t = time.perf_counter()
        arr = build_arrangement(case.a, case.b)
        times[family_of(obj)].append(time.perf_counter() - t)
        arrs.append((obj, case, arr))
    return times, arrs


def _report(title, times):
    allt = [t for ts in times.values() for t in ts]
    mean, median = 1e3 * statistics.mean(allt), 1e3 * statistics.median(allt)
    print(
        f"\n{title}: {len(allt)} cases, total {sum(allt):.3f} s, mean {mean:.2f} ms, "
        f"median {median:.2f} ms, max {1e3 * max(allt):.1f} ms"
    )
    for fam, ts in sorted(times.items()):
        print(
            f"  {fam:40s} n={len(ts):4d} mean {1e3 * statistics.mean(ts):7.2f} ms  "
            f"max {1e3 * max(ts):7.1f} ms"
        )
    return allt


def _areas(arr):
    out = defaultdict(Fraction)
    for f in range(1, arr.num_faces):
        out[(arr.face_loc_a[f], arr.face_loc_b[f])] += face_area2(arr, f) / 2
    return out


def test_seed_corpus_full():
    """All 1000 seed cases: build (timed), every invariant, exact areas against the
    oracle, and every cell label against the brute-force locator."""
    with open(SEED, encoding="utf-8") as fh:
        objs = _cases(fh)
    times, arrs = _timed_corpus(objs, lambda o: o.get("family", "?"))
    allt = _report("seed corpus", times)
    assert len(allt) == 1000
    assert statistics.mean(allt) < 0.05
    rng = random.Random(1)
    for obj, case, arr in arrs:
        arr.validate(geometry=True, planarity=True, labels=True)
        both, only_a, only_b = oracle.overlay_areas(oracle.edges(obj["a"]), oracle.edges(obj["b"]))
        areas = _areas(arr)
        assert (areas[(I, I)], areas[(I, E)], areas[(E, I)]) == (both, only_a, only_b)
        check_labels(arr, case.a, case.b, random_face_points(rng, arr, 5))


def test_review_families_full():
    objs = _cases(_review_lines())
    times, arrs = _timed_corpus(objs, lambda o: o["id"].rsplit("-", 1)[0].split("/")[0])
    allt = _report("review families (gen_review.py all 20 1)", times)
    assert statistics.mean(allt) < 0.05
    for obj, case, arr in arrs:
        arr.validate(geometry=True, planarity=True, labels=True)
        both, only_a, only_b = oracle.overlay_areas(oracle.edges(obj["a"]), oracle.edges(obj["b"]))
        areas = _areas(arr)
        assert (areas[(I, I)], areas[(I, E)], areas[(E, I)]) == (both, only_a, only_b)
        check_labels(arr, case.a, case.b)


@pytest.mark.parametrize("block", range(4))
def test_many_random_lattice_cases(block):
    for seed in range(block * 500, (block + 1) * 500):
        rng = random.Random(500_000 + seed)
        size = (3, 6, 10)[seed % 3]
        a, b = random_operand(rng, size), random_operand(rng, size)
        arr = build_arrangement(a, b)
        arr.validate(geometry=True, planarity=True, labels=True)
        assert arr.num_vertices - arr.num_edges + arr.num_faces == 1 + components(arr)
        check_labels(arr, a, b, random_face_points(rng, arr, 10))


# ================================================================= large inputs


def star(rng: random.Random, n: int) -> Polygon:
    angs = sorted(rng.uniform(0, 2 * math.pi) for _ in range(n))
    pts = []
    for t in angs:
        r = rng.uniform(0.2, 1.0)
        pts.append((r * math.cos(t), r * math.sin(t)))
    return Polygon([[*pts, pts[0]]])


def comb(n: int, vertical: bool) -> Polygon:
    """A comb with n teeth; two perpendicular combs cross about 4 n^2 times."""
    pts = []
    for i in range(n):
        pts += [(float(i), 0.0), (i + 0.5, float(n))]
    pts += [(float(n), -1.0), (0.0, -1.0)]
    if vertical:
        pts = [(y, x) for x, y in pts]
    return Polygon([[*pts, pts[0]]])


def _shoelace(poly: Polygon) -> Fraction:
    return abs(Fraction(signed_area2([(Fraction(x), Fraction(y)) for x, y in poly.shell]))) / 2


@pytest.mark.parametrize(("kind", "n"), [("star", 2000), ("comb", 100), ("comb", 150)])
def test_large_inputs(kind, n):
    rng = random.Random(n)
    if kind == "star":
        a, b = star(rng, n), star(rng, n)
    else:
        a, b = comb(n, False), comb(n, True)
    stats = {}
    t = time.perf_counter()
    arr = build_arrangement(a, b, stats=stats)
    dt = time.perf_counter() - t
    print(
        f"\n{kind} {n}: {dt:.2f} s, n={stats['n']} k={stats['k']} chains={stats['chains']} "
        f"chain pairs={stats['chain_pairs']} segment tests={stats['segment_tests']} "
        f"V={stats['V']} E={stats['E']} F={stats['F']}"
    )
    print("  phases: " + ", ".join(f"{k[2:]} {v:.2f}" for k, v in stats.items() if k[:2] == "t_"))
    arr.validate(geometry=True, labels=True)
    areas = _areas(arr)
    assert sum(v for (la, _), v in areas.items() if la == I) == _shoelace(a)
    assert sum(v for (_, lb), v in areas.items() if lb == I) == _shoelace(b)
    assert dt < 120


def test_budget_on_a_large_input():
    a, b = comb(250, False), comb(250, True)  # about 250k crossings: over the default
    t = time.perf_counter()
    with pytest.raises(BudgetExceeded) as info:
        build_arrangement(a, b)
    assert info.value.resource == "size" and info.value.limit == 200_000
    assert time.perf_counter() - t < 30
    with pytest.raises(BudgetExceeded) as info:
        build_arrangement(a, b, budget=Budget(max_size=None, max_seconds=1.0))
    assert info.value.resource == "time"
