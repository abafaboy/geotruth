"""Exact answers for cases.jsonl and mixed-points/cases.jsonl (no JTS involved).

For every case:
  valid      geotruth.validity.is_valid (exact OGC validity) of both operands
  overlay    geotruth.overlay.overlay for the four operations (non-strict OverlayNG semantics),
             each with the independent certificate (certify=True)
  relate     geotruth.relate.relate (exact DE-9IM) and geotruth.relate_witness (second route)
Independent checks where they apply:
  polygon/polygon  tests/reference/oracle.py (slab areas) and tests/reference/indep.py (Green's
                   theorem on boundary pieces): intersection/union/difference areas
  point operand    tests/reference/indep.py classify_point (winding number) for the point
Scaling facts used by the write-up:
  2e170 == 2 * 1e170 and the 1e170 triangle is 1e170 * the unit triangle, exactly
  the corpus case line-polygon-1-000090 is 2^732 * the unit-scale copy in ScanScales.java, exactly
Grid case (mixed-points): the vertices snapped to the integer grid (PrecisionModel(1)), and the
  exact non-strict union of the snapped operands, which is what OverlayNG documents for a fixed
  precision model.

Run: PYTHONPATH=<geotruth>/src:<geotruth> python3 exact_check.py
"""
import json
import math
import os
import sys
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, ROOT)

from geotruth.io import geometry_from_json, read_wkt  # noqa: E402
from geotruth.overlay import overlay  # noqa: E402
from geotruth.relate import relate  # noqa: E402
from geotruth.relate_witness import relate_witness  # noqa: E402
from geotruth.validity import is_valid  # noqa: E402
from tests.reference import indep, oracle  # noqa: E402

OPS = ("intersection", "union", "difference", "symdifference")


def fmt_area(a):
    f = F(int(a.numerator), int(a.denominator)) if hasattr(a, "numerator") else F(a)
    if f == 0:
        return "0"
    if F(1, 10 ** 300) < abs(f) < F(10) ** 300:
        return f"~{float(f):.6g}"
    e = len(str(abs(f.numerator))) - len(str(f.denominator))
    return f"~1e{e} (outside the double range)"


def check_case(c):
    ga, gb = geometry_from_json(c["a"]), geometry_from_json(c["b"])
    print(f"=== {c['id']}")
    print(f"  A = {c['a_wkt']}")
    print(f"  B = {c['b_wkt']}")
    print(f"  valid (exact): A {is_valid(ga)}, B {is_valid(gb)}")
    m1, m2 = relate(ga, gb, strict=True).matrix, relate_witness(ga, gb).matrix
    print(f"  relate: {m1} (witness route {m2}: {'agree' if m1 == m2 else 'DISAGREE'})")
    for op in OPS:
        r = overlay(ga, gb, op, certify=True)
        cert = r.certificate
        cert_s = "certificate ok" if cert is not None and cert.ok else f"certificate {cert}"
        print(f"  {op:13s} {r.wkt}   [area {fmt_area(r.area)}; {cert_s}]")
    ta, tb = c["a"]["type"], c["b"]["type"]
    if ta in ("Polygon", "MultiPolygon") and tb in ("Polygon", "MultiPolygon"):
        mp = lambda g: [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]  # noqa: E731
        o = oracle.evaluate({"id": c["id"], "a": mp(c["a"]), "b": mp(c["b"])})
        i = indep.evaluate_geoms(mp(c["a"]), mp(c["b"]))
        ex = o["exact"]
        agree = (F(ex["inter"]) == i["inter"] and F(ex["diff_ab"]) == i["diff_ab"]
                 and F(ex["diff_ba"]) == i["diff_ba"])
        print(f"  oracle.py: valid {o['valid_a']}/{o['valid_b']}, area(A n B) {fmt_area(F(ex['inter']))}, "
              f"area(A - B) {ex['diff_ab']}, area(B - A) {ex['diff_ba']}, equals {o['equals']}")
        print(f"  indep.py:  area(A n B) {fmt_area(i['inter'])}, area(A u B) {fmt_area(i['union'])}, "
              f"area(A - B) {i['diff_ab']}, equals {i['equals']}, selfcheck {i['selfcheck']}; "
              f"oracle and indep {'agree' if agree else 'DISAGREE'}")
    if tb == "Point" and ta in ("Polygon", "MultiPolygon"):
        polys = [c["a"]["coordinates"]] if ta == "Polygon" else c["a"]["coordinates"]
        edges = indep.directed_edges(indep.parse(polys))
        p = tuple(F(v) for v in c["b"]["coordinates"])
        print(f"  indep.py classify_point(B, A) = {indep.classify_point(p, edges)}")
    return ga, gb


def main():
    for path in ("cases.jsonl", os.path.join("mixed-points", "cases.jsonl")):
        print(f"##### {path}")
        for line in open(os.path.join(HERE, path)):
            c = json.loads(line)
            check_case(c)
            if c["id"] == "min-mixed-points-collapse-grid1":
                grid_case(c)
            print()
    scaling_facts()


def grid_case(c):
    """Snap every vertex to the integer grid (PrecisionModel(1): round half up, Math.round)."""
    def snap(v):
        return math.floor(v + 0.5)
    tri = c["a"]["coordinates"][1][0]
    snapped = [(snap(x), snap(y)) for x, y in tri]
    area2 = indep.twice_signed_area([(F(x), F(y)) for x, y in snapped])
    print(f"  grid 1: the triangle {tri} snaps to {snapped}: twice its signed area is {area2}, so it "
          "collapses to the segment (3 0)-(5 0); the square and the point are on the grid already")
    snapped_a = read_wkt("GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), LINESTRING (3 0, 5 0))")
    b = read_wkt(c["b_wkt"])
    for op in ("union", "symdifference"):
        r = overlay(snapped_a, b, op, certify=True)
        print(f"  non-strict {op} of the snapped operands (what OverlayNG documents for this precision "
              f"model): {r.wkt}")


def scaling_facts():
    print("##### scaling facts")
    print(f"  float 2e170 == 2 * float 1e170: {2e170 == 2 * 1e170}; "
          f"float 1e170 is the integer {int(1e170)}")
    lead = json.loads(open(os.path.join(HERE, "cases.jsonl")).readline())
    unit_a = [[-1.6113333702087402, 1.6939971446990967], [-1.611332654953003, 1.6939942836761475],
              [-1.6113319396972656, 1.6939964294433594], [-1.6113333702087402, 1.6939971446990967]]
    same = all(math.ldexp(x, 732) == X and math.ldexp(y, 732) == Y
               for (x, y), (X, Y) in zip(unit_a, lead["a"]["coordinates"][0]))
    print(f"  corpus case polygon == 2^732 * the unit-scale polygon of ScanScales.java: {same}")
    print(f"  sqrt(Double.MAX_VALUE) = {math.sqrt(sys.float_info.max):.6g}: a tolerance above it has an "
          "infinite square in double arithmetic")
    print(f"  OverlayNGRobust snap tolerance for the 1e170 triangle: 2e170 / 1e12 = {2e170 / 1e12:.3g}, "
          f"squared in double: {(2e170 / 1e12) * (2e170 / 1e12)}")


if __name__ == "__main__":
    main()
