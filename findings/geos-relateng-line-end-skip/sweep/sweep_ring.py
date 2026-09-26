"""Polygonal A vs MultiLineString B made of some of A's rings (as closed lines, possibly
partial) plus short spurs/segments on the lattice. Writes ring-<seed>.tsv/.exact."""
import random, sys
import os
GEOTRUTH_ROOT = os.path.abspath(__file__ + "/../../../..")  # the geotruth checkout
sys.path.insert(0, GEOTRUTH_ROOT + "/src"); sys.path.insert(0, GEOTRUTH_ROOT + "/tests")
from geotruth.geom import LineString, MultiLineString
from geotruth.io import to_wkt
from geotruth.relate import relate
from unit.witness_lattice import polygon, multipolygon, is_valid

def pt(rng): return float(rng.randint(0, 4)), float(rng.randint(-1, 4))
n = int(sys.argv[1]); seed = int(sys.argv[2]); rng = random.Random(seed)
with open(f"ring-{seed}.tsv", "w") as ft, open(f"ring-{seed}.exact", "w") as fe:
    i = 0
    while i < n:
        a = polygon(rng, 4) if rng.random() < 0.7 else multipolygon(rng, 4)
        if not is_valid(a): continue
        parts = []
        for r in a.iter_rings():
            c = list(r.coords)
            if rng.random() < 0.7: parts.append(c)
            elif rng.random() < 0.5:  # a partial ring
                k = rng.randint(2, len(c) - 1); parts.append(c[:k])
        for _ in range(rng.randint(1, 2)):
            p, q = pt(rng), pt(rng)
            if p != q: parts.append([p, q])
        if not parts: continue
        rng.shuffle(parts)
        b = MultiLineString([LineString(p) for p in parts])
        if rng.random() < 0.3: a, b = b, a
        ft.write(f"{to_wkt(a)}\t{to_wkt(b)}\n"); fe.write(relate(a, b).matrix + "\n"); i += 1
