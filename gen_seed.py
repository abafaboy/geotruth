"""Seed generator: a few near-degenerate families to smoke-test the pipeline.

usage: python gen_seed.py N_PER_FAMILY SEED > cases/seed.jsonl
"""
import json
import math
import random
import sys


def close(r):
    return r + [r[0]]


def rotated_square(cx, cy, th, s=1.0):
    c, sn = math.cos(th) * s / 2, math.sin(th) * s / 2
    pts = [[cx + c * dx - sn * dy, cy + sn * dx + c * dy] for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return close(pts)


def star(rng, cx, cy, r, n):
    pts = []
    for k in range(n):
        ang = 2 * math.pi * k / n + rng.uniform(-0.2, 0.2) * 2 * math.pi / n
        rr = r * rng.uniform(0.4, 1)
        pts.append([cx + rr * math.cos(ang), cy + rr * math.sin(ang)])
    return close(pts)


def rotate(ring, px, py, th):
    c, s = math.cos(th), math.sin(th)
    return [[px + c * (x - px) - s * (y - py), py + s * (x - px) + c * (y - py)] for x, y in ring]


def families(rng):
    # B is A rotated by a tiny angle about one of its own vertices
    a = star(rng, 0, 0, 1, rng.randint(3, 9))
    v = rng.choice(a[:-1])
    th = rng.choice([1, -1]) * 10 ** rng.uniform(-16, -8)
    yield "tiny-rotation", a, rotate(a, v[0], v[1], th)
    # two rotated unit squares placed edge to edge, the second nudged by a few ulps
    th = rng.uniform(0, math.pi / 2)
    d = 1.0 + rng.choice([0, 1, -1, 2, -2]) * 2.0 ** -52
    yield "rotated-neighbours", rotated_square(0, 0, th), rotated_square(d * math.cos(th), d * math.sin(th), th)
    # B shares a dyadic sub-segment of A's edge, on a sloped edge
    k = rng.randint(1, 7)
    p, q = [0.0, 0.0], [8.0, float(k)]
    t0, t1 = rng.randint(1, 3) / 8, rng.randint(5, 7) / 8
    m0 = [p[0] + t0 * (q[0] - p[0]), p[1] + t0 * (q[1] - p[1])]
    m1 = [p[0] + t1 * (q[0] - p[0]), p[1] + t1 * (q[1] - p[1])]
    yield "shared-sloped-edge", [p, q, [8.0, 9.0], [0.0, 9.0], p], [m0, m1, [m1[0], m1[1] - 3.0], m0]
    # the same pair far from the origin, as in projected map coordinates
    off = rng.choice([1e5, 1e6, 3e6, 1e7])
    a = star(rng, off, off, 1, rng.randint(3, 9))
    v = rng.choice(a[:-1])
    yield "tiny-rotation-offset", a, rotate(a, v[0], v[1], rng.choice([1, -1]) * 10 ** rng.uniform(-15, -9))


def main():
    n, seed = int(sys.argv[1]), int(sys.argv[2])
    rng = random.Random(seed)
    counts = {}
    for _ in range(n):
        for fam, a, b in families(rng):
            counts[fam] = counts.get(fam, 0) + 1
            print(json.dumps({"id": f"{fam}-{seed}-{counts[fam]:06d}", "family": fam, "a": [[a]], "b": [[b]]}))


if __name__ == "__main__":
    main()
