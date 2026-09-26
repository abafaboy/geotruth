"""Random near-collinear point triples that GEOSOrientationIndex classifies correctly at
unit scale, multiplied EXACTLY by 2^k (math.ldexp; every scaled value is checked to scale
back exactly). The exact orientation cannot depend on k, so every disagreement at 2^k
is caused by the magnitude alone. Calls the public C API function GEOSOrientationIndex_r
through ctypes; exact signs with fractions.Fraction.

    GEOS_C_LIB=/path/to/libgeos_c.so python3 orientation_random_scaling.py
"""
import ctypes, math, os, random
from fractions import Fraction as F

lib = ctypes.CDLL(os.environ.get("GEOS_C_LIB", "/tmp/claude-0/gb-build/geos-main/install/lib/libgeos_c.so"))
lib.GEOS_init_r.restype = ctypes.c_void_p
lib.GEOSOrientationIndex_r.argtypes = [ctypes.c_void_p] + [ctypes.c_double] * 6
lib.GEOSOrientationIndex_r.restype = ctypes.c_int
lib.GEOSversion.restype = ctypes.c_char_p
ctx = lib.GEOS_init_r()
print("GEOS", lib.GEOSversion().decode())


def exact(a, b, c, d, e, f):
    a, b, c, d, e, f = map(F, (a, b, c, d, e, f))
    det = (c - a) * (f - d) - (d - b) * (e - c)
    return (det > 0) - (det < 0)


random.seed(2)
base = []
while len(base) < 20000:
    a, b, c, d = [random.uniform(-8, 8) for _ in range(4)]
    t = random.uniform(-3, 3)
    e = a + t * (c - a)
    f = b + t * (d - b)
    for _ in range(random.randint(0, 2)):
        e = math.nextafter(e, random.choice([-math.inf, math.inf]))
    tr = (a, b, c, d, e, f)
    x = exact(*tr)
    if lib.GEOSOrientationIndex_r(ctx, *tr) == x:
        base.append((tr, x))
print("%d triples, all classified correctly at unit scale (none exactly collinear: %s)"
      % (len(base), all(x != 0 for _, x in base)))
print("k       ~scale    reported collinear   opposite sign   (of %d)" % len(base))
for k in [-400, -500, -505, -510, -512, -515, -520, -530, -540, -600, -1000,
          400, 500, 505, 507, 508, 510, 512, 600, 1000]:
    zero = flip = 0
    for tr, x in base:
        s = tuple(math.ldexp(v, k) for v in tr)
        assert all(math.ldexp(v, -k) == w for v, w in zip(s, tr))
        g = lib.GEOSOrientationIndex_r(ctx, *s)
        if g != x:
            if g == 0:
                zero += 1
            else:
                flip += 1
    print("2^%-5d ~1e%-5d  %8d             %8d" % (k, round(k * math.log10(2)), zero, flip))
