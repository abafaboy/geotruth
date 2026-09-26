"""For each Clipper2 adapter v2 result, check the PolyTree-derived polygons:
 - orientation vs level: every shell should have positive signed area, every hole negative
   (Clipper2 orients outer rings positive and holes negative in its solutions);
 - OGC reading (sum over polygons of |shell| - sum |holes|) vs even-odd reading (sum of
   signed ring areas). Exact arithmetic (Fractions of the doubles)."""
import json, sys
from fractions import Fraction as F

def sa(ring):
    s = F(0)
    for (x0, y0), (x1, y1) in zip(ring, ring[1:]):
        s += F(x0) * F(y1) - F(x1) * F(y0)
    return s / 2

def polys(g):
    if not isinstance(g, dict): return None
    if g['type'] == 'Polygon': return [g['coordinates']] if g['coordinates'] else []
    if g['type'] == 'MultiPolygon': return g['coordinates']
    return None

def check(g):
    ps = polys(g)
    if ps is None: return None
    bad = 0; ogc = F(0); eo = F(0)
    for p in ps:
        a = [sa(r) for r in p]
        if a[0] < 0: bad += 1
        bad += sum(1 for x in a[1:] if x > 0)
        ogc += abs(a[0]) - sum(abs(x) for x in a[1:])
        eo += sum(a)
    return bad, ogc, eo

def run(path):
    out = {}
    for line in open(path):
        r = json.loads(line)
        for op, g in (r.get('overlay') or {}).items():
            c = check(g)
            if c is None: continue
            bad, ogc, eo = c
            if bad or ogc != eo:
                out[(r['id'], op)] = (bad, float(ogc), float(eo))
    return out

if __name__ == '__main__':
    for path in sys.argv[1:]:
        res = run(path)
        ids = sorted({k[0] for k in res})
        print(f'{path}: {len(res)} outputs in {len(ids)} cases with a nesting/orientation mismatch')
        for k, v in sorted(res.items()):
            print(f'   {k[0]}  {k[1]}: mismatched rings {v[0]}, OGC-read area {v[1]:.17g}, even-odd area {v[2]:.17g}')
