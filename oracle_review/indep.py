"""Independent exact reference for polygon/polygon predicates and overlay areas.

Written for the oracle review, deliberately WITHOUT reusing any code or algorithm of
oracle.py, so that agreement between the two is evidence and not a tautology:

  oracle.py                               this file
  ------------------------------------    ------------------------------------------------
  gmpy2.mpq                               fractions.Fraction
  even-odd ray crossing                   winding number (Sunday) on re-oriented rings
  parametric segment intersection         line-equation (Cramer) intersection + bbox test
  vertical slab / trapezoid areas         Green's theorem on boundary pieces: every edge of A
                                          is split at every contact with B (and vice versa),
                                          each piece is classified by its midpoint as inside,
                                          outside, or on the other boundary (same/opposite
                                          direction), and the pieces that bound the result are
                                          integrated with the shoelace formula
  predicates from exact areas             predicates from the piece classification (no areas)
  ring_simple (orientation tests)         pairwise intersection SETS of ring edges

Also: exact Sutherland-Hodgman clipping and a separating-axis intersects test, for convex
polygons only (a third, even more independent, route for that sub-class).

Semantics assumed: valid OGC polygons / multipolygons (rings simple, holes inside shells,
parts with disjoint interiors; point touches allowed). Orientation of the input rings is
irrelevant: shells are re-oriented CCW and holes CW here.
"""
from fractions import Fraction as F

ZERO = F(0)
ONE = F(1)


# ----------------------------------------------------------------------------- basics

def fq(v):
    """Exact rational value of a JSON number (Python int or float)."""
    return F(v)


def dedup(ring):
    out = []
    for p in ring:
        if not out or out[-1] != p:
            out.append(p)
    return out


def twice_signed_area(pts):
    """pts: closed list (first == last)."""
    s = ZERO
    for i in range(len(pts) - 1):
        (x0, y0), (x1, y1) = pts[i], pts[i + 1]
        s += x0 * y1 - x1 * y0
    return s


def parse(geom):
    """-> list of polygons, each a list of closed rings of Fraction points, re-oriented:
    shell CCW (positive area), holes CW (negative area)."""
    polys = []
    for poly in geom:
        rs = []
        for k, ring in enumerate(poly):
            pts = dedup([(fq(x), fq(y)) for x, y in ring])
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            a2 = twice_signed_area(pts)
            if (k == 0 and a2 < 0) or (k > 0 and a2 > 0):
                pts = pts[::-1]
            rs.append(pts)
        polys.append(rs)
    return polys


def directed_edges(polys):
    out = []
    for rs in polys:
        for pts in rs:
            for i in range(len(pts) - 1):
                if pts[i] != pts[i + 1]:
                    out.append((pts[i], pts[i + 1]))
    return out


def area_of(polys):
    return sum((twice_signed_area(r) for rs in polys for r in rs), ZERO) / 2


# ------------------------------------------------------------- segment/segment contact

def _between(v, a, b):
    return (a <= v <= b) if a <= b else (b <= v <= a)


def _param(p0, p1, pt):
    """Parameter of pt (known to lie on line p0p1) along p0->p1."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    if abs(dx) >= abs(dy):
        return (pt[0] - p0[0]) / dx
    return (pt[1] - p0[1]) / dy


def contact_params(p0, p1, q0, q1):
    """Parameters t in [0, 1] along p0->p1 of the contact with closed segment q0q1:
    [] (none), [t] (one point) or [t0, t1] (collinear overlap, t0 < t1)."""
    # line equations  A x + B y = C
    A1, B1 = p1[1] - p0[1], p0[0] - p1[0]
    C1 = A1 * p0[0] + B1 * p0[1]
    A2, B2 = q1[1] - q0[1], q0[0] - q1[0]
    C2 = A2 * q0[0] + B2 * q0[1]
    det = A1 * B2 - A2 * B1
    if det != 0:
        x = (C1 * B2 - C2 * B1) / det
        y = (A1 * C2 - A2 * C1) / det
        if (_between(x, p0[0], p1[0]) and _between(y, p0[1], p1[1])
                and _between(x, q0[0], q1[0]) and _between(y, q0[1], q1[1])):
            return [_param(p0, p1, (x, y))]
        return []
    # parallel: same line iff q0 satisfies line 1
    if A1 * q0[0] + B1 * q0[1] != C1:
        return []
    t0, t1 = _param(p0, p1, q0), _param(p0, p1, q1)
    lo, hi = max(ZERO, min(t0, t1)), min(ONE, max(t0, t1))
    if lo > hi:
        return []
    return [lo] if lo == hi else [lo, hi]


# ----------------------------------------------------------------- point classification

def _isleft(a, b, p):
    return (b[0] - a[0]) * (p[1] - a[1]) - (p[0] - a[0]) * (b[1] - a[1])


def on_edge(p, a, b):
    if _isleft(a, b, p) != 0:
        return False
    return (p[0] - a[0]) * (b[0] - a[0]) + (p[1] - a[1]) * (b[1] - a[1]) >= 0 and \
           (p[0] - b[0]) * (a[0] - b[0]) + (p[1] - b[1]) * (a[1] - b[1]) >= 0


def winding(p, edges):
    wn = 0
    for a, b in edges:
        if a[1] <= p[1]:
            if b[1] > p[1] and _isleft(a, b, p) > 0:
                wn += 1
        elif b[1] <= p[1] and _isleft(a, b, p) < 0:
            wn -= 1
    return wn


def classify_point(p, edges):
    """'on', 'in' or 'out' for a valid (re-oriented) geometry given by its edges."""
    for a, b in edges:
        if on_edge(p, a, b):
            return "on"
    return "in" if winding(p, edges) != 0 else "out"


# --------------------------------------------------------------------- boundary pieces

def pieces(ea, eb):
    """Split every directed edge of ea at every contact with eb. Returns
    (list of (p, q, cls) with cls in in/out/same/opp relative to the other geometry,
    touched) where touched says whether any edge of ea meets any edge of eb."""
    out = []
    touched = False
    for p0, p1 in ea:
        ts = {ZERO, ONE}
        for q0, q1 in eb:
            # cheap bbox reject
            if max(p0[0], p1[0]) < min(q0[0], q1[0]) or max(q0[0], q1[0]) < min(p0[0], p1[0]):
                continue
            if max(p0[1], p1[1]) < min(q0[1], q1[1]) or max(q0[1], q1[1]) < min(p0[1], p1[1]):
                continue
            c = contact_params(p0, p1, q0, q1)
            if c:
                touched = True
                ts.update(c)
        ts = sorted(ts)
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        for t0, t1 in zip(ts, ts[1:]):
            a = (p0[0] + t0 * dx, p0[1] + t0 * dy)
            b = (p0[0] + t1 * dx, p0[1] + t1 * dy)
            tm = (t0 + t1) / 2
            m = (p0[0] + tm * dx, p0[1] + tm * dy)
            cls = None
            for q0, q1 in eb:
                if on_edge(m, q0, q1):
                    d = dx * (q1[0] - q0[0]) + dy * (q1[1] - q0[1])
                    cls = "same" if d > 0 else "opp"
                    break
            if cls is None:
                cls = "in" if winding(m, eb) != 0 else "out"
            out.append((a, b, cls))
    return out, touched


def _cr(a, b):
    return a[0] * b[1] - b[0] * a[1]


def evaluate_geoms(ga, gb):
    """Exact areas and predicates for two valid (multi)polygons given as JSON lists."""
    pa, pb = parse(ga), parse(gb)
    ea, eb = directed_edges(pa), directed_edges(pb)
    PA, touched = pieces(ea, eb)
    PB, _ = pieces(eb, ea)
    s = {k: ZERO for k in ("Ain", "Aout", "Asame", "Aopp", "Bin", "Bout", "Bsame", "Bopp")}
    have = {k: False for k in s}
    for tag, P in (("A", PA), ("B", PB)):
        for a, b, cls in P:
            s[tag + cls] += _cr(a, b)
            have[tag + cls] = True
    inter = (s["Ain"] + s["Bin"] + s["Asame"]) / 2
    union = (s["Aout"] + s["Bout"] + s["Asame"]) / 2
    diff_ab = (s["Aout"] - s["Bin"] + s["Aopp"]) / 2
    diff_ba = (s["Bout"] - s["Ain"] + s["Bopp"]) / 2
    area_a, area_b = area_of(pa), area_of(pb)
    selfcheck = (inter + diff_ab == area_a and inter + diff_ba == area_b
                 and union == inter + diff_ab + diff_ba)
    interiors_meet = have["Ain"] or have["Bin"] or have["Asame"]
    intersects = touched or have["Ain"] or have["Bin"] or have["Asame"] or have["Aopp"] \
        or have["Bsame"] or have["Bopp"]
    contains = not have["Bout"] and not have["Ain"] and not have["Aopp"]
    within = not have["Aout"] and not have["Bin"] and not have["Bopp"]
    return {
        "intersects": intersects,
        "disjoint": not intersects,
        "touches": intersects and not interiors_meet,
        "overlaps": interiors_meet and not contains and not within,
        "contains": contains,
        "covers": contains,
        "within": within,
        "covered_by": within,
        "equals": contains and within,
        "inter": inter, "union": union, "diff_ab": diff_ab, "diff_ba": diff_ba,
        "area_a": area_a, "area_b": area_b,
        "selfcheck": selfcheck,
    }


# --------------------------------------------------------------- convex-only routines

def convex_ccw(ring):
    """Closed JSON ring -> open CCW list of Fraction points (no repeats)."""
    pts = dedup([(fq(x), fq(y)) for x, y in ring])
    if pts[0] == pts[-1]:
        pts = pts[:-1]
    s = twice_signed_area(pts + [pts[0]])
    return pts if s > 0 else pts[::-1]


def sutherland_hodgman(subject, clip):
    """Exact clip of polygon `subject` by convex CCW polygon `clip` (closed half planes)."""
    out = list(subject)
    n = len(clip)
    for i in range(n):
        a, b = clip[i], clip[(i + 1) % n]
        inp, out = out, []
        if not inp:
            break
        for j in range(len(inp)):
            cur, prv = inp[j], inp[j - 1]
            cin, pin = _isleft(a, b, cur) >= 0, _isleft(a, b, prv) >= 0
            if cin:
                if not pin:
                    out.append(_line_x(prv, cur, a, b))
                out.append(cur)
            elif pin:
                out.append(_line_x(prv, cur, a, b))
    return out


def _line_x(p, q, a, b):
    """Intersection of segment pq with the line ab (pq known to cross it)."""
    dp, dq = _isleft(a, b, p), _isleft(a, b, q)
    t = dp / (dp - dq)
    return (p[0] + t * (q[0] - p[0]), p[1] + t * (q[1] - p[1]))


def poly_area(pts):
    if len(pts) < 3:
        return ZERO
    return twice_signed_area(list(pts) + [pts[0]]) / 2


def sat_intersects(P, Q):
    """Closed convex polygons (CCW, open lists) intersect iff no edge normal separates
    them strictly."""
    for A, B in ((P, Q), (Q, P)):
        n = len(A)
        for i in range(n):
            a, b = A[i], A[(i + 1) % n]
            if all(_isleft(a, b, q) < 0 for q in B):
                return False
    return True


def convex_evaluate(ra, rb):
    """Areas + predicates for two convex single rings, by clipping and SAT."""
    P, Q = convex_ccw(ra), convex_ccw(rb)
    inter = poly_area(sutherland_hodgman(P, Q))
    aa, ab = poly_area(P), poly_area(Q)
    inside = lambda pts, C: all(_isleft(C[i], C[(i + 1) % len(C)], p) >= 0
                                for p in pts for i in range(len(C)))
    contains = inside(Q, P)
    within = inside(P, Q)
    ix = sat_intersects(P, Q)
    return {
        "intersects": ix, "disjoint": not ix, "touches": ix and inter == 0,
        "overlaps": inter > 0 and not contains and not within,
        "contains": contains, "covers": contains, "within": within, "covered_by": within,
        "equals": contains and within,
        "inter": inter, "diff_ab": aa - inter, "diff_ba": ab - inter,
    }


# ------------------------------------------------------------------- ring simplicity

def ring_is_simple(ring):
    """Independent OGC simplicity test of one closed ring: consecutive duplicates are
    ignored; afterwards adjacent edges may meet only in their shared vertex and
    non-adjacent edges may not meet at all; at least 3 distinct vertices."""
    pts = dedup([(fq(x), fq(y)) for x, y in ring])
    if len(pts) < 2 or pts[0] != pts[-1]:
        return False
    pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return False
    E = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            c = contact_params(E[i][0], E[i][1], E[j][0], E[j][1])
            if j == i + 1:
                allowed = [ONE]
            elif i == 0 and j == n - 1:
                allowed = [ZERO]
            else:
                allowed = []
            if n == 3 and (i, j) == (0, 2):
                allowed = [ZERO]
            if c != allowed:
                return False
    return True
