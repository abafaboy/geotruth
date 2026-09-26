"""Shapely (GEOS) reproducer: overlay of two triangles loses most of B.

Run: python3 repro.py
Uses only Shapely's public API.
"""
import shapely
from shapely import wkt

A = wkt.loads("POLYGON ((1 1, -1e-20 0, 1 0, 1 1))")   # area 0.5 (+5e-21)
B = wkt.loads("POLYGON ((0 0, 1 1, 0 1, 0 0))")         # area 0.5

print("shapely", shapely.__version__, "GEOS", shapely.geos_version_string)
print("valid:", A.is_valid, B.is_valid, " areas:", A.area, B.area)
print("predicates: intersects", A.intersects(B), "overlaps", A.overlaps(B),
      "covers(A,B)", A.covers(B))
for name, g, exp in [
    ("union", A.union(B), "~1.0"),
    ("intersection", A.intersection(B), "~5e-21"),
    ("B - A", B.difference(A), "~0.5"),
    ("A - B", A.difference(B), "~0.5"),
    ("symdifference", A.symmetric_difference(B), "~1.0"),
]:
    print(f"{name:14s} area = {g.area!r:24s} (expected {exp})  {g.wkt}")
