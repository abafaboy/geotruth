"""The same input through Shapely (whatever GEOS it bundles), grid_size=1."""
import shapely
from shapely import wkt

a = wkt.loads("MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((3 0, 5 0, 5 0.4, 3 0)))")
p = wkt.loads("POINT (7 7)")
line = wkt.loads("LINESTRING (7 7, 8 8)")
print(f"shapely {shapely.__version__}, GEOS {shapely.geos_version_string}")
print("union(A, P, grid_size=1)          =", shapely.union(a, p, grid_size=1))
print("symmetric_difference(A, P, grid 1) =", shapely.symmetric_difference(a, p, grid_size=1))
print("difference(A, P, grid_size=1)     =", shapely.difference(a, p, grid_size=1))
print("union(A, LINE, grid_size=1)       =", shapely.union(a, line, grid_size=1))
