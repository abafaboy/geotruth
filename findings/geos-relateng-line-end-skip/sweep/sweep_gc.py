"""GeometryCollections of (often overlapping) polygons, some far away, vs L/ML/A/MA/GC
targets near the origin. Writes gc-<seed>.tsv/.exact."""
import random, sys
import os
GEOTRUTH_ROOT = os.path.abspath(__file__ + "/../../../..")  # the geotruth checkout
sys.path.insert(0, GEOTRUTH_ROOT + "/src"); sys.path.insert(0, GEOTRUTH_ROOT + "/tests")
from geotruth.geom import GeometryCollection, LineString, MultiLineString, Polygon
from geotruth.io import to_wkt
from geotruth.relate import relate
from unit.witness_lattice import polygon, multipolygon, is_valid, line, multiline, collection

def rect(rng, lo, hi):
    x0, x1 = sorted(rng.sample(range(lo, hi + 1), 2)); y0, y1 = sorted(rng.sample(range(lo, hi + 1), 2))
    return Polygon([[(float(x0), float(y0)), (float(x1), float(y0)), (float(x1), float(y1)), (float(x0), float(y1)), (float(x0), float(y0))]])

def gc(rng):
    parts = []
    for _ in range(rng.randint(2, 4)):
        lo, hi = (0, 4) if rng.random() < 0.5 else (6, 10)
        parts.append(rect(rng, lo, hi) if rng.random() < 0.6 else polygon_in(rng, lo))
    return GeometryCollection(parts)

def polygon_in(rng, lo):
    p = polygon(rng, 4)
    return Polygon([[(x + lo, y + lo) for x, y in r] for r in p.rings])

def target(rng):
    k = rng.choice(["L", "ML", "A", "MA", "GC"])
    return {"L": lambda: line(rng, 4), "ML": lambda: multiline(rng, 4), "A": lambda: polygon(rng, 4),
            "MA": lambda: multipolygon(rng, 4), "GC": lambda: collection(rng, 4)}[k]()

n = int(sys.argv[1]); seed = int(sys.argv[2]); rng = random.Random(seed)
with open(f"gc-{seed}.tsv", "w") as ft, open(f"gc-{seed}.exact", "w") as fe:
    i = 0
    while i < n:
        a, b = gc(rng), target(rng)
        if not (is_valid(a) and is_valid(b)): continue
        if rng.random() < 0.4: a, b = b, a
        ft.write(f"{to_wkt(a)}\t{to_wkt(b)}\n"); fe.write(relate(a, b).matrix + "\n"); i += 1
