"""Exact answers and independent checks for cases.jsonl (run from the repository root):

    PYTHONPATH=src python3 findings/geos-relateng-geometrycollection-semantics/exact_check.py

1. geotruth's two exact relate routes (arrangement, strict; witness points) must agree and match
   the stored matrix; exact validity (geotruth.validity) of both operands.
2. D2: the disputed point located exactly by geotruth.locate in the GC (union semantics) and in
   the union of its polygons (brute force: in the interior of some polygon, or on the boundary
   of several polygons whose sectors cover the whole neighbourhood, checked on a ring of test
   points at tiny exact offsets).
3. D3: the frame's union is the Polygon with a hole P = [0,3]^2 minus [1,2]^2; the audited
   polygon references tests/reference/oracle.py and indep.py evaluate (P, square).
4. D1: hand-checkable statements (the far point is outside B; B is inside the polygon element).
"""
import json
import sys
from fractions import Fraction as Fr
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests" / "reference")]
import indep  # noqa: E402
import oracle  # noqa: E402
from geotruth.io import read_wkt  # noqa: E402
from geotruth.locate import locate  # noqa: E402
from geotruth.relate import relate  # noqa: E402
from geotruth.relate_witness import relate_witness  # noqa: E402
from geotruth.validity import is_valid  # noqa: E402

HERE = Path(__file__).parent
rows = [json.loads(line) for line in open(HERE / "cases.jsonl")]
print("1. exact matrices (arrangement route, witness route) and exact validity")
for r in rows:
    a, b = read_wkt(r["a_wkt"]), read_wkt(r["b_wkt"])
    m1 = relate(a, b, strict=True).matrix
    m2 = relate_witness(a, b).matrix
    ok = m1 == m2 == r["expected_relate"]
    print(f"  {r['id'].split(':')[1]:34s} arrangement {m1}  witness {m2}  valid {is_valid(a)},{is_valid(b)}  {'ok' if ok else 'MISMATCH'}")
    assert ok

print("\n2. D2: the reflex vertex, located exactly")
ARROW = [[(0, 0), (2, 1), (4, 0), (2, 3), (0, 0)]]
RECT = [[(1, 0), (3, 0), (3, 1), (1, 1), (1, 0)]]
gc = read_wkt("GEOMETRYCOLLECTION (POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0)), POLYGON ((1 0, 3 0, 3 1, 1 1, 1 0)))")
print("  geotruth.locate((2,1), GC) =", locate((2, 1), gc))
# brute force: points at distance eps around (2,1) in 64 exact rational directions; each must be
# inside (or on) one of the two polygons for (2,1) to be an interior point of the union
eps = Fr(1, 10**6)
dirs = [(Fr(c), Fr(s)) for c, s in [(1, 0), (0, 1), (-1, 0), (0, -1)]]
for k in range(1, 16):
    t = Fr(k, 16)
    for sx, sy in [(1, 1), (-1, 1), (-1, -1), (1, -1)]:
        dirs += [(sx * t, sy * (1 - t)), (sx * (1 - t), sy * t)]
arrow, rect = read_wkt("POLYGON ((0 0, 2 1, 4 0, 2 3, 0 0))"), read_wkt("POLYGON ((1 0, 3 0, 3 1, 1 1, 1 0))")
uncovered = [d for d in dirs if locate((2 + eps * d[0], 1 + eps * d[1]), arrow) == "E"
             and locate((2 + eps * d[0], 1 + eps * d[1]), rect) == "E"]
print(f"  {len(dirs)} exact probe points at distance ~1e-6 around (2,1): {len(uncovered)} outside both polygons")
print("  in the arrowhead alone (2,1) is", locate((2, 1), arrow), "; in the rectangle alone", locate((2, 1), rect))

print("\n3. D3: the frame's union P = [0,3]^2 minus [1,2]^2 against the square, audited references")
P = [[[0, 0], [3, 0], [3, 3], [0, 3], [0, 0]], [[1, 1], [1, 2], [2, 2], [2, 1], [1, 1]]]
S = [[[0, 0], [3, 0], [3, 3], [0, 3], [0, 0]]]
ri = indep.evaluate_geoms([P], [S])
ro = oracle.evaluate({"id": "frame", "a": [P], "b": [S]})
keys = ["equals", "contains", "covers", "within", "covered_by", "overlaps", "touches"]
print("  indep.py :", {k: ri[k] for k in keys}, "area(P) =", ri["area_a"], "area(square) =", ri["area_b"])
print("  oracle.py:", {k: ro[k] for k in keys}, "area_diff(square - P) =", ro["exact"]["diff_ba"])
frame = read_wkt(rows[[r["id"].endswith("d3-frame-equals") for r in rows].index(True)]["a_wkt"])
print("  geotruth.locate((1.5,1.5), frame GC) =", locate((Fr(3, 2), Fr(3, 2)), frame),
      "; each strip:", [locate((Fr(3, 2), Fr(3, 2)), g) for g in frame.geometries])

print("\n4. D1: the far point and the covered polygon")
A = read_wkt("GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)), POINT (10 10))")
B = read_wkt("POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))")
print("  relate(polygon element, B) =", relate(A.geometries[0], B).matrix,
      "; POINT (10 10) in B:", locate((10, 10), B))
print("  so relate(A, B) = that matrix with IE raised to at least 0 (the point):", relate(A, B).matrix)
L = read_wkt("LINESTRING (0 0, 1 0, 0 1, 0 0)")
G = read_wkt("GEOMETRYCOLLECTION (POINT (0 0), LINESTRING (5 5, 6 6))")
print("  (1/2, 0) on the ring:", locate((Fr(1, 2), 0), L), "; in the GC:", locate((Fr(1, 2), 0), G),
      "-> the ring's interior meets the GC's exterior, so IE = 1 and within/coveredBy are false")
