"""GC-heavy relate sweep: python3 sweep.py FAMILY COUNT SEED -> FAMILY-SEED.tsv (A\tB) and .exact (exact relate(A,B)).
families: mix (mixed GCs: polygons + points/lines) and ovl (GCs of 2-3 overlapping polygons) vs every type.
No EMPTY elements, no zero-length lines (GEOS-valid inputs only)."""
import random, sys, importlib.util
from multiprocessing import Pool
import os
GEOTRUTH_ROOT = os.path.abspath(__file__ + "/../../../..")  # the geotruth checkout
sys.path[:0] = [GEOTRUTH_ROOT + "/src", GEOTRUTH_ROOT + "/tests", GEOTRUTH_ROOT + "/tests/reference"]
spec = importlib.util.spec_from_file_location("crosscheck_relate", GEOTRUTH_ROOT + "/tools/crosscheck_relate.py")
X = importlib.util.module_from_spec(spec); sys.modules["crosscheck_relate"] = X; spec.loader.exec_module(X)
from geotruth.geom import GeometryCollection, LineString, MultiLineString, MultiPoint, Point, Polygon
from geotruth.io import to_wkt
from geotruth.relate import relate

N = 2  # lattice 2*[0..N] -> coordinates 0,2,4 (+ midpoints via shifts below)

def pt(rng):
    return (float(rng.randint(0, 6)), float(rng.randint(0, 6)))

def vertices(g):
    return [c for c in g.iter_coords()]

def poly(rng):
    return X.adv_polygon(rng, 3)

def points_near(rng, ref):
    vs = vertices(ref) if ref is not None else []
    out = []
    for _ in range(rng.randint(1, 3)):
        r = rng.random()
        if vs and r < 0.4:
            out.append(rng.choice(vs))
        elif r < 0.7:
            out.append(pt(rng))
        else:
            out.append((float(rng.randint(10, 14)), float(rng.randint(10, 14))))  # far away
    return out

def line(rng, ref=None):
    vs = vertices(ref) if ref is not None else []
    while True:
        k = rng.randint(2, 4)
        pts = [rng.choice(vs) if vs and rng.random() < 0.5 else pt(rng) for _ in range(k)]
        if rng.random() < 0.25:
            pts.append(pts[0])
        if rng.random() < 0.1:
            pts = [(x + 10, y + 10) for x, y in pts]
        ls = LineString(pts)
        if len(set(pts)) >= 2 and not ls.is_zero_length:
            return ls

def mixed_gc(rng):
    parts = [poly(rng)]
    if rng.random() < 0.3:
        parts.append(poly(rng))
    ref = parts[0]
    r = rng.random()
    if r < 0.5:
        ps = points_near(rng, ref)
        parts.append(Point(ps[0]) if len(ps) == 1 else MultiPoint(ps))
    elif r < 0.8:
        parts.append(line(rng, ref))
        parts.append(Point(points_near(rng, ref)[0]))
    else:
        parts.append(line(rng, ref))
    if rng.random() < 0.3:  # sometimes no polygon at all: points + lines
        parts = [p for p in parts if not isinstance(p, Polygon)] or parts
        if len(parts) == 1:
            parts.append(Point(pt(rng)))
    rng.shuffle(parts)
    return GeometryCollection(parts)

def ovl_gc(rng):
    k = rng.choice((2, 2, 3))
    parts = [poly(rng) for _ in range(k)]
    if rng.random() < 0.3:  # a polygon with a vertex on another polygon's vertex or edge midpoint
        vs = vertices(parts[0])
        v = rng.choice(vs)
        parts.append(Polygon([X._closed([v, pt(rng), pt(rng)])]))
    return GeometryCollection(parts)

def target(rng, ref):
    kind = rng.choice(("P", "MP", "L", "L", "ML", "A", "A", "MA", "GC"))
    vs = vertices(ref)
    if kind == "P":
        return Point(rng.choice(vs) if rng.random() < 0.6 else pt(rng))
    if kind == "MP":
        return MultiPoint(points_near(rng, ref) + [rng.choice(vs)])
    if kind == "L":
        return line(rng, ref)
    if kind == "ML":
        return MultiLineString([line(rng, ref), line(rng, ref)])
    if kind == "A":
        return poly(rng)
    if kind == "MA":
        return X.adv_multipolygon(rng, 3)
    return mixed_gc(rng) if rng.random() < 0.5 else ovl_gc(rng)

def rect(rng, lo=0, hi=6):
    x0, x1 = sorted(rng.sample(range(lo, hi + 1), 2)); y0, y1 = sorted(rng.sample(range(lo, hi + 1), 2))
    return Polygon([[(float(x0), float(y0)), (float(x1), float(y0)), (float(x1), float(y1)), (float(x0), float(y1)), (float(x0), float(y0))]])

def notched(rng):
    """a polygon with a reflex vertex v, plus a polygon covering its notch through v"""
    vx, vy = rng.randint(2, 4), rng.randint(2, 4)
    dx1, dx2 = rng.randint(1, 2), rng.randint(1, 2)
    dy = rng.randint(1, 2)
    h = rng.randint(1, 3)
    # notch opens downward: v=(vx,vy), neighbours (vx-dx1, vy-dy) and (vx+dx2, vy-dy)
    p = [(vx, vy), (vx + dx2, vy - dy), (vx + dx2, vy + h), (vx - dx1, vy + h), (vx - dx1, vy - dy), (vx, vy)]
    poly = Polygon([[(float(x), float(y)) for x, y in p]])
    r = rng.random()
    if r < 0.4:  # rectangle with v on its top edge (covers the notch)
        cov = Polygon([[(float(vx - 1), float(vy - dy - 1)), (float(vx + 1), float(vy - dy - 1)), (float(vx + 1), float(vy)), (float(vx - 1), float(vy)), (float(vx - 1), float(vy - dy - 1))]])
    elif r < 0.7:  # triangle with apex v filling the notch exactly (adjacent)
        cov = Polygon([[(float(vx), float(vy)), (float(vx - dx1), float(vy - dy)), (float(vx + dx2), float(vy - dy)), (float(vx), float(vy))]])
    else:  # random polygon with a vertex at v
        cov = Polygon([X._closed([(float(vx), float(vy)), pt(rng), pt(rng)])])
    return poly, cov

def adj_gc(rng):
    poly, cov = notched(rng)
    parts = [poly, cov]
    if rng.random() < 0.3:
        parts.append(poly_or_rect(rng))
    rng.shuffle(parts)
    # sometimes rotate/reflect the whole thing (x<->y swap, flip) to vary orientations
    t = rng.randrange(4)
    def f(c):
        x, y = c
        return [(x, y), (y, x), (6 - x, y), (x, 6 - y)][t]
    return GeometryCollection([p.map_coords(f) for p in parts])

def poly_or_rect(rng):
    return rect(rng) if rng.random() < 0.5 else poly(rng)

def frame_gc(rng):
    """overlapping rectangles/triangles whose union may have holes"""
    k = rng.randint(3, 5)
    parts = [rect(rng) if rng.random() < 0.7 else poly(rng) for _ in range(k)]
    return GeometryCollection(parts)

def mix2_gc(rng):
    """mixed GC: lines along/near a polygon's boundary, points at vertices or far away"""
    base = poly_or_rect(rng)
    vs = vertices(base)
    parts = []
    r = rng.random()
    if r < 0.5:
        parts.append(base)
    ring = list(base.shell)
    if rng.random() < 0.5:
        parts.append(LineString(ring))  # the boundary as a closed line
    else:
        i = rng.randrange(len(ring) - 1)
        parts.append(LineString([ring[i], ring[i + 1]]))
    for _ in range(rng.randint(1, 2)):
        parts.append(Point(rng.choice(vs) if rng.random() < 0.5 else (float(rng.randint(8, 12)), float(rng.randint(8, 12)))))
    if len(parts) < 2 or all(isinstance(p, Point) for p in parts):
        parts.append(Point(pt(rng)))
    rng.shuffle(parts)
    return GeometryCollection(parts), base

def valid(g):
    return X.geos_valid(g) and not g.is_empty

def make(args):
    fam, seed, i = args
    rng = random.Random(seed * 1000003 + i)
    while True:
        if fam == "mix2":
            a, base = mix2_gc(rng)
            r = rng.random()
            b = base if r < 0.3 else (rect(rng) if r < 0.5 else target(rng, a))
        elif fam == "adj":
            a = adj_gc(rng)
            vs = vertices(a)
            r = rng.random()
            if r < 0.35:
                b = Point(rng.choice(vs))
            elif r < 0.7:
                v = rng.choice(vs)
                b = LineString([v, pt(rng)]) if rng.random() < 0.7 else LineString([pt(rng), v, pt(rng)])
            else:
                b = target(rng, a)
        elif fam == "frame":
            a = frame_gc(rng)
            r = rng.random()
            b = rect(rng) if r < 0.5 else target(rng, a)
        else:
            a = mixed_gc(rng) if fam == "mix" else ovl_gc(rng)
            b = target(rng, a)
        if valid(a) and valid(b) and not (isinstance(b, LineString) and b.is_zero_length):
            break
    wa, wb = to_wkt(a), to_wkt(b)
    try:
        m = relate(a, b, strict=True).matrix
    except Exception as e:
        m = "ENGINE:" + type(e).__name__
    return wa, wb, m

if __name__ == "__main__":
    fam, count, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    with Pool(2) as p:
        rows = p.map(make, [(fam, seed, i) for i in range(count)], chunksize=20)
    with open(f"{fam}-{seed}.tsv", "w") as f, open(f"{fam}-{seed}.exact", "w") as g:
        for wa, wb, m in rows:
            f.write(f"{wa}\t{wb}\n"); g.write(m + "\n")
    print(fam, seed, len(rows))
