"""Random sweep: MultiLineStrings with far-away elements vs P/MP/L/ML/A/MA near the origin.

Writes cases.tsv (A<TAB>B), exact.txt (exact matrix per line, arrangement route)."""
import random, sys
import os
GEOTRUTH_ROOT = os.path.abspath(__file__ + "/../../../..")  # the geotruth checkout
sys.path.insert(0, GEOTRUTH_ROOT + "/src"); sys.path.insert(0, GEOTRUTH_ROOT + "/tests")
from geotruth.geom import LineString, MultiLineString, Point, MultiPoint
from geotruth.io import to_wkt
from geotruth.relate import relate
from unit.witness_lattice import polygon, multipolygon, is_valid

def pt(rng, lo, hi):
    return float(rng.randint(lo, hi)), float(rng.randint(lo, hi))

def line(rng, lo, hi, shared):
    while True:
        pts = [pt(rng, lo, hi) for _ in range(rng.randint(2, 3))]
        if shared and rng.random() < 0.4:
            pts[rng.choice([0, -1])] = rng.choice(shared)
        if rng.random() < 0.25:
            pts.append(pts[0])
        if len(set(pts)) >= 2:
            return pts

def mline(rng):
    parts, shared = [], []
    for _ in range(rng.randint(2, 4)):
        lo, hi = (0, 4) if rng.random() < 0.5 else (6, 9)
        p = line(rng, lo, hi, [s for s in shared if (lo <= s[0] <= hi)])
        shared += [p[0], p[-1]]
        parts.append(LineString(p))
    return MultiLineString(parts)

def other(rng):
    k = rng.choice(["P", "MP", "L", "ML", "A", "MA"])
    if k == "P": return Point(pt(rng, 0, 4))
    if k == "MP": return MultiPoint([pt(rng, 0, 4) for _ in range(2)])
    if k == "L": return LineString(line(rng, 0, 4, []))
    if k == "ML": return MultiLineString([LineString(line(rng, 0, 4, [])) for _ in range(2)])
    if k == "A": return polygon(rng, 4)
    return multipolygon(rng, 4)

n = int(sys.argv[1]); seed = int(sys.argv[2])
rng = random.Random(seed)
with open(f"sweep-{seed}.tsv", "w") as ft, open(f"sweep-{seed}.exact", "w") as fe:
    i = 0
    while i < n:
        a, b = other(rng), mline(rng)
        if not (is_valid(a) and is_valid(b)):
            continue
        if rng.random() < 0.5:
            a, b = b, a
        m = relate(a, b).matrix
        ft.write(f"{to_wkt(a)}\t{to_wkt(b)}\n"); fe.write(m + "\n")
        i += 1
