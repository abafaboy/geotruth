"""RelateNG line-end-skip (and its computeAreaVertex twin) through Shapely (GEOS >= 3.13 uses RelateNG for relate()).

    python3 repro_shapely.py
"""
import shapely

CASES = [
    # (label, A, B, exact relate(A, B))
    ("case 1", "POINT (10 10)",
     "MULTILINESTRING ((0 0, 1 0, 1 1, 0 0), (5 5, 6 6))", "FF0FFF102"),
    ("case 1, B's elements swapped", "POINT (10 10)",
     "MULTILINESTRING ((5 5, 6 6), (0 0, 1 0, 1 1, 0 0))", "FF0FFF102"),
    ("case 1, operands swapped", "MULTILINESTRING ((0 0, 1 0, 1 1, 0 0), (5 5, 6 6))",
     "POINT (10 10)", "FF1FF00F2"),
    ("case 1, degenerate closed elem", "POINT (10 10)",
     "MULTILINESTRING ((0 0, 1 0, 0 0), (5 5, 6 6))", "FF0FFF102"),
    ("case 2", "POLYGON ((1 2, 4 0, 1 0, 1 2))",
     "MULTILINESTRING ((2 3, 1 1), (2 3, 4 3))", "1F2001102"),
    ("case 2, operands swapped", "MULTILINESTRING ((2 3, 1 1), (2 3, 4 3))",
     "POLYGON ((1 2, 4 0, 1 0, 1 2))", "101F00212"),
    ("case 3 (JTS #1175)", "LINESTRING (10 10, 20 20)",
     "MULTILINESTRING ((0 0, 1 0), (1 0, 2 0), (-1 0, 0 0))", "FF1FF0102"),
    ("case 4 (GC, computeAreaVertex)",
     "GEOMETRYCOLLECTION (POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)), POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)))",
     "LINESTRING (10 10, 11 11)", "FF2FF1102"),
    ("case 4, squares swapped",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)))",
     "LINESTRING (10 10, 11 11)", "FF2FF1102"),
    ("case 5 (GC, nested squares)",
     "GEOMETRYCOLLECTION (POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)), POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)))",
     "LINESTRING (10 10, 11 11)", "FF2FF1102"),
    ("case 5, squares swapped",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1)))",
     "LINESTRING (10 10, 11 11)", "FF2FF1102"),
]

print("shapely", shapely.__version__, "GEOS", shapely.geos_version_string)
for label, a, b, exact in CASES:
    ga, gb = shapely.from_wkt(a), shapely.from_wkt(b)
    got = shapely.relate(ga, gb)
    print(f"{label:30s} relate = {got}  exact {exact}  {'ok' if got == exact else 'WRONG'}")

b = shapely.from_wkt(CASES[0][2])
print("boundary(B) =", shapely.boundary(b).wkt,
      "| relate(POINT (5 5), B) =", shapely.relate(shapely.from_wkt("POINT (5 5)"), b))
print('relate_pattern(A, B, "FF*FF**0*") =',
      shapely.relate_pattern(shapely.from_wkt(CASES[0][1]), b, "FF*FF**0*"), "(exact: True)")
