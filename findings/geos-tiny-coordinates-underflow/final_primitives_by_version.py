import ctypes, math, glob, os
B="/tmp/claude-0/gb-build"
libs = {
 "3.11.4": glob.glob(B+"/triage/geos-multipolygon-touching-parts-predicates/venv-shapely20/lib/python3.11/site-packages/shapely.libs/libgeos_c-*.so*")[0],
 "3.13.1": glob.glob("/usr/local/lib/python3.11/dist-packages/shapely.libs/libgeos_c-*.so*")[0],
 "3.14.1": glob.glob(B+"/triage/geos-multipolygon-touching-parts-predicates/venv-shapely22/lib/python3.11/site-packages/shapely.libs/libgeos_c-*.so*")[0],
 "3.15.0": B+"/geos-release/install/lib/libgeos_c.so",
 "main":   B+"/geos-main/install/lib/libgeos_c.so",
}
import sys
name=sys.argv[1]; p=libs[name]
for f in glob.glob(os.path.dirname(p)+'/libgeos-*.so*')+glob.glob(os.path.dirname(p)+'/libgeos.so.3*'):
    ctypes.CDLL(f, mode=ctypes.RTLD_GLOBAL)
lib=ctypes.CDLL(p); lib.GEOS_init_r.restype=ctypes.c_void_p
lib.GEOSversion.restype=ctypes.c_char_p
lib.GEOSOrientationIndex_r.argtypes=[ctypes.c_void_p]+[ctypes.c_double]*6
D=ctypes.c_double
lib.GEOSSegmentIntersection_r.argtypes=[ctypes.c_void_p]+[D]*8+[ctypes.POINTER(D)]*2
ctx=lib.GEOS_init_r()
oi=lambda *a: lib.GEOSOrientationIndex_r(ctx,*a)
print(name, lib.GEOSversion().decode())
tr=(-1.6,1.2,-3.2,-1.8,-6.4,-7.8)
print("  near-collinear triple, exact -1:", [(k, oi(*[math.ldexp(v,k) for v in tr])) for k in (0,-510,-514,-520,510,512)])
print("  triangle (0 0),(s 0),(0 s), exact +1:", [(s, oi(0,0,s,0,0,s)) for s in (1.6e-162,1.5e-162,1e-200)])
print("  square edge (2S 0),(2S 2S),(S S), exact +1:", [(S, oi(2*S,0,2*S,2*S,S,S)) for S in (1e153,1e154,1e155,1e300)])
def si(S):
    x=D(); y=D(); r=lib.GEOSSegmentIntersection_r(ctx,2*S,0,2*S,2*S,S,S,3*S,S,ctypes.byref(x),ctypes.byref(y))
    return (r, (x.value/S, y.value/S)) if r==1 else (r,)
print("  GEOSSegmentIntersection((2S 0)-(2S 2S),(S S)-(3S S))/S, exact (2 1):", [(S, si(S)) for S in (1e102,1e103,1e-102,1e-103,1e-200)])
