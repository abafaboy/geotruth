"""Adapter contract v2 of the native adapters (DESIGN.md §4.1): the parse-echo canary, every
geometry type pair, "unsupported" for out-of-contract input, per-operation isolation, and
the v1 / v2 dispatch. Each test is skipped for a target whose build is absent."""

from __future__ import annotations

import json
import struct

import pytest
from test_native_support import (
    CANARY,
    FAULT_ENV,
    OPS,
    PREDICATES,
    TARGETS,
    V1_FIELDS,
    area,
    by_id,
    exact_pair,
    positions,
    require,
    run_adapter,
)

pytestmark = pytest.mark.unit
jsonschema = pytest.importorskip("jsonschema")

SQ = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
GEOMS = {
    "P": {"type": "Point", "coordinates": [1, 1]},
    "Pe": {"type": "Point", "coordinates": []},
    "L": {"type": "LineString", "coordinates": [[0, 0], [2, 2]]},
    "Le": {"type": "LineString", "coordinates": []},
    "A": {"type": "Polygon", "coordinates": [SQ]},
    "Ah": {"type": "Polygon", "coordinates": [[[-1, -1], [4, -1], [4, 4], [-1, 4], [-1, -1]],
                                              [[0.5, 0.5], [0.5, 1.5], [1.5, 1.5], [1.5, 0.5],
                                               [0.5, 0.5]]]},
    "Ae": {"type": "Polygon", "coordinates": []},
    "MP": {"type": "MultiPoint", "coordinates": [[1, 1], [3, 3]]},
    "ML": {"type": "MultiLineString", "coordinates": [[[0, 0], [1, 1]], [[1, 1], [3, 1]]]},
    "MA": {"type": "MultiPolygon", "coordinates": [
        [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
        [[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]]},
    "GC": {"type": "GeometryCollection", "geometries": [
        {"type": "Point", "coordinates": [5, 5]},
        {"type": "GeometryCollection", "geometries": [
            {"type": "Polygon", "coordinates": [[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]}]}]},
}
POLYGONAL = {"A", "Ah", "Ae", "MA"}


def pair_cases() -> list[dict]:
    return [{"id": f"pair-{ka}-{kb}", "family": "pairs", "tags": {},
             "provenance": {"source": "manual"}, "a": a, "b": b}
            for ka, a in GEOMS.items() for kb, b in GEOMS.items()]


def validator():
    from geotruth import schemas

    return schemas.validator("result")


def bits(x: float) -> bytes:
    return struct.pack("<d", x)


@pytest.fixture(params=TARGETS, ids=lambda t: t.id)
def tgt(request):
    require(request.param)
    return request.param


# ---------------------------------------------------------------------------- canary


def test_parse_echo_canary(tgt, tmp_path):
    """The echo returns exactly the doubles float() reads from the case (2^53+1 -> 2^53,
    subnormals, -0.0, 0.30000000000000004, the largest double), written by the adapter."""
    (r,) = run_adapter(tgt, [CANARY], tmp=tmp_path)
    validator().validate(r)
    assert r["lib"] == tgt.lib
    assert set(r) == {"id", "lib", "echo", "errors"} and r["errors"] == {}
    for key in ("a", "b"):
        got, want = r["echo"][key], CANARY[key]
        assert got["type"] == want["type"]
        gp, wp = positions(got), positions(want)
        assert gp == wp  # numerically equal, every position in order
        for g, w in zip(gp, wp, strict=True):
            for gv, wv in zip(g, w, strict=True):
                if tgt.id == "cgal" and wv == 0:
                    # exact rationals have no signed zero: -0.0 comes back as 0.0 (README)
                    continue
                assert bits(gv) == bits(wv), (tgt.id, key, gv, wv)


def test_canary_integer_literal_is_rounded_like_float(tgt, tmp_path):
    case = {"id": "canary-int", "ops": ["echo"],
            "a": {"type": "Point", "coordinates": [9007199254740993, -0.0]},
            "b": {"type": "Point", "coordinates": [18014398509481987, 2.2250738585072009e-308]}}
    (r,) = run_adapter(tgt, [case], tmp=tmp_path)
    assert r["echo"]["a"]["coordinates"][0] == 9007199254740992.0
    assert r["echo"]["b"]["coordinates"] == [18014398509481988.0, 2.2250738585072009e-308]


# ---------------------------------------------------------------------------- all type pairs


def expected_unsupported(tid: str, ka: str, kb: str) -> bool:
    """Is the whole pair outside the target's contract?"""
    if tid in ("clipper2", "cgal"):
        return not (ka in POLYGONAL and kb in POLYGONAL)
    if tid.startswith("boost"):
        return bool({ka, kb} & {"GC", "Pe"})
    return False


def test_every_type_pair(tgt, tmp_path):
    cases = pair_cases()
    out = run_adapter(tgt, cases, tmp=tmp_path)
    assert [r["id"] for r in out] == [c["id"] for c in cases]
    v = validator()
    for r in out:
        v.validate(r)
        assert r["lib"] == tgt.lib
        _, ka, kb = r["id"].split("-")
        # the default groups: everything but echo
        assert set(r) >= {"relate", "predicates", "valid_a", "valid_b", "overlay", "errors"}
        assert "echo" not in r
        assert set(r["predicates"]) == set(PREDICATES) and set(r["overlay"]) == set(OPS)
        # failures are exceptions of the library, never crashes or hangs of the adapter
        for path, err in r["errors"].items():
            assert isinstance(err, str) or err["kind"] == "memory", (r["id"], path, err)
        fields = [r["relate"], *r["predicates"].values(), *r["overlay"].values()]
        if expected_unsupported(tgt.id, ka, kb):
            assert all(f == "unsupported" for f in fields), (r["id"], r)
            continue
        assert "unsupported" not in (r["relate"], r["predicates"]["intersects"]), r["id"]
        if tgt.id.startswith("geos"):
            assert r["relate"] is not None or r["errors"].get("relate")
        if tgt.id in ("clipper2", "cgal"):
            assert r["relate"] is None
        if tgt.id == "clipper2":
            assert r["valid_a"] is None and r["valid_b"] is None
            assert all(r["predicates"][p] is None for p in PREDICATES
                       if p not in ("intersects", "disjoint"))
        if tgt.id.startswith("boost"):
            areal = ka in POLYGONAL and kb in POLYGONAL
            assert all((o == "unsupported") != areal for o in r["overlay"].values()), r["id"]


def relate_matches(matrix: str, pattern: str) -> bool:
    return all(p == "*" or (p == "T" and m != "F") or p == m
               for m, p in zip(matrix, pattern, strict=True))


def test_relate_agrees_with_the_named_predicates(tgt, tmp_path):
    """Adapter wiring: intersects/disjoint/within/contains/covers/covered_by agree with the
    relate matrix of the same library (GEOS and Boost; on these small lattice pairs)."""
    if tgt.id in ("clipper2", "cgal"):
        pytest.skip("no relate")
    for r in run_adapter(tgt, pair_cases(), tmp=tmp_path):
        m, p = r["relate"], r["predicates"]
        if not isinstance(m, str) or "e" in r["id"].split("-")[1] + r["id"].split("-")[2]:
            continue  # unsupported, or an empty operand (conventions differ)
        checks = {
            "intersects": not relate_matches(m, "FF*FF****"),
            "disjoint": relate_matches(m, "FF*FF****"),
            "within": relate_matches(m, "T*F**F***"),
            "contains": relate_matches(m, "T*****FF*"),
            "covered_by": any(relate_matches(m, q) for q in
                              ("T*F**F***", "*TF**F***", "**FT*F***", "**F*TF***")),
            "covers": any(relate_matches(m, q) for q in
                          ("T*****FF*", "*T****FF*", "***T**FF*", "****T*FF*")),
        }
        for name, want in checks.items():
            if p[name] in (True, False):
                assert p[name] == want, (tgt.id, r["id"], m, name, p[name])


def test_polygon_pairs_against_the_exact_answer(tgt, tmp_path):
    """Predicates and overlay areas of the valid polygon/polygon pairs against the exact
    answer (engine when available, else the oracle)."""
    areal = ("A", "Ah", "MA")
    cases = [c for c in pair_cases()
             if c["id"].split("-")[1] in areal and c["id"].split("-")[2] in areal]
    for r, c in zip(run_adapter(tgt, cases, tmp=tmp_path), cases, strict=True):
        e = exact_pair(c["a"], c["b"])
        assert e.valid_a and e.valid_b
        for key in ("valid_a", "valid_b"):
            # None: Clipper2, and CGAL for a MultiPolygon
            assert r[key] in (True, None), (tgt.id, r["id"], key)
        for name, want in e.predicates.items():
            if r["predicates"][name] is not None:
                assert r["predicates"][name] == want, (tgt.id, r["id"], name)
        for op in OPS:
            assert area(r["overlay"][op]) == e.areas[op], (tgt.id, r["id"], op)


# ---------------------------------------------------------------------------- out of contract


def test_clipper2_non_dyadic_and_out_of_range_are_unsupported(tmp_path):
    t = next(t for t in TARGETS if t.id == "clipper2")
    require(t)
    # 1e-30 needs a scale 2^k with k > 60; 2^62 is beyond the int64 contract
    tiny = {"type": "Polygon", "coordinates": [[[0, 0], [1e-30, 0], [0, 1], [0, 0]]]}
    huge = {"type": "Polygon", "coordinates": [[[0, 0], [2.0**62, 0], [0, 1], [0, 0]]]}
    sq = GEOMS["A"]
    out = run_adapter(t, [{"id": "tiny", "a": tiny, "b": sq}, {"id": "huge", "a": sq, "b": huge},
                          {"id": "ok", "a": sq, "b": sq}], tmp=tmp_path)
    for r in out[:2]:
        assert all(v == "unsupported" for v in (*r["overlay"].values(), r["valid_a"], r["relate"]))
        assert r["errors"] == {}
    assert out[2]["overlay"]["intersection"]["type"] == "Polygon"
    strict = run_adapter(t, [{"id": "edge", "a": sq, "b": {"type": "Polygon", "coordinates": [
        [[0, 0], [2.0**61, 0], [0, 1], [0, 0]]]}}], "--strict-range", tmp=tmp_path)
    assert strict[0]["overlay"]["union"] == "unsupported"


def test_cgal_nonfinite_is_invalid_and_unsupported(tmp_path):
    t = next(t for t in TARGETS if t.id == "cgal")
    require(t)
    path = tmp_path / "nan.jsonl"
    path.write_text('{"id": "nan", "a": {"type": "Polygon", "coordinates": [[[0, 0], [NaN, 0], '
                    '[0, 1], [0, 0]]]}, "b": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], '
                    '[0, 1], [0, 0]]]}}\n')
    (r,) = run_adapter(t, path)
    assert r["valid_a"] is False and r["valid_b"] is True
    assert r["overlay"]["union"] == "unsupported" and r["predicates"]["intersects"] == "unsupported"


# ---------------------------------------------------------------------------- isolation


def test_a_crash_fails_one_operation_only(tgt, tmp_path):
    case = {"id": "crash", "a": GEOMS["A"], "b": GEOMS["MA"]}
    (r,) = run_adapter(tgt, [case], env={FAULT_ENV[tgt.dir]: "crash:overlay.union"}, tmp=tmp_path)
    validator().validate(r)
    assert r["overlay"]["union"] is None
    assert r["errors"]["overlay.union"]["kind"] == "crash"
    assert "signal 11" in r["errors"]["overlay.union"]["message"]
    assert r["overlay"]["symdifference"]["type"] in ("Polygon", "MultiPolygon")  # after it
    assert r["overlay"]["intersection"]["type"] in ("Polygon", "MultiPolygon")   # before it


def test_a_hang_times_out_one_operation(tgt, tmp_path):
    env = {FAULT_ENV[tgt.dir]: "hang_:predicates.touches",
           "GEOS_ADAPTER_TIMEOUT": "1", "BG_ADAPTER_TIMEOUT": "1", "CGAL_ADAPTER_TIMEOUT": "1"}
    flags = ("--timeout", "1") if tgt.id == "clipper2" else ()
    (r,) = run_adapter(tgt, [{"id": "hang", "a": GEOMS["A"], "b": GEOMS["A"]}], *flags,
                       env=env, tmp=tmp_path)
    assert r["predicates"]["touches"] is None
    assert r["errors"]["predicates.touches"]["kind"] == "timeout"
    assert r["predicates"]["intersects"] is True
    assert r["overlay"]["union"]["type"] == "Polygon"


def test_no_fork_gives_the_same_answers(tgt, tmp_path):
    cases = pair_cases()[:40]
    forked = run_adapter(tgt, cases, tmp=tmp_path)
    flag = "--no-fork"
    assert run_adapter(tgt, cases, flag, tmp=tmp_path) == forked


# ---------------------------------------------------------------------------- dispatch


def test_legacy_lines_keep_the_v1_contract(tgt, tmp_path):
    legacy_case = {"id": "legacy", "family": "x",
                   "a": [[SQ]], "b": [[[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]]}
    typed_case = {"id": "typed", "a": GEOMS["A"], "b": GEOMS["A"]}
    out = by_id(run_adapter(tgt, [legacy_case, typed_case, legacy_case | {"id": "legacy2"}],
                            tmp=tmp_path))
    v1 = out["legacy"]
    assert set(V1_FIELDS) <= set(v1) and "relate" not in v1 and "overlay" not in v1
    assert v1["area_inter"] == 1.0 and v1["area_union"] == 7.0
    assert out["legacy2"] | {"id": "legacy"} == v1
    assert "overlay" in out["typed"] and "area_inter" not in out["typed"]
    (forced,) = run_adapter(tgt, [legacy_case], "--v2", tmp=tmp_path)
    validator().validate(forced)
    assert area(forced["overlay"]["intersection"]) == 1


def test_ops_select_the_groups_and_parse_errors_are_reported(tgt, tmp_path):
    path = tmp_path / "ops.jsonl"
    only = {"id": "only-relate", "ops": ["relate", "validity"], "a": GEOMS["A"], "b": GEOMS["A"]}
    bad = {"id": "bad-type", "a": {"type": "Triangle", "coordinates": []}, "b": GEOMS["A"]}
    path.write_text(json.dumps(only) + "\n\n" + json.dumps(bad) + "\n")  # blank: no output
    out = run_adapter(tgt, path)
    assert [r["id"] for r in out] == ["only-relate", "bad-type"]
    assert set(out[0]) == {"id", "lib", "relate", "valid_a", "valid_b", "errors"}
    assert set(out[1]) == {"id", "lib", "errors"} and "Triangle" in out[1]["errors"]["*"]
    for r in out:
        validator().validate(r)
