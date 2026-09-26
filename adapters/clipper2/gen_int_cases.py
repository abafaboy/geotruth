"""Integer-coordinate near-degenerate cases for Clipper2 (and anyone else).

Every coordinate is an integer exactly representable as a double, so Clipper2 runs these at
scale 2^0 and snaps each new intersection point to the unit grid. To keep that snapping far
below compare.py's 1e-6 relative tolerance, every shape (except in `int-thin-triangle`) is fat
and at least ~2^33 units across. The degeneracies live at the unit scale:

- shared collinear edges, vertices exactly on edges, vertex-to-vertex touches, collinear vertex
  chains, holes touching their shell, multipolygon parts touching at a corner, identical
  inputs, all exact because small lattice shapes are scaled by a large integer;
- near misses by one unit, edges crossing at slopes of a few units over 2^36..2^52;
- long triangles whose short side is one unit (`int-thin-triangle`: both operands thin, so
  losing such a triangle is a gross error);
- coordinates near 2^60 (inside Clipper2's MAX_COORD = 2^61 - 1) and in [2^61, 2^62)
  (outside it: the `int-beyond-maxcoord` family, which only tests the documented limit).

All inputs are valid OGC geometries (checked with shapely when it is installed, else with the
exact ring test in oracle.py, which covers single rings only).

usage: python gen_int_cases.py [N_PER_FAMILY] [SEED] > int_cases.jsonl
"""
import json
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

try:
    from shapely.geometry import MultiPolygon, Polygon

    def is_valid(mp):
        polys = [Polygon(p[0], p[1:]) for p in mp]
        g = polys[0] if len(polys) == 1 else MultiPolygon(polys)
        return g.is_valid
except ImportError:  # pragma: no cover
    from oracle import valid_single_polygon

    def is_valid(mp):
        return valid_single_polygon(mp) is not False

TWO53 = 2 ** 53

# large lattice units: products stay exact integers, and |coord| stays below 2^53
UNITS = [2 ** 33, 2 ** 36, 10 ** 11 + 3, 2 ** 40 + 1, 3 ** 24, 2 ** 44 - 1, 10 ** 13 + 7]
OFFSETS = [0, 0, 0, 10 ** 12, -(2 ** 45), 2 ** 49 + 12345, -(10 ** 15) - 1]


def exact_double(v):
    return float(v) == v


def close(r):
    return [[int(x), int(y)] for x, y in r] + [[int(r[0][0]), int(r[0][1])]]


def add(p, q, s=1):
    return (p[0] + s * q[0], p[1] + s * q[1])


def mul(v, t):
    return (v[0] * t, v[1] * t)


def primitive_dir(rng, m):
    while True:
        dx, dy = rng.randint(1, m), rng.randint(-m, m)
        if math.gcd(dx, abs(dy)) == 1:
            return (dx, dy)


class Lattice:
    """Maps small lattice points to large integer coordinates: p -> u*p + off (exact)."""

    def __init__(self, rng, ext=64):
        while True:
            self.u, self.off = rng.choice(UNITS), rng.choice(OFFSETS)
            if abs(self.off) + ext * self.u < TWO53:
                break

    def __call__(self, p):
        return (p[0] * self.u + self.off, p[1] * self.u + self.off)

    def ring(self, r):
        return [self(p) for p in r]


def edge_setup(rng, m=24):
    """A lattice parallelogram with a sloped edge P->Q = g*d and a normal n to its left."""
    d = primitive_dir(rng, 7)
    g = rng.randint(4, m)
    n = (-d[1], d[0]) if rng.random() < 0.5 else (0, rng.randint(1, 6))
    if n[0] * d[1] - n[1] * d[0] > 0:  # keep n on the left of P->Q
        n = mul(n, -1)
    nA = mul(n, rng.randint(2, 5))
    A = [(0, 0), mul(d, g), add(mul(d, g), nA), nA]
    return d, g, n, A


# ---------------------------------------------------------------------------------------
# families: each returns (a, b), lists of polygons of open rings in final coordinates

def fam_shared_edge_touch(rng):
    T = Lattice(rng)
    d, g, n, A = edge_setup(rng)
    i = rng.randint(0, g - 2)
    j = rng.randint(i + 1, g)
    s, e = mul(d, i), mul(d, j)
    nb = mul(n, -rng.randint(1, 4))  # the other side of the shared edge
    return [[T.ring(A)]], [[T.ring([s, add(s, nb), add(e, nb), e])]]


def fam_shared_edge_overlap(rng):
    T = Lattice(rng)
    d, g, n, A = edge_setup(rng)
    i = rng.randint(0, g - 2)
    j = rng.randint(i + 1, g + rng.randint(0, 3))
    s, e = mul(d, i), mul(d, j)
    nb = mul(n, rng.randint(1, 7))  # same side, possibly past A's far edge
    return [[T.ring(A)]], [[T.ring([s, e, add(e, nb), add(s, nb)])]]


def fam_vertex_on_edge(rng):
    T = Lattice(rng)
    d, g, n, A = edge_setup(rng)
    i = rng.randint(1, g - 1)
    apex = mul(d, i)
    side = rng.choice([-1, 1])  # -1: from outside (touch), +1: into A (overlap)
    base = add(apex, mul(n, side * rng.randint(1, 3)))
    w = rng.randint(1, 3)
    return [[T.ring(A)]], [[T.ring([apex, add(base, mul(d, w)), add(base, mul(d, -w))])]]


def fam_near_miss(rng):
    """B's apex is one unit (after scaling) off A's sloped edge: a hair of overlap or gap."""
    T = Lattice(rng)
    d, g, n, A = edge_setup(rng)
    i = rng.randint(1, g - 1)
    shift = rng.choice([(1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (2, -1)])
    base = add(mul(d, i), mul(n, -rng.randint(1, 4)))
    w = rng.randint(1, 3)
    B = [add(T(mul(d, i)), shift), T(add(base, mul(d, w))), T(add(base, mul(d, -w)))]
    return [[T.ring(A)]], [[B]]


def fam_thin_crossing(rng):
    """Fat quads whose facing edges cross at a slope of a few units over their length."""
    L = rng.choice([2 ** 36, 10 ** 12, 2 ** 44, 2 ** 50, 2 ** 52 - 2 ** 20])
    H = rng.choice([L // 2, L // 7, L])
    s = rng.randint(1, 9)
    A = [(0, 0), (L, s), (L, H), (0, H)]
    B = [(0, s), (L, 0), (L, -H), (0, -H)]
    if rng.random() < 0.5:
        B = [(x, y + rng.choice([-1, 1])) for x, y in B]
    if rng.random() < 0.5:
        A, B = [(y, x) for x, y in A], [(y, x) for x, y in B]
    return [[A]], [[B]]


def lattice_polygon(rng, size, npts):
    """Random simple lattice polygon: points sorted by angle around an interior point."""
    for _ in range(1000):
        pts = list({(rng.randint(0, size), rng.randint(0, size)) for _ in range(npts)})
        if len(pts) < 3:
            continue
        cx = sum(p[0] for p in pts) / len(pts) + 0.1234
        cy = sum(p[1] for p in pts) / len(pts) + 0.0567
        pts.sort(key=lambda p: math.atan2(p[1] - cy, p[0] - cx))
        if is_valid([[close(pts)]]):
            return pts
    raise RuntimeError("no simple polygon")


def fam_identical(rng):
    T = Lattice(rng)
    A = [mul(p, 2) for p in lattice_polygon(rng, 8, rng.randint(4, 9))]
    mode = rng.choice(["same", "rotated-start", "reversed", "collinear-inserted"])
    if mode == "same":
        B = list(A)
    elif mode == "rotated-start":
        k = rng.randint(1, len(A) - 1)
        B = A[k:] + A[:k]
    elif mode == "reversed":
        B = A[::-1]
    else:  # midpoints of every edge (lattice points, since A was doubled)
        B = []
        for p, q in zip(A, A[1:] + A[:1]):
            B += [p, ((p[0] + q[0]) // 2, (p[1] + q[1]) // 2)]
    return [[T.ring(A)]], [[T.ring(B)]]


def fam_hole_exact(rng):
    T = Lattice(rng)
    S = rng.randint(8, 20)
    a, b = rng.randint(2, 3), rng.randint(2, 3)
    shell = [(0, 0), (S, 0), (S, S), (0, S)]
    hole = [(a, b), (a + 1, S - b), (S - a, S - b - 2), (S - a - 1, b + 1)]
    mode = rng.choice(["equal", "inside", "grown", "shifted-unit", "edge-shared", "shrunk-unit"])
    if mode == "equal":
        B = T.ring(hole)
    elif mode == "inside":
        c = S // 2
        B = T.ring([(c - 1, c - 1), (c + 1, c - 1), (c + 1, c + 1), (c - 1, c + 1)])
    elif mode == "grown":
        B = T.ring([(a - 1, b - 1), (a + 1, S - b + 1), (S - a + 1, S - b - 1), (S - a, b)])
    elif mode == "shifted-unit":  # the hole moved by one unit after scaling
        dx, dy = rng.choice([(1, 0), (0, 1), (-1, 1)])
        B = [add(p, (dx, dy)) for p in T.ring(hole)]
    elif mode == "edge-shared":
        B = T.ring([(a, b), (a + 1, S - b), (a - 1, S - b)])
    else:  # a unit inside the hole at one vertex: B barely inside the hole
        B = T.ring(hole)
        B[0] = add(B[0], (1, 1))
    return [[T.ring(shell), T.ring(hole)]], [[B]]


def fam_hole_touches_shell(rng):
    T = Lattice(rng)
    S = rng.randint(8, 20)
    t = rng.randint(3, S - 3)
    shell = [(0, 0), (S, 0), (S, S), (0, S)]
    # the hole touches the shell's bottom edge at one point (valid OGC)
    hole = [(t, 0), (t + 2, 3), (t, 5), (t - 2, 3)] if rng.random() < 0.5 else \
           [(t, 0), (S - 1, S // 2), (1, S // 2)]
    mode = rng.choice(["below", "diamond", "inside-hole", "wedge", "below-unit-gap"])
    if mode == "below":
        B = T.ring([(t, 0), (t + 3, -4), (t - 3, -4)])
    elif mode == "diamond":
        B = T.ring([(t, -2), (t + 2, 0), (t, 2), (t - 2, 0)])
    elif mode == "inside-hole":
        B = T.ring([(t, 0), (t + 1, 2), (t - 1, 2)])
    elif mode == "wedge":
        B = T.ring([(t, 0), (t + 5, 1), (t + 5, -1)])
    else:
        B = T.ring([(t, 0), (t + 3, -4), (t - 3, -4)])
        B[0] = add(B[0], (0, -1))
    return [[T.ring(shell), T.ring(hole)]], [[B]]


def fam_multi_corner(rng):
    T = Lattice(rng)
    s = rng.randint(2, 9)
    A = [[[(0, 0), (s, 0), (s, s), (0, s)]], [[(s, s), (2 * s, s), (2 * s, 2 * s), (s, 2 * s)]]]
    mode = rng.choice(["diamond", "corner-touch", "l-shape", "strip"])
    if mode == "diamond":
        r = rng.randint(1, s)
        B = [[[(s, s - r), (s + r, s), (s, s + r), (s - r, s)]]]
    elif mode == "corner-touch":
        B = [[[(s, s), (2 * s, 0), (2 * s + 1, s - 1)]]]
    elif mode == "l-shape":
        B = [[[(s, 0), (2 * s, 0), (2 * s, s), (s, s)]], [[(0, s), (s, s), (s, 2 * s), (0, 2 * s)]]]
    else:
        B = [[[(0, s), (2 * s, s), (2 * s, s + 1), (0, s + 1)]]]
    tr = lambda mp: [[T.ring(r) for r in poly] for poly in mp]  # noqa: E731
    return tr(A), tr(B)


def fam_lattice_random(rng):
    T = Lattice(rng)
    size = rng.randint(3, 7)
    A = lattice_polygon(rng, size, rng.randint(4, 10))
    B = lattice_polygon(rng, size, rng.randint(3, 10))
    return [[T.ring(A)]], [[T.ring(B)]]


def fam_lattice_jitter(rng):
    """Random lattice polygons with one vertex of B moved by one unit after scaling."""
    a, b = fam_lattice_random(rng)
    ring = b[0][0]
    i = rng.randrange(len(ring))
    ring[i] = add(ring[i], rng.choice([(1, 0), (0, 1), (-1, 0), (0, -1), (1, -1)]))
    return a, b


def fam_near_parallel_large(rng):
    """Long, nearly parallel edges (slopes differ by e units over L) crossing mid-way."""
    L = rng.choice([2 ** 36, 2 ** 40, 2 ** 48, 2 ** 51, 2 ** 52])
    H = L // rng.choice([2, 3, 5])
    e = rng.randint(1, 3)
    A = [(0, 0), (L, L + e), (L - H, L + e + H), (-H, H)]
    B = [(0, e), (L, L), (L + H, L - H), (H, e - H)]
    if rng.random() < 0.5:
        A, B = [(y, x) for x, y in A], [(y, x) for x, y in B]
    return [[A]], [[B]]


def big_edge_family(rng, base, step, units):
    d, g, n, A = edge_setup(rng, 20)
    unit = step * rng.choice(units)
    i = rng.randint(1, g - 1)
    mode = rng.choice(["touch", "near-miss", "overlap", "shared-edge"])
    tr = lambda r: [(x * unit + base, y * unit + base) for x, y in r]  # noqa: E731
    if mode == "shared-edge":
        j = rng.randint(i + 1, g)
        nb = mul(n, -2)
        B = tr([mul(d, i), add(mul(d, i), nb), add(mul(d, j), nb), mul(d, j)])
    else:
        side = 1 if mode == "overlap" else -1
        b0 = add(mul(d, i), mul(n, side * 3))
        B = tr([mul(d, i), add(b0, mul(d, 2)), add(b0, mul(d, -2))])
        if mode == "near-miss":  # one representable step off the edge
            B[0] = add(B[0], mul(rng.choice([(1, 0), (0, 1), (-1, 0), (0, -1)]), step))
    return [[tr(A)]], [[B]]


def fam_near_maxcoord(rng):
    """Coordinates just above 2^60, inside Clipper2's MAX_COORD (2^61 - 1); ulp there is 2^8."""
    return big_edge_family(rng, 2 ** 60, 2 ** 8, [2 ** 30, 2 ** 40 + 1, 2 ** 43, 2 ** 44 - 1])


def fam_beyond_maxcoord(rng):
    """Coordinates in [2^61, 2^62): outside Clipper2's documented range (ulp 2^9 or 2^10)."""
    return big_edge_family(rng, 3 * 2 ** 60, 2 ** 10, [2 ** 30, 2 ** 40 + 1, 2 ** 44 - 1])


def fam_vertex_vertex(rng):
    T = Lattice(rng)
    A = lattice_polygon(rng, 6, rng.randint(4, 8))
    v = rng.choice(A)
    d = primitive_dir(rng, 5)
    if rng.random() < 0.5:
        d = mul(d, -1)
    far = add(v, mul(d, rng.randint(3, 8)))
    perp = (-d[1], d[0])
    return [[T.ring(A)]], [[T.ring([v, add(far, perp), add(far, perp, -1)])]]


def fam_collinear_chain(rng):
    """Collinear vertices along a shared horizontal edge: A at even x, B at every x."""
    T = Lattice(rng)
    m = rng.randint(3, 8)
    A = [(2 * x, 0) for x in range(0, m + 1)] + [(2 * m, 6), (0, 6)]
    lo = rng.randint(0, 2 * m - 1)
    hi = rng.randint(lo + 1, 2 * m + 2)
    side = rng.choice([-1, 1])
    B = [(x, 0) for x in range(lo, hi + 1)] + [(hi, side * rng.randint(1, 8)), (lo, side * 4)]
    return [[T.ring(A)]], [[T.ring(B)]]


def fam_thin_triangle(rng):
    """Long triangles whose short side is one unit, against other thin shapes.

    Both operands are thin, so a lost triangle is a large share of the exact areas. Every
    vertex of every exact result is a lattice point, so no rounding is needed anywhere.
    """
    # E < 2^25 with no offset keeps |coord| < 2^26, where ClipperD(precision 8) is exact too
    E = rng.choice([2 ** 20, 10 ** 6 + 1, 2 ** 25 - 1, 2 ** 33, 10 ** 11 + 1, 2 ** 40, 3 ** 30])
    off = 0 if E < 2 ** 25 else rng.choice([0, 0, 10 ** 12, -(2 ** 44)])
    p, q = rng.choice([((0, 0), (1, 0)), ((0, 0), (0, 1)), ((0, 0), (1, 1)), ((0, 1), (1, 0))])
    d = (q[0] - p[0], q[1] - p[1])
    far = (-d[1] * E + rng.randint(-3, 3), d[0] * E + rng.randint(-3, 3))
    if rng.random() < 0.5:
        far = (-far[0], -far[1])
    A = [p, q, far]
    mode = rng.choice(["identical", "rotated-start", "reversed", "parallelogram", "mirror",
                       "far-copy", "shifted-unit"])
    if mode == "identical":
        B = list(A)
    elif mode == "rotated-start":
        B = [q, far, p]
    elif mode == "reversed":
        B = A[::-1]
    elif mode == "parallelogram":  # 1-unit-wide parallelogram (4 vertices) containing A
        B = [p, q, add(far, d), far]
    elif mode == "mirror":  # thin triangle on the other side of A's long edge p-far
        B = [p, far, add(p, d, -1)]
    elif mode == "far-copy":  # a disjoint copy, moved sideways by about E
        B = [add(v, (far[1] - p[1], p[0] - far[0])) for v in A]
    else:  # shifted by the short side: touches A at q only
        B = [add(v, d) for v in A]
    tr = lambda r: [(x + off, y + off) for x, y in r]  # noqa: E731
    return [[tr(A)]], [[tr(B)]]


FAMILIES = [
    ("int-shared-edge-touch", fam_shared_edge_touch),
    ("int-shared-edge-overlap", fam_shared_edge_overlap),
    ("int-vertex-on-edge", fam_vertex_on_edge),
    ("int-near-miss", fam_near_miss),
    ("int-thin-crossing", fam_thin_crossing),
    ("int-identical", fam_identical),
    ("int-hole-exact", fam_hole_exact),
    ("int-hole-touches-shell", fam_hole_touches_shell),
    ("int-multi-corner", fam_multi_corner),
    ("int-lattice-random", fam_lattice_random),
    ("int-lattice-jitter", fam_lattice_jitter),
    ("int-near-parallel-large", fam_near_parallel_large),
    ("int-near-maxcoord", fam_near_maxcoord),
    ("int-beyond-maxcoord", fam_beyond_maxcoord),
    ("int-vertex-vertex", fam_vertex_vertex),
    ("int-collinear-chain", fam_collinear_chain),
    ("int-thin-triangle", fam_thin_triangle),
]


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 12
    seed = int(sys.argv[2]) if len(sys.argv) > 2 else 1
    rng = random.Random(seed)
    for fam, fn in FAMILIES:
        count = tries = 0
        while count < n:
            tries += 1
            if tries > 200 * n:
                raise RuntimeError(f"{fam}: cannot make valid cases")
            a, b = fn(rng)
            if rng.random() < 0.5:
                a, b = b, a
            ca = [[close(r) for r in poly] for poly in a]
            cb = [[close(r) for r in poly] for poly in b]
            coords = [v for mp in (ca, cb) for poly in mp for r in poly for p in r for v in p]
            if not all(exact_double(v) and abs(v) < 2 ** 62 for v in coords):
                continue
            if not (is_valid(ca) and is_valid(cb)):
                continue
            count += 1
            print(json.dumps({"id": f"{fam}-{seed}-{count:04d}", "family": fam, "a": ca, "b": cb}))


if __name__ == "__main__":
    main()
