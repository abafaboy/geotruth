"""Shared helpers for the generator suite (stdlib only; shapely is optional, for validation).

Geometry inside the generators: a MultiPolygon is a list of polygons, a polygon a list of
*open* rings (shell first), a ring a list of [x, y] floats. `finalize` closes the rings
(FORMAT.md wants the first point repeated at the end).

Two kinds of coordinate frames:

- `FloatFrame`: a centre and a size, for constructions computed in floating point
  (rotations, lerps, ulp nudges). The `lonlat` frame rounds to 12 decimals, like GeoJSON
  written with 1e-12 detail, and nudges in units of 1e-12 instead of ulps.
- `ExactFrame`: an integer lattice mapped to doubles by x = (X + ox) * 2^e with
  |X + ox| < 2^53, so every lattice point is an exact double. Constructions done with
  Python integers (points on edges at rational parameters, shared sub-edges, touching
  parts) stay exact after the mapping, and `pt` checks it with fractions.
"""
import math
import os
import sys
from fractions import Fraction

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import oracle  # noqa: E402
from oracle import Q, orient, on_segment, point_in, ring_simple, overlay_areas  # noqa: E402

try:  # optional: second opinion on validity of rings with holes and multipolygons
    import shapely
    from shapely.geometry import MultiPolygon, Polygon
except ImportError:  # pragma: no cover
    shapely = None

TWO53 = 2 ** 53
TAU = 2 * math.pi


class Reject(Exception):
    """A generator attempt did not produce what it wanted; the driver retries."""


# ----------------------------------------------------------------------------- floats

def nudge(x, k):
    """x moved by k ulps (k > 0 towards +inf)."""
    d = math.inf if k > 0 else -math.inf
    for _ in range(abs(k)):
        x = math.nextafter(x, d)
    return x


def lerp(p, q, t):
    return [p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1])]


def add(p, v, s=1.0):
    return [p[0] + s * v[0], p[1] + s * v[1]]


def sub(p, q):
    return [p[0] - q[0], p[1] - q[1]]


def unit(v):
    n = math.hypot(v[0], v[1])
    if n == 0:
        raise Reject("zero vector")
    return [v[0] / n, v[1] / n]


def left_normal(p, q):
    """Unit normal pointing to the left of p -> q."""
    d = unit(sub(q, p))
    return [-d[1], d[0]]


def rot_pt(p, c, th):
    cs, sn = math.cos(th), math.sin(th)
    dx, dy = p[0] - c[0], p[1] - c[1]
    return [c[0] + cs * dx - sn * dy, c[1] + sn * dx + cs * dy]


def rotate_ring(ring, c, th):
    return [rot_pt(p, c, th) for p in ring]


def centroid(ring):
    n = len(ring)
    return [sum(p[0] for p in ring) / n, sum(p[1] for p in ring) / n]


def signed_area(ring):
    s = 0.0
    n = len(ring)
    for i in range(n):
        p, q = ring[i], ring[(i + 1) % n]
        s += p[0] * q[1] - q[0] * p[1]
    return s / 2


def ccw(ring):
    """The ring in counter-clockwise order (float area; only for construction)."""
    return ring if signed_area(ring) > 0 else ring[::-1]


def log_uniform(rng, lo_exp, hi_exp):
    return 10.0 ** rng.uniform(lo_exp, hi_exp)


def sgn(rng):
    return rng.choice((-1, 1))


def star_ring(rng, c, r, n, rmin=0.35):
    """Star-shaped ring around c (CCW), n vertices at jittered angles."""
    ph = rng.uniform(0, TAU)
    pts = []
    for k in range(n):
        ang = ph + TAU * (k + rng.uniform(-0.35, 0.35)) / n
        rr = r * rng.uniform(rmin, 1.0)
        pts.append([c[0] + rr * math.cos(ang), c[1] + rr * math.sin(ang)])
    return pts


def convex_ring(rng, c, r, n, ratio=0.4):
    """Convex ring (CCW): points of a random ellipse (axis ratio >= ratio) at sorted random angles."""
    angs = sorted(rng.uniform(0, TAU) for _ in range(n))
    ax, ay = r, r * rng.uniform(ratio, 1.0)
    ph = rng.uniform(0, TAU)
    cs, sn = math.cos(ph), math.sin(ph)
    pts = []
    for a in angs:
        x, y = ax * math.cos(a), ay * math.sin(a)
        pts.append([c[0] + cs * x - sn * y, c[1] + sn * x + cs * y])
    return pts


def rect_ring(c, w, h, th=0.0):
    pts = [[-w / 2, -h / 2], [w / 2, -h / 2], [w / 2, h / 2], [-w / 2, h / 2]]
    return [rot_pt([c[0] + x, c[1] + y], c, th) for x, y in pts]


class FloatFrame:
    """Where a floating-point construction lives: centre, size, and decimal rounding."""

    def __init__(self, kind, cx, cy, size, decimals=None):
        self.kind, self.c, self.size, self.decimals = kind, [cx, cy], size, decimals

    def fix(self, p):
        if self.decimals is None:
            return [float(p[0]), float(p[1])]
        return [round(p[0], self.decimals), round(p[1], self.decimals)]

    def fix_ring(self, ring):
        return [self.fix(p) for p in ring]

    def perturb(self, x, k):
        """k ulps (or k units of the last decimal in a decimal frame)."""
        if self.decimals is None:
            return nudge(x, k)
        return round(x + k * 10.0 ** -self.decimals, self.decimals)

    def perturb_pt(self, p, kx, ky):
        return [self.perturb(p[0], kx), self.perturb(p[1], ky)]

    def tiny(self, rng, lo=-16, hi=-9):
        """A tiny absolute distance: 10^U(lo,hi) relative to the coordinate magnitude."""
        mag = max(abs(self.c[0]), abs(self.c[1]), self.size)
        d = mag * log_uniform(rng, lo, hi)
        if self.decimals is not None:
            d = max(d, 10.0 ** -self.decimals)
        return d


def float_frame(rng, kinds=("origin", "moderate", "projected", "lonlat")):
    kind = rng.choice(kinds)
    if kind == "origin":
        return FloatFrame(kind, 0.0, 0.0, log_uniform(rng, -0.5, 0.5))
    if kind == "moderate":
        return FloatFrame(kind, rng.uniform(-1000, 1000), rng.uniform(-1000, 1000), log_uniform(rng, -2, 2))
    if kind == "projected":  # easting/northing-like map coordinates, metres
        return FloatFrame(kind, rng.uniform(1e5, 1e7), rng.uniform(1e5, 1e7), log_uniform(rng, 0, 3))
    if kind == "lonlat":
        return FloatFrame(kind, rng.uniform(-180, 180), rng.uniform(-85, 85), log_uniform(rng, -4, 0), 12)
    raise ValueError(kind)


# ----------------------------------------------------------------------------- exact lattice

class ExactFrame:
    """Integer lattice point (X, Y) -> doubles ((X + ox) * 2^e, (Y + oy) * 2^e), exactly.

    Local constructions should keep |X|, |Y| <= 2^S (a little more is fine)."""

    def __init__(self, kind, e, ox, oy, S):
        self.kind, self.e, self.ox, self.oy, self.S = kind, e, ox, oy, S
        self.scale = Fraction(2) ** e

    def pt(self, p):
        out = []
        for v, o in ((p[0], self.ox), (p[1], self.oy)):
            w = int(v) + o
            if abs(w) >= TWO53:
                raise Reject("out of exact range")
            f = math.ldexp(float(w), self.e)
            if Fraction(f) != w * self.scale:
                raise Reject("inexact lattice point")
            out.append(f)
        return out

    def ring(self, r):
        return [self.pt(p) for p in r]


def exact_frame(rng, kinds=("unit", "int", "projected", "lonlat")):
    """A random lattice frame; S is the number of bits available for local geometry."""
    kind = rng.choice(kinds)
    for _ in range(100):
        if kind == "unit":  # coordinates in about [-1, 1], b fractional bits
            b = rng.randint(8, 50)
            fr = ExactFrame(kind, -b, 0, 0, b)
        elif kind == "int":  # plain integers, optionally far from the origin
            S = rng.randint(6, 30)
            # offset at most 2^20 extents away, so that rounding intersection points at that
            # magnitude stays far below compare.py's 1e-6 relative area tolerance
            ob = rng.randint(0, min(52 - S - 3, S + 20))
            fr = ExactFrame(kind, 0, rng.randint(-2 ** ob, 2 ** ob), rng.randint(-2 ** ob, 2 ** ob), S)
        else:
            if kind == "projected":
                cx, cy, ext = rng.uniform(1e5, 1e7), rng.uniform(1e5, 1e7), log_uniform(rng, 0, 3)
            else:
                cx, cy, ext = rng.uniform(-180, 180), rng.uniform(-85, 85), log_uniform(rng, -4, 0)
            E = math.frexp(max(abs(cx), abs(cy), 1.0))[1]  # |c| < 2^E
            e = E - rng.randint(30, 51)  # lattice step 2^e: 30..51 bits below the magnitude
            S = math.floor(math.log2(ext)) - e
            if S < 8:
                e -= 8 - S
                S = 8
            fr = ExactFrame(kind, e, round(cx / 2.0 ** e), round(cy / 2.0 ** e), S)
        if max(abs(fr.ox), abs(fr.oy)) + 2 ** (fr.S + 3) < TWO53:
            return fr
    raise Reject("no frame")


def icross(o, a, b):
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def iadd(p, v, s=1):
    return (p[0] + s * v[0], p[1] + s * v[1])


def isub(p, q):
    return (p[0] - q[0], p[1] - q[1])


def convex_hull(points):
    """Strictly convex hull (CCW), integer points."""
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts
    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and icross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and icross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def rand_convex_int(rng, k, R, c=(0, 0), ratio=0.4):
    """Random strictly convex lattice polygon (CCW) with up to k vertices, radius ~R."""
    if R < 2:
        raise Reject("radius too small")
    pts = [(c[0] + round(p[0]), c[1] + round(p[1])) for p in convex_ring(rng, (0, 0), R, k, ratio)]
    h = convex_hull(pts)
    if len(h) < 3:
        raise Reject("degenerate hull")
    return h


def rand_star_int(rng, k, R, c=(0, 0)):
    if R < 4:
        raise Reject("radius too small")
    pts = [(c[0] + round(p[0]), c[1] + round(p[1])) for p in star_ring(rng, (0, 0), R, k)]
    if not oracle.ring_simple([(Q(x), Q(y)) for x, y in pts + pts[:1]]):
        raise Reject("star not simple")
    return pts


def rand_vec(rng, M, sloped=False):
    for _ in range(100):
        v = (rng.randint(-M, M), rng.randint(-M, M))
        if v != (0, 0) and (not sloped or (v[0] != 0 and v[1] != 0)):
            return v
    raise Reject("no vector")


def rand_vec_side(rng, D, M, side, lo=0):
    """Random integer vector v with |v|_inf <= M on the given side of direction D
    (side +1: left, cross(D, v) > 0; -1: right)."""
    for _ in range(200):
        v = (rng.randint(-M, M), rng.randint(-M, M))
        if max(abs(v[0]), abs(v[1])) < lo:
            continue
        c = D[0] * v[1] - D[1] * v[0]
        if c * side > 0:
            return v
    raise Reject("no side vector")


def verify_on_segment(v, a, b):
    """Exact check (rationals) that float point v lies on the closed segment ab."""
    V, A, B = (Q(v[0]), Q(v[1])), (Q(a[0]), Q(a[1])), (Q(b[0]), Q(b[1]))
    if orient(A, B, V) != 0 or not on_segment(V, A, B):
        raise Reject("point not exactly on edge")


# ----------------------------------------------------------------------------- validity

def _qring(r):
    return [(Q(x), Q(y)) for x, y in r]


def _qedges(r):
    return [(p, q) for p, q in zip(r, r[1:]) if p != q]


def _key(p, a, b):
    return p[0] if a[0] != b[0] else p[1]


def contact(ea, eb):
    """Points where two edge sets meet, exactly; None if they share a segment of positive length."""
    pts = set()
    for a, b in ea:
        axl, axh = min(a[0], b[0]), max(a[0], b[0])
        ayl, ayh = min(a[1], b[1]), max(a[1], b[1])
        for c, d in eb:
            if max(c[0], d[0]) < axl or min(c[0], d[0]) > axh or max(c[1], d[1]) < ayl or min(c[1], d[1]) > ayh:
                continue
            o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
            if o1 == 0 and o2 == 0:
                # collinear: overlap along the line
                lo = max(min(_key(a, a, b), _key(b, a, b)), min(_key(c, a, b), _key(d, a, b)))
                hi = min(max(_key(a, a, b), _key(b, a, b)), max(_key(c, a, b), _key(d, a, b)))
                if lo < hi:
                    return None
                if lo == hi:
                    for p in (a, b, c, d):
                        if _key(p, a, b) == lo:
                            pts.add(p)
                            break
                continue
            if o1 != o2 and o3 != o4:
                if o1 == 0:
                    pts.add(c)
                elif o2 == 0:
                    pts.add(d)
                elif o3 == 0:
                    pts.add(a)
                elif o4 == 0:
                    pts.add(b)
                else:
                    den = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])
                    t = ((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) / den
                    pts.add((a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])))
            else:
                for p, (s, e) in ((c, (a, b)), (d, (a, b)), (a, (c, d)), (b, (c, d))):
                    if orient(s, e, p) == 0 and on_segment(p, s, e):
                        pts.add(p)
    return pts


def exact_valid(mp):
    """Exact OGC validity for a closed-ring MultiPolygon: (ok, reason).

    Conservative: rings of one polygon may touch in at most one point per pair, and the
    touch graph must be a forest (so the interior stays connected; three rings through one
    point count as a cycle and are rejected even though they can be valid)."""
    polys = [[_qring(r) for r in poly] for poly in mp]
    for poly in polys:
        for r in poly:
            if len(r) < 4 or r[0] != r[-1]:
                return False, "ring not closed"
            if not ring_simple(r):
                return False, "ring not simple"
    for poly in polys:
        E = [_qedges(r) for r in poly]
        parent = list(range(len(poly)))

        def find(i):
            while parent[i] != i:
                i = parent[i]
            return i

        for i in range(len(poly)):
            for j in range(i + 1, len(poly)):
                c = contact(E[i], E[j])
                if c is None:
                    return False, "rings share a segment"
                if len(c) > 1:
                    return False, "rings touch in more than one point"
                if c:
                    ri, rj = find(i), find(j)
                    if ri == rj:
                        return False, "ring touches form a cycle"
                    parent[ri] = rj
                vi = next(p for p in poly[i] if p not in c)
                vj = next(p for p in poly[j] if p not in c)
                if i == 0:
                    if point_in(vj, E[0]) != 1:
                        return False, "hole not inside shell"
                elif point_in(vi, E[j]) != -1 or point_in(vj, E[i]) != -1:
                    return False, "nested holes"
    allE = [[e for r in poly for e in _qedges(r)] for poly in polys]
    for i in range(len(polys)):
        for j in range(i + 1, len(polys)):
            for ri in polys[i]:
                for rj in polys[j]:
                    if contact(_qedges(ri), _qedges(rj)) is None:
                        return False, "parts share a segment"
            both, _, _ = overlay_areas(allE[i], allE[j])
            if both != 0:
                return False, "parts overlap"
    return True, ""


def shapely_valid(mp):
    if shapely is None:
        return None
    polys = [Polygon(p[0], p[1:]) for p in mp]
    g = polys[0] if len(polys) == 1 else MultiPolygon(polys)
    return bool(g.is_valid)


def check_valid(mp):
    """(ok, reason) for a closed-ring MultiPolygon. A single ring is decided by the oracle's
    exact test alone; anything with holes or several parts needs the exact test here AND
    shapely.is_valid to agree that it is valid."""
    for poly in mp:
        for r in poly:
            for x, y in r:
                if not (math.isfinite(x) and math.isfinite(y)):
                    return False, "non-finite"
    if len(mp) == 1 and len(mp[0]) == 1:
        return (True, "") if oracle.valid_single_polygon(mp) else (False, "exact: ring not simple")
    ok, why = exact_valid(mp)
    sv = shapely_valid(mp)
    if not ok:
        return False, "exact: " + why + ("" if sv is not True else " (shapely says valid)")
    if sv is False:
        return False, "shapely invalid, exact valid"
    return True, ""


def n_edges(mp):
    return sum(len(r) for poly in mp for r in poly)


def finalize(rng, mp):
    """Random part order, random start vertex and orientation per ring; closes the rings."""
    out = []
    parts = list(mp)
    rng.shuffle(parts)
    for poly in parts:
        rings = []
        for k, r in enumerate(poly):
            r = [[float(x), float(y)] for x, y in r]
            # drop repeated consecutive points (e.g. from decimal rounding) and an explicit
            # closing point if a construction left one
            r = [p for k, p in enumerate(r) if k == 0 or p != r[k - 1]]
            while len(r) > 1 and r[0] == r[-1]:
                r = r[:-1]
            if len(r) < 3:
                raise Reject("ring collapsed")
            s = rng.randrange(len(r))
            r = r[s:] + r[:s]
            if rng.random() < 0.5:
                r = r[::-1]
            rings.append(r + [r[0]])
        holes = rings[1:]
        rng.shuffle(holes)
        out.append([rings[0]] + holes)
    return out


def rounding_floor(a, b):
    """Largest area change that rounding every output vertex to the nearest double can cause:
    ulp(max |coordinate|) * (perimeter A + perimeter B). Moving a vertex by d changes the
    area by at most d * |next - prev| / 2, the output perimeter is at most the sum of the
    input perimeters, and a rounded vertex moves by at most ulp * sqrt(2) / 2."""
    m = max(abs(v) for g in (a, b) for poly in g for r in poly for p in r for v in p)
    per = sum(math.hypot(q[0] - p[0], q[1] - p[1])
              for g in (a, b) for poly in g for r in poly for p, q in zip(r, r[1:]))
    return math.ulp(m) * per
