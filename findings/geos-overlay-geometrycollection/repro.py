"""The GEOS GeometryCollection overlay defects through Shapely (public API only).

shapely.symmetric_difference / difference / intersection call GEOSSymDifference_r etc.
(HeuristicOverlay); with grid_size=0 they call the *Prec_r functions, i.e. OverlayNG
directly, which is shown as a control.

Run: python3 repro.py
"""
import shapely
from shapely import wkt

CASES = [
    # (name, A, B, op, exact)
    ("1a symdiff, GC(one polygon) vs point outside",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))", "POINT (3 3)",
     "symmetric_difference", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)), POINT (3 3))"),
    ("1b symdiff, GC(POLYGON EMPTY) vs point",
     "GEOMETRYCOLLECTION (POLYGON EMPTY)", "POINT (1 1)",
     "symmetric_difference", "POINT (1 1)"),
    ("1c symdiff, point on the line of a mixed GC",
     "POINT (1 0)", "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))",
     "symmetric_difference", "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))"),
    ("1d symdiff of equal point sets (square + inner line vs square)",
     "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (0 1, 2 1))",
     "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))", "symmetric_difference", "POLYGON EMPTY"),
    ("2a difference, point on the line of a mixed GC",
     "POINT (1 0)", "GEOMETRYCOLLECTION (LINESTRING (0 0, 2 0), POINT (3 3))",
     "difference", "POINT EMPTY"),
    ("3a intersection, GC(POLYGON EMPTY) vs point",
     "GEOMETRYCOLLECTION (POLYGON EMPTY)", "POINT (1 1)", "intersection", "POINT EMPTY"),
    ("3b intersection, POINT EMPTY vs GC(one polygon)",
     "POINT EMPTY", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))",
     "intersection", "POINT EMPTY"),
    ("3c difference, POINT EMPTY minus GC(one polygon)",
     "POINT EMPTY", "GEOMETRYCOLLECTION (POLYGON ((0 0, 4 0, 0 4, 0 0)))",
     "difference", "POINT EMPTY"),
    ("3d intersection, mixed GC vs MULTIPOLYGON EMPTY",
     "GEOMETRYCOLLECTION (POINT (0 2), LINESTRING (0 0, 6 0))", "MULTIPOLYGON EMPTY",
     "intersection", "LINESTRING EMPTY"),
    ("4a (secondary) intersection, point on a line of the GC; the GC's lines cross at (1.2 3.2)",
     "POINT (3 2)", "GEOMETRYCOLLECTION (MULTILINESTRING ((0 2, 2 4), (0 4, 6 0)), POINT (9 9))",
     "intersection", "POINT (3 2)"),
    ("4b (secondary) intersection, segment on a line of the GC",
     "LINESTRING (3 2, 6 0)", "GEOMETRYCOLLECTION (MULTILINESTRING ((0 2, 2 4), (0 4, 6 0)), POINT (9 9))",
     "intersection", "LINESTRING (3 2, 6 0)"),
    ("5a (minor) intersection, GC(line, GEOMETRYCOLLECTION EMPTY)",
     "LINESTRING (0 0, 1 1)", "GEOMETRYCOLLECTION (LINESTRING (0 1, 1 0), GEOMETRYCOLLECTION EMPTY)",
     "intersection", "POINT (0.5 0.5)"),
]


def run(fn, a, b, **kw):
    try:
        return fn(a, b, **kw)
    except Exception as exc:  # GEOSException
        return f"{type(exc).__name__}: {exc}"


def verdict(res, exact, prec=False):
    if isinstance(res, str):
        return "   (documented: OverlayNG rejects a mixed-dimension GC)" \
            if prec and "mixed-dimension" in res else "   <-- EXCEPTION"
    if not res.equals(exact):
        return "   <-- WRONG (point set differs)"
    if exact.is_empty and res.geom_type != exact.geom_type:
        return "   (same point set, other empty type)"
    return "   ok"


print(f"shapely {shapely.__version__}, GEOS {shapely.geos_version_string}")
for name, a, b, op, exact in CASES:
    ga, gb, gx = wkt.loads(a), wkt.loads(b), wkt.loads(exact)
    fn = getattr(shapely, op)
    print(f"\n{name}\n  A = {a}\n  B = {b}\n  valid: A={shapely.is_valid(ga)} B={shapely.is_valid(gb)}")
    print("  exact".ljust(28) + exact)
    r = run(fn, ga, gb)
    print(f"  {op}(A, B)".ljust(28) + f"{r if isinstance(r, str) else r.wkt}{verdict(r, gx)}")
    r = run(fn, ga, gb, grid_size=0)
    print("  ... grid_size=0".ljust(28) + f"{r if isinstance(r, str) else r.wkt}{verdict(r, gx, True)}")
