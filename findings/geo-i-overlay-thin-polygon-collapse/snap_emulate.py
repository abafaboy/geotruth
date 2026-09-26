# Emulates i_float 1.16.0 FloatPointAdapter::new + float_to_int (the auto-scaled i32 grid
# used by geo 0.33.1 BooleanOps via i_overlay 4.5.2) in IEEE double arithmetic.
import json, math, sys
from fractions import Fraction as F
def to_i32(v):  # (v + 0.5.copysign(v)) as i32  -> round half away from zero, then truncate
    return int(v + math.copysign(0.5, v))
def adapter(pts):
    xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
    a=(max(xs)-min(xs))*0.5; b=(max(ys)-min(ys))*0.5
    ox=min(xs)+a; oy=min(ys)+b
    m=max(a,b); lg=to_i32(math.log2(m)); e=29-lg
    return (ox,oy,2.0**e,e)
def area2(r):
    return abs(sum(F(p[0])*F(q[1])-F(q[0])*F(p[1]) for p,q in zip(r,r[1:]+r[:1])))/2
for l in open(sys.argv[1]):
    c=json.loads(l)
    rings=[r[:-1] for poly in c["a"]+c["b"] for r in poly]
    ox,oy,s,e=adapter([p for r in rings for p in r])
    print(c["id"], f"offset=({ox!r},{oy!r}) scale=2^{e} grid step=2^{-e}={2.0**-e!r}")
    for name,g in (("A",c["a"]),("B",c["b"])):
        r=[(float(x),float(y)) for x,y in g[0][0][:-1]]
        sn=[(to_i32((x-ox)*s),to_i32((y-oy)*s)) for x,y in r]
        print(f"   {name}: exact area {area2(r)}  snapped ints {sn}  snapped area (grid units^2) {area2(sn)}  -> {float(area2(sn))*(2.0**-e)**2!r}")
