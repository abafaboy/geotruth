"""Summarise `compare.py --json` output by family and kind of disagreement.

usage: python gen/summarize.py CASES_DIR COMPARE_DIR [--examples K] [--families f1,f2]

CASES_DIR holds <family>.jsonl case files, COMPARE_DIR the matching <family>.jsonl files
written by `compare.py CASES ORACLE RESULTS --json`. For each family: the number of cases,
the number of cases with at least one disagreement, and per kind (predicate / area /
validity / error) the number of disagreeing cases, the keys involved, and K example ids.

Area disagreements are also split by the output-rounding floor (common.rounding_floor):
"beyond floor" means |got - exact| exceeds ulp(max |coord|) * (perimeter A + perimeter B),
the most that rounding every output vertex to the nearest double could explain. An area
disagreement within the floor is not evidence of a bug (compare.py's 1e-6 relative
tolerance is below what rounding can explain for that case, e.g. two ulp-thin slivers).
"""
import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import rounding_floor  # noqa: E402

KINDS = ["predicate", "area", "validity", "error"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cases_dir")
    ap.add_argument("compare_dir")
    ap.add_argument("--examples", type=int, default=3)
    ap.add_argument("--families", default="")
    args = ap.parse_args()
    fams = [f for f in args.families.split(",") if f] or sorted(
        f[:-6] for f in os.listdir(args.compare_dir) if f.endswith(".jsonl"))
    total_cases = total_bad = 0
    lines = ["| family | cases | cases with disagreement | predicate | area (beyond floor) | validity | error |",
             "|---|---:|---:|---:|---:|---:|---:|"]
    details = []
    for fam in fams:
        cpath = os.path.join(args.cases_dir, fam + ".jsonl")
        cases = {}
        if os.path.exists(cpath):
            for line in open(cpath):
                if line.strip():
                    c = json.loads(line)
                    cases[c["id"]] = c
        n = len(cases)
        recs = [json.loads(line) for line in open(os.path.join(args.compare_dir, fam + ".jsonl")) if line.strip()]
        by_kind = defaultdict(list)  # kind -> ordered unique ids
        keys = defaultdict(Counter)
        for r in recs:
            if r["id"] not in by_kind[r["kind"]]:
                by_kind[r["kind"]].append(r["id"])
            keys[r["kind"]][r["key"]] += 1
        beyond = []
        for r in recs:
            if r["kind"] == "area" and r["id"] in cases and r["id"] not in beyond:
                c = cases[r["id"]]
                if abs(r["got"] - r["exact"]) > rounding_floor(c["a"], c["b"]):
                    beyond.append(r["id"])
        bad = len({r["id"] for r in recs})
        total_cases += n
        total_bad += bad
        cols = [str(len(by_kind[k])) + (f" ({len(beyond)})" if k == "area" else "") for k in KINDS]
        lines.append(f"| {fam} | {n} | {bad} | " + " | ".join(cols) + " |")
        for k in KINDS:
            if by_kind[k]:
                ks = ", ".join(f"{key} {c}" for key, c in keys[k].most_common())
                details.append(f"- {fam} / {k}: {len(by_kind[k])} cases ({ks}); e.g. "
                               + ", ".join(by_kind[k][:args.examples]))
                if k == "area":
                    details.append(f"  - beyond rounding floor: {len(beyond)}"
                                   + ("; e.g. " + ", ".join(beyond[:args.examples]) if beyond else ""))
    lines.append(f"| total | {total_cases} | {total_bad} | | | | |")
    print("\n".join(lines))
    print()
    print("\n".join(details))


if __name__ == "__main__":
    main()
