"""Diagnostic only: re-evaluates GEOS's orientationIndexFilter
(include/geos/algorithm/CGAlgorithmsDD.h:97-111) in Python floats (IEEE-754 binary64,
round-to-nearest, like the compiled C++ without FMA contraction) for the triples of
primitives_scaling.c, to show which step decides the wrong answers.

    python3 diag_filter_emulation.py
"""
import math

C = 3.3306690621773724e-16


def filt(p1x, p1y, p2x, p2y, qx, qy):
    # orientationIndexFilter(pa=p1, pb=p2, pc=q), as called from orientationIndex
    detleft = (p1x - qx) * (p2y - qy)
    detright = (p1y - qy) * (p2x - qx)
    det = detleft - detright
    error = abs(detleft + detright) * C
    if abs(det) >= error:
        return "decides %+d" % ((det > 0) - (det < 0)), detleft, detright, det, error
    return "defers to DD", detleft, detright, det, error


for name, t, ks in [("A=(0 0) B=(1 0) P=(0 1)", (0.0, 0.0, 1.0, 0.0, 0.0, 1.0), [0, -537, -538, 512]),
                    ("A=(-1.6 1.2) B=(-3.2 -1.8) P=(-6.4 -7.8)", (-1.6, 1.2, -3.2, -1.8, -6.4, -7.8),
                     [0, -510, -514, -520, 512])]:
    print(name)
    for k in ks:
        s = [math.ldexp(v, k) for v in t]
        r, dl, dr, det, err = filt(*s)
        print("  2^%-5d detleft=%-24r detright=%-24r det=%-10r error=%-10r -> %s" % (k, dl, dr, det, err, r))
