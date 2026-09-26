"""Adapter (FORMAT.md contract) around indep.py, the independent exact implementation
written for the oracle review. Running it through compare.py against the oracle's
results is a full second-opinion check of the oracle on any case file.

usage: python oracle_review/indep_adapter.py CASES.jsonl > results.jsonl
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import indep  # noqa: E402

LIB = "indep-exact@oracle_review"
PRED = ["intersects", "disjoint", "touches", "overlaps", "contains", "covers", "within",
        "covered_by", "equals"]


def to_float(q):
    try:
        return float(q)
    except OverflowError:
        return math.inf


def run(case):
    out = {"id": case["id"], "lib": LIB, "errors": {}}
    for key, g in (("valid_a", case["a"]), ("valid_b", case["b"])):
        try:
            out[key] = indep.ring_is_simple(g[0][0]) if len(g) == 1 and len(g[0]) == 1 else None
        except Exception as e:  # noqa: BLE001
            out[key], out["errors"][key] = None, repr(e)
    try:
        r = indep.evaluate_geoms(case["a"], case["b"])
        for p in PRED:
            out[p] = r[p]
        out["area_inter"] = to_float(r["inter"])
        out["area_union"] = to_float(r["union"])
        out["area_diff"] = to_float(r["diff_ab"])
        out["area_symdiff"] = to_float(r["diff_ab"] + r["diff_ba"])
        out["exact"] = {"inter": str(r["inter"]), "diff_ab": str(r["diff_ab"]), "diff_ba": str(r["diff_ba"])}
        if not r["selfcheck"]:
            out["errors"]["selfcheck"] = "inter + diff != shoelace area (input invalid?)"
    except Exception as e:  # noqa: BLE001
        for p in PRED + ["area_inter", "area_union", "area_diff", "area_symdiff"]:
            out.setdefault(p, None)
        out["errors"]["evaluate"] = repr(e)
    return out


def main():
    for line in open(sys.argv[1]):
        if line.strip():
            print(json.dumps(run(json.loads(line))), flush=True)


if __name__ == "__main__":
    main()
