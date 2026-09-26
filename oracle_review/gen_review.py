"""Case generators for the oracle review (FORMAT.md case lines).

usage: python gen_review.py FAMILY N SEED > cases.jsonl      (FAMILY may be 'all')

Families
  convex-grid        convex hulls of small-integer points: shared edges, partial shared
                     edges, vertex on edge, identical copies, adjacent translates, nested
  convex-grid-rot    the same pairs rotated / scaled by one common float map: degeneracy
                     turns into near-degeneracy (differences of a few ulps)
  convex-ulp         unit squares / rotated squares one or two ulps apart or overlapping
  convex-float       generic random convex polygons with random double coordinates
  general-grid       unions of grid cells and half-cells (holes touching the shell at a
                     point, parts touching at a point, collinear edges everywhere) with B
                     derived from A (copy, shift, filled hole, superset, subset, mirror)
  general-float      generic star polygons with holes and multipolygons (double coords)
  extreme            general-grid / convex-grid pairs scaled by 2^k, k in [-1074, 600]
  edge               hand-made edge cases (see EDGE_CASES)
"""
import json
import math
import random
import sys

from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import unary_union
import shapely

# ------------------------------------------------------------------------ helpers


def close(r):
    return [list(p) for p in r] + [list(r[0])]


def hull(points):
    """Andrew monotone chain on exact (int/dyadic) points; drops collinear points."""
    pts = sorted(set(map(tuple, points)))
    if len(pts) < 3:
        return None

    def cr(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
    lo, hi = [], []
    for p in pts:
        while len(lo) >= 2 and cr(lo[-2], lo[-1], p) <= 0:
            lo.pop()
        lo.append(p)
    for p in reversed(pts):
        while len(hi) >= 2 and cr(hi[-2], hi[-1], p) <= 0:
            hi.pop()
        hi.append(p)
    h = lo[:-1] + hi[:-1]
    return h if len(h) >= 3 else None


def mp_of(g):
    if g.is_empty:
        return None
    if g.geom_type == "Polygon":
        ps = [g]
    elif g.geom_type == "MultiPolygon":
        ps = list(g.geoms)
    else:
        ps = [x for x in getattr(g, "geoms", []) if x.geom_type == "Polygon" and not x.is_empty]
    if not ps:
        return None
    return [[[list(map(float, c)) for c in p.exterior.coords]]
            + [[list(map(float, c)) for c in h.coords] for h in p.interiors] for p in ps]


def build(mp):
    polys = [Polygon(p[0], p[1:]) for p in mp]
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def valid(mp):
    try:
        return bool(build(mp).is_valid)
    except Exception:  # noqa: BLE001
        return False


def mapxy(mp, f):
    return [[[list(f(x, y)) for x, y in ring] for ring in poly] for poly in mp]


def rng_float_map(rng):
    """A random rotation+scale+offset evaluated in doubles (inexact on purpose)."""
    th = rng.uniform(0, 2 * math.pi)
    s = rng.choice([1.0, 0.1, 1e-3, 7.3, 1e3])
    c, sn = math.cos(th) * s, math.sin(th) * s
    ox, oy = rng.choice([(0.0, 0.0), (rng.uniform(-10, 10), rng.uniform(-10, 10)), (1e6, -3e6)])
    return lambda x, y: (ox + c * x - sn * y, oy + sn * x + c * y)


def exact_map(rng):
    """A random exact map: swap / negate / power-of-two scale / small integer shift."""
    sw, nx, ny = rng.random() < .5, rng.choice([1, -1]), rng.choice([1, -1])
    k = rng.randint(-8, 8)
    dx, dy = rng.randint(-5, 5), rng.randint(-5, 5)

    def f(x, y):
        if sw:
            x, y = y, x
        return (math.ldexp(nx * x + dx, k), math.ldexp(ny * y + dy, k))
    return f


# ------------------------------------------------------------------------ convex


def rand_hull(rng, G, k=None):
    for _ in range(100):
        k2 = k or rng.randint(3, 8)
        h = hull([(rng.randint(0, G), rng.randint(0, G)) for _ in range(k2)])
        if h:
            return h
    return [(0, 0), (G, 0), (G, G)]


def outside_points(rng, p, q, G, n):
    """Integer points strictly right of the directed line p->q (outside a CCW hull)."""
    out = []
    for _ in range(200):
        x, y = rng.randint(-G, 2 * G), rng.randint(-G, 2 * G)
        if (q[0] - p[0]) * (y - p[1]) - (q[1] - p[1]) * (x - p[0]) < 0:
            out.append((x, y))
            if len(out) >= n:
                break
    return out


def convex_pair(rng):
    G = rng.choice([1, 2, 3, 4, 6, 8, 12])
    A = rand_hull(rng, G)
    kind = rng.choice(["indep", "identical", "shared-edge", "partial-edge", "vertex-on-edge",
                       "shift", "nested", "rev-rep"])
    n = len(A)
    i = rng.randrange(n)
    p, q = A[i], A[(i + 1) % n]
    if kind == "indep":
        B = rand_hull(rng, G)
    elif kind == "identical":
        j = rng.randrange(n)
        B = A[j:] + A[:j]
    elif kind == "rev-rep":
        B = list(reversed(A))
        j = rng.randrange(n)
        B = B[:j] + [B[j]] + B[j:]
    elif kind == "shared-edge":
        B = hull([p, q] + outside_points(rng, p, q, G, rng.randint(1, 3))) or A
    elif kind == "partial-edge":
        t0, t1 = sorted(rng.sample(range(0, 9), 2))
        m0 = (p[0] + t0 * (q[0] - p[0]) / 8, p[1] + t0 * (q[1] - p[1]) / 8)
        m1 = (p[0] + t1 * (q[0] - p[0]) / 8, p[1] + t1 * (q[1] - p[1]) / 8)
        side = rng.choice([-1, 1])  # -1 outside A, +1 overlapping into A
        extra = []
        for _ in range(rng.randint(1, 2)):
            if side < 0:
                extra += outside_points(rng, p, q, G, 1)
            else:
                extra.append((rng.randint(0, G), rng.randint(0, G)))
        B = hull([m0, m1] + extra) or A
    elif kind == "vertex-on-edge":
        t = rng.randint(1, 7) / 8
        m = (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
        B = hull([m] + outside_points(rng, p, q, G, 2)) or A
        if rng.random() < .5:
            B = hull([m] + [(rng.randint(0, G), rng.randint(0, G)) for _ in range(3)]) or B
    elif kind == "shift":
        dx, dy = rng.randint(-G, G), rng.randint(-G, G)
        B = [(x + dx, y + dy) for x, y in A]
    else:  # nested: B = hull of dyadic points of A (inside or on boundary)
        pts = []
        for _ in range(rng.randint(3, 6)):
            u = rng.randint(0, 8)
            v = rng.randint(0, 8 - u)
            w = 8 - u - v  # barycentric weights /8: exact dyadic points in A (or on it)
            a0, a1, a2 = A[0], A[rng.randrange(1, n)], A[rng.randrange(1, n)]
            pts.append(((u * a0[0] + v * a1[0] + w * a2[0]) / 8, (u * a0[1] + v * a1[1] + w * a2[1]) / 8))
        B = hull(pts + [rng.choice(A)]) or A
    a = [[close([(float(x), float(y)) for x, y in A])]]
    b = [[close([(float(x), float(y)) for x, y in B])]]
    return kind, a, b


def gen_convex_grid(rng, n):
    for _ in range(n):
        kind, a, b = convex_pair(rng)
        f = exact_map(rng)
        yield f"convex-grid/{kind}", mapxy(a, f), mapxy(b, f)


def gen_convex_grid_rot(rng, n):
    for _ in range(n):
        kind, a, b = convex_pair(rng)
        f = rng_float_map(rng)
        yield f"convex-grid-rot/{kind}", mapxy(a, f), mapxy(b, f)


def nudge(x, k):
    for _ in range(abs(k)):
        x = math.nextafter(x, math.inf if k > 0 else -math.inf)
    return x


def gen_convex_ulp(rng, n):
    for _ in range(n):
        k = rng.choice([-2, -1, 0, 1, 2])
        which = rng.randrange(4)
        if which == 0:  # axis aligned neighbours
            a = [[close([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])]]
            x0 = nudge(1.0, k)
            b = [[close([(x0, 0.0), (2.0, 0.0), (2.0, 1.0), (x0, 1.0)])]]
        elif which == 1:  # rotated neighbours like the seed
            th = rng.uniform(0, math.pi / 2)
            d = 1.0 + k * 2.0 ** -52

            def sq(cx, cy):
                c, s = math.cos(th) / 2, math.sin(th) / 2
                return close([(cx + c * dx - s * dy, cy + s * dx + c * dy)
                              for dx, dy in ((-1, -1), (1, -1), (1, 1), (-1, 1))])
            a, b = [[sq(0.0, 0.0)]], [[sq(d * math.cos(th), d * math.sin(th))]]
        elif which == 2:  # one vertex of a copy moved by k ulps in x and/or y
            A = rand_hull(rng, rng.choice([2, 4, 8]))
            f = rng_float_map(rng)
            ra = close([f(x, y) for x, y in A])
            rb = [list(p) for p in ra[:-1]]
            j = rng.randrange(len(rb))
            rb[j] = [nudge(rb[j][0], k), nudge(rb[j][1], rng.choice([-1, 0, 1]))]
            a, b = [[ra]], [[close(rb)]]
            if not (valid(a) and valid(b)):
                a, b = [[ra]], [[ra]]
        else:  # triangle apex a few ulps across the opposite triangle's edge
            p, q = (0.0, 0.0), (rng.uniform(1, 3), rng.uniform(0.1, 3))
            t = rng.choice([0.25, 0.5, 0.75, rng.random()])
            m = (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))
            m = (nudge(m[0], k), nudge(m[1], rng.choice([-1, 0, 1])))
            a = [[close([p, q, (0.0, q[1] + 1.0)])]]
            b = [[close([m, (q[0] + 1.0, -1.0), (q[0] + 2.0, 0.5)])]]
        yield f"convex-ulp/{which}", a, b


def gen_convex_float(rng, n):
    for _ in range(n):
        def one():
            cx, cy, r = rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(0.2, 1.5)
            pts = [(cx + r * rng.uniform(-1, 1), cy + r * rng.uniform(-1, 1))
                   for _ in range(rng.randint(3, 12))]
            return close(hull(pts) or [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)])
        yield "convex-float", [[one()]], [[one()]]


# ------------------------------------------------------------------------ general


def grid_union(rng, G, ncells, tri_prob=0.3):
    shapes = []
    for _ in range(ncells):
        i, j = rng.randrange(G), rng.randrange(G)
        if rng.random() < tri_prob:
            c = [(i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)]
            k = rng.randrange(4)
            shapes.append(Polygon([c[k], c[(k + 1) % 4], c[(k + 2) % 4]]))
        else:
            shapes.append(box(i, j, i + 1, j + 1))
    return unary_union(shapes)


def gen_general_grid(rng, n):
    made = 0
    while made < n:
        G = rng.choice([3, 4, 5, 6, 8])
        ga = grid_union(rng, G, rng.randint(2, G * G))
        a = mp_of(ga)
        if not a or not valid(a):
            continue
        kind = rng.choice(["indep", "identical", "shift", "hole", "superset", "subset",
                           "mirror", "indep"])
        gb = None
        if kind == "indep":
            gb = grid_union(rng, G, rng.randint(2, G * G))
        elif kind == "identical":
            gb = ga
        elif kind == "shift":
            gb = shapely.affinity.translate(ga, rng.randint(-2, 2), rng.randint(-2, 2))
        elif kind == "hole":
            holes = [h for p in (a) for h in p[1:]]
            if not holes:
                continue
            gb = Polygon(rng.choice(holes))
            if rng.random() < .5:
                gb = unary_union([gb, grid_union(rng, G, 2)])
        elif kind == "superset":
            gb = unary_union([ga, grid_union(rng, G, rng.randint(1, G))])
        elif kind == "subset":
            gb = ga.difference(grid_union(rng, G, rng.randint(1, G * 2)))
        else:
            gb = shapely.affinity.scale(ga, -1, 1, origin=(G / 2, 0))
        b = mp_of(gb)
        if not b or not valid(b):
            continue
        if kind == "identical" and rng.random() < .5:
            # representation change: rotate ring starts, reverse, duplicate a point
            b = [[_rerep(rng, r) for r in poly] for poly in b][::-1]
        f = exact_map(rng)
        made += 1
        yield f"general-grid/{kind}", mapxy(a, f), mapxy(b, f)


def _rerep(rng, ring):
    r = ring[:-1]
    j = rng.randrange(len(r))
    r = r[j:] + r[:j]
    if rng.random() < .5:
        r = r[::-1]
    j = rng.randrange(len(r))
    r = r[:j] + [r[j]] + r[j:]
    return [list(p) for p in r] + [list(r[0])]


def star(rng, cx, cy, r0, r1, n):
    pts = []
    for k in range(n):
        ang = 2 * math.pi * k / n + rng.uniform(-0.3, 0.3) * 2 * math.pi / n
        rr = rng.uniform(r0, r1)
        pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
    return close(pts)


def rand_general_float(rng):
    polys = []
    nparts = rng.choice([1, 1, 2, 3])
    centers = [(0.0, 0.0), (2.5, 0.3), (-0.4, 2.6)]
    for pi in range(nparts):
        cx, cy = centers[pi]
        cx += rng.uniform(-0.3, 0.3)
        cy += rng.uniform(-0.3, 0.3)
        shell = star(rng, cx, cy, 0.8, 1.2, rng.randint(5, 14))
        holes = []
        nh = rng.choice([0, 0, 1, 2])
        if nh == 1:
            holes.append(star(rng, cx, cy, 0.15, 0.4, rng.randint(3, 8)))
        elif nh == 2:
            holes.append(star(rng, cx - 0.3, cy, 0.05, 0.2, rng.randint(3, 6)))
            holes.append(star(rng, cx + 0.3, cy, 0.05, 0.2, rng.randint(3, 6)))
        polys.append([shell] + holes)
    return polys


def gen_general_float(rng, n):
    made = 0
    while made < n:
        a = rand_general_float(rng)
        b = rand_general_float(rng)
        if rng.random() < .5:
            dx, dy = rng.uniform(-2, 2), rng.uniform(-2, 2)
            b = mapxy(b, lambda x, y: (x + dx, y + dy))
        if not (valid(a) and valid(b)):
            continue
        made += 1
        yield "general-float", a, b


def gen_extreme(rng, n):
    for i in range(n):
        if i % 2:
            kind, a, b = convex_pair(rng)
        else:
            a = b = None
            while not (a and b and valid(a) and valid(b)):
                G = rng.choice([3, 4])
                a, b = mp_of(grid_union(rng, G, 6)), mp_of(grid_union(rng, G, 6))
            kind = "grid"
        k = rng.choice([-1074, -1070, -1060, -1000, -600, -300, 300, 500, 505, 510, 511, 512, 600])
        f = lambda x, y, k=k: (math.ldexp(x, k), math.ldexp(y, k))
        yield f"extreme/{kind}/2^{k}", mapxy(a, f), mapxy(b, f)


# ------------------------------------------------------------------------ edge cases

def sq(x0, y0, x1, y1):
    return close([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


U = math.ulp(1.0)
EDGE_CASES = {
    "identical-square": ([[sq(0, 0, 1, 1)]], [[sq(0, 0, 1, 1)]]),
    "shared-edge": ([[sq(0, 0, 1, 1)]], [[sq(1, 0, 2, 1)]]),
    "shared-partial-edge": ([[sq(0, 0, 2, 2)]], [[sq(2, 1, 3, 3)]]),
    "corner-touch": ([[sq(0, 0, 1, 1)]], [[sq(1, 1, 2, 2)]]),
    "inside-touching": ([[sq(0, 0, 4, 4)]], [[sq(0, 1, 2, 3)]]),
    "inside-strict": ([[sq(0, 0, 4, 4)]], [[sq(1, 1, 2, 2)]]),
    "hole-filled": ([[sq(0, 0, 4, 4), sq(1, 1, 3, 3)]], [[sq(1, 1, 3, 3)]]),
    "hole-filled-plus": ([[sq(0, 0, 4, 4), sq(1, 1, 3, 3)]], [[sq(1, 1, 3, 3.5)]]),
    "in-hole-strict": ([[sq(0, 0, 4, 4), sq(1, 1, 3, 3)]], [[sq(1.5, 1.5, 2.5, 2.5)]]),
    "hole-touch-shell-point": ([[sq(0, 0, 4, 4), close([(0, 2), (2, 1), (2, 3)])]],
                               [[close([(-1, 2), (0, 2), (1, 2.5), (-1, 3)])]]),
    "hole-touch-shell-point-b-in-hole": ([[sq(0, 0, 4, 4), close([(0, 2), (2, 1), (2, 3)])]],
                                         [[close([(0.5, 2), (1.5, 1.75), (1.5, 2.25)])]]),
    "hole-touch-shell-point-b-fills": ([[sq(0, 0, 4, 4), close([(0, 2), (2, 1), (2, 3)])]],
                                       [[close([(0, 2), (2, 1), (2, 3)])]]),
    "holes-touch-each-other": ([[sq(0, 0, 6, 6), sq(1, 1, 3, 3), sq(3, 3, 5, 5)]],
                               [[sq(2, 2, 4, 4)]]),
    "multi-touch-point": ([[sq(0, 0, 1, 1)], [sq(1, 1, 2, 2)]], [[sq(0.5, 0.5, 1.5, 1.5)]]),
    "multi-touch-point-b-through": ([[sq(0, 0, 1, 1)], [sq(1, 1, 2, 2)]],
                                    [[close([(1, 1), (2, 0), (3, 1), (2, -1)])]]),
    "multi-touch-point-b-diag": ([[sq(0, 0, 1, 1)], [sq(1, 1, 2, 2)]],
                                 [[sq(1, 0, 2, 1)], [sq(0, 1, 1, 2)]]),
    "island-in-hole": ([[sq(0, 0, 6, 6), sq(1, 1, 5, 5)], [sq(2, 2, 4, 4)]],
                       [[sq(1.5, 1.5, 4.5, 4.5)]]),
    "island-in-hole-equals-b": ([[sq(0, 0, 6, 6), sq(1, 1, 5, 5)], [sq(2, 2, 4, 4)]],
                                [[sq(2, 2, 4, 4)]]),
    "vertical-edges": ([[sq(0, 0, 1, 1)]], [[close([(0.5, -1), (0.5, 2), (2, 0.5)])]]),
    "vertical-collinear": ([[sq(0, 0, 1, 3)]], [[close([(1, 1), (2, 0), (2, 4), (1, 2)])]]),
    "horizontal-collinear": ([[close([(0, 0), (3, 0), (1.5, 2)])]], [[close([(1, 0), (5, 0), (3, -2)])]]),
    "horizontal-collinear-same-side": ([[close([(0, 0), (3, 0), (1.5, 2)])]],
                                       [[close([(1, 0), (5, 0), (3, 2)])]]),
    "sloped-collinear": ([[close([(0, 0), (3, 1), (0, 3)])]], [[close([(1.5, 0.5), (6, 2), (6, -2)])]]),
    "sloped-vertex-on-edge": ([[close([(0, 0), (3, 1), (0, 3)])]], [[close([(1.5, 0.5), (4, 0), (4, -1)])]]),
    "repeated-points": ([[close([(0, 0), (0, 0), (1, 0), (1, 0), (1, 1), (0, 1), (0, 1)])]],
                        [[close([(0.5, 0.5), (2, 0.5), (2, 0.5), (2, 2), (0.5, 2)])]]),
    "repeated-closing": ([[[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0], [0, 0]]]], [[sq(0.5, 0.5, 2, 2)]]),
    "ulp-gap": ([[sq(0, 0, 1, 1)]], [[sq(1 + U, 0, 2, 1)]]),
    "ulp-overlap": ([[sq(0, 0, 1, 1)]], [[sq(1 - U / 2, 0, 2, 1)]]),
    "ulp-gap-corner": ([[sq(0, 0, 1, 1)]], [[sq(1 + U, 1 + U, 2, 2)]]),
    "tiny-1e-300": ([[sq(0, 0, 1e-300, 1e-300)]], [[sq(5e-301, 5e-301, 2e-300, 2e-300)]]),
    "tiny-subnormal": ([[sq(0, 0, 4e-323, 4e-323)]], [[sq(2e-323, 2e-323, 1e-322, 1e-322)]]),
    "tiny-min-subnormal": ([[sq(0, 0, 5e-324, 5e-324)]], [[sq(0, 0, 5e-324, 5e-324)]]),
    "big-1e150": ([[sq(0, 0, 1e150, 1e150)]], [[sq(5e149, 5e149, 2e150, 2e150)]]),
    "big-1e154": ([[sq(0, 0, 1e154, 1e154)]], [[sq(5e153, 5e153, 2e154, 2e154)]]),
    "big-1e155": ([[sq(0, 0, 1e155, 1e155)]], [[sq(5e154, 5e154, 2e155, 2e155)]]),
    "big-1e300": ([[sq(0, 0, 1e300, 1e300)]], [[sq(5e299, 5e299, 2e300, 2e300)]]),
    "big-1e300-disjoint": ([[sq(0, 0, 1e300, 1e300)]], [[sq(2e300, 2e300, 3e300, 3e300)]]),
    "mixed-scale": ([[sq(-1e300, -1e300, 1e300, 1e300)]], [[sq(0, 0, 1e-300, 1e-300)]]),
    "huge-offset-small": ([[sq(1e15, 1e15, 1e15 + 1, 1e15 + 1)]], [[sq(1e15 + 0.5, 1e15, 1e15 + 2, 1e15 + 1)]]),
    "int-json": ([[[[0, 0], [3, 0], [3, 3], [0, 3], [0, 0]]]], [[[[1, 1], [4, 1], [4, 4], [1, 4], [1, 1]]]]),
    "neg-zero": ([[close([(-0.0, -0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)])]], [[sq(0.0, 0.0, 1.0, 1.0)]]),
    "cw-shell-ccw-hole": ([[close([(0, 0), (0, 4), (4, 4), (4, 0)]), close([(1, 1), (3, 1), (3, 3), (1, 3)])]],
                          [[sq(2, 2, 5, 5)]]),
    "star-crossing-at-vertices": ([[close([(0, 0), (2, 1), (4, 0), (3, 2), (4, 4), (2, 3), (0, 4), (1, 2)])]],
                                  [[close([(2, -1), (3, 2), (2, 5), (1, 2)])]]),
    "comb-vertical": ([[close([(0, 0), (5, 0), (5, 3), (4, 3), (4, 1), (3, 1), (3, 3), (2, 3), (2, 1), (1, 1), (1, 3), (0, 3)])]],
                      [[close([(1, 1), (4, 1), (4, 3), (1, 3)])]]),
    "same-x-many": ([[close([(0, 0), (1, 0), (1, 1), (1, 2), (1, 3), (0, 3)])]],
                    [[close([(1, 1), (2, 1), (2, 2), (1, 2)])]]),
}


def gen_edge(rng, n):
    for name, (a, b) in EDGE_CASES.items():
        yield f"edge/{name}", a, b


GENS = {
    "convex-grid": gen_convex_grid, "convex-grid-rot": gen_convex_grid_rot,
    "convex-ulp": gen_convex_ulp, "convex-float": gen_convex_float,
    "general-grid": gen_general_grid, "general-float": gen_general_float,
    "extreme": gen_extreme, "edge": gen_edge,
}


def main():
    fam, n, seed = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    fams = list(GENS) if fam == "all" else [fam]
    for fm in fams:
        rng = random.Random(f"{fm}-{seed}")
        for i, (family, a, b) in enumerate(GENS[fm](rng, n)):
            print(json.dumps({"id": f"{fm}-{seed}-{i:06d}", "family": family, "a": a, "b": b}))


if __name__ == "__main__":
    main()
