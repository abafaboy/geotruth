"""validity.valid_geometry vs GEOS is_valid on random small-integer multi-ring inputs
(valid and invalid mixed: holes touching / crossing / sharing edges with the shell,
nested or overlapping holes, hole cycles, parts touching at points or along edges).

usage: python validity_check.py N SEED
"""
import json
import os
import random
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from validity import valid_geometry  # noqa: E402
from shapely.geometry import MultiPolygon, Polygon  # noqa: E402
from shapely.validation import explain_validity  # noqa: E402


def geos(mp):
    try:
        ps = [Polygon(p[0], p[1:]) for p in mp]
        g = ps[0] if len(ps) == 1 else MultiPolygon(ps)
        v = bool(g.is_valid)
        return v, ("" if v else explain_validity(g).split("[")[0])
    except Exception as e:  # noqa: BLE001
        return False, type(e).__name__


def closed(pts):
    return [[float(x), float(y)] for x, y in pts] + [[float(pts[0][0]), float(pts[0][1])]]


def rand_ring(rng, x0, y0, x1, y1):
    k = rng.randrange(3)
    if k == 0:
        a, b = sorted(rng.sample(range(x0, x1 + 1), 2)) if x1 > x0 else (x0, x0 + 1)
        c, d = sorted(rng.sample(range(y0, y1 + 1), 2)) if y1 > y0 else (y0, y0 + 1)
        return closed([(a, c), (b, c), (b, d), (a, d)])
    if k == 1:
        return closed([(rng.randint(x0, x1), rng.randint(y0, y1)) for _ in range(3)])
    # a diamond / quad around a point
    cx, cy = rng.randint(x0, x1), rng.randint(y0, y1)
    r = rng.randint(1, 2)
    return closed([(cx - r, cy), (cx, cy - r), (cx + r, cy), (cx, cy + r)])


def rand_poly(rng, G, ox=0, oy=0):
    shell = closed([(ox, oy), (ox + G, oy), (ox + G, oy + G), (ox, oy + G)])
    if rng.random() < .3:
        shell = closed([(ox, oy), (ox + G, oy), (ox + G // 2, oy + G)])
    holes = [rand_ring(rng, ox, oy, ox + G, oy + G) for _ in range(rng.choice([0, 1, 1, 2, 2, 3]))]
    return [shell] + holes


def main():
    n, seed = int(sys.argv[1]), int(sys.argv[2])
    rng = random.Random(seed)
    stats, examples = Counter(), {}
    for _ in range(n):
        G = rng.choice([2, 3, 4, 6])
        if rng.random() < .55:
            mp = [rand_poly(rng, G)]
        else:
            mp = []
            for _ in range(rng.randint(2, 3)):
                ox, oy = rng.randint(-1, G), rng.randint(-1, G)
                if rng.random() < .5:
                    mp.append([rand_ring(rng, ox, oy, ox + G, oy + G)])
                else:
                    mp.append(rand_poly(rng, max(2, G // 2), ox, oy))
        mine = valid_geometry(mp)
        g, why = geos(mp)
        key = (mine, g, why if mine != g else "")
        stats[key] += 1
        if mine != g:
            examples.setdefault(key, mp)
    print(f"geometries: {n}")
    for (m, g, why), c in sorted(stats.items(), key=str):
        print(f"  valid_geometry={m!s:5s} geos={g!s:5s} {c:6d}  {'<-- DISAGREE ' + why if m != g else ''}")
    for k, mp in examples.items():
        print("example", k, json.dumps(mp))


if __name__ == "__main__":
    main()
