"""Re-check case files: format, validity, and how many cases have exact boundary contact.

usage: python gen/validate.py CASES.jsonl [CASES.jsonl ...]

Per file: number of cases, format/validity problems (should be 0), and exact contact
statistics between the two operands' boundaries, all decided with rationals:
  shared   the boundaries share a segment of positive length
  touch    a vertex of one operand lies exactly on the other's boundary (no shared segment)
  none     the boundaries have no exact vertex-on-boundary contact
  floor>tol  cases whose output-rounding floor (common.rounding_floor) exceeds compare.py's
           area tolerance 1e-6 * max(area A, area B): for those, an area disagreement is not
           evidence (predicates are still exact questions)
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import (  # noqa: E402
    _qedges, _qring, check_valid, contact, on_segment, oracle, orient, rounding_floor,
)


def boundary_contact(a, b):
    ea = [e for poly in a for r in poly for e in _qedges(_qring(r))]
    eb = [e for poly in b for r in poly for e in _qedges(_qring(r))]
    if contact(ea, eb) is None:
        return "shared"
    for pts, es in (([p for p, _ in ea], eb), ([p for p, _ in eb], ea)):
        for p in pts:
            for s, t in es:
                if orient(s, t, p) == 0 and on_segment(p, s, t):
                    return "touch"
    return "none"


def check_format(case):
    probs = []
    for k in ("id", "family", "a", "b"):
        if k not in case:
            probs.append(f"missing {k}")
    for g in ("a", "b"):
        for poly in case.get(g, []):
            for r in poly:
                if r[0] != r[-1]:
                    probs.append(f"{g}: ring not closed")
                if any(not isinstance(v, float) for p in r for v in p):
                    probs.append(f"{g}: non-float coordinate")
    return probs


def main():
    for path in sys.argv[1:]:
        ids = set()
        stats = Counter()
        problems = []
        for line in open(path):
            if not line.strip():
                continue
            c = json.loads(line)
            if c["id"] in ids:
                problems.append(f"{c['id']}: duplicate id")
            ids.add(c["id"])
            problems += [f"{c['id']}: {p}" for p in check_format(c)]
            for g in ("a", "b"):
                ok, why = check_valid(c[g])
                if not ok:
                    problems.append(f"{c['id']}: {g} invalid: {why}")
            stats[boundary_contact(c["a"], c["b"])] += 1
            amax = max(float(oracle.shoelace(c["a"])), float(oracle.shoelace(c["b"])))
            stats["floor>tol"] += rounding_floor(c["a"], c["b"]) > 1e-6 * amax
            stats["cases"] += 1
            stats["multi/holes"] += any(len(c[g]) > 1 or len(c[g][0]) > 1 for g in ("a", "b"))
        print(f"{os.path.basename(path):24s} cases {stats['cases']:5d}  problems {len(problems):3d}  "
              f"shared {stats['shared']:4d}  touch {stats['touch']:4d}  none {stats['none']:4d}  "
              f"holes/multi {stats['multi/holes']:4d}  floor>tol {stats['floor>tol']:3d}")
        for p in problems[:10]:
            print("   ", p)


if __name__ == "__main__":
    main()
