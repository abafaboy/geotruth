import sys
import os
GEOTRUTH_ROOT = os.path.abspath(__file__ + "/../../../..")  # the geotruth checkout
sys.path.insert(0, GEOTRUTH_ROOT + "/src")
from geotruth.predicates import transpose
from collections import Counter
tot = Counter()
for name in sys.argv[1:]:
    ex = [l.strip() for l in open(f"{name}.exact")]
    def ok(b):
        return [o.split()[0] == e and o.split()[1] == transpose(e) for o, e in zip(open(f"{name}.{b}"), ex)]
    main, eX, M, N, HV, allv = (ok(b) for b in ("main", "eX", "eXM", "eXN", "eXHV", "eallV"))
    c = Counter()
    for i in range(len(ex)):
        if main[i]:
            c["main ok"] += 1; continue
        if eX[i]:
            c["fixed by known fixes (X/SEG/P1/P3)"] += 1; continue
        k = tuple(n for n, v in (("D1", M[i]), ("D2", N[i]), ("D3", HV[i])) if v)
        if k:
            c["fixed by " + "|".join(k)] += 1
        elif allv[i]:
            c["needs combination"] += 1
        else:
            c["unfixed (inexact node)"] += 1
    print(name, len(ex), dict(c)); tot.update(c)
print("TOTAL", dict(tot))
