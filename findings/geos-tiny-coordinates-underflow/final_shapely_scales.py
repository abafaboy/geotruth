import shapely, warnings; warnings.simplefilter("ignore")
from shapely import wkt
print("shapely", shapely.__version__, "GEOS", shapely.geos_version_string)
for S in ("e102", "e103", "e105", "e-103", "e-104"):
    A = wkt.loads(f"POLYGON ((0 0, 2{S} 0, 2{S} 2{S}, 0 2{S}, 0 0))")
    B = wkt.loads(f"POLYGON ((1{S} 1{S}, 3{S} 1{S}, 3{S} 3{S}, 1{S} 3{S}, 1{S} 1{S}))")
    print(f"  S=1{S}: relate={A.relate(B)} overlaps={A.overlaps(B)} intersection={A.intersection(B).wkt}")
