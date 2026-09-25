"""Compare a library's results with the exact oracle and list every disagreement.

usage: python compare.py CASES.jsonl ORACLE.jsonl RESULTS.jsonl [--json]
"""
import json
import sys

PREDICATES = ["intersects", "disjoint", "touches", "overlaps", "contains", "covers",
              "within", "covered_by", "equals"]
AREAS = ["area_inter", "area_union", "area_diff", "area_symdiff"]
REL_TOL = 1e-6


def load(path):
    return {r["id"]: r for r in map(json.loads, filter(str.strip, open(path)))}


def compare(case, orc, res):
    found = []
    va, vb = orc.get("valid_a"), orc.get("valid_b")
    inputs_valid = va is not False and vb is not False
    for key, exact in (("valid_a", va), ("valid_b", vb)):
        if exact is not None and res.get(key) is not None and res[key] != exact:
            found.append(("validity", key, exact, res[key]))
    if not inputs_valid:
        return found
    for key, msg in (res.get("errors") or {}).items():
        found.append(("error", key, None, msg))
    for p in PREDICATES:
        if res.get(p) is not None and res[p] != orc[p]:
            found.append(("predicate", p, orc[p], res[p]))
    scale = max(orc["area_a"], orc["area_b"], 1e-300)
    for k in AREAS:
        if res.get(k) is not None and abs(res[k] - orc[k]) > REL_TOL * scale:
            found.append(("area", k, orc[k], res[k]))
    return found


def main():
    cases, orc, res = load(sys.argv[1]), load(sys.argv[2]), load(sys.argv[3])
    as_json = "--json" in sys.argv
    n = 0
    for cid, r in res.items():
        if cid not in orc:
            continue
        for kind, key, exact, got in compare(cases.get(cid), orc[cid], r):
            n += 1
            rec = {"id": cid, "family": (cases.get(cid) or {}).get("family"), "lib": r.get("lib"),
                   "kind": kind, "key": key, "exact": exact, "got": got}
            print(json.dumps(rec) if as_json else f"{cid}\t{rec['lib']}\t{kind}\t{key}\texact={exact}\tgot={got}")
    print(f"# {n} disagreements over {len(res)} cases", file=sys.stderr)


if __name__ == "__main__":
    main()
