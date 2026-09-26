"""Shapely counterpart of repro.c (public Shapely API only): the same shapes at unit
scale (control) and at 1e-200.

    python3 repro.py
"""
import shapely
from shapely import wkt
from shapely.validation import explain_validity

nbad = 0


def rd(tmpl, unit):
    return wkt.loads(tmpl.replace("S", unit))


def check(what, fn, expected):
    global nbad
    try:
        got = fn()
    except Exception as e:  # noqa: BLE001
        got = "EXCEPTION %s" % e
    ok = got == expected
    nbad += not ok
    print("  %-28s %s (expected %s)%s" % (what, got, expected, "" if ok else "  <-- WRONG"))


def num(v):
    r = repr(float(v))
    return r[:-2] if r.endswith(".0") else r


def txt(g):
    # WKT with full double precision on every GEOS version (the GEOS 3.11 WKT writer
    # prints 1e-200 as 0), built from the coordinates.
    ring = lambda cs: "(" + ", ".join("%s %s" % (num(x), num(y)) for x, y in cs) + ")"
    if g.is_empty:
        return g.geom_type.upper() + " EMPTY"
    if g.geom_type == "Point":
        return "POINT (%s %s)" % (num(g.x), num(g.y))
    if g.geom_type == "Polygon":
        return "POLYGON (" + ", ".join(ring(r.coords) for r in [g.exterior, *g.interiors]) + ")"
    return g.wkt


def norm(g):
    return txt(shapely.normalize(g))


def run(unit):
    print('===== unit S = "%s" =====' % unit)
    t = rd("POLYGON ((0 0, 1S 0, 0 1S, 0 0))", unit)
    print("T =", txt(t))
    check("T.is_valid", lambda: t.is_valid, True)
    check("explain_validity(T)", lambda: explain_validity(t), "Valid Geometry")

    h = rd("POLYGON ((0 0, 4S 0, 4S 4S, 0 4S, 0 0), (1S 1S, 1S 2S, 2S 2S, 2S 1S, 1S 1S))", unit)
    print("H =", txt(h))
    check("H.is_valid", lambda: h.is_valid, True)

    a = rd("POLYGON ((0 0, 2S 0, 2S 2S, 0 2S, 0 0))", unit)
    p = rd("POINT (1S 1S)", unit)
    print("A =", txt(a))
    print("P =", txt(p), " (the centre of A)")
    check("A.contains(P)", lambda: a.contains(p), True)
    check("A.relate(P)", lambda: a.relate(p), "0F2FF1FF2")

    b = rd("POLYGON ((1S 1S, 3S 1S, 3S 3S, 1S 3S, 1S 1S))", unit)
    print("B =", txt(b))
    check("A.relate(B)", lambda: a.relate(b), "212101212")
    check("A.overlaps(B)", lambda: a.overlaps(b), True)
    check("A.touches(B)", lambda: a.touches(b), False)
    check("A.intersection(B)", lambda: norm(a.intersection(b)),
          norm(rd("POLYGON ((1S 1S, 2S 1S, 2S 2S, 1S 2S, 1S 1S))", unit)))
    check("A.union(B)", lambda: norm(a.union(b)),
          norm(rd("POLYGON ((0 0, 2S 0, 2S 1S, 3S 1S, 3S 3S, 1S 3S, 1S 2S, 0 2S, 0 0))", unit)))
    print()


print("shapely %s, GEOS %s\n" % (shapely.__version__, shapely.geos_version_string))
run("")
run("e-200")
print("%d wrong result(s)" % nbad)
