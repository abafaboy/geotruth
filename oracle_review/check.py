"""Adversarial checks of ../oracle.py on a case file.

usage: python check.py CASES.jsonl [--jobs 2] [--shapely] [--out failures.json]

Per case:
  oracle-crash      oracle.evaluate raised (message recorded)
  indep-*           the oracle differs from indep.py (independent exact implementation)
  convex-*          the oracle differs from exact Sutherland-Hodgman / separating axis
  prop-identity     predicate / area identities violated inside one oracle answer
  prop-swap         evaluate(B, A) is not the mirror of evaluate(A, B)
  prop-map          answer changes under an exact map (swap x/y, negate, scale by 2^k)
  prop-rerep        answer changes under a representation change (ring start, orientation,
                    repeated points, part order, hole order)
  shapely-*         (with --shapely, only for generic families) Shapely/GEOS disagrees
"""
import json
import math
import os
import random
import sys
from fractions import Fraction as F
from multiprocessing import Pool

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

import oracle  # noqa: E402
import indep  # noqa: E402

PRED = ["intersects", "disjoint", "touches", "overlaps", "contains", "covers", "within",
        "covered_by", "equals"]
MIRROR = {"contains": "within", "within": "contains", "covers": "covered_by",
          "covered_by": "covers"}
GENERIC = ("convex-float", "general-float")
SHAPELY = "--shapely" in sys.argv


def sf(q):
    """float() that saturates to +-inf instead of raising OverflowError."""
    try:
        return float(q)
    except OverflowError:
        return math.inf if q > 0 else -math.inf


def ex(res):
    return {k: F(v) for k, v in res["exact"].items()}


def mapgeom(g, f):
    return [[[list(f(x, y)) for x, y in ring] for ring in poly] for poly in g]


def rerep(g, rng):
    out = []
    for poly in g:
        rings = []
        for ring in poly:
            r = ring[:-1]
            j = rng.randrange(len(r))
            r = r[j:] + r[:j]
            if rng.random() < .5:
                r = r[::-1]
            j = rng.randrange(len(r))
            r = r[:j] + [r[j]] + r[j:]
            rings.append(r + [r[0]])
        rings = rings[:1] + rings[1:][::-1]
        out.append(rings)
    return out[::-1]


def is_convex_single(g):
    if len(g) != 1 or len(g[0]) != 1:
        return False
    pts = indep.dedup([(F(x), F(y)) for x, y in g[0][0]])[:-1]
    n = len(pts)
    if n < 3:
        return False
    sgn = 0
    for i in range(n):
        a, b, c = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
        cr = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if cr != 0:
            s = 1 if cr > 0 else -1
            if sgn and s != sgn:
                return False
            sgn = s
    return sgn != 0


def check_case(line):
    case = json.loads(line)
    cid, fam = case["id"], case.get("family", "")
    rng = random.Random(cid)
    fails = []

    def fail(kind, **info):
        fails.append({"id": cid, "family": fam, "kind": kind, **info})

    try:
        o = oracle.evaluate(case)
    except Exception as e:  # noqa: BLE001
        fail("oracle-crash", error=f"{type(e).__name__}: {e}")
        return cid, fam, fails
    oe = ex(o)

    # inputs must be valid for any comparison to mean something
    def geom_valid(g, v):
        """Exact single-ring validity from the oracle; otherwise GEOS on a copy scaled by
        an exact power of two to magnitude ~1 (GEOS validity underflows on tiny inputs,
        e.g. valid grid geometry scaled by 2^-600 is reported self-intersecting)."""
        if v is not None:
            return v
        from shapely.geometry import MultiPolygon, Polygon
        m = max(abs(c) for poly in g for ring in poly for p in ring for c in p) or 1.0
        e = math.frexp(m)[1]
        g2 = mapgeom(g, lambda x, y: (math.ldexp(x, -e), math.ldexp(y, -e)))
        if mapgeom(g2, lambda x, y: (math.ldexp(x, e), math.ldexp(y, e))) != g:
            g2 = g  # normalisation not exact: fall back to the raw input
        ps = [Polygon(p[0], p[1:]) for p in g2]
        return bool((ps[0] if len(ps) == 1 else MultiPolygon(ps)).is_valid)
    if not (geom_valid(case["a"], o["valid_a"]) and geom_valid(case["b"], o["valid_b"])):
        fail("skipped-invalid-input")
        return cid, fam, fails

    # --- independent exact implementation
    try:
        r = indep.evaluate_geoms(case["a"], case["b"])
    except Exception as e:  # noqa: BLE001
        fail("indep-crash", error=repr(e))
        r = None
    if r is not None:
        if not r["selfcheck"]:
            fail("indep-selfcheck")
        for p in PRED:
            if o[p] != r[p]:
                fail("indep-predicate", key=p, oracle=o[p], indep=r[p])
        for k in ("inter", "diff_ab", "diff_ba"):
            if oe[k] != r[k]:
                fail("indep-area", key=k, oracle=str(oe[k]), indep=str(r[k]))
        if oe["inter"] + oe["diff_ab"] != r["area_a"] or oe["inter"] + oe["diff_ba"] != r["area_b"]:
            fail("prop-identity", what="inter+diff != independent shoelace area")

    # --- identities inside one answer
    ids = {
        "disjoint==!intersects": o["disjoint"] == (not o["intersects"]),
        "touches=>intersects&inter0": (not o["touches"]) or (o["intersects"] and oe["inter"] == 0),
        "equals==contains&within": o["equals"] == (o["contains"] and o["within"]),
        "overlaps=>!contains&!within": (not o["overlaps"]) or not (o["contains"] or o["within"]),
        "contains=>intersects": (not o["contains"]) or o["intersects"],
        "within=>intersects": (not o["within"]) or o["intersects"],
        "covers==contains": o["covers"] == o["contains"],
        "covered_by==within": o["covered_by"] == o["within"],
        "inter>0=>intersects": oe["inter"] == 0 or o["intersects"],
        "nonneg": min(oe.values()) >= 0,
        "union==a+b-inter": o["area_union"] == sf(oe["inter"] + oe["diff_ab"] + oe["diff_ba"]),
        "exactly-one-of(disjoint,touches,interiors)": (o["disjoint"] + o["touches"] + (oe["inter"] > 0)) == 1,
    }
    for k, ok in ids.items():
        if not ok:
            fail("prop-identity", what=k)

    # --- swap symmetry
    try:
        s = oracle.evaluate({"id": cid, "a": case["b"], "b": case["a"]})
        se = ex(s)
        if se["inter"] != oe["inter"] or se["diff_ab"] != oe["diff_ba"] or se["diff_ba"] != oe["diff_ab"]:
            fail("prop-swap", what="areas")
        for p in PRED:
            if s[MIRROR.get(p, p)] != o[p]:
                fail("prop-swap", what=p)
    except Exception as e:  # noqa: BLE001
        fail("oracle-crash", error=f"swap: {type(e).__name__}: {e}")

    # --- exact map (only when it is exact: power-of-two scale kept in normal range)
    sw, nx, ny = rng.random() < .5, rng.choice([1, -1]), rng.choice([1, -1])
    k = rng.randint(-20, 20)
    coords = [abs(c) for poly in case["a"] + case["b"] for ring in poly for p in ring for c in p if c]
    if coords and min(coords) * 2.0 ** k > 2.0 ** -1000 and max(coords) * 2.0 ** k < 2.0 ** 500:
        def f(x, y):
            if sw:
                x, y = y, x
            return (math.ldexp(nx * x, k), math.ldexp(ny * y, k))
        try:
            m = oracle.evaluate({"id": cid, "a": mapgeom(case["a"], f), "b": mapgeom(case["b"], f)})
            me = ex(m)
            sc = F(2) ** (2 * k)
            if any(me[q] != oe[q] * sc for q in oe):
                fail("prop-map", what="areas", k=k, swap=sw)
            for p in PRED:
                if m[p] != o[p]:
                    fail("prop-map", what=p, k=k, swap=sw)
        except Exception as e:  # noqa: BLE001
            fail("oracle-crash", error=f"map: {type(e).__name__}: {e}")

    # --- representation change
    try:
        m = oracle.evaluate({"id": cid, "a": rerep(case["a"], rng), "b": rerep(case["b"], rng)})
        me = ex(m)
        if me != oe:
            fail("prop-rerep", what="areas")
        for p in PRED:
            if m[p] != o[p]:
                fail("prop-rerep", what=p)
    except Exception as e:  # noqa: BLE001
        fail("oracle-crash", error=f"rerep: {type(e).__name__}: {e}")

    # --- convex route
    if is_convex_single(case["a"]) and is_convex_single(case["b"]):
        c = indep.convex_evaluate(case["a"][0][0], case["b"][0][0])
        for p in PRED:
            if o[p] != c[p]:
                fail("convex-predicate", key=p, oracle=o[p], convex=c[p])
        for q in ("inter", "diff_ab", "diff_ba"):
            if oe[q] != c[q]:
                fail("convex-area", key=q, oracle=str(oe[q]), convex=str(c[q]))

    # --- Shapely on generic inputs
    if SHAPELY and fam.startswith(GENERIC):
        import shapely
        from shapely.geometry import MultiPolygon, Polygon

        def build(mp):
            ps = [Polygon(p[0], p[1:]) for p in mp]
            return ps[0] if len(ps) == 1 else MultiPolygon(ps)
        A, B = build(case["a"]), build(case["b"])
        for p in PRED:
            got = bool(getattr(A, p)(B))
            if got != o[p]:
                fail("shapely-predicate", key=p, oracle=o[p], shapely=got)
        scale = max(o["area_a"], o["area_b"])
        for key, got, exv in (("inter", A.intersection(B).area, oe["inter"]),
                              ("diff_ab", A.difference(B).area, oe["diff_ab"]),
                              ("diff_ba", B.difference(A).area, oe["diff_ba"])):
            if abs(got - float(exv)) > 1e-9 * scale:
                fail("shapely-area", key=key, oracle=float(exv), shapely=got)
    return cid, fam, fails


def main():
    path = sys.argv[1]
    jobs = int(sys.argv[sys.argv.index("--jobs") + 1]) if "--jobs" in sys.argv else 2
    out = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None
    lines = [ln for ln in open(path) if ln.strip()]
    counts, per_fam, allfails = {}, {}, []
    with Pool(jobs) as pool:
        for cid, fam, fails in pool.imap_unordered(check_case, lines, chunksize=4):
            top = fam.split("/")[0]
            per_fam[top] = per_fam.get(top, 0) + 1
            for f in fails:
                key = (top, f["kind"])
                counts[key] = counts.get(key, 0) + 1
                allfails.append(f)
    print(f"cases: {len(lines)}  by family: {json.dumps(per_fam, sort_keys=True)}")
    if not counts:
        print("no failures")
    for (fam, kind), n in sorted(counts.items()):
        print(f"  {fam:18s} {kind:20s} {n}")
    if out:
        with open(out, "w") as fh:
            json.dump(allfails, fh, indent=1)


if __name__ == "__main__":
    main()
