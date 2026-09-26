"""Same cases as repro.c, through Shapely (public API only), plus an exact check of where
the critical vertex lies, using only the standard library.

    python3 repro.py
"""
from fractions import Fraction

import shapely
from shapely import wkt

print(f"shapely {shapely.__version__}, GEOS {shapely.geos_version_string}\n")

A = wkt.loads("POLYGON ((0 0, 3 0, 3 1, 0 0))")
CASES = [
    ("Case 1", "POLYGON ((2 2, 1 2, 2 0.6666666666666666, 2 2))", (2.0, 0.6666666666666666)),
    ("Case 2", "POLYGON ((2.5 0.5, 3 0.5, 2.5 0.8333333333333334, 2.5 0.5))", (2.5, 0.8333333333333334)),
]


def side_of_edge(p, a=(3.0, 1.0), b=(0.0, 0.0)):
    """Exact sign of cross(b - a, p - a): > 0 means p is left of a->b, i.e. inside the CCW
    triangle A (whose edge (3 1)->(0 0) is the hypotenuse)."""
    ax, ay, bx, by, px, py = map(Fraction, (*a, *b, *p))
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


for name, wkt_b, p in CASES:
    B = wkt.loads(wkt_b)
    P = shapely.Point(p)
    d = side_of_edge(p)
    print(f"{name}: A = {A.wkt}\n        B = {B.wkt}")
    print(f"  valid: {A.is_valid}, {B.is_valid}")
    print(f"  exact: vertex P = {P.wkt} of B is {'INSIDE' if d > 0 else 'OUTSIDE' if d < 0 else 'ON'} A "
          f"(cross product = {d} = {float(d):.3g}; exact y = {Fraction(p[1])}, x/3 = {Fraction(p[0]) / 3})")
    print(f"  relate(A, B) = {A.relate(B)}   (exact: 212101212)")
    print(f"  touches={A.touches(B)} overlaps={A.overlaps(B)} contains={A.contains(B)} covers={A.covers(B)}")
    print(f"  A.contains(P)={A.contains(P)}  A.intersects(P)={A.intersects(P)}  B.intersects(P)={B.intersects(P)}")
    print()
