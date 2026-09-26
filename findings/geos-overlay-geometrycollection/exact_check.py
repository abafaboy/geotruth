"""Exact answers and independent checks for cases.jsonl.

For every case:
  valid        geotruth.validity.is_valid (exact, GEOS-default rules) and GEOS isValid
               (Shapely) on both operands
  exact        geotruth.overlay.overlay(..., certify=True): the exact result, checked by the
               independent certificate of geotruth.overlay_certify; must equal the recorded
               'exact' field
  GEOS         the recorded GEOS main / 3.15.0 result, certified as a point set against
               the operands (structure=False): a failed certificate names a witness point
               that GEOS puts in the wrong place
  hand         the one geometric fact each case rests on, decided with
               tests/reference/indep.py (Fraction arithmetic, no geotruth code)

Run: PYTHONPATH=<geotruth>/src python3 exact_check.py [cases.jsonl]
"""
import json
import sys
from fractions import Fraction as F
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path[:0] = [str(REPO / "src"), str(REPO / "tests")]

from geotruth.io import canonicalize, read_wkt, to_wkt  # noqa: E402
from geotruth.overlay import overlay  # noqa: E402
from geotruth.overlay_certify import certify  # noqa: E402
from geotruth.validity import is_valid  # noqa: E402
from reference import indep  # noqa: E402

try:
    import shapely
except ImportError:  # GEOS validity is optional
    shapely = None

TRI = [[[(0, 0), (4, 0), (0, 4), (0, 0)]]]          # the triangle of cases 1a, 3b, 3c
SQUARE = [[[(0, 0), (2, 0), (2, 2), (0, 2), (0, 0)]]]  # the square of case 1d


def P(x, y):
    return (F(x), F(y))


def hand_facts(case_id):
    """(statement, value, expected value) for the fact the case rests on."""
    tri = indep.directed_edges(indep.parse(TRI))
    sq = indep.directed_edges(indep.parse(SQUARE))
    facts = {
        "1a": [("POINT (3 3) vs the triangle", indep.classify_point(P(3, 3), tri), "out")],
        "1b": [("GC(POLYGON EMPTY) has no points: A xor B = B", True, True)],
        "1c": [("(1 0) on segment (0 0)-(2 0)", indep.on_edge(P(1, 0), P(0, 0), P(2, 0)), True),
               ("(3 3) on segment (0 0)-(2 0)", indep.on_edge(P(3, 3), P(0, 0), P(2, 0)), False)],
        "1d": [("(0 1) on the square's boundary", indep.classify_point(P(0, 1), sq), "on"),
               ("(2 1) on the square's boundary", indep.classify_point(P(2, 1), sq), "on"),
               ("(1 1) inside the square", indep.classify_point(P(1, 1), sq), "in")],
        "1e": [("(1 1) vs the triangle", indep.classify_point(P(1, 1), tri), "in"),
               ("(2 2) vs the triangle", indep.classify_point(P(2, 2), tri), "on"),
               ("(6 6) vs the triangle", indep.classify_point(P(6, 6), tri), "out")],
        "2a": [("(1 0) on segment (0 0)-(2 0)", indep.on_edge(P(1, 0), P(0, 0), P(2, 0)), True)],
        "3a": [("an empty operand: the intersection is empty", True, True)],
        "3b": [("an empty operand: the intersection is empty", True, True)],
        "3c": [("an empty first operand: the difference is empty", True, True)],
        "3d": [("an empty operand: the intersection is empty", True, True)],
        "4a": [("(3 2) on segment (0 4)-(6 0)", indep.on_edge(P(3, 2), P(0, 4), P(6, 0)), True)],
        "4b": [("(3 2) on segment (0 4)-(6 0)", indep.on_edge(P(3, 2), P(0, 4), P(6, 0)), True),
               ("(6 0) on segment (0 4)-(6 0)", indep.on_edge(P(6, 0), P(0, 4), P(6, 0)), True)],
        "5a": [("(1/2 1/2) on both segments",
                indep.on_edge(P(F(1, 2), F(1, 2)), P(0, 0), P(1, 1))
                and indep.on_edge(P(F(1, 2), F(1, 2)), P(0, 1), P(1, 0)), True)],
    }
    return facts[case_id.split("-")[0]]


def main(path):
    ok_all = True
    if shapely is not None:
        print(f"GEOS isValid via shapely {shapely.__version__} (GEOS {shapely.geos_version_string})")
    for line in open(path):
        c = json.loads(line)
        a, b = read_wkt(c["a"]), read_wkt(c["b"])
        print(f"\n{c['id']}  {c['op']}  [{c['defect']}]\n  A = {c['a']}\n  B = {c['b']}")
        gv = ""
        if shapely is not None:
            gv = (f"; GEOS isValid A={shapely.is_valid(shapely.from_wkt(c['a']))}"
                  f" B={shapely.is_valid(shapely.from_wkt(c['b']))}")
        print(f"  valid (exact) A={is_valid(a)} B={is_valid(b)}{gv}")
        res = overlay(a, b, c["op"], certify=True)
        mine = to_wkt(canonicalize(res.geometry))
        want = to_wkt(canonicalize(read_wkt(c["exact"])))
        agree = mine == want
        ok_all &= agree
        print(f"  exact (geotruth, certified) {mine}   {'= recorded' if agree else '!= recorded ' + want}")
        for key in ("geos_main", "geos_3150"):
            g = c[key]
            if g.startswith("EXCEPTION"):
                print(f"  {key:10s} {g}")
                continue
            cert = certify(a, b, c["op"], read_wkt(g), structure=False)
            print(f"  {key:10s} {g}   certificate: {cert.summary()}")
        for text, got, exp in hand_facts(c["id"]):
            ok_all &= got == exp
            print(f"  hand (indep.py): {text}: {got}{'' if got == exp else '  <-- UNEXPECTED'}")
    print("\nall exact answers and hand facts as recorded" if ok_all else "\nMISMATCH")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else str(HERE / "cases.jsonl")))
