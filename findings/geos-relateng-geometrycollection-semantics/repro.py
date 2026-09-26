"""RelateNG on valid GeometryCollections, through Shapely (public API only).

    python3 repro.py            # uses cases.jsonl next to this file

For each case: shapely.relate(A, B) and (B, A) against the exact matrix, the named predicates
of (A, B) against the exact values, and shapely.relate(shapely.union_all(parts of A), B), i.e.
GEOS on its own overlay union of A's elements. Each call is guarded, because GEOS < 3.13
(RelateOp) rejects GeometryCollection arguments.
"""
import json
from pathlib import Path

import shapely

PN = ["intersects", "contains", "within", "covers", "covered_by", "touches", "overlaps", "crosses", "equals"]


def transpose(m):
    return "".join(m[3 * j + i] for i in range(3) for j in range(3))


def guard(f, *args):
    try:
        return f(*args)
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {str(exc)[:70]}"


def main():
    print(f"shapely {shapely.__version__}, GEOS {shapely.geos_version_string}")
    wrong = 0
    rows = [json.loads(line) for line in open(Path(__file__).with_name("cases.jsonl"))]
    for c in rows:
        a, b = shapely.from_wkt(c["a_wkt"]), shapely.from_wkt(c["b_wkt"])
        ex = c["expected_relate"]
        m1, m2 = guard(shapely.relate, a, b), guard(shapely.relate, b, a)
        parts = list(a.geoms) if hasattr(a, "geoms") else [a]
        mu = guard(lambda: shapely.relate(shapely.union_all(parts), b))
        bad = m1 != ex or m2 != transpose(ex)
        lines = [f"  relate(A,B) = {m1}   exact {ex}" + ("   <-- WRONG" if m1 != ex else ""),
                 f"  relate(B,A) = {m2}   exact {transpose(ex)}" + ("   <-- WRONG" if m2 != transpose(ex) else ""),
                 f"  relate(union_all(A),B) = {mu}" + ("   (= exact)" if mu == ex else "")]
        for i, name in enumerate(PN):
            got = guard(getattr(shapely, name), a, b)
            want = c["expected_predicates"][i] == "1"
            if not isinstance(got, str):
                got = bool(got)
            if got != want:
                lines.append(f"  {name}(A,B) = {got}   exact {want}   <-- WRONG")
                bad = True
        print(f"\n[{c['id'].split(':')[1]}]  isValid: {shapely.is_valid(a)}, {shapely.is_valid(b)}")
        print("\n".join(lines) if bad else "\n".join(lines) + "\n  ok")
        wrong += bad
    print(f"\n{wrong} of {len(rows)} cases wrong")


if __name__ == "__main__":
    main()
