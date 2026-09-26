"""Generate every case family into cases/<family>.jsonl.

usage: python gen/run_all.py N SEED [--families f1,f2,...] [--outdir DIR] [--stats]

Each family gets exactly N cases, ids `<family>-<SEED>-<nnnnnn>-<variant>`. Generation is
deterministic for a given (N, SEED) and family (each family has its own random stream; the
validity filter uses the installed shapely for rings with holes / multipolygons, so a
different GEOS could in principle change which attempts are kept).

Every emitted operand is valid: a single ring passes oracle.valid_single_polygon (exact);
anything with holes or several parts passes common.exact_valid (exact, conservative) AND
shapely.is_valid. Rejection counts go to stderr (--stats prints all reasons).
"""
import argparse
import json
import os
import random
import sys
import time
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import Reject, check_valid, finalize, n_edges, shapely  # noqa: E402
from families import FAMILIES  # noqa: E402

MAX_EDGES = 300  # both operands together; keeps the exact oracle fast


def generate(name, fn, n, seed, log=None):
    rng = random.Random(f"{name}:{seed}")
    out, seen = [], set()
    stats = Counter()
    attempts = 0
    while len(out) < n:
        attempts += 1
        if attempts > 500 * n + 2000:
            raise RuntimeError(f"{name}: too many rejected attempts ({stats.most_common(5)})")
        try:
            variant, a, b = fn(rng)
            a, b = finalize(rng, a), finalize(rng, b)
        except Reject as e:
            stats["reject: " + str(e)] += 1
            continue
        except (ZeroDivisionError, ValueError, OverflowError) as e:
            stats["construction error: " + type(e).__name__] += 1
            continue
        if n_edges(a) + n_edges(b) > MAX_EDGES:
            stats["too many edges"] += 1
            continue
        ok = True
        for g in (a, b):
            good, why = check_valid(g)
            if not good:
                stats["invalid: " + why] += 1
                ok = False
                break
        if not ok:
            continue
        key = json.dumps([a, b])
        if key in seen:
            stats["duplicate"] += 1
            continue
        seen.add(key)
        stats["kept"] += 1
        out.append({"id": f"{name}-{seed}-{len(out) + 1:06d}-{variant}", "family": name, "a": a, "b": b})
    return out, stats, attempts


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("n", type=int)
    ap.add_argument("seed", type=int)
    ap.add_argument("--families", default="")
    ap.add_argument("--outdir", default=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "cases"))
    ap.add_argument("--stats", action="store_true", help="print every rejection reason")
    args = ap.parse_args()
    if shapely is None:
        print("warning: shapely not installed; holes/multipolygons are checked exactly only", file=sys.stderr)
    want = set(filter(None, args.families.split(",")))
    unknown = want - {name for name, _ in FAMILIES}
    if unknown:
        sys.exit(f"unknown families: {sorted(unknown)}")
    os.makedirs(args.outdir, exist_ok=True)
    for name, fn in FAMILIES:
        if want and name not in want:
            continue
        t0 = time.time()
        cases, stats, attempts = generate(name, fn, args.n, args.seed)
        path = os.path.join(args.outdir, f"{name}.jsonl")
        with open(path, "w") as f:
            for c in cases:
                f.write(json.dumps(c) + "\n")
        rej = attempts - len(cases)
        print(f"{name:16s} {len(cases):5d} cases  {attempts:6d} attempts  {rej:5d} rejected  "
              f"{time.time() - t0:6.1f}s  -> {path}", file=sys.stderr)
        if args.stats:
            for k, c in sorted(stats.items(), key=lambda kv: -kv[1]):
                if k != "kept":
                    print(f"    {c:6d}  {k}", file=sys.stderr)


if __name__ == "__main__":
    main()
