"""Differential scan of GEOS overlay on GeometryCollection operands against geotruth.

  python3 scan.py gen N SEED > cases.tsv          # GC-involving, GEOS-valid pairs
  python3 scan.py exact cases.tsv > exact.jsonl   # exact results (all four ops)
  python3 scan.py classify cases.tsv exact.jsonl geos-out.tsv   # verdict counts

Cases come from the geotruth cross-check generators (tools/crosscheck_relate.py:
adversarial_cases and lattice_cases); a pair is kept when at least one operand is a
GeometryCollection and both are GEOS-valid. Each case is also tagged 'simple' when every
GC operand flattens to a valid homogeneous geometry (OverlayNG's own input requirement).
"""
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]  # findings/<slug>/ -> repo root
sys.path[:0] = [str(REPO / "src"), str(REPO / "tests"), str(REPO / "tools")]

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("crosscheck_overlay", REPO / "tools" / "crosscheck_overlay.py")
X = importlib.util.module_from_spec(spec)
sys.modules["crosscheck_overlay"] = X
spec.loader.exec_module(X)
R = X.R

from geotruth.geom import GeometryCollection, LineString, MultiPolygon, Point, Polygon  # noqa: E402
from geotruth.io import geometry_from_json, geometry_to_json, read_wkt, to_wkt  # noqa: E402
from geotruth.overlay import overlay  # noqa: E402

OPS = ("intersection", "union", "difference", "symdifference")


def atoms(g):
    if isinstance(g, GeometryCollection):
        for e in g.geometries:
            yield from atoms(e)
    else:
        yield from g.elements() if hasattr(g, "elements") else [g]


def dims(g):
    out = set()
    for e in atoms(g):
        if e.is_empty:
            continue
        out.add(0 if isinstance(e, Point) else 1 if isinstance(e, LineString) else 2)
    return out


def simple_gc(g):
    """OverlayNG's requirement: a GC must flatten to a valid homogeneous Multi-geometry."""
    if not isinstance(g, GeometryCollection):
        return True
    d = dims(g)
    if len(d) > 1:
        return False
    if d == {2}:
        polys = [e for e in atoms(g) if isinstance(e, Polygon) and not e.is_empty]
        return R.in_contract(MultiPolygon(polys)) if len(polys) > 1 else True
    return True


def gen(n, seed):
    seen = 0
    for src in (R.adversarial_cases(n, seed), R.lattice_cases(n, seed)):
        for c in src:
            if not (isinstance(c.a, GeometryCollection) or isinstance(c.b, GeometryCollection)):
                continue
            if not (R.geos_valid(c.a) and R.geos_valid(c.b)):
                continue
            tag = "simple" if simple_gc(c.a) and simple_gc(c.b) else "mixed"
            print(f"{c.id}|{tag}\t{to_wkt(c.a)}\t{to_wkt(c.b)}")
            seen += 1
    print(f"{seen} cases", file=sys.stderr)


def exact(path):
    for line in open(path):
        cid, wa, wb = line.rstrip("\n").split("\t")
        a, b = read_wkt(wa), read_wkt(wb)
        rec = {"id": cid}
        for op in OPS:
            try:
                rec[op] = geometry_to_json(overlay(a, b, op).geometry, exact=True)
            except Exception as exc:  # budget etc.
                rec[op] = {"error": f"{type(exc).__name__}: {exc}"}
        print(json.dumps(rec), flush=True)


def classify(cases_path, exact_path, geos_path, show=3):
    cases = {}
    for line in open(cases_path):
        cid, wa, wb = line.rstrip("\n").split("\t")
        cases[cid] = (wa, wb)
    ex = {}
    for line in open(exact_path):
        r = json.loads(line)
        ex[r["id"]] = r
    res = defaultdict(dict)
    for line in open(geos_path):
        cid, op, out = line.rstrip("\n").split("\t", 2)
        res[cid][op] = out
    counts = Counter()
    examples = defaultdict(list)
    for cid, (wa, wb) in cases.items():
        tag = cid.rsplit("|", 1)[1]
        a, b = read_wkt(wa), read_wkt(wb)
        for op in OPS:
            out = res.get(cid, {}).get(op)
            if out is None:
                out = res.get(cid, {}).get("ALL", "ERR missing")
            mine_j = ex[cid][op]
            if "error" in mine_j:
                counts[(op, tag, "exact-engine-error")] += 1
                continue
            mine = geometry_from_json(mine_j, exact=True)
            theirs = out[4:] if out.startswith("ERR ") else out
            if out.startswith("ERR ") or out.startswith("CRASH"):
                v = "geos-error: " + ("AssertionFailed" if "Assertion" in out else out[:60])
            else:
                v, _ = X.geos_verdict(a, b, op, mine, read_wkt(theirs))
            counts[(op, tag, v)] += 1
            if len(examples[(op, v)]) < show and not (v == "exact" or v.startswith("same-point-set")):
                examples[(op, v)].append((cid, wa, wb, theirs, to_wkt(mine)))
    for k in sorted(counts):
        print(f"{counts[k]:6d}  {k[0]:14s} {k[1]:7s} {k[2]}")
    print()
    for (op, v), exs in sorted(examples.items()):
        for cid, wa, wb, t, m in exs:
            print(f"[{op} | {v}] {cid}\n   A = {wa}\n   B = {wb}\n   GEOS  = {t}\n   exact = {m}")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "gen":
        gen(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == "exact":
        exact(sys.argv[2])
    else:
        classify(*sys.argv[2:5])
