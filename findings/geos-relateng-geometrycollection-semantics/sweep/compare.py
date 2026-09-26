"""python3 compare.py NAME build... : compare rb-<build> outputs NAME.<build> with NAME.exact.
Prints per build: cases wrong in relate(A,B) / relate(B,A) / any named predicate of (A,B), and diff signatures."""
import sys
from collections import Counter
import os
GEOTRUTH_ROOT = os.path.abspath(__file__ + "/../../../..")  # the geotruth checkout
sys.path.insert(0, GEOTRUTH_ROOT + "/src")
from geotruth.io import read_wkt
from geotruth.predicates import predicates, transpose
E = ("II", "IB", "IE", "BI", "BB", "BE", "EI", "EB", "EE")
PN = ("intersects", "contains", "within", "covers", "covered_by", "touches", "overlaps", "crosses")
def sig(ex, got):
    return ",".join(f"{E[i]}:{ex[i]}->{got[i]}" for i in range(9) if ex[i] != got[i])
def load(name, build):
    return [l.split() for l in open(f"{name}.{build}")]
def main():
    name, builds = sys.argv[1], sys.argv[2:]
    rows = [l.rstrip("\n").split("\t") for l in open(f"{name}.tsv")]
    exact = [l.strip() for l in open(f"{name}.exact")]
    dims = []
    for a, b in rows:
        ga, gb = read_wkt(a), read_wkt(b)
        dims.append((ga.real_dimension, gb.real_dimension))
    for build in builds:
        out = load(name, build)
        c = Counter(); sigs = Counter(); psig = Counter()
        for (a, b), ex, (da, db), o in zip(rows, exact, dims, out):
            m1, m2, bits = o
            w1, w2 = m1 != ex, m2 != transpose(ex)
            pe = predicates(ex, da, db)
            wrongp = [PN[i] for i in range(8) if int(bits[i]) != int(pe[PN[i]])]
            c["AB wrong"] += w1; c["BA wrong"] += w2; c["pred wrong"] += bool(wrongp)
            if w1: sigs["AB " + sig(ex, m1)] += 1
            if w2: sigs["BA " + sig(transpose(ex), m2)] += 1
            for p in wrongp: psig[p] += 1
        print(f"== {name} {build}: {len(rows)} cases, {dict(c)}; predicates wrong: {dict(psig)}")
        for s, k in sigs.most_common(12):
            print(f"   {k:5d}  {s}")
main()
