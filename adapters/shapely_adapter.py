"""Shapely / GEOS adapter (reference implementation of the adapter contract in FORMAT.md).

usage: python adapters/shapely_adapter.py CASES.jsonl > results.jsonl
"""
import json
import sys

import shapely
from shapely.geometry import MultiPolygon, Polygon

LIB = f"geos@{shapely.geos_version_string}+shapely@{shapely.__version__}"
PREDICATES = ["intersects", "disjoint", "touches", "overlaps", "contains", "covers", "within", "equals"]


def build(mp):
    polys = [Polygon(p[0], p[1:]) for p in mp]
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


def run(case):
    out = {"id": case["id"], "lib": LIB, "errors": {}}
    a, b = build(case["a"]), build(case["b"])
    for key, geom in (("valid_a", a), ("valid_b", b)):
        try:
            out[key] = bool(geom.is_valid)
        except Exception as e:  # noqa: BLE001
            out[key], out["errors"][key] = None, repr(e)
    for p in PREDICATES:
        try:
            out[p] = bool(getattr(a, p)(b))
        except Exception as e:  # noqa: BLE001
            out[p], out["errors"][p] = None, repr(e)
    try:
        out["covered_by"] = bool(a.covered_by(b))
    except Exception as e:  # noqa: BLE001
        out["covered_by"], out["errors"]["covered_by"] = None, repr(e)
    for key, fn in (("area_inter", a.intersection), ("area_union", a.union),
                    ("area_diff", a.difference), ("area_symdiff", a.symmetric_difference)):
        try:
            out[key] = float(fn(b).area)
        except Exception as e:  # noqa: BLE001
            out[key], out["errors"][key] = None, repr(e)
    return out


def main():
    for line in open(sys.argv[1]):
        if line.strip():
            print(json.dumps(run(json.loads(line))), flush=True)


if __name__ == "__main__":
    main()
