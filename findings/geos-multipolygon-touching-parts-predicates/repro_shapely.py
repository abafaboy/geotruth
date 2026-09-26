"""Shapely (GEOS) repro. Public API only.   python repro_shapely.py"""
import shapely
from shapely import wkt

CASES = [
    ("case 1: MultiPolygon A contains its own part B",
     "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))",
     "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))", "2F2F11FF2"),
    ("case 2: shell A contains polygon-with-touching-hole B",
     "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))",
     "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))", "212F1FFF2"),
    ("case 3: polygon-with-touching-hole A touches adjacent B",
     "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))",
     "POLYGON ((0 -1, 4 -1, 4 0, 0 0, 0 -1))", "FF2F11212"),
]

print("shapely", shapely.__version__, "GEOS", shapely.geos_version_string)
for name, wa, wb, exp in CASES:
    a, b = wkt.loads(wa), wkt.loads(wb)
    print(name)
    print(f"  valid: {shapely.is_valid_reason(a)} / {shapely.is_valid_reason(b)}")
    print(f"  relate expected {exp}  got {a.relate(b)}")
    print(f"  contains={a.contains(b)} covers={a.covers(b)} touches={a.touches(b)} "
          f"overlaps={a.overlaps(b)}  area(B - A)={b.difference(a).area}  area(A & B)={a.intersection(b).area}")
