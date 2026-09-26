"""Mutation test of the review harness: plant small defects in a COPY of oracle.py
(in memory; oracle.py itself is never touched) and check that check.py / ring_check.py
notice them. A surviving mutant means either the harness is blind there or the mutant
is equivalent on valid input (explained in the table below).

usage: python mutants.py CASES.jsonl [EVERY_NTH] [PART/NPARTS]
"""
import itertools
import json
import os
import sys
import types
from fractions import Fraction as F

HERE = os.path.dirname(os.path.abspath(__file__))
ORACLE = os.path.join(os.path.dirname(HERE), "oracle.py")
sys.path.insert(0, HERE)
import check  # noqa: E402
import indep  # noqa: E402

# (name, old, new, expectation)
MUTANTS = [
    ("sort-left-y-only", "active.sort(key=lambda t: t[0] + t[1])", "active.sort(key=lambda t: t[0])", "kill"),
    ("sort-right-y-only", "active.sort(key=lambda t: t[0] + t[1])", "active.sort(key=lambda t: t[1])", "kill"),
    ("no-sort", "active.sort(key=lambda t: t[0] + t[1])", "pass", "kill"),
    ("no-crossing-events", "xs.update(crossing_x(a, b, c, d))", "pass", "kill"),
    ("slab-span-strict", "if lo[0] <= xl and hi[0] >= xr:", "if lo[0] < xl and hi[0] >= xr:", "kill"),
    ("bbox-filter-strict", "if max(a[0], b[0]) < min(c[0], d[0])", "if max(a[0], b[0]) <= min(c[0], d[0])", "equivalent"),
    ("intersects-one-way", "    if any(point_in(r[0], ea) >= 0 for r in rings(gb)):\n        return True\n", "", "kill"),
    ("touches-no-intersects", '"touches": inter and both == 0', '"touches": both == 0', "kill"),
    ("overlaps-or", '"overlaps": both > 0 and da > 0 and db > 0', '"overlaps": both > 0 and (da > 0 or db > 0)', "kill"),
    ("equals-wrong", '"equals": da == 0 and db == 0', '"equals": both > 0 and da == 0', "kill"),
    ("area-half-wrong", "w = (xr - xl) * HALF", "w = (xr - xl)", "kill"),
    ("pip-no-boundary", "            return 0\n        if (a[1] > p[1])", "            pass\n        if (a[1] > p[1])", "kill"),
    ("ring-no-foldback", "                        return False\n                continue", "                        pass\n                continue", "kill-ring"),
    ("ring-no-nonadjacent", "            if seg_intersect(a, b, c, d):\n                return False\n    return True",
     "            pass\n    return True", "kill-ring"),
    ("ring-min3-to-min2", "    if n < 3:\n        return False", "    if n < 2:\n        return False", "kill-ring"),
    # expected equivalent on valid input (explained in README)
    ("crossing-strict", "if 0 <= t <= 1 and 0 <= u <= 1:", "if 0 < t < 1 and 0 < u < 1:", "equivalent"),
    ("pip-other-halfopen", "if (a[1] > p[1]) != (b[1] > p[1]):", "if (a[1] >= p[1]) != (b[1] >= p[1]):", "equivalent"),
    ("seg-no-collinear-cases", "    if o1 == 0 and on_segment(c, a, b):", "    return False\n    if o1 == 0 and on_segment(c, a, b):", "equivalent?"),
    ("intersects-strict-vertex", "if any(point_in(r[0], eb) >= 0 for r in rings(ga)):", "if any(point_in(r[0], eb) > 0 for r in rings(ga)):", "equivalent"),
]


def ring_kills(mod):
    grid = [(F(x), F(y)) for x in range(3) for y in range(3)]
    for n in (3, 4, 5):
        for seq in itertools.product(grid, repeat=n):
            ring = list(seq) + [seq[0]]
            if mod.ring_simple(ring) != indep.ring_is_simple([(float(x), float(y)) for x, y in ring]):
                return True
    return False


def main():
    path = sys.argv[1]
    every = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    lines = [ln for i, ln in enumerate(open(path)) if ln.strip() and i % every == 0]
    src = open(ORACLE).read()
    print(f"{len(lines)} cases per mutant")
    # baseline: failures of the unmodified oracle (the known overflow crashes) are not kills
    base = set()
    for ln in lines:
        for f in check.check_case(ln)[2]:
            base.add((f["id"], f["kind"]))
    print(f"baseline failures of the real oracle on this sample: {len(base)}")
    k, m = map(int, (sys.argv[3] if len(sys.argv) > 3 else "0/1").split("/"))
    for idx, (name, old, new, expect) in enumerate(MUTANTS):
        if idx % m != k:
            continue
        assert src.count(old) == 1, (name, src.count(old))
        mod = types.ModuleType(f"oracle_{name}")
        exec(compile(src.replace(old, new), f"<{name}>", "exec"), mod.__dict__)
        check.oracle = mod
        killed_by = {}
        for ln in lines:
            _, _, fails = check.check_case(ln)
            for f in fails:
                if f["kind"] != "skipped-invalid-input" and (f["id"], f["kind"]) not in base:
                    killed_by[f["kind"]] = killed_by.get(f["kind"], 0) + 1
        if ring_kills(mod):
            killed_by["ring_check"] = 1
        verdict = "KILLED" if killed_by else "survived"
        print(f"{name:26s} expect={expect:12s} {verdict:9s} {json.dumps(killed_by, sort_keys=True)}")


if __name__ == "__main__":
    main()
