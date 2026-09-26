"""Shapely repro: GEOS RelateNG segfaults on valid GeometryCollections with an EMPTY element.

Each call runs in a fresh interpreter so a segfault is reported instead of ending the run.
Run: python3 repro.py            (uses the shapely importable by this python)
"""
import subprocess
import sys

import shapely

CASES = [
    # (name, A, B, expected relate(A, B))
    ("1  point on the shared edge of two squares, GC has a POLYGON EMPTY",
     "POINT (2 1)",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
     "POLYGON ((2 0, 4 0, 4 2, 2 2, 2 0)), POLYGON EMPTY)",
     "0FFFFF212"),
    ("2  GC(point, LINESTRING EMPTY) vs POINT EMPTY",
     "GEOMETRYCOLLECTION (POINT (0 0), LINESTRING EMPTY)", "POINT EMPTY", "FF0FFFFF2"),
    ("3  GC(line, POLYGON EMPTY) vs a disjoint point (wrong matrix, no crash)",
     "GEOMETRYCOLLECTION (LINESTRING (0 0, 1 0), POLYGON EMPTY)", "POINT (5 5)", "FF1FF00F2"),
]

CHILD = r"""
import sys, shapely
a, b, op = shapely.from_wkt(sys.argv[1]), shapely.from_wkt(sys.argv[2]), sys.argv[3]
print(shapely.relate(a, b) if op == "relate" else getattr(shapely, op)(a, b))
"""


def call(a, b, op):
    p = subprocess.run([sys.executable, "-c", CHILD, a, b, op], capture_output=True, text=True)
    if p.returncode < 0:
        return f"CRASH (signal {-p.returncode})"
    if p.returncode:
        return "exception: " + p.stderr.strip().splitlines()[-1]
    return p.stdout.strip()


print(f"shapely {shapely.__version__}, GEOS {shapely.geos_version_string}")
for name, a, b, expected in CASES:
    ga, gb = shapely.from_wkt(a), shapely.from_wkt(b)
    print(f"\ncase {name}\n  A = {a}\n  B = {b}")
    print(f"  is_valid(A) = {shapely.is_valid(ga)}, is_valid(B) = {shapely.is_valid(gb)}")
    print(f"  expected relate(A, B) = {expected}")
    for op in ("relate", "intersects", "within", "touches"):
        got = call(a, b, op)
        mark = ""
        if got.startswith("CRASH"):
            mark = "   <-- CRASH"
        elif op == "relate":
            mark = "   ok" if got == expected else "   <-- WRONG"
        print(f"  {op + '(A, B)':16s} {got}{mark}")
