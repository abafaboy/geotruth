"""Case families. Each generator takes a random.Random and returns (variant, A, B), where A
and B are MultiPolygons with open rings (see common.py), or raises Reject. The driver
(run_all.py) randomises ring start/orientation, closes the rings, checks validity and
retries on rejection.

Families (one output file each):

  near-collinear  vertices a few ulps off an edge, edges bent by ulps, nearly collinear edges
  vertex-on-edge  vertices EXACTLY on another polygon's (sloped) edge, at dyadic/rational
                  parameters on an exact lattice (checked with rationals)
  shared-edge     fully / partially shared collinear edges (sloped, exact), shared polylines,
                  shared edges between arbitrary doubles, float-computed split points
  tiny-transform  the same polygon rotated / translated / scaled by 1 ulp .. 1e-9, at the
                  origin, at projected-map offsets (1e5..1e7) and lon/lat (1e-12 decimals)
  sliver-spike    spikes and cracks of tiny width, thin slivers along edges, nearly
                  coincident parallel edges, needles
  hole-contact    polygons with holes; the other operand fills, touches, shares an edge
                  with, or nearly touches the hole boundary
  multi-touch     multipolygons whose parts touch at a point (checkerboards, fans, T-touch,
                  island in a hole), with the other operand at or around the touch point
  tiling-contact  rotated unit squares / equilateral triangles from a float-computed tiling:
                  neighbours, same tile computed two ways, tiny gaps and overlaps
  int-grid        integer lattice families: polyominoes (holes, touching parts, collinear
                  vertices), rotated integer lattices, lattice polygons, lattice triangles
  scaled          a case from another family with all coordinates multiplied by
                  2^k (exact, k in -27..27) or 10^U(-8,8) (rounded)
"""
import math

from common import (  # noqa: F401
    Q, Reject, TAU, ExactFrame, FloatFrame, add, centroid, convex_ring, ccw, exact_frame,
    float_frame, iadd, icross, isub, left_normal, lerp, log_uniform, nudge, oracle,
    rand_convex_int, rand_star_int, rand_vec, rand_vec_side, rect_ring, rot_pt, rotate_ring,
    sgn, star_ring, sub, unit, verify_on_segment,
)


def P1(ring):
    """A MultiPolygon with one polygon without holes."""
    return [[ring]]


def maybe_swap(rng, a, b):
    return (b, a) if rng.random() < 0.5 else (a, b)


def small_k(rng, lo=-3, hi=3):
    return rng.randint(lo, hi)


def base_polygon(rng, fr, n=None):
    """A random convex or star ring (CCW) around the frame centre."""
    n = n or rng.randint(3, 8)
    if rng.random() < 0.6:
        r = convex_ring(rng, fr.c, fr.size, n)
    else:
        r = star_ring(rng, fr.c, fr.size, max(n, 4))
    return ccw(fr.fix_ring(r))


# ============================================================================ near-collinear

def gen_near_collinear(rng):
    fr = float_frame(rng)
    v = rng.choice(["offedge-out", "offedge-in", "bent-edge", "bent-both", "near-parallel",
                    "zigzag", "extension"])
    A = base_polygon(rng, fr)
    n = len(A)
    i = rng.randrange(n)
    P, R = A[i], A[(i + 1) % n]
    nout = [-x for x in left_normal(P, R)]  # A is CCW: interior on the left of P -> R
    s = fr.size

    def near(t):
        return fr.perturb_pt(lerp(P, R, t), small_k(rng), small_k(rng))

    def fan(apex, side, rlo, rhi, m=2):
        """m points around apex in the half plane on `side` (+1 outside A), by angle."""
        base = math.atan2(side * nout[1], side * nout[0])
        angs = sorted(base + rng.uniform(-1.4, 1.4) for _ in range(m))
        return [fr.fix(add(apex, [math.cos(a), math.sin(a)], s * rng.uniform(rlo, rhi))) for a in angs]

    def along(pts, ascending):
        """Points ordered by their projection on P -> R."""
        d = sub(R, P)
        return sorted(pts, key=lambda p: (p[0] - P[0]) * d[0] + (p[1] - P[1]) * d[1], reverse=not ascending)

    if v in ("offedge-out", "offedge-in"):
        V = near(rng.uniform(0.05, 0.95))
        side = 1 if v == "offedge-out" else -1
        rlo, rhi = (0.2, 1.0) if side == 1 else (0.05, 0.4)
        B = [V] + fan(V, side, rlo, rhi, rng.randint(2, 3))
        a, b = P1(A), P1(B)
    elif v in ("bent-edge", "bent-both"):
        M = near(rng.uniform(0.1, 0.9))
        A2 = A[:i + 1] + [M] + A[i + 1:]
        side = sgn(rng)  # B outside (touching) or inside (overlapping) A
        others = along(fan(lerp(P, R, 0.5), side, 0.3, 1.0, rng.randint(1, 2)), True)
        if v == "bent-both":
            B = [R, near(rng.uniform(0.1, 0.9)), P] + others
        else:
            B = [R, P] + others
        a, b = P1(A2), P1(B)
    elif v == "near-parallel":
        t0, t1 = rng.uniform(-0.4, 0.5), rng.uniform(0.5, 1.4)
        P2, R2 = near(t0), near(t1)
        side = sgn(rng)
        h = s * rng.uniform(0.1, 0.6)
        B = [P2, R2, fr.fix(add(R2, nout, side * h)), fr.fix(add(P2, nout, side * h))]
        a, b = P1(A), P1(B)
    elif v == "zigzag":
        m = rng.randint(2, 6)
        ts = sorted(rng.uniform(0.02, 0.98) for _ in range(m))
        chain = [near(t) for t in ts]
        side = sgn(rng)
        far = fan(lerp(P, R, 0.5), side, 0.3, 1.0, rng.randint(1, 2))
        # chain runs P -> R; close through the far points from the R end back to P
        B = chain + along(far, False)
        a, b = P1(A), P1(B)
    else:  # extension: B's edge continues A's edge beyond the vertex P
        P2 = fr.perturb_pt(P, small_k(rng, -2, 2), small_k(rng, -2, 2))
        E = near(-rng.uniform(0.2, 1.0))
        side = sgn(rng)
        B = [P2, E, fr.fix(add(lerp(P2, E, 0.5), nout, side * s * rng.uniform(0.2, 0.8)))]
        a, b = P1(A), P1(B)
    a, b = maybe_swap(rng, a, b)
    return f"{v}.{fr.kind}", a, b


# ============================================================================ vertex-on-edge

def lattice_polygon(rng, fr, n_par, k=None, star=False, R=None, c=None, ratio=0.4):
    """Lattice polygon whose edges carry lattice points at every parameter m/n_par.

    Returns (A, W): A[i] = c + n_par * W[i], and the point at t = m/n_par on edge i is
    A[i] + m * (W[i+1] - W[i])."""
    k = k or rng.randint(3, 7)
    R = R if R is not None else 2 ** (fr.S - 1)
    Rw = R // n_par
    if Rw < 4:
        raise Reject("lattice too coarse")
    W = rand_star_int(rng, max(k, 4), Rw) if star else rand_convex_int(rng, k, Rw, ratio=ratio)
    if c is None:
        c = (rng.randrange(n_par), rng.randrange(n_par))
    A = [(c[0] + n_par * x, c[1] + n_par * y) for x, y in W]
    return A, W


def on_edge(A, W, i, m):
    k = len(A)
    d = isub(W[(i + 1) % k], W[i])
    return iadd(A[i], d, m)


def edge_dir(W, i):
    return isub(W[(i + 1) % len(W)], W[i])


def check_on_edges(fa, pairs):
    """pairs: (float point, edge index into float ring fa)."""
    for p, i in pairs:
        verify_on_segment(p, fa[i], fa[(i + 1) % len(fa)])


def pick_n(rng, fr):
    if rng.random() < 0.7:
        return 2 ** rng.randint(1, min(10, fr.S - 5))  # dyadic parameter m / 2^j
    return rng.randint(3, 40)  # any rational parameter: still exact on the lattice


def gen_vertex_on_edge(rng):
    fr = exact_frame(rng)
    n = pick_n(rng, fr)
    v = rng.choice(["apex-out", "apex-in", "cross", "two-edges", "inscribed", "on-vertex",
                    "star-apex"])
    A, W = lattice_polygon(rng, fr, n, star=(v == "star-apex"))
    k = len(A)
    M = 2 ** (fr.S - 2)
    checks = []
    i = rng.randrange(k)
    m = rng.randint(1, n - 1)
    V = on_edge(A, W, i, m)
    D = edge_dir(W, i)
    if v in ("apex-out", "apex-in", "star-apex"):
        side = -1 if v != "apex-in" else 1
        span = M if side == -1 else M // 4
        r1 = rand_vec_side(rng, D, span, side, lo=span // 16)
        r2 = rand_vec_side(rng, D, span, side, lo=span // 16)
        B = [V, iadd(V, r1), iadd(V, r2)]
        checks.append((0, i))
    elif v == "cross":
        r1 = rand_vec_side(rng, D, M, -1, lo=M // 16)
        r2 = rand_vec_side(rng, D, M // 4, 1, lo=M // 64)
        B = [V, iadd(V, r1), iadd(V, r2)]
        if rng.random() < 0.5:
            B.insert(2, iadd(V, rand_vec(rng, M // 2)))
        checks.append((0, i))
    elif v == "two-edges":
        j = (i + rng.randint(1, k - 1)) % k
        V2 = on_edge(A, W, j, rng.randint(1, n - 1))
        X = iadd(V, rand_vec(rng, M))
        B = [V, V2, X]
        checks += [(0, i), (1, j)]
    elif v == "inscribed":
        idx = sorted(rng.sample(range(k), rng.randint(3, k))) if k > 3 else [0, 1, 2]
        B, checks = [], []
        for e in idx:
            if rng.random() < 0.25:
                B.append(A[e])  # share a vertex too
            else:
                B.append(on_edge(A, W, e, rng.randint(1, n - 1)))
                checks.append((len(B) - 1, e))
    else:  # on-vertex
        V = A[i]
        B = [V, iadd(V, rand_vec(rng, M)), iadd(V, rand_vec(rng, M))]
    fa, fb = fr.ring(A), fr.ring(B)
    check_on_edges(fa, [(fb[bi], ai) for bi, ai in checks])
    a, b = maybe_swap(rng, P1(fa), P1(fb))
    return f"{v}.n{n}.{fr.kind}", a, b


# ============================================================================ shared-edge

def gen_shared_edge(rng):
    v = rng.choice(["full-opp", "full-same", "sub-opp", "sub-same", "overhang-opp",
                    "overhang-same", "split", "chain", "chain-ulp", "float-full", "float-mid",
                    "float-sub"])
    if v.startswith("float"):
        return gen_shared_edge_float(rng, v)
    if v.startswith("chain"):
        return gen_shared_chain(rng, v)
    fr = exact_frame(rng)
    n = pick_n(rng, fr) if rng.random() < 0.7 else rng.randint(2, 8)
    M = 2 ** (fr.S - 2)
    Dm = max(1, M // n)
    if Dm < 2:
        raise Reject("lattice too coarse")
    D = rand_vec(rng, Dm, sloped=rng.random() < 0.85)
    Nl = (-D[1], D[0])
    P = rand_vec(rng, M // 2)
    Rq = iadd(P, D, n)

    def side_pt(side):
        a_ = rng.uniform(-0.5, n + 0.5)
        b_ = rng.uniform(0.2, 1.0) * n
        jit = rand_vec(rng, max(1, int(max(abs(D[0]), abs(D[1])) * n // 20)))
        p = (P[0] + round(a_ * D[0] + side * b_ * Nl[0]) + jit[0],
             P[1] + round(a_ * D[1] + side * b_ * Nl[1]) + jit[1])
        return p

    def body(side, cnt):
        pts = [side_pt(side) for _ in range(cnt)]
        # order the far points by their position along D so the ring closes simply
        pts.sort(key=lambda p: (p[0] - P[0]) * D[0] + (p[1] - P[1]) * D[1], reverse=(side == 1))
        return pts

    same = v.endswith("same")
    A = [P, Rq] + body(1, rng.randint(1, 3))
    bside = 1 if same else -1
    if v.startswith("full"):
        e0, e1 = 0, n
    elif v.startswith("sub"):
        e0, e1 = sorted(rng.sample(range(n + 1), 2))
        if (e0, e1) == (0, n):
            raise Reject("sub-edge is the full edge")
    elif v.startswith("overhang"):
        e0 = rng.randint(-n, n - 1)
        e1 = rng.randint(max(e0 + 1, 1), 2 * n)
        if e0 >= 0 and e1 <= n:
            e0 = -rng.randint(1, n)
    else:  # split: both have extra collinear vertices on the shared edge, different ones
        e0, e1 = 0, n
    B0, B1 = iadd(P, D, e0), iadd(P, D, e1)
    far = body(bside, rng.randint(1, 3))
    if bside == 1:
        B = [B0, B1] + far
    else:
        B = [B1, B0] + far
    if v == "split" and n >= 3:
        ma = sorted(rng.sample(range(1, n), rng.randint(1, min(3, n - 1))))
        mb = sorted(rng.sample(range(1, n), rng.randint(1, min(3, n - 1))))
        A = [P] + [iadd(P, D, x) for x in ma] + A[1:]
        mid = [iadd(P, D, x) for x in mb]
        B = [B1] + mid[::-1] + [B0] + far if bside == -1 else [B0] + mid + [B1] + far
    fa, fb = fr.ring(A), fr.ring(B)
    # exactness: every lattice point on the line P + tD is exactly on A's edge line
    for p in (fb[0], fb[1]):
        Pf, Rf = fr.pt(P), fr.pt(Rq)
        if oracle.orient((Q(Pf[0]), Q(Pf[1])), (Q(Rf[0]), Q(Rf[1])), (Q(p[0]), Q(p[1]))) != 0:
            raise Reject("shared edge not collinear")
    a, b = maybe_swap(rng, P1(fa), P1(fb))
    return f"{v}.n{n}.{fr.kind}", a, b


def gen_shared_chain(rng, v):
    """A convex lattice polygon cut in two by a lattice polyline; A and B share the polyline."""
    fr = exact_frame(rng)
    R = 2 ** (fr.S - 1)
    W = rand_convex_int(rng, rng.randint(4, 9), R)
    k = len(W)
    if k < 4:
        raise Reject("too few vertices")
    i = rng.randrange(k)
    j = (i + rng.randint(2, k - 2)) % k
    G = isub(W[j], W[i])
    L = max(abs(G[0]), abs(G[1]))
    cnt = rng.randint(1, 5)
    ts = sorted(rng.uniform(0.05, 0.95) for _ in range(cnt))
    wig = max(1, L // rng.choice([8, 30, 1000, 10 ** 6]))
    chain = []
    for t in ts:
        base = (W[i][0] + round(t * G[0]), W[i][1] + round(t * G[1]))
        chain.append(iadd(base, rand_vec(rng, wig)))
    arcA = [W[(i + s) % k] for s in range((j - i) % k + 1)]  # i .. j along the boundary
    arcB = [W[(j + s) % k] for s in range((i - j) % k + 1)]  # j .. i
    A = arcA + chain[::-1]
    B = arcB + chain
    fa, fb = fr.ring(A), fr.ring(B)
    if v == "chain-ulp":
        # B's copy of the chain moved by an ulp per coordinate: shared becomes nearly shared
        nb = len(arcB)
        for q in range(nb, len(fb)):
            fb[q] = [nudge(fb[q][0], small_k(rng, -1, 1)), nudge(fb[q][1], small_k(rng, -1, 1))]
    a, b = maybe_swap(rng, P1(fa), P1(fb))
    return f"{v}.{fr.kind}", a, b


def gen_shared_edge_float(rng, v):
    fr = float_frame(rng)
    s = fr.size
    P = fr.fix(add(fr.c, [rng.uniform(-1, 1), rng.uniform(-1, 1)], s))
    ang = rng.uniform(0, TAU)
    R = fr.fix(add(P, [math.cos(ang), math.sin(ang)], s * rng.uniform(0.5, 2)))
    nl = left_normal(P, R)

    def far(side, cnt):
        pts = []
        for _ in range(cnt):
            t = rng.uniform(-0.3, 1.3)
            pts.append(fr.fix(add(lerp(P, R, t), nl, side * s * rng.uniform(0.2, 1.0))))
        # order along P->R, then close
        d = sub(R, P)
        pts.sort(key=lambda p: (p[0] - P[0]) * d[0] + (p[1] - P[1]) * d[1], reverse=(side == 1))
        return pts

    A = [P, R] + far(1, rng.randint(1, 3))
    side = -1 if rng.random() < 0.75 else 1
    fb = far(side, rng.randint(1, 3))
    if v == "float-full":
        B = ([R, P] if side == -1 else [P, R]) + fb
    elif v == "float-mid":
        Mid = fr.fix(lerp(P, R, rng.choice([0.5, 1 / 3, rng.uniform(0.05, 0.95)])))
        B = ([R, Mid, P] if side == -1 else [P, Mid, R]) + fb
        if rng.random() < 0.3:  # A also carries a (differently computed) split point
            A = [P, fr.fix(lerp(P, R, rng.uniform(0.05, 0.95)))] + A[1:]
    else:  # float-sub: B's edge is a float-computed sub-segment of A's edge
        t0, t1 = sorted((rng.uniform(-0.2, 1.2), rng.uniform(-0.2, 1.2)))
        if t1 - t0 < 0.05:
            raise Reject("short")
        E0, E1 = fr.fix(lerp(P, R, t0)), fr.fix(lerp(P, R, t1))
        B = ([E1, E0] if side == -1 else [E0, E1]) + fb
    a, b = maybe_swap(rng, P1(A), P1(B))
    return f"{v}.{fr.kind}", a, b


# ============================================================================ tiny-transform

def gen_tiny_transform(rng):
    fr = float_frame(rng, kinds=("origin", "projected", "lonlat", "origin", "projected",
                                 "lonlat", "moderate"))
    shape = rng.choice(["star", "convex", "rect", "rotrect", "parcel"])
    s = fr.size
    if shape == "star":
        A = star_ring(rng, fr.c, s, rng.randint(4, 12))
    elif shape == "convex":
        A = convex_ring(rng, fr.c, s, rng.randint(3, 9))
    elif shape == "rect":
        A = rect_ring(fr.c, s * rng.uniform(0.3, 2), s * rng.uniform(0.3, 2))
    elif shape == "rotrect":
        A = rect_ring(fr.c, s * rng.uniform(0.3, 2), s * rng.uniform(0.3, 2), rng.uniform(0, TAU))
    else:  # a parcel-like quadrilateral with one nearly straight vertex
        A = convex_ring(rng, fr.c, s, 4)
        A.insert(2, lerp(A[1], A[2], rng.uniform(0.2, 0.8)))
    A = fr.fix_ring(A)
    v = rng.choice(["rot-vertex", "rot-centroid", "rot-far", "shift-ulp", "shift-abs", "scale",
                    "same", "rot-shift"])
    # every transform moves the farthest vertex by `disp`: 1 ulp .. 1e-9 of the coordinate
    # magnitude (at least 1e-12 in the lon/lat frame, whose coordinates have 12 decimals)
    disp = fr.tiny(rng, -15.6, -9)

    def rotated(pivot):
        rad = max(math.hypot(p[0] - pivot[0], p[1] - pivot[1]) for p in A)
        return rotate_ring(A, pivot, sgn(rng) * disp / rad)

    if v == "rot-vertex":
        B = rotated(rng.choice(A))
    elif v == "rot-centroid":
        B = rotated(centroid(A))
    elif v == "rot-far":
        ang = rng.uniform(0, TAU)
        B = rotated(add(fr.c, [math.cos(ang), math.sin(ang)], 10 * s))
    elif v == "shift-ulp":
        kx, ky = small_k(rng), small_k(rng)
        if (kx, ky) == (0, 0):
            kx = 1
        B = [fr.perturb_pt(p, kx, ky) for p in A]
    elif v == "shift-abs":
        ang = rng.uniform(0, TAU)
        B = [add(p, [math.cos(ang), math.sin(ang)], disp) for p in A]
    elif v == "scale":
        c = centroid(A)
        rad = max(math.hypot(p[0] - c[0], p[1] - c[1]) for p in A)
        f = 1 + sgn(rng) * disp / rad
        B = [[c[0] + f * (p[0] - c[0]), c[1] + f * (p[1] - c[1])] for p in A]
    elif v == "same":
        B = [list(p) for p in A]
    else:
        B = rotated(rng.choice(A))
        ang = rng.uniform(0, TAU)
        B = [add(p, [math.cos(ang), math.sin(ang)], fr.tiny(rng, -15.6, -9)) for p in B]
    B = fr.fix_ring(B)
    a, b = maybe_swap(rng, P1(A), P1(B))
    return f"{v}.{shape}.{fr.kind}", a, b


# ============================================================================ sliver-spike

def gen_sliver_spike(rng):
    fr = float_frame(rng)
    v = rng.choice(["spike-out", "spike-in", "sliver-in", "sliver-out", "sliver-straddle",
                    "parallel-gap", "parallel-overlap", "needle-cross", "sliver-pair"])
    s = fr.size
    A = ccw(fr.fix_ring(convex_ring(rng, fr.c, s, rng.randint(3, 7))))
    n = len(A)
    i = rng.randrange(n)
    P, R = A[i], A[(i + 1) % n]
    nout = [-x for x in left_normal(P, R)]
    d = unit(sub(R, P))

    def width():
        """Spike / sliver width: a few ulps, or 1 ulp .. 1e-8 of the coordinate magnitude."""
        if rng.random() < 0.4:
            return None  # ulp-level: handled by the caller
        return fr.tiny(rng, -15.6, -8)

    if v in ("spike-out", "spike-in"):
        t = rng.uniform(0.2, 0.8)
        E1 = fr.fix(lerp(P, R, t))
        w = width()
        if w is None:
            E2 = fr.perturb_pt(E1, sgn(rng) * rng.randint(1, 4) if d[0] != 0 else 0,
                               sgn(rng) * rng.randint(1, 4) if d[1] != 0 else 0)
            # keep E2 after E1 along P -> R
            if (E2[0] - E1[0]) * d[0] + (E2[1] - E1[1]) * d[1] < 0:
                E1, E2 = E2, E1
        else:
            E2 = fr.fix(lerp(P, R, t + w / math.hypot(R[0] - P[0], R[1] - P[1])))
        L = s * (rng.uniform(0.3, 1.5) if v == "spike-out" else rng.uniform(0.05, 0.5))
        S = fr.fix(add(lerp(E1, E2, 0.5), nout, L if v == "spike-out" else -L))
        A2 = A[:i + 1] + [E1, S, E2] + A[i + 1:]
        kind = rng.choice(["cross", "tip", "tip-vertex", "cover", "beside"])
        mid = lerp(lerp(E1, E2, 0.5), S, rng.uniform(0.2, 0.8))
        h = s * rng.uniform(0.02, 0.3)
        if kind == "cross":  # a box straddling the spike across its length
            B = rect_ring(mid, h, s * rng.uniform(0.1, 0.5), math.atan2(nout[1], nout[0]))
        elif kind == "tip":
            B = rect_ring(S, h, h, rng.uniform(0, TAU))
        elif kind == "tip-vertex":  # B has a vertex exactly at the spike tip
            ang = math.atan2(nout[1], nout[0]) * (1 if v == "spike-out" else -1)
            B = [S, add(S, [math.cos(ang + 0.5), math.sin(ang + 0.5)], h),
                 add(S, [math.cos(ang - 0.5), math.sin(ang - 0.5)], h)]
        elif kind == "cover":
            B = rect_ring(lerp(E1, S, 0.5), L * 1.5, L * 1.5, rng.uniform(0, TAU))
        else:  # beside: box touching the spike's side region only near-ly
            B = rect_ring(add(mid, d, h / 2 + s * log_uniform(rng, -15, -9)), h, h,
                          math.atan2(d[1], d[0]))
        a, b = P1(A2), P1(fr.fix_ring(B))
    elif v in ("sliver-in", "sliver-out", "sliver-straddle"):
        t0, t1 = sorted((rng.uniform(-0.2, 1.2), rng.uniform(-0.2, 1.2)))
        if t1 - t0 < 0.05:
            raise Reject("short")
        P2, R2 = fr.fix(lerp(P, R, t0)), fr.fix(lerp(P, R, t1))
        w = width()
        if w is None:
            w = fr.tiny(rng, -16, -15)
        off = {"sliver-in": 0.0, "sliver-out": w, "sliver-straddle": w / 2}[v]
        base0, base1 = add(P2, nout, off), add(R2, nout, off)
        B = [base0, base1, add(base1, nout, -w), add(base0, nout, -w)]
        a, b = P1(A), P1(fr.fix_ring(B))
    elif v.startswith("parallel"):
        t0, t1 = sorted((rng.uniform(-0.5, 1.0), rng.uniform(0.0, 1.5)))
        if t1 - t0 < 0.05:
            raise Reject("short")
        dlt = fr.tiny(rng)
        if v == "parallel-overlap":
            dlt = -dlt
        P2 = fr.fix(add(lerp(P, R, t0), nout, dlt))
        R2 = fr.fix(add(lerp(P, R, t1), nout, dlt))
        h = s * rng.uniform(0.1, 0.8)
        B = [R2, P2, fr.fix(add(P2, nout, h)), fr.fix(add(R2, nout, h))]
        a, b = P1(A), P1(B)
    elif v == "needle-cross":
        L = s * rng.uniform(0.5, 2)
        ang = rng.uniform(0, TAU)
        dd = [math.cos(ang), math.sin(ang)]
        nn = [-dd[1], dd[0]]
        w = fr.tiny(rng, -15.6, -7)
        base = fr.c
        N = [fr.fix(add(base, nn, -w / 2)), fr.fix(add(base, nn, w / 2)), fr.fix(add(base, dd, L))]
        cross_ang = ang + math.pi / 2 + rng.uniform(-1.2, 1.2)
        B = rect_ring(add(base, dd, L * rng.uniform(0.05, 0.95)), s * rng.uniform(0.05, 0.5),
                      s * rng.uniform(0.2, 1), cross_ang)
        a, b = P1(N), P1(fr.fix_ring(B))
    else:  # sliver-pair: two thin triangles crossing at a shallow angle
        L = s * rng.uniform(0.5, 2)
        ang = rng.uniform(0, TAU)
        tris = []
        for k in range(2):
            a2 = ang + (k * sgn(rng) * log_uniform(rng, -12, -5))
            dd = [math.cos(a2), math.sin(a2)]
            nn = [-dd[1], dd[0]]
            w = fr.tiny(rng, -15, -7)
            base = add(fr.c, dd, -L * rng.uniform(0.3, 0.7))
            tris.append(fr.fix_ring([add(base, nn, -w), add(add(base, dd, L), nn, rng.uniform(-w, w)),
                                     add(base, nn, w)]))
        a, b = P1(tris[0]), P1(tris[1])
    a, b = maybe_swap(rng, a, b)
    return f"{v}.{fr.kind}", a, b


# ============================================================================ hole-contact

def gen_hole_contact(rng):
    fr = exact_frame(rng)
    n = pick_n(rng, fr) if rng.random() < 0.6 else rng.randint(2, 6)
    v = rng.choice(["fill", "fill-ulp-in", "fill-ulp-out", "fill-scaled", "touch-in",
                    "touch-solid", "share-in", "share-solid", "cross-near", "cover-hole-edge",
                    "hole-touch-shell", "two-holes-touch", "both-holed"])
    R = 2 ** (fr.S - 1)
    shell, Ws = lattice_polygon(rng, fr, n, k=rng.randint(5, 9), R=R, ratio=0.85)
    sc = (sum(p[0] for p in shell) // len(shell), sum(p[1] for p in shell) // len(shell))
    rh = int(R * rng.uniform(0.1, 0.25))
    ang = rng.uniform(0, TAU)
    off = rng.uniform(0, 0.25) * R
    hc = (sc[0] + round(off * math.cos(ang)), sc[1] + round(off * math.sin(ang)))
    hole, Wh = lattice_polygon(rng, fr, n, k=rng.randint(3, 6), R=rh, c=hc)
    kh = len(hole)
    holes = [hole]
    if v not in ("hole-touch-shell", "two-holes-touch") and rng.random() < 0.3:
        # an unrelated second hole on the far side
        h2c = (sc[0] - round(0.4 * R * math.cos(ang)), sc[1] - round(0.4 * R * math.sin(ang)))
        h2 = rand_convex_int(rng, rng.randint(3, 5), max(4, rh // 3), h2c)
        holes.append(h2)
    M = rh
    checks = []  # (B ring index, hole ring, edge index)
    fl = None  # float B built directly
    i = rng.randrange(kh)
    D = edge_dir(Wh, i)
    if v == "fill":
        B = list(hole)
    elif v in ("fill-ulp-in", "fill-ulp-out", "fill-scaled"):
        fh = fr.ring(hole)
        c = centroid(fh)
        sign_ = -1 if v == "fill-ulp-in" else 1
        if v == "fill-scaled":
            # farthest vertex moves by 1 ulp .. 1e-9 of the coordinate magnitude
            mag = max(abs(x) for p in fh for x in p)
            rad = max(math.hypot(p[0] - c[0], p[1] - c[1]) for p in fh)
            f = 1 + sgn(rng) * mag * log_uniform(rng, -15.6, -9) / rad
            fl = [[c[0] + f * (p[0] - c[0]), c[1] + f * (p[1] - c[1])] for p in fh]
        else:
            k_ = rng.randint(1, 3)
            fl = [[nudge(p[0], sign_ * k_ * (1 if p[0] > c[0] else -1)),
                   nudge(p[1], sign_ * k_ * (1 if p[1] > c[1] else -1))] for p in fh]
        B = None
    elif v in ("touch-in", "touch-solid"):
        V = on_edge(hole, Wh, i, rng.randint(1, n - 1))
        side = 1 if v == "touch-in" else -1  # hole is CCW: its inside is on the left
        span = M // 2 if side == 1 else M
        B = [V, iadd(V, rand_vec_side(rng, D, span, side, lo=span // 8)),
             iadd(V, rand_vec_side(rng, D, span, side, lo=span // 8))]
        checks.append((0, i))
    elif v in ("share-in", "share-solid"):
        m0 = rng.randint(0, n - 1)
        m1 = rng.randint(m0 + 1, n)
        E0, E1 = on_edge(hole, Wh, i, m0), on_edge(hole, Wh, i, m1)
        side = 1 if v == "share-in" else -1
        span = M // 2 if side == 1 else M
        X = iadd(lerp_int(E0, E1, 0.5), rand_vec_side(rng, D, span, side, lo=span // 8))
        B = [E0, E1, X] if side == 1 else [E1, E0, X]
        checks += [(0, i), (1, i)]
    elif v == "cross-near":
        fh = fr.ring(hole)
        P, R2 = fh[i], fh[(i + 1) % kh]
        V = lerp(P, R2, rng.uniform(0.0, 1.0)) if rng.random() < 0.7 else list(P)
        V = [nudge(V[0], small_k(rng)), nudge(V[1], small_k(rng))]
        big = [fr.pt(iadd(hc, rand_vec(rng, 2 * rh))) for _ in range(2)]
        fl = [V] + big
        B = None
    elif v == "cover-hole-edge":
        # B shares a whole hole edge and covers part of the hole and part of the solid
        E0, E1 = hole[i], hole[(i + 1) % kh]
        side = sgn(rng)  # +1: into the hole (and through it into the solid), -1: solid side
        X = iadd(E1, rand_vec_side(rng, D, 2 * rh, side, lo=rh // 4))
        Y = iadd(E0, rand_vec_side(rng, D, 2 * rh, side, lo=rh // 4))
        B = [E0, E1, X, Y]
    elif v == "hole-touch-shell":
        j = rng.randrange(len(shell))
        T = on_edge(shell, Ws, j, rng.randint(1, n - 1))
        Dj = edge_dir(Ws, j)
        span = max(8, R // 4)
        h = [T, iadd(T, rand_vec_side(rng, Dj, span, 1, lo=span // 8)),
             iadd(T, rand_vec_side(rng, Dj, span, 1, lo=span // 8))]
        holes = [h]
        kind = rng.choice(["apex", "box", "fill"])
        if kind == "apex":
            B = [T, iadd(T, rand_vec(rng, span)), iadd(T, rand_vec(rng, span))]
        elif kind == "fill":
            B = list(h)
        else:
            q = max(2, span // rng.choice([2, 8, 64]))
            B = [iadd(T, (-q, -q)), iadd(T, (q, -q)), iadd(T, (q, q)), iadd(T, (-q, q))]
        v = f"{v}-{kind}"
    elif v == "two-holes-touch":
        T = on_edge(hole, Wh, i, rng.randint(1, n - 1)) if rng.random() < 0.6 else hole[i]
        span = max(8, rh // 2)
        h2 = [T, iadd(T, rand_vec_side(rng, D, span, -1, lo=span // 8)),
              iadd(T, rand_vec_side(rng, D, span, -1, lo=span // 8))]
        holes = [hole, h2]
        kind = rng.choice(["apex", "box"])
        if kind == "apex":
            B = [T, iadd(T, rand_vec(rng, span)), iadd(T, rand_vec(rng, span))]
        else:
            q = max(2, span // rng.choice([2, 8, 64]))
            B = [iadd(T, (-q, -q)), iadd(T, (q, -q)), iadd(T, (q, q)), iadd(T, (-q, q))]
        v = f"{v}-{kind}"
    else:  # both-holed: B has its own shell but the same hole (or a hole sharing an edge)
        bs = rand_convex_int(rng, rng.randint(5, 8), R, sc, ratio=0.85)
        bh = list(hole) if rng.random() < 0.5 else [hole[i], hole[(i + 1) % kh], iadd(hc, rand_vec(rng, rh // 2))]
        B = None
        fa = [fr.ring(shell)] + [fr.ring(h) for h in holes]
        fb = [fr.ring(bs), fr.ring(bh)]
        a, b = maybe_swap(rng, [fa], [fb])
        return f"{v}.n{n}.{fr.kind}", a, b
    fa = [fr.ring(shell)] + [fr.ring(h) for h in holes]
    fb = fl if fl is not None else fr.ring(B)
    fho = fr.ring(hole)
    for bi, ei in checks:
        verify_on_segment(fb[bi], fho[ei], fho[(ei + 1) % kh])
    a, b = maybe_swap(rng, [fa], P1(fb))
    return f"{v}.n{n}.{fr.kind}", a, b


def lerp_int(p, q, t):
    return (p[0] + round(t * (q[0] - p[0])), p[1] + round(t * (q[1] - p[1])))


# ============================================================================ multi-touch

def rotate_mp(mp, c, th):
    return [[rotate_ring(r, c, th) for r in poly] for poly in mp]


def gen_multi_touch(rng):
    fr = exact_frame(rng)
    v = rng.choice(["checker", "fan", "t-touch", "island", "chain"])
    M = 2 ** (fr.S - 2)
    T = None  # a touch point (lattice)
    if v in ("checker", "chain"):
        a_ = rng.randint(1, max(1, M // 4))
        b_ = rng.randint(0, max(0, M // 4)) if rng.random() < 0.8 else 0
        if rng.random() < 0.5:
            a_, b_ = 2 * (a_ // 2) or 2, 2 * (b_ // 2)  # even, so half-cells are lattice points
        u, w = (a_, b_), (-b_, a_)
        O = rand_vec(rng, M // 2)

        def cell(i, j):
            p = iadd(iadd(O, u, i), w, j)
            return [p, iadd(p, u), iadd(iadd(p, u), w), iadd(p, w)]

        g = rng.randint(2, 3)
        if v == "checker":
            black = [(i, j) for i in range(g) for j in range(g) if (i + j) % 2 == 0]
            white = [(i, j) for i in range(g) for j in range(g) if (i + j) % 2 == 1]
            if len(black) > 2 and rng.random() < 0.5:
                black = rng.sample(black, rng.randint(2, len(black)))
            T = iadd(iadd(O, u), w)  # the corner shared by cells (0,0) and (1,1)
        else:
            black = [(k, k) for k in range(g + 1)]
            white = [(k + 1, k) for k in range(g)]
            T = iadd(iadd(O, u), w)
        A = [[cell(i, j)] for i, j in black]
        kind = rng.choice(["white", "whites", "center", "diag", "part", "apex"])
        if kind == "white":
            B = [[cell(*rng.choice(white))]]
        elif kind == "whites":
            B = [[cell(i, j)] for i, j in white]
        elif kind == "center":  # a cell-sized square centred on the touch point
            hu, hw = (u[0] // 2, u[1] // 2), (w[0] // 2, w[1] // 2)
            if (2 * hu[0], 2 * hu[1]) != u:
                hu, hw = u, w
            p = isub(isub(T, hu), hw)
            B = [[[p, iadd(p, hu, 2), iadd(iadd(p, hu, 2), hw, 2), iadd(p, hw, 2)]]]
        elif kind == "diag":  # a band through the touch point along the white diagonal
            q = rand_vec(rng, max(1, (abs(a_) + abs(b_)) // 8))
            d1, d2 = iadd(isub(T, u), w), iadd(isub(T, w), u)  # far corners of the white cells
            B = [[[iadd(d1, q), iadd(d2, q), isub(d2, q), isub(d1, q)]]]
        elif kind == "part":
            B = [list(A[rng.randrange(len(A))])]
        else:
            B = [[[T, iadd(T, rand_vec(rng, M // 4)), iadd(T, rand_vec(rng, M // 4))]]]
        v = f"{v}-{kind}"
    elif v == "fan":
        C = rand_vec(rng, M // 2)
        k = rng.randint(2, 4)
        angs = sorted(rng.uniform(0, TAU) for _ in range(2 * k))
        dirs = [(round(M * math.cos(t) * rng.uniform(0.3, 1)), round(M * math.sin(t) * rng.uniform(0.3, 1)))
                for t in angs]
        A, gaps = [], []
        for q in range(k):
            d0, d1 = dirs[2 * q], dirs[2 * q + 1]
            if d0[0] * d1[1] - d0[1] * d1[0] <= 0:
                raise Reject("fan sector >= 180")
            A.append([[C, iadd(C, d0), iadd(C, d1)]])
            gaps.append((d1, dirs[(2 * q + 2) % (2 * k)]))
        kind = rng.choice(["gap", "gap-shared", "box", "part", "through"])
        if kind in ("gap", "gap-shared"):
            g0, g1 = rng.choice(gaps)
            if kind == "gap":
                g0 = (g0[0] + g1[0], g0[1] + g1[1])
            if g0[0] * g1[1] - g0[1] * g1[0] <= 0:
                raise Reject("gap sector >= 180")
            B = [[[C, iadd(C, g0), iadd(C, g1)]]]
        elif kind == "box":
            q = max(1, M // rng.choice([4, 64, 2 ** 20]))
            B = [[[iadd(C, (-q, -q)), iadd(C, (q, -q)), iadd(C, (q, q)), iadd(C, (-q, q))]]]
        elif kind == "part":
            B = [list(A[rng.randrange(k)])]
        else:
            d = rand_vec(rng, M)
            q = rand_vec(rng, max(1, M // 16))
            B = [[[iadd(isub(C, d), q), iadd(iadd(C, d), q), isub(iadd(C, d), q), isub(isub(C, d), q)]]]
        T = C
        v = f"{v}{k}-{kind}"
    elif v == "t-touch":
        n = pick_n(rng, fr)
        P1_, W1 = lattice_polygon(rng, fr, n, R=M)
        i = rng.randrange(len(P1_))
        T = on_edge(P1_, W1, i, rng.randint(1, n - 1))
        D = edge_dir(W1, i)
        p2 = [T, iadd(T, rand_vec_side(rng, D, M, -1, lo=M // 8)),
              iadd(T, rand_vec_side(rng, D, M, -1, lo=M // 8))]
        A = [[P1_], [p2]]
        kind = rng.choice(["box", "apex", "part", "bridge"])
        if kind == "box":
            q = max(1, M // rng.choice([4, 64, 2 ** 20]))
            B = [[[iadd(T, (-q, -q)), iadd(T, (q, -q)), iadd(T, (q, q)), iadd(T, (-q, q))]]]
        elif kind == "apex":
            B = [[[T, iadd(T, rand_vec(rng, M)), iadd(T, rand_vec(rng, M))]]]
        elif kind == "part":
            B = [[list(p2)]] if rng.random() < 0.5 else [[list(P1_)]]
        else:  # a triangle with one vertex in each part
            B = [[[iadd(T, rand_vec_side(rng, D, M // 2, 1, lo=M // 16)),
                   iadd(T, rand_vec_side(rng, D, M // 2, -1, lo=M // 16)),
                   iadd(T, rand_vec(rng, M))]]]
        v = f"{v}-{kind}"
    else:  # island: part 2 inside part 1's hole, touching the hole boundary at one point
        n = pick_n(rng, fr)
        R = 2 * M
        shell = rand_convex_int(rng, rng.randint(4, 8), R, ratio=0.85)
        sc = (sum(p[0] for p in shell) // len(shell), sum(p[1] for p in shell) // len(shell))
        hole, Wh = lattice_polygon(rng, fr, n, k=rng.randint(3, 6), R=R // 3, c=sc, ratio=0.7)
        i = rng.randrange(len(hole))
        T = on_edge(hole, Wh, i, rng.randint(1, n - 1)) if rng.random() < 0.7 else hole[i]
        D = edge_dir(Wh, i)
        span = R // 30
        isl = [T, iadd(T, rand_vec_side(rng, D, span, 1, lo=span // 8)),
               iadd(T, rand_vec_side(rng, D, span, 1, lo=span // 8))]
        A = [[shell, hole], [isl]]
        kind = rng.choice(["box", "hole", "apex", "island"])
        if kind == "box":
            q = max(1, span // rng.choice([2, 64, 2 ** 20]))
            B = [[[iadd(T, (-q, -q)), iadd(T, (q, -q)), iadd(T, (q, q)), iadd(T, (-q, q))]]]
        elif kind == "hole":
            B = [[list(hole)]]
        elif kind == "apex":
            B = [[[T, iadd(T, rand_vec(rng, span)), iadd(T, rand_vec(rng, span))]]]
        else:
            B = [[list(isl)]]
        v = f"{v}-{kind}"
    fa = [[fr.ring(r) for r in poly] for poly in A]
    fb = [[fr.ring(r) for r in poly] for poly in B]
    if rng.random() < 0.2:
        # rotate the whole configuration in floating point: exact touches become near
        th = rng.uniform(0, TAU)
        c = fr.pt(T) if T is not None else fa[0][0][0]
        fa, fb = rotate_mp(fa, c, th), rotate_mp(fb, c, th)
        v += "-rot"
    a, b = maybe_swap(rng, fa, fb)
    return f"{v}.{fr.kind}", a, b


# ============================================================================ tiling-contact

def gen_tiling_contact(rng):
    """Tiles of a rotated square or equilateral-triangle tiling, each tile computed in floating
    point by one of three formulas (so shared edges agree only up to rounding)."""
    fr = float_frame(rng, kinds=("origin", "origin", "origin", "moderate", "projected", "lonlat"))
    s = 1.0 if fr.kind in ("origin", "moderate", "projected") else fr.size
    if rng.random() < 0.2:
        th = rng.choice([0.0, math.pi / 4, math.pi / 6, math.pi / 3, math.pi / 2, math.pi])
    else:
        th = rng.uniform(0, TAU)
    O = list(fr.c)
    shape = rng.choice(["sq", "tri"])
    v = rng.choice(["edge", "edge", "corner", "same", "gap", "overlap", "multi", "strip"])
    if v == "strip":
        shape = "sq"
    methods = ["direct", "center", "accum"]
    mA, mB = rng.choice(methods), rng.choice(methods)
    u = [s * math.cos(th), s * math.sin(th)]
    if shape == "sq":
        w = [-s * math.sin(th), s * math.cos(th)]
    else:
        w = [s * math.cos(th + math.pi / 3), s * math.sin(th + math.pi / 3)]

    def corner(i, j):
        return [O[0] + i * u[0] + j * w[0], O[1] + i * u[1] + j * w[1]]

    if shape == "sq":
        def tile(i, j, meth):
            if meth == "direct":
                return [corner(i, j), corner(i + 1, j), corner(i + 1, j + 1), corner(i, j + 1)]
            if meth == "center":
                c = corner(i + 0.5, j + 0.5)
                return [[c[0] + sx * u[0] / 2 + sy * w[0] / 2, c[1] + sx * u[1] / 2 + sy * w[1] / 2]
                        for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
            p = corner(i, j)
            q = add(p, u)
            return [p, q, add(q, w), add(p, w)]

        def neighbours(i, kind):
            return [(1, 0), (0, 1), (-1, 0), (0, -1)] if kind == "edge" else [(1, 1), (1, -1), (-1, 1), (-1, -1)]
    else:
        # triangle (i, j): i = 2*ii + k, k = 0 up triangle, k = 1 down triangle
        def tile(i, j, meth):
            ii, k = divmod(i, 2)
            idx = [(ii, j), (ii + 1, j), (ii, j + 1)] if k == 0 else [(ii + 1, j), (ii + 1, j + 1), (ii, j + 1)]
            if meth == "direct":
                return [corner(*p) for p in idx]
            if meth == "center":
                c = corner(ii + (1 + k) / 3, j + (1 + k) / 3)
                base = th - (math.pi / 6 if k == 0 else math.pi / 2)
                r = s / math.sqrt(3)
                return [[c[0] + r * math.cos(base + q * TAU / 3), c[1] + r * math.sin(base + q * TAU / 3)]
                        for q in range(3)]
            if k == 0:
                p0 = corner(ii, j)
                return [p0, add(p0, u), add(p0, w)]
            q0, q2, p0 = corner(ii + 1, j), corner(ii, j + 1), corner(ii, j)
            # rhombus completion: reflect the up triangle's apex across the shared edge
            return [q0, [q0[0] + q2[0] - p0[0], q0[1] + q2[1] - p0[1]], q2]

        def neighbours(i, kind):
            if kind == "edge":
                return [(1, 0), (-1, 0), (1, -1)] if i % 2 == 0 else [(-1, 0), (1, 0), (-1, 1)]
            return [(2, 0), (-2, 0), (0, 1), (0, -1), (2, -1), (-2, 1)]

    i0, j0 = rng.randint(-6, 6), rng.randint(-3, 3)
    A = tile(i0, j0, mA)

    def nb(kind):
        di, dj = rng.choice(neighbours(i0, kind))
        return i0 + di, j0 + dj

    if v in ("edge", "gap", "overlap"):
        B = tile(*nb("edge"), mB)
        if v != "edge":
            nrm = unit(sub(centroid(B), centroid(A)))
            if rng.random() < 0.5:
                k = rng.randint(1, 4) * (1 if v == "gap" else -1)
                B = [[nudge(p[0], k if nrm[0] > 0 else -k), nudge(p[1], k if nrm[1] > 0 else -k)] for p in B]
            else:
                dlt = fr.tiny(rng) * (1 if v == "gap" else -1)
                B = [add(p, nrm, dlt) for p in B]
        a, b = P1(fr.fix_ring(A)), P1(fr.fix_ring(B))
    elif v == "corner":
        a, b = P1(fr.fix_ring(A)), P1(fr.fix_ring(tile(*nb("corner"), mB)))
    elif v == "same":
        if mA == mB:
            mB = rng.choice([m for m in methods if m != mA])
        a, b = P1(fr.fix_ring(A)), P1(fr.fix_ring(tile(i0, j0, mB)))
    elif v == "multi":
        # A: tiles that meet only at corners; B: a tile sharing edges with them
        if shape == "sq":
            cells = [(i0, j0), (i0 + 1, j0 + 1)] + ([(i0 + 2, j0)] if rng.random() < 0.5 else [])
            cand = [(i0 + 1, j0), (i0, j0 + 1), (i0 + 1, j0 - 1)]
        else:
            cells = [(i0, j0), (i0 + 2, j0)] + ([(i0, j0 + 1)] if rng.random() < 0.5 else [])
            cand = [(i0 + 1, j0), (i0 - 1, j0), (i0 + 1, j0 - 1)]
        a = [[fr.fix_ring(tile(i, j, mA))] for i, j in cells]
        b = P1(fr.fix_ring(tile(*rng.choice(cand), mB)))
    else:  # strip: A is one polygon covering L squares (all tile corners kept as vertices)
        L = rng.randint(2, 4)
        bottom = [corner(i0 + k, j0) for k in range(L + 1)]
        top = [corner(i0 + k, j0 + 1) for k in range(L, -1, -1)]
        a = P1(fr.fix_ring(bottom + top))
        b = P1(fr.fix_ring(tile(i0 + rng.randrange(L), j0 - 1, mB)))
    a, b = maybe_swap(rng, a, b)
    return f"{shape}-{v}.{mA}-{mB}.{fr.kind}", a, b


# ============================================================================ int-grid

def trace_cells(cells, merge=False):
    """Boundary of a union of unit cells as a MultiPolygon of integer rings (open).

    Directed boundary edges keep the interior on the left; at a vertex where two cells touch
    diagonally the leftmost turn is taken, so rings never touch themselves (parts and holes
    that touch at a point become separate rings)."""
    es = set()
    for x, y in cells:
        pts = [(x, y), (x + 1, y), (x + 1, y + 1), (x, y + 1)]
        for p, q in zip(pts, pts[1:] + pts[:1]):
            if (q, p) in es:
                es.remove((q, p))
            else:
                es.add((p, q))
    out = {}
    for p, q in es:
        out.setdefault(p, []).append(q)
    used = set()
    rings = []
    for e0 in sorted(es):
        if e0 in used:
            continue
        ring, e = [], e0
        while e not in used:
            used.add(e)
            ring.append(e[0])
            p, q = e
            d = (q[0] - p[0], q[1] - p[1])

            def rank(r, q=q, d=d):
                dd = (r[0] - q[0], r[1] - q[1])
                c = d[0] * dd[1] - d[1] * dd[0]
                return 0 if c > 0 else (1 if c == 0 else 2)
            e = (q, min(out[q], key=rank))
        if merge:
            k = len(ring)
            ring = [ring[t] for t in range(k)
                    if icross(ring[t - 1], ring[t], ring[(t + 1) % k]) != 0]
        rings.append(ring)

    def area2(r):
        return sum(r[t][0] * r[(t + 1) % len(r)][1] - r[(t + 1) % len(r)][0] * r[t][1] for t in range(len(r)))

    shells = [r for r in rings if area2(r) > 0]
    holes = [r for r in rings if area2(r) < 0]
    polys = [[s] for s in shells]
    for h in holes:
        p, q = h[0], h[1]
        # centre of the filled cell to the left of the hole's first edge, doubled coordinates
        d = (q[0] - p[0], q[1] - p[1])
        cx, cy = p[0] + q[0] - d[1], p[1] + q[1] + d[0]
        pt = (Q(cx, 2), Q(cy, 2))
        best = None
        for k, s in enumerate(shells):
            e = [((Q(a[0]), Q(a[1])), (Q(b[0]), Q(b[1]))) for a, b in zip(s, s[1:] + s[:1])]
            if oracle.point_in(pt, e) == 1 and (best is None or area2(s) < area2(shells[best])):
                best = k
        if best is None:
            raise Reject("orphan hole")
        polys[best].append(h)
    return polys


def grow_cells(rng, g, ncells, start=None):
    cells = {start or (rng.randrange(g), rng.randrange(g))}
    tries = 0
    while len(cells) < ncells and tries < 50 * ncells:
        tries += 1
        c = rng.choice(sorted(cells))
        dx, dy = rng.choice(((1, 0), (-1, 0), (0, 1), (0, -1)))
        nc = (c[0] + dx, c[1] + dy)
        if 0 <= nc[0] < g and 0 <= nc[1] < g:
            cells.add(nc)
    return cells


def random_cells(rng, g):
    if rng.random() < 0.6:
        return grow_cells(rng, g, rng.randint(1, max(1, g * g * 2 // 3)))
    p = rng.uniform(0.3, 0.7)
    cells = {(x, y) for x in range(g) for y in range(g) if rng.random() < p}
    return cells or {(0, 0)}


def int_map(rng, big):
    """An integer linear map (rotation-like lattice, optional shear) and offset."""
    kind = rng.choice(["id", "id", "rot", "shear"])
    if kind == "id":
        m = (1, 0, 0, 1)
    elif kind == "rot":
        a, b = rng.randint(1, 5), rng.randint(1, 5) * sgn(rng)
        m = (a, -b, b, a)
    else:
        m = (1, rng.randint(1, 4) * sgn(rng), 0, 1)
    if big:
        L = rng.choice([2 ** 20, 2 ** 33, 10 ** 11 + 3, 3 ** 20, 2 ** 40 + 1, 1000003])
        off = (rng.randint(-2 ** 45, 2 ** 45), rng.randint(-2 ** 45, 2 ** 45))
    else:
        L = rng.choice([1, 1, 1, 2, 3, 10])
        off = (rng.randint(-100, 100), rng.randint(-100, 100)) if rng.random() < 0.5 else (0, 0)
    return kind, m, L, off


def apply_int_map(mp, m, L, off, e=0):
    out = []
    for poly in mp:
        rs = []
        for r in poly:
            rr = []
            for x, y in r:
                X = L * (m[0] * x + m[1] * y) + off[0]
                Y = L * (m[2] * x + m[3] * y) + off[1]
                if abs(X) >= 2 ** 53 or abs(Y) >= 2 ** 53:
                    raise Reject("int out of range")
                rr.append([math.ldexp(float(X), e), math.ldexp(float(Y), e)])
            rs.append(rr)
        out.append(rs)
    return out


def lattice_simple_polygon(rng, G, extra):
    """Random simple polygon with vertices on the grid 0..G, plus extra collinear lattice
    vertices inserted on edges."""
    n = rng.randint(3, 10)
    c = (G / 2 + rng.uniform(-G / 8, G / 8), G / 2 + rng.uniform(-G / 8, G / 8))
    pts = []
    for p in star_ring(rng, c, G / 2, n, rmin=0.2):
        q = (min(G, max(0, round(p[0]))), min(G, max(0, round(p[1]))))
        if not pts or q != pts[-1]:
            pts.append(q)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts.pop()
    if len(pts) < 3 or not oracle.ring_simple([(Q(x), Q(y)) for x, y in pts + pts[:1]]):
        raise Reject("lattice polygon not simple")
    if extra:
        out = []
        for k, p in enumerate(pts):
            q = pts[(k + 1) % len(pts)]
            out.append(p)
            g = math.gcd(abs(q[0] - p[0]), abs(q[1] - p[1]))
            if g > 1 and rng.random() < 0.6:
                step = ((q[0] - p[0]) // g, (q[1] - p[1]) // g)
                for t in sorted(rng.sample(range(1, g), rng.randint(1, g - 1))):
                    out.append((p[0] + t * step[0], p[1] + t * step[1]))
        pts = out
    return pts


def gen_int_grid(rng):
    v = rng.choice(["polyomino", "polyomino-merged", "lattice-poly", "lattice-poly",
                    "lattice-tri"])
    big = rng.random() < 0.35
    if v.startswith("polyomino"):
        g = rng.randint(2, 7)
        A = trace_cells(random_cells(rng, g), merge=v.endswith("merged"))
        sh = (rng.randint(-g // 2, g // 2), rng.randint(-g // 2, g // 2)) if rng.random() < 0.6 else (0, 0)
        cb = {(x + sh[0], y + sh[1]) for x, y in random_cells(rng, g)}
        B = trace_cells(cb, merge=rng.random() < 0.5 and v.endswith("merged"))
    elif v == "lattice-poly":
        G = rng.choice([2, 4, 6, 8, 12, 16, 32])
        A = [[lattice_simple_polygon(rng, G, rng.random() < 0.6)]]
        if rng.random() < 0.3:
            # B keeps some of A's vertices: shared vertices and shared collinear edges
            pa = A[0][0]
            B = [[[p for p in pa if rng.random() < 0.7] or pa]]
            if len(B[0][0]) < 3 or not oracle.ring_simple([(Q(x), Q(y)) for x, y in B[0][0] + B[0][0][:1]]):
                B = [[lattice_simple_polygon(rng, G, rng.random() < 0.6)]]
        else:
            B = [[lattice_simple_polygon(rng, G, rng.random() < 0.6)]]
    else:  # lattice-tri: triangles on a small grid sharing edges/vertices or vertex-on-edge
        G = rng.choice([2, 3, 4, 6, 8])
        pts = [(x, y) for x in range(G + 1) for y in range(G + 1)]
        tri = rng.sample(pts, 3)
        if icross(*tri) == 0:
            raise Reject("flat")
        kind = rng.choice(["edge", "vertex", "on-edge", "any"])
        if kind == "edge":
            p, q = rng.sample(tri, 2)
            r = rng.choice(pts)
            B = [p, q, r]
        elif kind == "vertex":
            B = [rng.choice(tri)] + rng.sample(pts, 2)
        elif kind == "on-edge":
            p, q = rng.sample(tri, 2)
            gg = math.gcd(abs(q[0] - p[0]), abs(q[1] - p[1]))
            if gg < 2:
                raise Reject("no lattice point on edge")
            t = rng.randint(1, gg - 1)
            V = (p[0] + t * (q[0] - p[0]) // gg, p[1] + t * (q[1] - p[1]) // gg)
            B = [V] + rng.sample(pts, 2)
        else:
            B = rng.sample(pts, 3)
        if icross(*B) == 0:
            raise Reject("flat")
        A, B = [[tri]], [[B]]
        v = f"{v}-{kind}"
    kind, m, L, off = int_map(rng, big)
    e = 0
    if not big and rng.random() < 0.2:
        e = -rng.randint(1, 40)  # dyadic grid step 2^e (Clipper-style exact scaling)
    a = apply_int_map(A, m, L, off, e)
    b = apply_int_map(B, m, L, off, e)
    if n_edges_mp(a) + n_edges_mp(b) > 260:
        raise Reject("too large")
    tag = ("big" if big else ("dyadic" if e else "small")) + "-" + kind
    return f"{v}.{tag}", a, b


def n_edges_mp(mp):
    return sum(len(r) for poly in mp for r in poly)


# ============================================================================ scaled

BASE = [
    ("near-collinear", gen_near_collinear),
    ("vertex-on-edge", gen_vertex_on_edge),
    ("shared-edge", gen_shared_edge),
    ("tiny-transform", gen_tiny_transform),
    ("sliver-spike", gen_sliver_spike),
    ("hole-contact", gen_hole_contact),
    ("multi-touch", gen_multi_touch),
    ("tiling-contact", gen_tiling_contact),
    ("int-grid", gen_int_grid),
]


def gen_scaled(rng):
    name, fn = rng.choice(BASE)
    v, a, b = fn(rng)
    if rng.random() < 0.5:
        k = rng.randint(-27, 27)
        s, tag = 2.0 ** k, f"p2e{k}"
    else:
        s = 10.0 ** rng.uniform(-8, 8)
        tag = f"dec{math.log10(s):+.1f}"

    def sc(mp):
        return [[[[x * s, y * s] for x, y in r] for r in poly] for poly in mp]

    return f"{name}.{v}.{tag}", sc(a), sc(b)


FAMILIES = BASE + [("scaled", gen_scaled)]
