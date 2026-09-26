"""harness/compare.py: the v1 comparer lists every disagreement, and nothing else."""

import json
import subprocess
import sys

import pytest

ORACLE = {
    "id": "c1", "lib": "oracle", "valid_a": True, "valid_b": True,
    "intersects": True, "disjoint": False, "touches": False, "overlaps": True,
    "contains": False, "covers": False, "within": False, "covered_by": False, "equals": False,
    "area_a": 4.0, "area_b": 4.0,
    "area_inter": 1.0, "area_union": 7.0, "area_diff": 3.0, "area_symdiff": 6.0,
}


def result(**changes):
    res = {k: v for k, v in ORACLE.items() if k not in ("area_a", "area_b")}
    res.update({"lib": "lib@1", "errors": {}, **changes})
    return res


@pytest.mark.unit
def test_agreement_gives_nothing(compare_mod):
    assert compare_mod.compare({}, ORACLE, result()) == []


@pytest.mark.unit
def test_predicate_disagreement(compare_mod):
    found = compare_mod.compare({}, ORACLE, result(touches=True))
    assert found == [("predicate", "touches", False, True)]


@pytest.mark.unit
def test_null_fields_are_not_disagreements(compare_mod):
    res = result(touches=None, area_union=None, valid_a=None)
    assert compare_mod.compare({}, ORACLE, res) == []


@pytest.mark.unit
def test_area_tolerance_is_relative_to_the_operands(compare_mod):
    # 1e-6 of max(area A, area B) = 4e-6 is tolerated, 1e-5 is not
    assert compare_mod.compare({}, ORACLE, result(area_inter=1.0 + 3e-6)) == []
    found = compare_mod.compare({}, ORACLE, result(area_inter=1.0 + 1e-5))
    assert [f[:2] for f in found] == [("area", "area_inter")]


@pytest.mark.unit
def test_errors_are_reported_on_valid_input(compare_mod):
    res = result(area_union=None, errors={"area_union": "TopologyException: x"})
    assert compare_mod.compare({}, ORACLE, res) == [
        ("error", "area_union", None, "TopologyException: x")]


@pytest.mark.unit
def test_invalid_input_is_judged_on_validity_only(compare_mod):
    orc = {"id": "c1", "lib": "oracle", "valid_a": False, "valid_b": True}
    res = result(valid_a=True, touches=True, errors={"area_inter": "boom"})
    assert compare_mod.compare({}, orc, res) == [("validity", "valid_a", False, True)]


@pytest.mark.unit
def test_command_line_on_seed_expected_answers(repo, tmp_path):
    """The expected answers compared with themselves: 1000 cases, no disagreement."""
    seed = repo / "corpus" / "cases" / "seed.jsonl"
    expected = repo / "corpus" / "expected-v1" / "seed.jsonl"
    out = subprocess.run([sys.executable, str(repo / "harness" / "compare.py"), str(seed),
                          str(expected), str(expected), "--json"],
                         capture_output=True, text=True, check=True)
    assert out.stdout == ""
    assert "# 0 disagreements over 1000 cases" in out.stderr


@pytest.mark.crosscheck
def test_shapely_adapter_agrees_with_expected_on_seed(repo, tmp_path):
    """The reference adapter's seed baseline: GEOS gives 0 disagreements (harness/README.md)."""
    pytest.importorskip("shapely")
    seed = repo / "corpus" / "cases" / "seed.jsonl"
    sample = tmp_path / "sample.jsonl"
    sample.write_text("".join(seed.read_text().splitlines(keepends=True)[::4]))
    results = tmp_path / "shapely.jsonl"
    with open(results, "w") as f:
        subprocess.run([sys.executable, str(repo / "adapters" / "shapely" / "shapely_adapter.py"),
                        str(sample)], stdout=f, check=True)
    out = subprocess.run([sys.executable, str(repo / "harness" / "compare.py"), str(sample),
                          str(repo / "corpus" / "expected-v1" / "seed.jsonl"), str(results),
                          "--json"], capture_output=True, text=True, check=True)
    assert [json.loads(line) for line in out.stdout.splitlines()] == []
    assert "# 0 disagreements over 250 cases" in out.stderr
