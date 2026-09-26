"""For cases wrong in a build: does the exact arrangement have a non-dyadic intersection point
(GEOS cannot represent it: the known inexact-node class)? python3 inexact.py NAME build"""
import sys
sys.path[:0] = ["/home/user/geotruth/src"]
from geotruth.io import read_wkt
from geotruth.predicates import transpose
from geotruth.relate_witness import relate_witness
name, b = sys.argv[1:3]
rows = [l.rstrip("\n").split("\t") for l in open(f"{name}.tsv")]
ex = [l.strip() for l in open(f"{name}.exact")]
out = [l.split() for l in open(f"{name}.{b}")]
from collections import Counter
c = Counter()
for i, ((a, bb), e, o) in enumerate(zip(rows, ex, out)):
    if o[0] == e and o[1] == transpose(e):
        continue
    res = relate_witness(read_wkt(a), read_wkt(bb), keep_witnesses=True)
    inexact = any(w.kind == "intersection" and w.point[2] & (w.point[2] - 1) for w in res.witnesses)
    c[inexact] += 1
    if not inexact:
        print("NOT inexact:", i, e, o[0], o[1])
print(name, b, "wrong cases with a non-dyadic intersection point:", dict(c))
