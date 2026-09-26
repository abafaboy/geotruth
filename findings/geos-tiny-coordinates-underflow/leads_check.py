# Usage: GEOSOP=/path/to/geosop python3 leads_check.py   (default: the GEOS main build used in this hunt)
# Original leads from oracle_review/README.md, checked with Shapely and with geosop (GEOS main).
import math, subprocess, shapely
from shapely.geometry import box, Polygon
from shapely.validation import explain_validity
import os
GEOSOP = os.environ.get("GEOSOP", "/tmp/claude-0/gb-build/geos-main/install/bin/geosop")
def geosop(a, b, op):
    args = [GEOSOP, "-a", a] + (["-b", b] if b else []) + [op]
    return subprocess.run(args, capture_output=True, text=True).stdout.strip()
print("shapely", shapely.__version__, "GEOS", shapely.geos_version_string)
for s in [1e-150, 1e-160, 1e-162, 1e-170, 1e-200, 1e-300]:
    a, b = box(0, 0, s, s), box(s/2, s/2, 2*s, 2*s)
    print("s=%-7g shapely relate=%s touches=%s | geos-main relate=%s" % (s, a.relate(b), a.touches(b), geosop(a.wkt, b.wkt, "relate")))
for k in [-520, -530, -535, -538, -540, -600]:
    f = math.ldexp(1.0, k)
    p = Polygon([(0,0),(4*f,0),(4*f,4*f),(0,4*f)], [[(0,2*f),(2*f,1*f),(2*f,3*f)]])
    w = "POLYGON ((%r %r, %r %r, %r %r, %r %r, %r %r), (%r %r, %r %r, %r %r, %r %r))" % (0.,0.,4*f,0.,4*f,4*f,0.,4*f,0.,0., 0.,2*f,2*f,f,2*f,3*f,0.,2*f)
    print("2^%d: shapely %s | geos-main %s" % (k, explain_validity(p), geosop(w, None, "isValid")))
