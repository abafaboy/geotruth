"""Exact (rational) check of every expected answer in repro.c / repro.py / Repro.java.

Uses Python's Fraction (every double converts exactly) and the independent exact
implementation in ../../oracle_review (indep.py, validity.py). No GEOS involved.

    python3 exact_check.py
"""
import os
import sys
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "oracle_review"))
import indep  # noqa: E402
import validity  # noqa: E402

s1, s2, s3, s4 = 1e-200, 2e-200, 3e-200, 4e-200
S1, S2, S3, S4 = F(s1), F(s2), F(s3), F(s4)

print("1. The input doubles, exactly")
print("   0 < 1e-200 < 2e-200 < 3e-200 < 4e-200 :", 0 < S1 < S2 < S3 < S4)
print("   2e-200 == 2*1e-200 and 4e-200 == 4*1e-200 exactly:", S2 == 2 * S1, S4 == 4 * S1)

print("\n2. Orientation of (0 0), (1e-200 0), (0 1e-200)")
det_exact = (S1 - 0) * (S1 - 0) - (0 - 0) * (0 - 0)
print("   exact determinant = (1e-200)^2 > 0 :", det_exact > 0, " (about 1e-400)")
print("   the same products in double arithmetic: 1e-200 * 1e-200 =", s1 * s1)
print("   -> in doubles both products are 0, so det = 0 and the points look collinear")
lo, hi = 1e-163, 1e-161
for _ in range(200):  # bisect for the smallest s with s*s > 0 in doubles
    mid = (lo + hi) / 2
    if mid * mid > 0:
        hi = mid
    else:
        lo = mid
print("   s*s rounds to 0 in doubles for s below about %.6g (= 2^-537.5)" % hi)

print("\n3. Validity (exact OGC rules, oracle_review/validity.py)")
T = [[[[0.0, 0.0], [s1, 0.0], [0.0, s1], [0.0, 0.0]]]]
H = [[[[0.0, 0.0], [s4, 0.0], [s4, s4], [0.0, s4], [0.0, 0.0]],
      [[s1, s1], [s1, s2], [s2, s2], [s2, s1], [s1, s1]]]]
print("   T = POLYGON ((0 0, 1e-200 0, 0 1e-200, 0 0)) valid:", validity.valid_geometry(T),
      "| ring simple (indep):", indep.ring_is_simple(T[0][0]))
print("   H = square [0,4e-200]^2 with hole [1e-200,2e-200]^2 valid:", validity.valid_geometry(H))

print("\n4. Point P = (1e-200 1e-200) against A = [0,2e-200]^2")
A = [[[[0.0, 0.0], [s2, 0.0], [s2, s2], [0.0, s2], [0.0, 0.0]]]]
B = [[[[s1, s1], [s3, s1], [s3, s3], [s1, s3], [s1, s1]]]]
edges_a = indep.directed_edges(indep.parse(A))
print("   location of P in A:", indep.classify_point((S1, S1), edges_a),
      " -> contains(A, P) = true, relate(A, P) = 0F2FF1FF2")

print("\n5. A = [0,2e-200]^2 and B = [1e-200,3e-200]^2")
r = indep.evaluate_geoms(A, B)
print("   intersects=%s touches=%s overlaps=%s contains=%s within=%s" %
      (r["intersects"], r["touches"], r["overlaps"], r["contains"], r["within"]))
print("   exact area(A n B) == (1e-200)^2 :", r["inter"] == S1 * S1, "(> 0, so interiors meet)")
print("   exact area(A u B) == 7*(1e-200)^2 :", r["union"] == 7 * S1 * S1)
print("   -> relate(A, B) = 212101212; A n B = [1e-200,2e-200]^2;"
      " A u B = the 8-vertex union of both squares")

print("\n6. Segment (2e-200 0)-(2e-200 2e-200) against (1e-200 1e-200)-(3e-200 1e-200)")
c = indep.contact_params((S2, F(0)), (S2, S2), (S1, S1), (S3, S1))
pt = (S2, 0 + c[0] * (S2 - 0)) if len(c) == 1 else None
print("   contact parameters:", [str(t) for t in c], "-> point", pt and (float(pt[0]), float(pt[1])),
      "== (2e-200, 1e-200):", pt == (S2, S1))

print("\n7. primitives_scaling.c: exact orientation of the three triples")
import math  # noqa: E402
TRIPLES = [("A=(0 0) B=(1 0) P=(0 1)", (0.0, 0.0, 1.0, 0.0, 0.0, 1.0)),
           ("A=(-1.6 1.2) B=(-3.2 -1.8) P=(-6.4 -7.8)", (-1.6, 1.2, -3.2, -1.8, -6.4, -7.8)),
           ("A=(0 0) B=(1 1) P=(2 2+2^-40)", (0.0, 0.0, 1.0, 1.0, 2.0, 2.0 + 2.0 ** -40))]
KS = [0, -400, -500, -505, -510, -514, -520, -530, -537, -538, -540, -600, -1000,
      400, 500, 505, 508, 510, 512, 600, 1000]
for name, t in TRIPLES:
    signs = set()
    for k in KS:
        s = [math.ldexp(v, k) for v in t]
        assert all(math.ldexp(v, -k) == w for v, w in zip(s, t)), "scaling not exact"
        ax, ay, bx, by, px, py = map(F, s)
        det = (bx - ax) * (py - by) - (by - ay) * (px - bx)
        signs.add((det > 0) - (det < 0))
    ax, ay, bx, by, px, py = map(F, t)
    det1 = (bx - ax) * (py - by) - (by - ay) * (px - bx)
    print("   %-42s exact det at unit scale = %s; sign at every 2^k listed: %s"
          % (name, det1, sorted(signs)))
