"""Exact oracle for polygon/polygon predicates and overlay areas.

Every double is a rational number, so the true answer for the exact input
coordinates can be computed with rational arithmetic and no tolerance at all.
A library that disagrees on a predicate, or whose overlay area is off by more
than rounding can explain, is wrong for that input.

Geometry format (shared by all adapters, see FORMAT.md): a MultiPolygon as nested
lists, GeoJSON style, rings closed (first point repeated at the end):
    [ [ shell, hole, hole, ... ], [ shell, ... ], ... ]   with ring = [[x, y], ...]

Areas are computed by a vertical slab decomposition: cut the plane at the x of
every vertex and every edge/edge intersection. Inside an open slab no two edges
cross, so the edges spanning it are totally ordered by height, and the region
between two consecutive edges is a trapezoid lying wholly inside or outside each
operand (even-odd rule). Summing trapezoid areas by membership class gives
|A and B|, |A - B| and |B - A| exactly.

usage: python oracle.py cases.jsonl > oracle.jsonl
"""
import json
import math
import os
import sys

try:
    from gmpy2 import mpq as Q
except ImportError:  # pragma: no cover
    from fractions import Fraction as Q

ZERO = Q(0)
HALF = Q(1, 2)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "oracle_review"))
import validity  # noqa: E402  exact OGC/GEOS validity for any shape (review finding F3)


def num(v):
    """The exact value an adapter sees: JSON integers above 2^53 round like doubles (F4)."""
    return Q(float(v))


def fl(q):
    """float() that saturates instead of raising OverflowError on huge areas (F1)."""
    try:
        return float(q)
    except OverflowError:
        return math.inf


def rings(geom):
    for poly in geom:
        for ring in poly:
            yield [(num(x), num(y)) for x, y in ring]


def edges(geom):
    out = []
    for r in rings(geom):
        for p, q in zip(r, r[1:]):
            if p != q:
                out.append((p, q))
    return out


def orient(a, b, c):
    """Sign of the cross product (b - a) x (c - a): 1 left turn, -1 right, 0 collinear."""
    v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    return (v > 0) - (v < 0)


def on_segment(p, a, b):
    """p on the closed segment ab (p already known collinear with a, b)."""
    return min(a[0], b[0]) <= p[0] <= max(a[0], b[0]) and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])


def seg_intersect(a, b, c, d):
    """Closed segments ab and cd share at least one point."""
    o1, o2, o3, o4 = orient(a, b, c), orient(a, b, d), orient(c, d, a), orient(c, d, b)
    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and on_segment(c, a, b):
        return True
    if o2 == 0 and on_segment(d, a, b):
        return True
    if o3 == 0 and on_segment(a, c, d):
        return True
    if o4 == 0 and on_segment(b, c, d):
        return True
    return False


def crossing_x(a, b, c, d):
    """x coordinates where segments ab and cd meet (proper crossing or touch)."""
    xs = []
    denom = (b[0] - a[0]) * (d[1] - c[1]) - (b[1] - a[1]) * (d[0] - c[0])
    if denom != 0:
        t = ((c[0] - a[0]) * (d[1] - c[1]) - (c[1] - a[1]) * (d[0] - c[0])) / denom
        u = ((c[0] - a[0]) * (b[1] - a[1]) - (c[1] - a[1]) * (b[0] - a[0])) / denom
        if 0 <= t <= 1 and 0 <= u <= 1:
            xs.append(a[0] + t * (b[0] - a[0]))
    # collinear overlaps only meet at existing endpoints, already events
    return xs


def point_in(p, geom_edges):
    """Closed point-in-region test by even-odd rule: 1 inside, 0 on boundary, -1 outside."""
    inside = False
    for a, b in geom_edges:
        if orient(a, b, p) == 0 and on_segment(p, a, b):
            return 0
        if (a[1] > p[1]) != (b[1] > p[1]):
            x = a[0] + (p[1] - a[1]) * (b[0] - a[0]) / (b[1] - a[1])
            if x > p[0]:
                inside = not inside
    return 1 if inside else -1


def overlay_areas(ea, eb):
    """Exact areas of A and B, A - B, B - A, from the slab decomposition."""
    tagged = [(e, 0) for e in ea] + [(e, 1) for e in eb]
    xs = set()
    for (a, b), _ in tagged:
        xs.add(a[0])
        xs.add(b[0])
    alle = [e for e, _ in tagged]
    for i in range(len(alle)):
        a, b = alle[i]
        for j in range(i + 1, len(alle)):
            c, d = alle[j]
            if max(a[0], b[0]) < min(c[0], d[0]) or max(c[0], d[0]) < min(a[0], b[0]):
                continue
            if max(a[1], b[1]) < min(c[1], d[1]) or max(c[1], d[1]) < min(a[1], b[1]):
                continue
            xs.update(crossing_x(a, b, c, d))
    xs = sorted(xs)
    both = onlya = onlyb = ZERO
    for xl, xr in zip(xs, xs[1:]):
        active = []
        for (a, b), tag in tagged:
            if a[0] == b[0]:
                continue
            lo, hi = (a, b) if a[0] < b[0] else (b, a)
            if lo[0] <= xl and hi[0] >= xr:
                s = (hi[1] - lo[1]) / (hi[0] - lo[0])
                active.append((lo[1] + s * (xl - lo[0]), lo[1] + s * (xr - lo[0]), tag))
        active.sort(key=lambda t: t[0] + t[1])
        pa = pb = False
        w = (xr - xl) * HALF
        for (yl0, yr0, tag), (yl1, yr1, _) in zip(active, active[1:]):
            if tag == 0:
                pa = not pa
            else:
                pb = not pb
            area = w * ((yl1 - yl0) + (yr1 - yr0))
            if pa and pb:
                both += area
            elif pa:
                onlya += area
            elif pb:
                onlyb += area
    return both, onlya, onlyb


def intersects(ga, gb, ea, eb):
    for a, b in ea:
        for c, d in eb:
            if seg_intersect(a, b, c, d):
                return True
    # no boundary contact: each ring lies wholly inside or outside the other
    # geometry, so testing one vertex per ring decides it
    if any(point_in(r[0], eb) >= 0 for r in rings(ga)):
        return True
    if any(point_in(r[0], ea) >= 0 for r in rings(gb)):
        return True
    return False


def ring_simple(r):
    """Exact test that a closed ring is simple (the OGC/GEOS notion: no self-touch)."""
    pts = [r[0]]
    for p in r[1:]:
        if p != pts[-1]:
            pts.append(p)
    if pts[0] != pts[-1]:
        return False
    pts = pts[:-1]
    n = len(pts)
    if n < 3:
        return False
    es = [(pts[i], pts[(i + 1) % n]) for i in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            a, b = es[i]
            c, d = es[j]
            if j == i + 1 or (i == 0 and j == n - 1):
                # adjacent: may only share the common vertex, no fold-back
                shared, other_i, other_j = (b, a, d) if j == i + 1 else (a, b, c)
                if orient(other_i, shared, other_j) == 0:
                    if on_segment(other_j, other_i, shared) or on_segment(other_i, shared, other_j):
                        return False
                continue
            if seg_intersect(a, b, c, d):
                return False
    return True


def valid_single_polygon(geom):
    """Exact validity for one polygon without holes; None for other shapes."""
    if len(geom) != 1 or len(geom[0]) != 1:
        return None
    return ring_simple([(num(x), num(y)) for x, y in geom[0][0]])


def shoelace(geom):
    total = ZERO
    for poly in geom:
        for k, ring in enumerate(poly):
            r = [(num(x), num(y)) for x, y in ring]
            s = sum(p[0] * q[1] - q[0] * p[1] for p, q in zip(r, r[1:])) * HALF
            total += abs(s) if k == 0 else -abs(s)
    return total


def finite(geom):
    return all(math.isfinite(float(v)) for poly in geom for ring in poly for pt in ring for v in pt[:2])


def geom_valid(geom):
    """Exact validity of any shape (single ring, holes, multipolygon); False if non-finite."""
    if not finite(geom):
        return False
    return bool(validity.valid_geometry(geom))


def evaluate(case):
    a, b = case["a"], case["b"]
    va, vb = geom_valid(a), geom_valid(b)
    if not (va and vb):
        # nothing else is defined for invalid input, and compare.py reads nothing else (F2)
        return {"id": case["id"], "lib": "oracle", "valid_a": va, "valid_b": vb}
    ea, eb = edges(a), edges(b)
    both, da, db = overlay_areas(ea, eb)
    inter = intersects(a, b, ea, eb)
    res = {
        "id": case["id"],
        "lib": "oracle",
        "valid_a": va,
        "valid_b": vb,
        "intersects": inter,
        "disjoint": not inter,
        "touches": inter and both == 0,
        "overlaps": both > 0 and da > 0 and db > 0,
        "contains": db == 0,
        "covers": db == 0,
        "within": da == 0,
        "covered_by": da == 0,
        "equals": da == 0 and db == 0,
        "area_a": fl(both + da),
        "area_b": fl(both + db),
        "area_inter": fl(both),
        "area_union": fl(both + da + db),
        "area_diff": fl(da),
        "area_symdiff": fl(da + db),
        "exact": {"inter": str(both), "diff_ab": str(da), "diff_ba": str(db)},
    }
    # internal consistency: slab areas must agree with the shoelace formula
    assert both + da == shoelace(a) and both + db == shoelace(b), case["id"]
    return res


def main():
    for line in open(sys.argv[1]):
        if not line.strip():
            continue
        case = json.loads(line)
        try:
            res = evaluate(case)
        except Exception as e:  # noqa: BLE001  one bad case must not stop the run (F2)
            res = {"id": case.get("id"), "lib": "oracle", "oracle_error": repr(e)}
        print(json.dumps(res), flush=True)


if __name__ == "__main__":
    main()
