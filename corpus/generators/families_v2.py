"""Case families of corpus v2 that go beyond polygon/polygon (DESIGN §3).

Each generator takes a ``random.Random`` and returns ``(variant, a, b, flags)`` with
``a`` and ``b`` typed JSON geometries (``{"type": ..., "coordinates": ...}``), or raises
:class:`common.Reject`. The driver (``tiers.py``) checks validity with the exact engine
(``geotruth.validity``), computes the tags and deduplicates.

Constructions are made on an integer lattice and mapped to doubles exactly by an
``ExactFrame`` (``common.exact_frame``: unit, int, projected or lon/lat), so every
contact (a point on a segment at a rational parameter, a collinear overlap, a shared
vertex, a T-junction) is exact. Two optional post-transforms, marked in the variant:

- ``.extreme``: every coordinate multiplied by 2^k, |k| in 500..900 (exact); tagged
  range "extreme";
- ``.rot``: the whole case rotated by a random angle in floating point, which turns the
  exact contacts into ulp-level near-contacts.

Families
--------

``line-line``
    two (multi)lines: collinear overlap / containment / touch, T-junction (endpoint in the
    other's segment interior), endpoint on an interior vertex, endpoints meeting,
    interior vertex touching or crossing a segment, crossing and touching at a shared
    interior vertex, proper crossing (control), identical lines split differently.
``line-mod2``
    Mod-2 boundary rule: closed lines, endpoints shared by 2, 3 or 4 lines, a closed line
    with a tail, an endpoint in another line's interior; probed by points, lines,
    polygons and the same configuration.
``point-geometry``
    (multi)points on a line vertex, segment interior, line endpoint, closed-line endpoint,
    polygon vertex, edge, hole edge, interior, hole, exterior; equal and duplicate points.
``line-polygon``
    a line along an edge (full, sub-segment, overhanging, a chain of edges), through a
    vertex (crossing or tangent), inside touching the boundary at an endpoint or an
    interior vertex, a chord, touching from outside, crossing, in a hole touching it,
    the shell ring as a closed line, multilines of these.
``gc``
    GeometryCollections: overlapping polygons (whose union is the point set), polygons
    sharing an edge (the shared edge is interior), polygon + line + point, a line
    covered by a polygon, nested collections, GC against GC.
``empty``
    the empty-geometry convention family: every empty type (and collections of empties,
    multi-geometries with empty elements) against empties and non-empty geometries of
    every type. Tagged ``convention`` where an operand is empty.
``invalid-zero-length-line``
    lines whose points all coincide (real dimension 0 in RelateNG; invalid for GEOS
    IsValidOp: "Too few distinct points"), alone, in a MultiLineString or in a GC.
"""

from __future__ import annotations

import math

from common import Reject, convex_hull, exact_frame, rand_convex_int

# ============================================================================ builders
# Geometries are typed JSON with integer lattice coordinates until realize() maps them.


def P(p):
    return {"type": "Point", "coordinates": [p[0], p[1]]}


def L(pts):
    return {"type": "LineString", "coordinates": [[p[0], p[1]] for p in pts]}


def ML(lines):
    return {"type": "MultiLineString", "coordinates": [g["coordinates"] for g in lines]}


def MP(pts):
    return {"type": "MultiPoint", "coordinates": [[p[0], p[1]] for p in pts]}


def _close(r):
    r = [[p[0], p[1]] for p in r]
    return [*r, r[0]]


def A(shell, *holes):
    return {"type": "Polygon", "coordinates": [_close(shell)] + [_close(h) for h in holes]}


def MA(polys):
    return {"type": "MultiPolygon", "coordinates": [g["coordinates"] for g in polys]}


def GC(*geoms):
    return {"type": "GeometryCollection", "geometries": list(geoms)}


EMPTY = {
    "POINT EMPTY": {"type": "Point", "coordinates": []},
    "LINESTRING EMPTY": {"type": "LineString", "coordinates": []},
    "POLYGON EMPTY": {"type": "Polygon", "coordinates": []},
    "MULTIPOINT EMPTY": {"type": "MultiPoint", "coordinates": []},
    "MULTILINESTRING EMPTY": {"type": "MultiLineString", "coordinates": []},
    "MULTIPOLYGON EMPTY": {"type": "MultiPolygon", "coordinates": []},
    "GEOMETRYCOLLECTION EMPTY": {"type": "GeometryCollection", "geometries": []},
    "MULTIPOINT (EMPTY)": {"type": "MultiPoint", "coordinates": [[]]},
    "MULTILINESTRING (EMPTY)": {"type": "MultiLineString", "coordinates": [[]]},
    "MULTIPOLYGON (EMPTY)": {"type": "MultiPolygon", "coordinates": [[]]},
    "GEOMETRYCOLLECTION (POINT EMPTY)": {
        "type": "GeometryCollection",
        "geometries": [{"type": "Point", "coordinates": []}],
    },
    "GEOMETRYCOLLECTION (LINESTRING EMPTY, POLYGON EMPTY)": {
        "type": "GeometryCollection",
        "geometries": [
            {"type": "LineString", "coordinates": []},
            {"type": "Polygon", "coordinates": []},
        ],
    },
}


def _map_coords(c, f):
    if isinstance(c, list) and len(c) == 2 and all(isinstance(v, (int, float)) for v in c):
        return f(c)
    if isinstance(c, list):
        return [_map_coords(x, f) for x in c]
    return c


def mapg(g, f):
    """The geometry with every position replaced by f(position)."""
    if g["type"] == "GeometryCollection":
        return {"type": g["type"], "geometries": [mapg(x, f) for x in g["geometries"]]}
    return {"type": g["type"], "coordinates": _map_coords(g["coordinates"], f)}


def positions(g):
    out = []
    mapg(g, lambda p: out.append(p) or p)
    return out


# ============================================================================ lattice


def add(p, v, s=1):
    return (p[0] + s * v[0], p[1] + s * v[1])


def sub(p, q):
    return (p[0] - q[0], p[1] - q[1])


def cross(u, v):
    return u[0] * v[1] - u[1] * v[0]


def rvec(rng, m, sloped=None):
    """A random non-zero lattice vector with |components| <= m."""
    if sloped is None:
        sloped = rng.random() < 0.75
    for _ in range(200):
        v = (rng.randint(-m, m), rng.randint(-m, m))
        if v != (0, 0) and (not sloped or (v[0] and v[1])):
            return v
    raise Reject("no vector")


def side_vec(rng, d, m, side):
    """A lattice vector v, |v| <= m, with sign(cross(d, v)) == side."""
    for _ in range(200):
        v = rvec(rng, m, sloped=False)
        if cross(d, v) * side > 0:
            return v
    raise Reject("no side vector")


def rpt(rng, r):
    return (rng.randint(-r, r), rng.randint(-r, r))


def tail(rng, start, k, m):
    """k random points continuing a polyline from start (start excluded)."""
    out, p = [], start
    for _ in range(k):
        p = add(p, rvec(rng, m))
        out.append(p)
    return out


class Frame:
    """An exact lattice frame and a local scale R (|local coordinates| ~ R)."""

    def __init__(self, rng, kinds=("unit", "int", "projected", "lonlat")):
        self.fr = exact_frame(rng, kinds)
        top = max(3, min(self.fr.S - 4, 14))
        self.r = rng.randint(3, top)
        self.R = 2**self.r
        self.kind = self.fr.kind

    def realize(self, g):
        return mapg(g, lambda p: self.fr.pt(p))


def convex(rng, R, k=None, c=(0, 0)):
    return [tuple(p) for p in rand_convex_int(rng, k or rng.randint(3, 7), R, c)]


def interior_point(poly):
    """A lattice point strictly inside a strictly convex CCW lattice polygon (or Reject)."""
    n = len(poly)
    cx = sum(p[0] for p in poly) // n
    cy = sum(p[1] for p in poly) // n
    c = (cx, cy)
    for i in range(n):
        if cross(sub(poly[(i + 1) % n], poly[i]), sub(c, poly[i])) <= 0:
            raise Reject("centroid not strictly inside")
    return c


def edge_point(poly, i, m, f):
    """The point at parameter m/f on edge i (lattice when the polygon is scaled by f)."""
    p, q = poly[i], poly[(i + 1) % len(poly)]
    e = sub(q, p)
    if (e[0] * m) % f or (e[1] * m) % f:
        raise Reject("edge point off lattice")
    return (p[0] + e[0] * m // f, p[1] + e[1] * m // f)


def scaled_poly(rng, R, f, k=None):
    """A convex polygon with every coordinate a multiple of f (so edge points at m/f are
    lattice points)."""
    base = convex(rng, max(2, R // f), k)
    return [(x * f, y * f) for x, y in base]


# ============================================================================ post


def post_transform(rng, g_a, g_b, variant, *, allow_rot=True, allow_extreme=True):
    """Optionally rotate in floating point (.rot) or scale by 2^k (.extreme)."""
    u = rng.random()
    if allow_extreme and u < 0.10:
        k = rng.choice((-1, 1)) * rng.randint(500, 900)

        def sc(p):
            x, y = math.ldexp(p[0], k), math.ldexp(p[1], k)
            for v, w in ((x, p[0]), (y, p[1])):
                if w != 0 and not (2.3e-308 < abs(v) < 1.7e308):
                    raise Reject("extreme scale out of range")
            return [x, y]

        return mapg(g_a, sc), mapg(g_b, sc), variant + ".extreme"
    if allow_rot and u < 0.25:
        pts = positions(g_a) + positions(g_b)
        if not pts:
            return g_a, g_b, variant
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        th = rng.uniform(0, 2 * math.pi)
        cs, sn = math.cos(th), math.sin(th)

        def rot(p):
            dx, dy = p[0] - cx, p[1] - cy
            return [cx + cs * dx - sn * dy, cy + sn * dx + cs * dy]

        return mapg(g_a, rot), mapg(g_b, rot), variant + ".rot"
    return g_a, g_b, variant


def finish(rng, fr, v, a, b, flags=(), *, swap=True, rot=True, extreme=True):
    if swap and rng.random() < 0.5:
        a, b = b, a
        v = v + ".ba"
    a, b = fr.realize(a), fr.realize(b)
    a, b, v = post_transform(rng, a, b, f"{v}.{fr.kind}", allow_rot=rot, allow_extreme=extreme)
    return v, a, b, tuple(flags)


def maybe_multi_line(rng, line_geom, R):
    """Sometimes wrap a LineString into a MultiLineString with a far-away second line."""
    if rng.random() < 0.25:
        far = (3 * R + rng.randint(0, R), 3 * R + rng.randint(0, R))
        return ML([line_geom, L([far, add(far, rvec(rng, 3))])])
    return line_geom


# ============================================================================ line-line


def gen_line_line(rng):
    fr = Frame(rng)
    R = fr.R
    v = rng.choice(
        [
            "collinear-overlap",
            "collinear-contained",
            "collinear-touch-end",
            "collinear-touch-vertex",
            "t-junction",
            "endpoint-on-vertex",
            "endpoint-endpoint",
            "vertex-touch",
            "vertex-cross",
            "shared-vertex",
            "proper-cross",
            "identical",
        ]
    )
    d = rvec(rng, 3)
    o = rpt(rng, R // 2)
    m = max(1, R // (4 * max(abs(d[0]), abs(d[1]))))
    a_len = rng.randint(2, max(2, min(m, 12)))

    def on(t):
        return add(o, d, t)

    def pre(k=None):
        k = rng.randint(0, 2) if k is None else k
        return list(reversed(tail(rng, o, k, max(2, R // 4))))

    if v in ("collinear-overlap", "collinear-contained"):
        if v == "collinear-overlap":
            b0 = rng.randint(-3, a_len - 1)
            b1 = rng.randint(max(b0 + 1, 1), a_len + 3)
            if (b0, b1) == (0, a_len):
                raise Reject("identical overlap")
        else:
            if a_len < 3:
                raise Reject("too short")
            b0 = rng.randint(1, a_len - 2)
            b1 = rng.randint(b0 + 1, a_len - 1)
        split = [on(t) for t in range(1, a_len) if rng.random() < 0.3]
        la = [*pre(), o, *split, on(a_len), *tail(rng, on(a_len), rng.randint(0, 2), R // 4)]
        lb = [on(b0), on(b1)]
        if rng.random() < 0.5:
            lb = lb + tail(rng, on(b1), rng.randint(1, 2), R // 4)
        if rng.random() < 0.5:
            lb = lb[::-1]
    elif v.startswith("collinear-touch"):
        after = [] if v.endswith("end") else tail(rng, on(a_len), rng.randint(1, 2), R // 4)
        la = [*pre(), o, on(a_len), *after]
        lb = [on(a_len), on(a_len + rng.randint(1, 4))]
        lb = lb + tail(rng, lb[-1], rng.randint(0, 2), R // 4)
    elif v == "t-junction":
        t = rng.randint(1, a_len - 1)
        la = [*pre(), o, on(a_len), *tail(rng, on(a_len), rng.randint(0, 2), R // 4)]
        w = side_vec(rng, d, max(2, R // 4), rng.choice((-1, 1)))
        lb = [on(t), add(on(t), w), *tail(rng, add(on(t), w), rng.randint(0, 2), R // 4)]
    elif v == "endpoint-on-vertex":
        la = [*pre(rng.randint(1, 2)), o, *tail(rng, o, rng.randint(1, 3), R // 4)]
        lb = [o, *tail(rng, o, rng.randint(1, 3), R // 4)]
    elif v == "endpoint-endpoint":
        la = [o, *tail(rng, o, rng.randint(1, 3), R // 4)]
        lb = [o, *tail(rng, o, rng.randint(1, 3), R // 4)]
    elif v in ("vertex-touch", "vertex-cross"):
        t = rng.randint(1, a_len - 1)
        la = [*pre(), o, on(a_len), *tail(rng, on(a_len), rng.randint(0, 2), R // 4)]
        s1 = rng.choice((-1, 1))
        s2 = s1 if v == "vertex-touch" else -s1
        x = on(t)
        lb = [
            add(x, side_vec(rng, d, max(2, R // 4), s1)),
            x,
            add(x, side_vec(rng, d, max(2, R // 4), s2)),
        ]
    elif v == "shared-vertex":
        la = [*pre(1), o, *tail(rng, o, rng.randint(1, 2), R // 4)]
        lb = [*pre(1), o, *tail(rng, o, rng.randint(1, 2), R // 4)]
    elif v == "proper-cross":
        la = [
            add(o, (-R // 2, rng.randint(-R // 2, R // 2))),
            add(o, (R // 2, rng.randint(-R // 2, R // 2))),
        ]
        lb = [
            add(o, (rng.randint(-R // 2, R // 2), -R // 2)),
            add(o, (rng.randint(-R // 2, R // 2), R // 2)),
        ]
    else:  # identical: the same point set, split and oriented differently
        la = [o] + [on(t) for t in range(1, a_len) if rng.random() < 0.4] + [on(a_len)]
        la += tail(rng, on(a_len), rng.randint(0, 2), R // 4)
        extra = [on(t) for t in range(1, a_len) if rng.random() < 0.4]
        lb = [o, *extra, *la[len([p for p in la if p in [on(t) for t in range(a_len)]]) :]]
        lb = [p for i, p in enumerate(lb) if i == 0 or p != lb[i - 1]]
        if rng.random() < 0.5:
            lb = lb[::-1]
    a = maybe_multi_line(rng, L(la), R)
    b = maybe_multi_line(rng, L(lb), R)
    return finish(rng, fr, v, a, b)


# ============================================================================ line-mod2


def _loop(rng, e, R):
    """A closed line starting and ending at e (a lattice triangle or quad)."""
    k = rng.randint(2, 3)
    pts = [e]
    for i in range(k):
        ang = 2 * math.pi * (i + 1) / (k + 1) + rng.uniform(-0.3, 0.3)
        r = rng.randint(max(2, R // 4), max(3, R // 2))
        pts.append((e[0] + round(r * math.cos(ang)), e[1] + round(r * math.sin(ang))))
    if len(set(pts)) < len(pts):
        raise Reject("degenerate loop")
    return [*pts, e]


def gen_line_mod2(rng):
    fr = Frame(rng)
    R = fr.R
    e = rpt(rng, R // 4)
    cfg = rng.choice(
        ["closed", "shared2", "shared3", "shared4", "closed-tail", "two-closed", "t-inside"]
    )
    m = max(2, R // 3)

    def spoke():
        return [e, *tail(rng, e, rng.randint(1, 2), m)]

    if cfg == "closed":
        lines = [_loop(rng, e, R)]
    elif cfg.startswith("shared"):
        lines = [spoke() for _ in range(int(cfg[-1]))]
        for i, ln in enumerate(lines):
            if rng.random() < 0.5 and i:
                lines[i] = ln[::-1]
    elif cfg == "closed-tail":
        lines = [_loop(rng, e, R), spoke()]
    elif cfg == "two-closed":
        lines = [_loop(rng, e, R), _loop(rng, e, R)]
    else:  # t-inside: e is an interior vertex of one line and the endpoint of another
        lines = [[*tail(rng, e, 1, m)[::-1], e, *tail(rng, e, 1, m)], spoke()]
    rng.shuffle(lines)
    a = L(lines[0]) if len(lines) == 1 and rng.random() < 0.5 else ML([L(x) for x in lines])
    probe = rng.choice(
        ["point", "multipoint", "line-end", "line-through", "same", "poly-vertex", "line-along"]
    )
    if probe == "point":
        b = P(e)
    elif probe == "multipoint":
        other = lines[0][1]
        b = MP([e, other] if rng.random() < 0.5 else [other, e])
    elif probe == "line-end":
        b = L([e, *tail(rng, e, rng.randint(1, 2), m)])
    elif probe == "line-through":
        w = rvec(rng, max(2, R // 4))
        b = L([add(e, w, -1), e, add(e, w)] if rng.random() < 0.5 else [add(e, w, -1), add(e, w)])
    elif probe == "same":
        other = [x[::-1] if rng.random() < 0.5 else x for x in lines]
        rng.shuffle(other)
        b = ML([L(x) for x in other])
    elif probe == "poly-vertex":
        poly = convex(rng, max(2, R // 3))
        sh = sub(e, poly[0])
        b = A([add(p, sh) for p in poly])
    else:
        b = L(rng.choice(lines))
    return finish(rng, fr, f"{cfg}.{probe}", a, b, ("mod2",))


# ============================================================================ points


def gen_point_geometry(rng):
    fr = Frame(rng)
    R = fr.R
    f = rng.choice((2, 4, 8, 3, 5))
    v = rng.choice(
        [
            "line-vertex",
            "line-segment",
            "line-endpoint",
            "closed-line-endpoint",
            "poly-vertex",
            "poly-edge",
            "hole-edge",
            "poly-interior",
            "in-hole",
            "exterior",
            "multipoint-mixed",
            "point-equal",
            "multipoint-duplicate",
        ]
    )
    if v.startswith("line") or v == "closed-line-endpoint":
        d = rvec(rng, 3)
        o = rpt(rng, R // 2)
        n = rng.randint(2, 6)
        if v == "closed-line-endpoint":
            pts = _loop(rng, o, R)
            q = o
        else:
            pts = [add(o, d, 0), add(o, d, n), *tail(rng, add(o, d, n), rng.randint(0, 2), R // 4)]
            q = {
                "line-vertex": pts[1] if len(pts) > 2 else pts[0],
                "line-segment": add(o, d, rng.randint(1, n - 1)),
                "line-endpoint": rng.choice((pts[0], pts[-1])),
            }[v]
        other = (
            L(pts) if rng.random() < 0.7 else ML([L(pts), L([add(o, (R, R)), add(o, (R, R + 1))])])
        )
        a = P(q) if rng.random() < 0.6 else MP([q, add(q, (R, -R))])
        return finish(rng, fr, v, a, other)
    shell = scaled_poly(rng, R, f)
    hole = None
    if v in ("hole-edge", "in-hole") or rng.random() < 0.3:
        c = interior_point(shell)
        hs = [((p[0] - c[0]) // 3 + c[0], (p[1] - c[1]) // 3 + c[1]) for p in shell]
        hs = [(x - x % f, y - y % f) for x, y in hs]
        if len(set(hs)) < 3:
            raise Reject("hole collapsed")
        hole = hs[::-1]
    poly = A(shell, hole) if hole else A(shell)
    i = rng.randrange(len(shell))
    if v == "poly-vertex":
        q = shell[i]
    elif v == "poly-edge":
        q = edge_point(shell, i, rng.randint(1, f - 1), f)
    elif v == "hole-edge":
        q = edge_point(hole[::-1], rng.randrange(len(hole)), rng.randint(0, f - 1), f)
    elif v == "in-hole":
        q = interior_point(hole[::-1])
    elif v == "poly-interior":
        q = interior_point(shell)
        if hole:  # halfway between a shell vertex and the centre: in the solid part
            q = ((shell[i][0] + q[0]) // 2, (shell[i][1] + q[1]) // 2)
    elif v == "exterior":
        q = add(shell[i], sub(shell[i], interior_point(shell)))
    elif v == "multipoint-mixed":
        cands = [
            shell[i],
            edge_point(shell, i, 1, f),
            interior_point(shell),
            add(shell[i], sub(shell[i], interior_point(shell))),
        ]
        rng.shuffle(cands)
        return finish(rng, fr, v, MP(cands[: rng.randint(2, 4)]), poly)
    elif v == "point-equal":
        q = rpt(rng, R)
        return finish(rng, fr, v, P(q), P(q) if rng.random() < 0.5 else MP([q, q]))
    else:  # multipoint-duplicate
        q, r = rpt(rng, R), rpt(rng, R)
        return finish(rng, fr, v, MP([q, r, q]), MP([r, q]) if rng.random() < 0.5 else P(q))
    if rng.random() < 0.8:
        other = poly
    else:
        far = (3 * R, 3 * R)
        other = MA([poly, A([far, add(far, (f, 0)), add(far, (0, f))])])
    return finish(rng, fr, v, P(q), other)


# ============================================================================ line-polygon


def gen_line_polygon(rng):
    fr = Frame(rng)
    R = fr.R
    f = rng.choice((2, 4, 8, 3, 6))
    shell = scaled_poly(rng, R, f, rng.randint(3, 6))
    n = len(shell)
    i = rng.randrange(n)
    p0, p1, p2 = shell[i], shell[(i + 1) % n], shell[(i + 2) % n]
    pm = shell[i - 1]
    c = interior_point(shell)
    v = rng.choice(
        [
            "along-edge-full",
            "along-edge-sub",
            "along-edge-overhang",
            "along-chain",
            "through-vertex",
            "vertex-tangent",
            "inside-touch-endpoint",
            "inside-touch-vertex",
            "chord",
            "outside-touch",
            "crossing",
            "hole-touch",
            "hole-edge",
            "ring-as-line",
            "multiline",
        ]
    )
    hole = None

    def ep(m, k=None):
        return edge_point(shell, i if k is None else k, m, f)

    if v == "along-edge-full":
        line = [p0, p1]
    elif v == "along-edge-sub":
        m1 = rng.randint(0, f - 1)
        m2 = rng.randint(m1 + 1, f)
        if (m1, m2) == (0, f):
            raise Reject("full edge")
        line = [ep(m1), ep(m2)]
    elif v == "along-edge-overhang":
        e = sub(p1, p0)
        line = [ep(rng.randint(0, f - 1)), (p1[0] + e[0] // f, p1[1] + e[1] // f)]
    elif v == "along-chain":
        line = [ep(rng.randint(0, f - 1)), p1, p2]
    elif v == "through-vertex":
        u = sub(p0, c)
        line = [add(p0, u), c] if rng.random() < 0.5 else [add(p0, u), p0, c]
    elif v == "vertex-tangent":
        dvec = add(sub(p0, pm), sub(p1, p0))
        line = (
            [add(p0, dvec, -1), p0, add(p0, dvec)]
            if rng.random() < 0.5
            else [add(p0, dvec, -1), add(p0, dvec)]
        )
    elif v == "inside-touch-endpoint":
        line = [ep(rng.randint(0, f - 1)), c]
    elif v == "inside-touch-vertex":
        q = ep(rng.randint(1, f - 1))
        line = [c, q, ((q[0] + p1[0] + c[0]) // 3, (q[1] + p1[1] + c[1]) // 3)]
    elif v == "chord":
        k = (i + rng.randint(1, n - 1)) % n
        line = [ep(rng.randint(0, f - 1)), ep(rng.randint(0, f - 1), k)]
        if line[0] == line[1]:
            raise Reject("chord collapsed")
    elif v == "outside-touch":
        q = ep(rng.randint(0, f - 1))
        line = [q, add(q, sub(q, c))]
    elif v == "crossing":
        line = [add(p0, sub(p0, c)), add(p2, sub(p2, c))]
    elif v in ("hole-touch", "hole-edge"):
        hs = [((p[0] - c[0]) // 2 + c[0], (p[1] - c[1]) // 2 + c[1]) for p in shell]
        hs = [(x - x % f, y - y % f) for x, y in hs]
        if len(set(hs)) < 3:
            raise Reject("hole collapsed")
        hole = hs
        hc = interior_point(hs)
        k = rng.randrange(len(hs))
        hq = edge_point(hs, k, rng.randint(0, f - 1), f)
        if v == "hole-touch":
            line = [hc, hq]
        else:
            line = [hs[k], hs[(k + 1) % len(hs)]]
    elif v == "ring-as-line":
        s = rng.randrange(n)
        ring = shell[s:] + shell[:s]
        if rng.random() < 0.5:
            ring = ring[::-1]
        line = [*ring, ring[0]]
    else:  # multiline
        line = None
    poly = A(shell, hole[::-1]) if hole else A(shell)
    if line is None:
        g_line = ML([L([p0, p1]), L([ep(rng.randint(0, f - 1), (i + 2) % n), c])])
    else:
        g_line = maybe_multi_line(rng, L(line), R)
    if rng.random() < 0.15:
        far = (3 * R, 3 * R)
        poly = MA([poly, A([far, add(far, (f, 0)), add(far, (0, f))])])
    return finish(rng, fr, v, g_line, poly)


# ============================================================================ gc


def _two_sided(rng, s, t, R):
    """Two convex lattice polygons on either side of the shared edge s-t (CCW each)."""
    d = sub(t, s)
    polys = []
    for side in (1, -1):
        pts = [s, t]
        for _ in range(rng.randint(1, 2)):
            u = side_vec(rng, d, max(2, R // 3), side)
            pts.append(add(s if rng.random() < 0.5 else t, u))
        h = [tuple(p) for p in convex_hull(pts)]
        if s not in h or t not in h or len(h) < 3:
            raise Reject("shared edge not on hull")
        polys.append(h)
    return polys


def gen_gc(rng):
    fr = Frame(rng)
    R = fr.R
    v = rng.choice(
        ["overlap-2poly", "adjacent-2poly", "poly-line-point", "line-in-poly", "nested", "gc-gc"]
    )
    p1 = convex(rng, max(4, R // 2))
    c1 = interior_point(p1)
    probe = None
    if v == "overlap-2poly":
        sh = rvec(rng, max(2, R // 4))
        p2 = (
            [add(p, sh) for p in p1]
            if rng.random() < 0.5
            else convex(rng, max(4, R // 2), None, sh)
        )
        a = GC(A(p1), A(p2))
        probe = rng.choice(["poly-part", "line-across", "point-inner-boundary", "reordered"])
        if probe == "poly-part":
            b = A(p1)
        elif probe == "line-across":
            b = L([c1, interior_point(p2)])
        elif probe == "point-inner-boundary":
            b = P(p1[rng.randrange(len(p1))])
        else:
            b = GC(A(p2), A(p1))
    elif v == "adjacent-2poly":
        s = rpt(rng, R // 4)
        t = add(s, rvec(rng, max(2, R // 4)))
        q1, q2 = _two_sided(rng, s, t, R)
        a = GC(A(q1), A(q2)) if rng.random() < 0.7 else GC(A(q1), GC(A(q2)))
        probe = rng.choice(["shared-edge-line", "shared-edge-point", "one-part", "union-poly"])
        if probe == "shared-edge-line":
            b = L([s, t])
        elif probe == "shared-edge-point":
            g = math.gcd(abs(t[0] - s[0]), abs(t[1] - s[1]))
            if g < 2:
                raise Reject("no lattice point inside the shared edge")
            b = P(add(s, ((t[0] - s[0]) // g, (t[1] - s[1]) // g)))
        elif probe == "one-part":
            b = A(q2)
        else:  # the same two parts in the other order (a MultiPolygon would be invalid)
            b = GC(A(q2), A(q1))
    elif v == "poly-line-point":
        o = p1[0]
        out = add(o, sub(o, c1))
        line = [c1, out]
        pt = c1 if rng.random() < 0.5 else out
        a = GC(A(p1), L(line), P(pt))
        probe = rng.choice(["poly", "line", "point", "outside-part"])
        b = {"poly": A(p1), "line": L(line), "point": P(o), "outside-part": L([o, out])}[probe]
    elif v == "line-in-poly":
        q = p1[rng.randrange(len(p1))]
        a = GC(A(p1), L([c1, q]))
        probe = rng.choice(["poly", "line", "mpoint"])
        b = {"poly": A(p1), "line": L([c1, q]), "mpoint": MP([c1, q])}[probe]
    elif v == "nested":
        a = GC(GC(A(p1)), MP([c1, add(p1[0], sub(p1[0], c1))]))
        probe = rng.choice(["line", "poly", "point"])
        b = {"line": L([c1, p1[1]]), "poly": A(p1), "point": P(c1)}[probe]
    else:  # gc-gc
        sh = rvec(rng, max(2, R // 4))
        p2 = [add(p, sh) for p in p1]
        a = GC(A(p1), L([c1, p1[0]]))
        b = GC(A(p2), P(c1))
        probe = "mixed"
    return finish(rng, fr, f"{v}.{probe}", a, b, ("gc",))


# ============================================================================ empty


def _nonempty_samples(rng, R):
    poly = convex(rng, max(4, R // 2))
    c = interior_point(poly)
    q = poly[0]
    return {
        "Point": P(c),
        "MultiPoint": MP([c, q]),
        "LineString": L([c, q]),
        "MultiLineString": ML([L([c, q]), L([q, poly[1]])]),
        "Polygon": A(poly),
        "MultiPolygon": MA([A(poly), A([(3 * R, 3 * R), (3 * R + 2, 3 * R), (3 * R, 3 * R + 2)])]),
        "GeometryCollection": GC(A(poly), L([q, add(q, sub(q, c))]), P(c)),
        # non-empty geometries with empty elements
        "MultiPoint+EMPTY": {"type": "MultiPoint", "coordinates": [[c[0], c[1]], []]},
        "MultiPolygon+EMPTY": {"type": "MultiPolygon", "coordinates": [[], A(poly)["coordinates"]]},
        "GC+EMPTY": GC(EMPTY["POLYGON EMPTY"], L([c, q]), EMPTY["POINT EMPTY"]),
        "MultiLineString+EMPTY": {
            "type": "MultiLineString",
            "coordinates": [[], L([c, q])["coordinates"]],
        },
    }


def gen_empty(rng):
    fr = Frame(rng, ("unit", "int"))
    samples = _nonempty_samples(rng, fr.R)
    empties = list(EMPTY)
    u = rng.random()
    if u < 0.3:
        ea, eb = rng.choice(empties), rng.choice(empties)
        a, b = EMPTY[ea], EMPTY[eb]
        v = "empty-empty"
    elif u < 0.8:
        e = rng.choice(empties)
        name = rng.choice(sorted(samples))
        a, b = EMPTY[e], samples[name]
        v = "empty-vs-" + name.replace("+EMPTY", "-with-empty")
        if rng.random() < 0.5:
            a, b = b, a
            v += ".ba"
    else:
        names = sorted(n for n in samples if n.endswith("+EMPTY"))
        name = rng.choice(names)
        other = rng.choice(sorted(samples))
        a, b = samples[name], samples[other]
        v = "empty-elements"
    flags = ["empty"]
    ga_empty = _is_empty_json(a)
    gb_empty = _is_empty_json(b)
    if ga_empty or gb_empty:
        flags.append("convention")
    return finish(rng, fr, v, a, b, flags, swap=False, rot=False, extreme=False)


def _is_empty_json(g):
    return not positions(g)


# ============================================================================ invalid


def gen_invalid_zero_length_line(rng):
    fr = Frame(rng)
    R = fr.R
    p = rpt(rng, R // 2)
    form = rng.choice(["two-points", "three-points", "mls-mixed", "gc"])
    if form == "two-points":
        a = L([p, p])
    elif form == "three-points":
        a = L([p, p, p])
    elif form == "mls-mixed":
        a = ML([L([p, p]), L([add(p, (1, 2)), add(p, (R // 2, 1))])])
    else:
        a = GC(L([p, p]), P(add(p, (R // 3, 1))))
    probe = rng.choice(
        ["point", "line-through", "line-end", "poly-inside", "poly-vertex", "poly-edge", "same"]
    )
    if probe == "point":
        b = P(p)
    elif probe == "line-through":
        w = rvec(rng, 3)
        b = L([add(p, w, -1), add(p, w)])
    elif probe == "line-end":
        b = L([p, add(p, rvec(rng, R // 4 + 1))])
    elif probe == "poly-inside":
        poly = convex(rng, max(4, R // 3))
        c = interior_point(poly)
        b = A([add(q, sub(p, c)) for q in poly])
    elif probe == "poly-vertex":
        poly = convex(rng, max(4, R // 3))
        b = A([add(q, sub(p, poly[0])) for q in poly])
    elif probe == "poly-edge":
        poly = [(x * 2, y * 2) for x, y in convex(rng, max(4, R // 6))]
        q = edge_point(poly, 0, 1, 2)
        b = A([add(r, sub(p, q)) for r in poly])
    else:
        b = L([p, p])
    return finish(rng, fr, f"{form}.{probe}", a, b, ("zero-length-line", "invalid-input"))


#: The v2 families, in corpus order. Families starting with "invalid-" hold invalid input.
FAMILIES_V2 = [
    ("line-line", gen_line_line),
    ("line-mod2", gen_line_mod2),
    ("point-geometry", gen_point_geometry),
    ("line-polygon", gen_line_polygon),
    ("gc", gen_gc),
    ("empty", gen_empty),
    ("invalid-zero-length-line", gen_invalid_zero_length_line),
]
