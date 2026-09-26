"""geotruth.minimize: ddmin over parts/holes/vertices, decimals, one adapter call per round."""

from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest
from corpus_testlib import REPO

from geotruth.export.answers import exact_answer
from geotruth.io import geometry_from_json, read_wkt
from geotruth.minimize import (
    AdapterRunner,
    MinimizeError,
    Target,
    case_size,
    error_signature,
    field_for,
    load_case,
    minimised_record,
    minimize,
    part_paths,
    remove_parts,
)
from geotruth.validity import is_valid

pytestmark = pytest.mark.unit

# A fake v2 library: intersects is always False; union output is always A itself.
FAKE_V2 = """
import json, sys
for line in open(sys.argv[1]):
    c = json.loads(line)
    out = {"id": c["id"], "lib": "fake@1",
           "predicates": {"intersects": False},
           "overlay": {"union": c["a"]}}
    print(json.dumps(out))
"""
# A fake v1 library that throws on area_inter when A has more than 4 distinct vertices.
FAKE_V1 = """
import json, sys
for line in open(sys.argv[1]):
    c = json.loads(line)
    pts = {tuple(p) for poly in c["a"] for ring in poly for p in ring}
    errs = {"area_inter": f"Error: boom at [{len(pts)}.5, 2]"} if len(pts) > 4 else {}
    print(json.dumps({"id": c["id"], "lib": "fakev1@1", "area_inter": 1.0, "errors": errs}))
"""


def fake_runner(tmp_path: Path, source: str, contract: str) -> AdapterRunner:
    script = tmp_path / f"fake_{contract}.py"
    script.write_text(textwrap.dedent(source))
    target = Target("fake", "fake@1", f"{sys.executable} {script}", contract, script)
    return AdapterRunner(target, root=tmp_path)


def typed(wkt):
    from geotruth.io import geometry_to_json

    return geometry_to_json(read_wkt(wkt))


# ============================================================================ helpers


def test_field_names_for_each_contract():
    assert field_for("within", True) == "predicates.within"
    assert field_for("area_union", True) == "overlay.union"
    assert field_for("predicates.within", False) == "within"
    assert field_for("overlay.symdifference", False) == "area_symdiff"
    assert field_for("relate", True) == "relate"


def test_error_signature_masks_numbers():
    a = error_signature("Error: Unable to complete output ring starting at [0.36, 0.60]")
    b = error_signature("Error: Unable to complete output ring starting at [-1.5e-3, 2]")
    assert a == b
    assert error_signature({"kind": "timeout", "message": "10 s"}).startswith("timeout")


def test_parts_and_sizes():
    g = typed(
        "GEOMETRYCOLLECTION (POINT (1 2), GEOMETRYCOLLECTION (LINESTRING (0 0, 1 1), "
        "POINT (3 3)), MULTIPOINT ((5 5), (6 6)))"
    )
    assert part_paths(g) == [(0,), (1, 0), (1, 1), (2, 0), (2, 1)]
    h = remove_parts(g, {(1, 0), (1, 1)})
    assert [x["type"] for x in h["geometries"]] == ["Point", "MultiPoint"]
    mp = typed("MULTIPOLYGON (((0 0, 1 0, 0 1, 0 0)), ((5 5, 6 5, 5 6, 5 5)))")
    assert remove_parts(mp, {(0,)})["coordinates"] == [mp["coordinates"][1]]
    # digits of "1.5", "2", "0.25", "1"
    assert case_size(typed("POINT (1.5 2)"), typed("POINT (0.25 1)")) == (2, 9, 2)


def test_load_case_forms(tmp_path):
    p = tmp_path / "c.jsonl"
    p.write_text('{"id": "x", "a": [], "b": []}\n{"id": "y", "a": [], "b": []}\n')
    assert load_case(f"{p}#y")["id"] == "y"
    assert load_case(str(p), "x")["id"] == "x"
    with pytest.raises(MinimizeError):
        load_case(str(p))
    assert load_case('{"id": "z", "a": 1, "b": 2}')["id"] == "z"


# ============================================================================ fakes


def test_value_kind_shrinks_and_batches(tmp_path):
    runner = fake_runner(tmp_path, FAKE_V2, "v2")
    case = {
        "id": "big",
        "family": "t",
        "a": typed(
            "MULTIPOLYGON (((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 2 4, 4 4, 4 2, 2 2)), "
            "((20 0, 30 0, 30 10, 20 0)))"
        ),
        "b": typed(
            "POLYGON ((5.123456789 5.987654321, 15.5 5.25, 15.5 15.75, 5.5 15.125, "
            "5.123456789 5.987654321))"
        ),
    }
    res = minimize(case, runner, "intersects")
    assert res.kind == "value" and res.field == "predicates.intersects"
    assert res.after < res.before
    assert res.after[0] <= 8  # two triangles at most
    ga, gb = geometry_from_json(res.a), geometry_from_json(res.b)
    assert is_valid(ga) and is_valid(gb)
    assert exact_answer(ga, gb, areas=False).predicates["intersects"] is True
    # one adapter call per round (plus the initial check), each on a batch of candidates
    assert res.adapter_calls <= res.rounds + 1
    assert runner.cases_run > runner.calls
    rec = minimised_record(case, res, runner.target)
    assert rec["provenance"]["parent"] == "big" and rec["id"] == "big.min"
    from geotruth import schemas

    schemas.validate("case", rec)


def test_area_kind_on_overlay_output(tmp_path):
    runner = fake_runner(tmp_path, FAKE_V2, "v2")
    case = {
        "id": "u",
        "a": typed("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))"),
        "b": typed("POLYGON ((2 2, 6 2, 6 6, 2 6, 2 2))"),
    }
    res = minimize(case, runner, "overlay.union")
    assert res.kind == "area"
    ans = exact_answer(geometry_from_json(res.a), geometry_from_json(res.b))
    assert ans.areas["union"] > ans.areas["a"]  # the fake's answer (area A) is still wrong


def test_error_kind_v1_contract(tmp_path):
    runner = fake_runner(tmp_path, FAKE_V1, "v1")
    case = {
        "id": "e",
        "a": [[[[0, 0], [8, 0], [9, 4], [8, 8], [4, 9], [0, 8], [0, 0]]]],
        "b": [[[[1, 1], [2, 1], [1, 2], [1, 1]]]],
    }
    res = minimize(case, runner, "area_inter")
    assert res.kind == "error"
    a_pts = {tuple(p) for ring in res.a["coordinates"] for p in ring}
    assert len(a_pts) == 5  # the smallest A that still makes the fake throw
    assert res.after < res.before


def test_case_that_does_not_fail_is_refused(tmp_path):
    runner = fake_runner(tmp_path, FAKE_V2, "v2")
    case = {"id": "d", "a": typed("POINT (0 0)"), "b": typed("POINT (5 5)")}
    with pytest.raises(MinimizeError, match="does not fail"):
        minimize(case, runner, "intersects")


def test_v1_adapter_rejects_non_polygons(tmp_path):
    runner = fake_runner(tmp_path, FAKE_V1, "v1")
    case = {"id": "l", "a": typed("LINESTRING (0 0, 1 1)"), "b": typed("POINT (0 0)")}
    with pytest.raises(MinimizeError, match="polygons only"):
        minimize(case, runner, "area_inter")


def test_cli_minimize_with_a_manifest_target(tmp_path, capsys, monkeypatch):
    """`geotruth minimize` finds the target in adapters/*/adapter.toml (here: a fake one)."""
    import geotruth.minimize as gm

    runner_script = tmp_path / "fake.py"
    runner_script.write_text(textwrap.dedent(FAKE_V2))
    monkeypatch.setattr(
        gm,
        "find_target",
        lambda lib, root=REPO: Target(
            lib, "fake@1", f"{sys.executable} {runner_script}", "v2", runner_script
        ),
    )
    case = tmp_path / "case.json"
    case.write_text(
        json.dumps(
            {
                "id": "c",
                "a": typed("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))"),
                "b": typed("POLYGON ((1 1, 2 1, 2 2, 1 1))"),
            }
        )
    )
    out = tmp_path / "min.json"
    from geotruth.cli import main

    assert (
        main(
            [
                "minimize",
                str(case),
                "--lib",
                "fake",
                "--field",
                "intersects",
                "--json",
                "-o",
                str(out),
            ]
        )
        == 0
    )
    report = json.loads(capsys.readouterr().out)
    assert report["after"]["coordinates"] <= report["before"]["coordinates"]
    assert json.loads(out.read_text())["provenance"]["source"] == "minimised"
