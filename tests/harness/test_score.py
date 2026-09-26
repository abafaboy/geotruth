"""The scorer (src/geotruth/harness/score.py, DESIGN §4.3) on synthetic results: every
verdict and overlay tier, derived-field dedup, conventions, engine abstentions, schema
validity of every record; and end to end, the engine control scores 100% while every fault
of the mutant is caught."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from geotruth import schemas
from geotruth.harness import engine, score
from geotruth.harness.control import ControlLibrary, MutantLibrary
from geotruth.harness.manifest import find_target
from geotruth.harness.pyadapter import Config, Runner, answer_line
from geotruth.io import case_from_json

pytestmark = pytest.mark.unit
pytest.importorskip("jsonschema")

SQ_A = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
SQ_B = [[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]


def case(cid: str, a, b, **extra) -> dict:
    return {
        "id": cid,
        "family": "synthetic",
        "tags": {"degeneracy": "lattice"},
        "provenance": {"source": "manual"},
        "a": {"type": "Polygon", "coordinates": [a]} if isinstance(a, list) else a,
        "b": {"type": "Polygon", "coordinates": [b]} if isinstance(b, list) else b,
        **extra,
    }


def expected_for(c: dict) -> dict:
    rec = engine.expected_record(case_from_json(c))
    schemas.validate("expected", rec)
    return rec


def good_result(c: dict, exp: dict, lib: str = "fake@1") -> dict:
    """A result that agrees with the expected answer (overlays: the exact result rounded)."""
    from geotruth.harness.control import rounded_json
    from geotruth.io import geometry_from_json

    res = {
        "id": c["id"],
        "lib": lib,
        "relate": exp["relate"],
        "predicates": dict(exp["predicates"]),
        "valid_a": exp["validity"]["a"]["valid"],
        "valid_b": exp["validity"]["b"]["valid"],
        "overlay": {},
        "errors": {},
    }
    for op, v in exp["overlay"].items():
        res["overlay"][op] = rounded_json(geometry_from_json(v["non_strict"]["exact"], exact=True))
    schemas.validate("result", res)
    return res


def run_score(c: dict, exp: dict, res: dict, target: str | None = "geos-main") -> dict:
    ctx = score.ScoreContext(
        target=find_target(target) if target else None,
        lib_id=target or "x",
        versions={"engine": "0.1.0"},
    )
    recs = score.score_case(case_from_json(c), exp, res, ctx)
    for r in recs:
        schemas.validate("score", r)
    return {r["capability"]: r for r in recs}


@pytest.fixture(scope="module")
def base():
    c = case("sq", SQ_A, SQ_B)
    exp = expected_for(c)
    return c, exp, good_result(c, exp)


# ============================================================================ verdicts


def test_all_correct(base):
    c, exp, res = base
    got = run_score(c, exp, res)
    assert set(got) == {
        "relate",
        "predicates",
        "validity",
        *(f"overlay.{op}" for op in score.OVERLAY_OPS),
    }
    assert all(r["verdict"] == "correct" for r in got.values())
    assert {got[f"overlay.{op}"]["tier"] for op in score.OVERLAY_OPS} == {"exact"}


def test_relate_and_predicates_wrong(base):
    c, exp, res = base
    bad = copy.deepcopy(res)
    bad["relate"] = "212111212"
    bad["predicates"]["touches"] = True
    got = run_score(c, exp, bad)
    assert got["relate"]["verdict"] == "wrong" and got["relate"]["fields"] == ["relate"]
    assert got["relate"]["cluster"].endswith("relate:BB")
    p = got["predicates"]
    assert p["verdict"] == "wrong" and p["fields"] == ["predicates.touches"] and not p["derived"]


def test_predicates_derived_from_wrong_relate_are_counted_once(base):
    """rust-geo derives its predicates from relate: with relate wrong too, the predicates
    record is marked derived and the headline counts the case once."""
    c, exp, res = base
    bad = copy.deepcopy(res)
    bad["relate"] = "FF2FF1212"
    bad["predicates"]["intersects"] = False
    bad["predicates"]["disjoint"] = True
    got = run_score(c, exp, bad, target="rust-geo")
    assert got["relate"]["verdict"] == "wrong"
    assert got["predicates"]["verdict"] == "wrong" and got["predicates"]["derived"] is True
    s = score.summarize(got.values())
    assert s["headline_failures"] == 1 and s["derived"] == {"predicates": 1}
    # the same predicates with a correct relate are not deduplicated
    bad["relate"] = exp["relate"]
    got = run_score(c, exp, bad, target="rust-geo")
    assert got["predicates"]["derived"] is False


def test_overlay_derived_from_a_wrong_overlay_is_counted_once(base):
    """Turf's symdifference is derived from two differences (manifest): with difference
    wrong too, the symdifference record is marked derived; alone, it is not."""
    c, exp, res = base
    far = {"type": "Polygon", "coordinates": [[[50, 50], [51, 50], [51, 51], [50, 51], [50, 50]]]}
    bad = copy.deepcopy(res)
    bad["overlay"]["difference"] = far
    bad["overlay"]["symdifference"] = far
    got = run_score(c, exp, bad, target="turf")
    assert got["overlay.difference"]["tier"] == "topological"  # missing and extra parts
    assert got["overlay.symdifference"]["verdict"] == "wrong"
    assert got["overlay.symdifference"]["derived"] is True
    assert "derived" not in got["overlay.difference"]
    s = score.summarize(got.values())
    assert s["derived"] == {"overlay.symdifference": 1}
    assert "derived from another overlay" in score.summary_table(s)
    bad["overlay"]["difference"] = res["overlay"]["difference"]
    got = run_score(c, exp, bad, target="turf")
    assert "derived" not in got["overlay.symdifference"]
    # a library whose symdifference is its own call is never deduplicated
    bad["overlay"]["difference"] = far
    got = run_score(c, exp, bad, target="polygon-clipping")
    assert "derived" not in got["overlay.symdifference"]


def test_convention_null_unsupported_and_error(base):
    c, exp, res = base
    exp2 = copy.deepcopy(exp)
    exp2["conventions"] = ["predicates.equals"]
    bad = copy.deepcopy(res)
    bad["predicates"]["equals"] = not exp["predicates"]["equals"]
    assert run_score(c, exp2, bad)["predicates"]["verdict"] == "convention"
    nulls = copy.deepcopy(res)
    nulls["relate"] = None
    nulls["predicates"] = dict.fromkeys(nulls["predicates"])
    nulls["valid_a"] = nulls["valid_b"] = "unsupported"
    got = run_score(c, exp, nulls)
    assert got["relate"]["verdict"] == "not_reported"
    assert got["predicates"]["verdict"] == "not_reported"
    assert got["validity"]["verdict"] == "unsupported"
    err = copy.deepcopy(res)
    err["relate"] = None
    err["overlay"]["union"] = None
    err["errors"] = {
        "relate": "TopologyException: side location conflict",
        "overlay.union": {"kind": "timeout", "message": "3 s"},
    }
    got = run_score(c, exp, err)
    assert got["relate"]["verdict"] == "error"
    u = got["overlay.union"]
    assert u["verdict"] == "error" and u["tier"] == "exception"
    assert u["metrics"]["error_kind"] == "timeout"
    assert score.summarize(got.values())["headline_failures"] == 2


def test_engine_abstentions_are_never_counted(base):
    c, _, res = base
    for status in ("engine_skipped", "engine_error"):
        e = {"id": c["id"], "engine": {"version": "0.1.0"}, "status": status, "reason": "budget"}
        got = run_score(c, e, res)
        assert {r["verdict"] for r in got.values()} == {status}
        assert score.summarize(got.values())["headline_failures"] == 0


def test_invalid_input_scores_validity_only():
    bow = [[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]
    c = case("bow", bow, SQ_B)
    exp = expected_for(c)
    assert exp["validity"]["a"]["valid"] is False and "relate" not in exp
    res = {
        "id": "bow",
        "lib": "x@1",
        "relate": "212101212",
        "predicates": {"intersects": True},
        "valid_a": True,
        "valid_b": True,
        "overlay": {"union": None},
        "errors": {},
    }
    got = run_score(c, exp, res)
    assert set(got) == {"validity"}
    assert got["validity"]["verdict"] == "wrong" and got["validity"]["fields"] == ["valid_a"]


def test_parse_echo_canary():
    cases = json.loads((Path(schemas.schema_dir()) / "examples" / "case.v2.valid.json").read_text())
    (c,) = [x for x in cases if x.get("ops") == ["echo"]]
    from geotruth.io import geometry_from_json, geometry_to_json

    echo = {k: geometry_to_json(geometry_from_json(c[k])) for k in ("a", "b")}
    res = {"id": c["id"], "lib": "x@1", "echo": echo, "errors": {}}
    assert run_score(c, None, res)["echo"]["verdict"] == "correct"
    flipped = copy.deepcopy(echo)
    flipped["a"]["coordinates"][1][0] = 0.0  # -0.0 lost its sign
    got = run_score(c, None, {**res, "echo": flipped})["echo"]
    assert got["verdict"] == "wrong" and got["fields"] == ["echo.a"]
    rounded = copy.deepcopy(echo)
    rounded["a"]["coordinates"][1][1] = 0.3  # 0.30000000000000004 printed with 17 digits too few
    assert run_score(c, None, {**res, "echo": rounded})["echo"]["verdict"] == "wrong"


# ============================================================================ overlay tiers


def _grade(
    c: dict, exp: dict, geom: dict, op: str = "intersection", target: str | None = "geos-main"
):
    res = {"id": c["id"], "lib": "x@1", "overlay": {op: geom}, "errors": {}}
    return run_score(c, exp, res, target)[f"overlay.{op}"]


def test_overlay_tiers_rounding_budget_gross():
    # a tri-tri intersection with a non-dyadic exact vertex (2/3, 2/3)
    ta = [[0, 0], [1, 1], [0, 1], [0, 0]]
    tb = [[0, 1], [2, 0], [2, 1], [0, 1]]
    c = case("tri", ta, tb)
    exp = expected_for(c)
    third = 2 / 3
    correctly_rounded = {
        "type": "Polygon",
        "coordinates": [[[0, 1], [third, third], [1, 1], [0, 1]]],
    }
    r = _grade(c, exp, correctly_rounded)
    assert r["tier"] == "rounding" and r["verdict"] == "correct"
    assert "hausdorff2" in r["metrics"] and r["metrics"]["output_valid"] is True
    # moved by 1e-12: beyond the rounding floor, within GEOS's 1e-8 M
    off = third + 1e-12
    within = {"type": "Polygon", "coordinates": [[[0, 1], [off, off], [1, 1], [0, 1]]]}
    r = _grade(c, exp, within)
    assert r["tier"] == "budget" and r["verdict"] == "correct"
    # the same output is gross for a library whose budget is the rounding floor only
    assert _grade(c, exp, within, target="engine-control")["tier"] == "gross"
    # and for one without a documented budget
    assert _grade(c, exp, within, target="martinez")["tier"] == "gross"
    far = {"type": "Polygon", "coordinates": [[[0, 1], [0.6, 0.6], [1, 1], [0, 1]]]}
    r = _grade(c, exp, far)
    assert r["tier"] == "gross" and r["verdict"] == "wrong"
    assert score.summarize([r])["headline_failures"] == 1


def test_overlay_topological_invalid_missing_and_extra():
    c = case("sq2", SQ_A, SQ_B)
    exp = expected_for(c)
    # a bow-tie instead of the unit square: invalid output (measured by even-odd)
    bow = {"type": "Polygon", "coordinates": [[[1, 1], [2, 2], [2, 1], [1, 2], [1, 1]]]}
    r = _grade(c, exp, bow)
    assert r["tier"] == "topological" and r["metrics"]["output_valid"] is False
    # the symmetric difference is two L-shapes: one of them missing
    sym = exp["overlay"]["symdifference"]["areal"]["exact"]
    one = {
        "type": "Polygon",
        "coordinates": [
            [[float(eval(x)), float(eval(y))] for x, y in ring] for ring in sym["coordinates"][0]
        ],
    }
    r = _grade(c, exp, one, "symdifference")
    assert r["tier"] == "topological" and r["metrics"]["missing_components"] == 1
    # an extra, far-away component
    extra = {
        "type": "MultiPolygon",
        "coordinates": [
            [[[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]]],
            [[[10, 10], [11, 10], [11, 11], [10, 11], [10, 10]]],
        ],
    }
    r = _grade(c, exp, extra)
    assert r["tier"] == "topological" and r["metrics"]["extra_components"] == 1


def test_overlay_exact_equal_point_sets_and_variants():
    c = case("sq3", SQ_A, SQ_B)
    exp = expected_for(c)
    # same point set, other start vertex, orientation and an extra collinear vertex
    same = {
        "type": "MultiPolygon",
        "coordinates": [[[[2, 2], [1.5, 2], [1, 2], [1, 1], [2, 1], [2, 2]]]],
    }
    assert _grade(c, exp, same)["tier"] == "exact"
    # touching squares: the areal intersection is empty, the non-strict one a line
    cc = case(
        "touch", [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]], [[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]
    )
    e2 = expected_for(cc)
    empty = {"type": "Polygon", "coordinates": []}
    r = _grade(cc, e2, empty)
    assert r["tier"] == "exact" and r["metrics"]["variant"] == "areal"
    line = {"type": "LineString", "coordinates": [[1, 1], [1, 0]]}
    r = _grade(cc, e2, line)
    assert r["tier"] == "exact" and r["metrics"]["variant"] == "non_strict"
    wrong_line = {"type": "LineString", "coordinates": [[1, 1], [1, 0.5]]}
    assert _grade(cc, e2, wrong_line)["tier"] == "gross"


def test_thin_component_may_vanish_within_budget():
    """An exact sliver thinner than delta that the library drops is within its budget, but
    not within the rounding floor; for a library without a budget it is a missing component."""
    a = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
    far = [[20, 0], [30, 0], [30, 10], [20, 10], [20, 0]]
    sliver = [[9.999999999, 0], [10, 0], [10, 10], [9.999999999, 10], [9.999999999, 0]]
    c = case("thin", {"type": "MultiPolygon", "coordinates": [[a], [far]]}, sliver)
    exp = expected_for(c)
    assert exp["overlay"]["intersection"]["areal"]["wkt"].startswith("POLYGON ((9.999999999 0")
    empty = {"type": "Polygon", "coordinates": []}
    r = _grade(c, exp, empty)
    assert r["verdict"] == "correct" and r["tier"] == "budget", r
    assert r["metrics"].get("excused_thin") == 1
    r = _grade(c, exp, empty, target="martinez")
    assert r["tier"] == "topological" and r["metrics"]["missing_components"] == 1


def test_extreme_range_metrics_do_not_overflow():
    """Coordinates near 1e200: squared distances and area budgets exceed the double range;
    they are reported as decimal strings, never as a scorer failure."""
    big = 1e200
    a = [[0, 0], [2 * big, 0], [2 * big, 2 * big], [0, 2 * big], [0, 0]]
    b = [[big, big], [3 * big, big], [3 * big, 3 * big], [big, 3 * big], [big, big]]
    c = case("extreme", a, b)
    exp = expected_for(c)
    moved = {
        "type": "Polygon",
        "coordinates": [
            [[big, big], [2 * big, big], [2 * big, 2.5 * big], [big, 2 * big], [big, big]]
        ],
    }
    r = _grade(c, exp, moved)
    assert r["verdict"] == "wrong" and r["tier"] == "gross"
    assert "area_budget_decimal" in r["metrics"] and "area_budget" not in r["metrics"]
    good = good_result(c, exp)
    recs = run_score(c, exp, good)
    s = score.summarize(recs.values())
    assert s["headline_failures"] == 0 and s["scorer_failures"] == 0


def test_scorer_failure_is_isolated_and_counted(base, monkeypatch):
    """A capability the scorer fails on gets its own engine_error record (the rest of the
    case is still graded); the summary counts it and the table warns."""
    c, exp, res = base

    def boom(*args, **kwargs):
        raise ZeroDivisionError("synthetic")

    monkeypatch.setattr(score, "grade_overlay", boom)
    got = run_score(c, exp, res)
    assert got["relate"]["verdict"] == "correct" and got["validity"]["verdict"] == "correct"
    r = got["overlay.union"]
    assert r["verdict"] == "engine_error" and r["got"].startswith("scorer failed: ZeroDivision")
    s = score.summarize(got.values())
    assert s["scorer_failures"] == 4 and s["headline_failures"] == 0
    assert "WARNING: 4 records the scorer failed on" in score.summary_table(s)


def test_mutant_overlay_mutation_changes_a_collinear_vertex():
    """The mutant moves ring[1] off its neighbours' chord: a collinear vertex moved along
    its own edge would leave the point set (and the grade) unchanged."""
    from geotruth.harness.control import _displaced

    ring = [[0.0, 0.0], [1.0, 0.0], [2.0, 0.0], [2.0, 2.0], [0.0, 2.0], [0.0, 0.0]]
    x, y = _displaced(ring)
    assert x == 1.0 and y == 2 / 256
    # a tiny ring far from the origin: the move is 2^-20 of the largest ordinate
    tiny = [[100.0, 0.0], [100.0 + 1e-12, 0.0], [100.0 + 1e-12, 1e-12], [100.0, 0.0]]
    x, y = _displaced(tiny)
    assert ((x - tiny[1][0]) ** 2 + (y - tiny[1][1]) ** 2) ** 0.5 >= 100 * 2.0**-20 * 0.999


def test_summary_table_mentions_headline():
    c = case("sq4", SQ_A, SQ_B)
    exp = expected_for(c)
    res = good_result(c, exp)
    res["relate"] = "FF2FF1212"
    recs = list(run_score(c, exp, res).values())
    s = score.summarize(recs)
    table = score.summary_table(s)
    assert "1 headline failures" in table and "overlay tiers" in table
    assert s["clusters"] == {"geos-main|synthetic|relate:II,IB,BI,BB": 1}
    assert s["scorer_failures"] == 0 and "WARNING" not in table


# ============================================================================ control and mutant


def _cases() -> list[dict]:
    out = [
        case("sq", SQ_A, SQ_B),
        case(
            "touch",
            [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]],
            [[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]],
        ),
        case("tri", [[0, 0], [1, 1], [0, 1], [0, 0]], [[0, 1], [2, 0], [2, 1], [0, 1]]),
        case(
            "hole",
            [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]],
            [[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]],
        ),
        case("far", SQ_A, [[5, 5], [6, 5], [6, 6], [5, 5]]),
        case("same", SQ_A, SQ_A),
        case("line", {"type": "LineString", "coordinates": [[-1, 1], [3, 1]]}, SQ_A),
        case("pts", {"type": "MultiPoint", "coordinates": [[1, 1], [5, 5]]}, SQ_A),
        case("empty", {"type": "Point", "coordinates": []}, SQ_A),
        case(
            "tiny",
            [[0, 0], [1e-300, 0], [1e-300, 1e-300], [0, 0]],
            [[0, 0], [1e-300, 1e-300], [0, 1e-300], [0, 0]],
        ),
        case("bow", [[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]], SQ_B),
    ]
    cases = json.loads((Path(schemas.schema_dir()) / "examples" / "case.v2.valid.json").read_text())
    out += [x for x in cases if x.get("ops") == ["echo"]]
    return out * 2  # 24 cases: every 17th fault lands on several kinds of field


def _run_library(lib, cases: list[dict]) -> list[dict]:
    runner = Runner(lib, Config(fork=False))
    out = []
    for i, c in enumerate(cases):
        c = {**c, "id": f"{c['id']}-{i}"}
        rec, parsed = answer_line(lib, runner, json.dumps(c))
        out.append((c, lib.postprocess(rec, parsed)))
    return out


def _score_all(pairs, target: str) -> list[dict]:
    ctx = score.ScoreContext(target=find_target(target), lib_id=target)
    recs = []
    for c, res in pairs:
        schemas.validate("result", json.loads(json.dumps(res)))
        recs += score.score_case(
            case_from_json(c), expected_for(c) if c.get("ops") != ["echo"] else None, res, ctx
        )
    for r in recs:
        schemas.validate("score", r)
    return recs


def test_engine_control_scores_100_percent():
    pairs = _run_library(ControlLibrary(), _cases())
    recs = _score_all(pairs, "engine-control")
    s = score.summarize(recs)
    assert s["headline_failures"] == 0, [r for r in recs if r["verdict"] in ("wrong", "error")]
    verdicts = {v for caps in s["verdicts"].values() for v in caps}
    assert verdicts <= {"correct", "unsupported", "not_reported"}
    assert s["verdicts"]["echo"] == {"correct": 2}
    assert sum(s["verdicts"]["relate"].values()) == 20  # 10 valid cases x 2
    assert all(r["tier"] in ("exact", "rounding") for r in recs if "tier" in r)


def test_mutant_is_caught():
    lib = MutantLibrary()
    pairs = _run_library(lib, _cases())
    recs = _score_all(pairs, "mutant")
    assert lib.mutations, "the mutant made no mutation"
    by = {(r["id"], r["capability"]): r for r in recs}
    kinds = set()
    for cid, path in lib.mutations:
        cap = "predicates" if path.startswith("predicates.") else path
        r = by[(cid, cap)]
        kinds.add(cap.split(".")[0])
        if cap == "predicates":
            assert r["verdict"] in ("wrong", "convention") and path in r["fields"], r
        else:
            assert r["verdict"] == "wrong" and r["tier"] in ("gross", "topological"), r
    assert kinds == {"predicates", "overlay"}
    assert score.summarize(recs)["headline_failures"] >= len(lib.mutations) - sum(
        1 for r in recs if r["verdict"] == "convention"
    )
