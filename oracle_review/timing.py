"""Oracle run time versus input size (two random star polygons with n vertices each,
generic double coordinates, heavily overlapping).

usage: python timing.py 50 100 200 400
"""
import math
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import oracle  # noqa: E402


def star(rng, n, cx):
    pts = []
    for k in range(n):
        a = 2 * math.pi * (k + rng.uniform(-.3, .3)) / n
        r = rng.uniform(.5, 1)
        pts.append([cx + r * math.cos(a), r * math.sin(a)])
    return pts + [pts[0]]


def main():
    rng = random.Random(1)
    for n in map(int, sys.argv[1:]):
        case = {"id": f"t{n}", "a": [[star(rng, n, 0.0)]], "b": [[star(rng, n, 0.3)]]}
        t = time.time()
        oracle.evaluate(case)
        print(f"n={n:5d} vertices per operand: {time.time() - t:8.2f} s", flush=True)


if __name__ == "__main__":
    main()
