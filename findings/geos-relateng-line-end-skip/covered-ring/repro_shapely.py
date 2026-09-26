"""RelateNG, GEOS >= 3.13.1: a linear B is not self-noded when A is polygonal.

    python3 repro_shapely.py
"""
import shapely

CASES = [
    # (label, A, B, exact relate(A, B))
    ("case 1", "POLYGON ((0 0, 2 0, 1 1, 0 0))",
     "MULTILINESTRING ((0 0, 2 0, 1 1, 0 0), (1 0, 1 -1))", "FF210F102"),
    ("case 1, operands swapped", "MULTILINESTRING ((0 0, 2 0, 1 1, 0 0), (1 0, 1 -1))",
     "POLYGON ((0 0, 2 0, 1 1, 0 0))", "F11F002F2"),
    ("case 2 (rectangle)", "POLYGON ((0 0, 2 0, 2 1, 0 1, 0 0))",
     "MULTILINESTRING ((0 0, 2 0, 2 1, 0 1, 0 0), (1 0, 1 -1))", "FF210F102"),
    ("case 3 (one LineString)", "POLYGON ((0 0, 2 0, 1 1, 0 0))",
     "LINESTRING (0 0, 2 0, 1 1, 0 0, 1 -1, 1 0)", "FF210F1F2"),
    ("case 4 (hole touch)", "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))",
     "LINESTRING (0 0, 4 0)", "FF2101FF2"),
    ("case 5 (touching parts)", "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 2, 2 3, 0 3, 1 2)))",
     "LINESTRING (0 2, 2 2)", "FF2101FF2"),
    ("case 6 (GC as B)", "POLYGON ((0 0, 0 3, 3 3, 3 2, 0 0))",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), POLYGON ((1 0, 2 0, 2 4, 1 4, 1 0)))",
     "2FF11F212"),
]

print("shapely", shapely.__version__, "GEOS", shapely.geos_version_string)
for label, a, b, exact in CASES:
    ga, gb = shapely.from_wkt(a), shapely.from_wkt(b)
    try:
        got = shapely.relate(ga, gb)
    except shapely.errors.GEOSException as e:  # GEOS < 3.13 (RelateOp) and GCs
        print(f"{label:26s} relate raised {e}")
        continue
    print(f"{label:26s} relate = {got}  exact {exact}  {'ok' if got == exact else 'WRONG'}")
a4, b4 = shapely.from_wkt(CASES[4][1]), shapely.from_wkt(CASES[4][2])
a5, b5 = shapely.from_wkt(CASES[5][1]), shapely.from_wkt(CASES[5][2])
print("case 4: contains =", shapely.contains(a4, b4), "(exact False), touches =",
      shapely.touches(a4, b4), "(exact True)")
print("case 5: covers =", shapely.covers(a5, b5), "(exact True)")
a6, b6 = shapely.from_wkt(CASES[6][1]), shapely.from_wkt(CASES[6][2])
try:
    print("case 6: within(A, B) =", shapely.within(a6, b6), "(exact True), contains(B, A) =",
          shapely.contains(b6, a6), "(exact True)")
except shapely.errors.GEOSException as e:
    print("case 6: within/contains raised", e)
