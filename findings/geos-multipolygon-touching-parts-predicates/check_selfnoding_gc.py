"""Supporting check (public API only): wrapping the polygonal operand in a GeometryCollection
makes RelateNG self-node it (RelateGeometry::isSelfNodingRequired() is true for a GC with more
than one element). The point-set is unchanged: POINT (3 3) lies in the polygon's interior.
With self-noding, all three cases give the expected matrices."""
import shapely
from shapely import wkt

CASES = [
    ("case 1", "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), POLYGON ((1 2, 2 3, 0 3, 1 2)))",
     "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))", "2F2F11FF2"),
    ("case 2", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0)), POINT (3 3))",
     "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0))", "212F1FFF2"),
    ("case 3", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 1, 1 1, 2 0)), POINT (3 3))",
     "POLYGON ((0 -1, 4 -1, 4 0, 0 0, 0 -1))", "FF2F11212"),
]
print("shapely", shapely.__version__, "GEOS", shapely.geos_version_string)
for name, wa, wb, exp in CASES:
    a, b = wkt.loads(wa), wkt.loads(wb)
    print(f"{name}: A={wa}\n        B={wb}\n  relate expected {exp} got {a.relate(b)}")
