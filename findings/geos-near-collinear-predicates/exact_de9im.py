"""Exact DE-9IM for two valid polygons/multipolygons (JSON MultiPolygon coords), built on
oracle_review/indep.py's exact boundary-piece classification."""
import sys, json
import os
ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
sys.path.insert(0, os.path.join(ROOT, "oracle_review"))
sys.path.insert(0, ROOT)
import indep
from indep import parse, directed_edges, pieces, ZERO

def exact_relate(ga, gb):
    pa, pb = parse(ga), parse(gb)
    ea, eb = directed_edges(pa), directed_edges(pb)
    PA, touched = pieces(ea, eb)
    PB, _ = pieces(eb, ea)
    r = indep.evaluate_geoms(ga, gb)
    hA = {c for _, _, c in PA}
    hB = {c for _, _, c in PB}
    II = "2" if ("in" in hA or "in" in hB or "same" in hA or r["inter"] > 0) else "F"
    IB = "1" if "in" in hB else "F"
    IE = "2" if r["diff_ab"] > 0 else "F"
    BI = "1" if "in" in hA else "F"
    BB = "1" if ("same" in hA or "opp" in hA) else ("0" if touched else "F")
    BE = "1" if "out" in hA else "F"
    EI = "2" if r["diff_ba"] > 0 else "F"
    EB = "1" if "out" in hB else "F"
    return II + IB + IE + BI + BB + BE + EI + EB + "2", r

def to_wkt(mp):
    def ring(r): return "(" + ", ".join(f"{x!r} {y!r}" for x, y in r) + ")"
    def poly(p): return "(" + ", ".join(ring(r) for r in p) + ")"
    if len(mp) == 1: return "POLYGON " + poly(mp[0])
    return "MULTIPOLYGON (" + ", ".join(poly(p) for p in mp) + ")"

if __name__ == "__main__":
    for line in open(sys.argv[1]):
        c = json.loads(line)
        m, r = exact_relate(c["a"], c["b"])
        print(c["id"], m, float(r["inter"]), float(r["diff_ab"]), float(r["diff_ba"]))
