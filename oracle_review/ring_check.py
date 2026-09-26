"""ring_simple (oracle.py) vs an independent simplicity test vs GEOS is_valid.

usage: python ring_check.py [N_RANDOM] [SEED]

Exhaustive: every vertex sequence of length 3, 4, 5 on the 3x3 integer grid (consecutive
repeats included), closed by repeating the first point. Random: longer rings on a 5x5
grid and on dyadic points of a 2x2 grid, with repeated points, rotated by an exact map.
GEOS validity is exact on such small integer/dyadic inputs (its orientation predicate is
robust and every intersection is decided by orientation tests), so any three-way
disagreement is a real semantic difference.
"""
import itertools
import os
import random
import sys
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import oracle  # noqa: E402
import indep  # noqa: E402
from shapely.geometry import Polygon  # noqa: E402


def geos_valid(ring):
    try:
        return bool(Polygon(ring).is_valid)
    except Exception:  # noqa: BLE001  (fewer than 4 coordinates etc.)
        return False


def main():
    nrand = int(sys.argv[1]) if len(sys.argv) > 1 else 50000
    rng = random.Random(int(sys.argv[2]) if len(sys.argv) > 2 else 1)
    grid = [(float(x), float(y)) for x in range(3) for y in range(3)]
    rings = []
    for n in (3, 4, 5):
        for seq in itertools.product(grid, repeat=n):
            rings.append(("exh3x3", list(seq) + [seq[0]]))
    for _ in range(nrand):
        kind = rng.randrange(3)
        n = rng.randint(4, 9)
        if kind == 0:
            pts = [(float(rng.randint(0, 4)), float(rng.randint(0, 4))) for _ in range(n)]
        elif kind == 1:
            pts = [(rng.randint(0, 8) / 4, rng.randint(0, 8) / 4) for _ in range(n)]
        else:  # star-ish simple candidates with occasional pinches / spikes
            pts = [(float(rng.randint(0, 6)), float(rng.randint(0, 6))) for _ in range(n)]
            if rng.random() < .5:
                j = rng.randrange(n)
                pts.insert(rng.randrange(n), pts[j])  # repeated non-consecutive vertex
        if rng.random() < .3:
            j = rng.randrange(len(pts))
            pts.insert(j, pts[j])  # consecutive repeat
        ring = pts + [pts[0]]
        if rng.random() < .1:
            ring.append(pts[0])  # repeated closing point
        sw = rng.random() < .5
        k = rng.randint(-3, 3)
        ring = [((y, x) if sw else (x, y)) for x, y in ring]
        ring = [(x * 2.0 ** k, y * 2.0 ** k) for x, y in ring]
        rings.append((f"rand{kind}", ring))

    stats = {}
    examples = {}
    for kind, ring in rings:
        o = oracle.ring_simple([(F(x), F(y)) for x, y in ring])
        i = indep.ring_is_simple(ring)
        g = geos_valid(ring)
        key = (kind, o, i, g)
        stats[key] = stats.get(key, 0) + 1
        if not (o == i == g):
            examples.setdefault((o, i, g), ring)
    print(f"rings tested: {len(rings)}")
    print("kind       oracle  indep  geos   count")
    for (kind, o, i, g), c in sorted(stats.items()):
        flag = "" if o == i == g else "   <-- DISAGREE"
        print(f"{kind:9s}  {o!s:6s}  {i!s:5s}  {g!s:5s}  {c}{flag}")
    for k, ring in examples.items():
        print("example (oracle, indep, geos) =", k, ring)


if __name__ == "__main__":
    main()
