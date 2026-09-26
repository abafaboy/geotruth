import shapely
from shapely import wkt
print(shapely.__version__, shapely.geos_version_string)
for S in ("e150","e154","e155","e200","e300"):
    f=lambda t: wkt.loads(t.replace("S",S))
    A=f("POLYGON ((0 0, 2S 0, 2S 2S, 0 2S, 0 0))"); B=f("POLYGON ((1S 1S, 3S 1S, 3S 3S, 1S 3S, 1S 1S))"); P=f("POINT (1S 1S)")
    H=f("POLYGON ((0 0, 4S 0, 4S 4S, 0 4S, 0 0), (1S 1S, 1S 2S, 2S 2S, 2S 1S, 1S 1S))")
    try: hv=H.is_valid
    except Exception as e: hv="EXC "+str(e)[:40]
    print(S, "contains", A.contains(P), "relAP", A.relate(P), "relAB", A.relate(B), "H valid", hv)
