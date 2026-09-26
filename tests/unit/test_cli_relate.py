"""Tests of ``geotruth relate`` (src/geotruth/commands/relate.py)."""

from __future__ import annotations

import io
import json

import pytest

from geotruth import cli
from geotruth.commands import relate as cmd

SQ = "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"
LINE = "LINESTRING (1 1, 3 1)"


def run(capsys, *argv: str) -> tuple[int, str, str]:
    status = cli.main(["relate", *argv])
    out = capsys.readouterr()
    return status, out.out, out.err


def test_registered():
    commands = cli.discover()
    assert "relate" in commands and commands["relate"].error is None
    assert commands["relate"].help.startswith("print the exact DE-9IM")


def test_text_output(capsys):
    status, out, err = run(capsys, SQ, LINE)
    assert status == 0 and err == ""
    assert "relate: 1020F1102" in out
    assert "A: Polygon (5 coordinates; real dimension 2)" in out
    assert "      I  B  E\n   I  1  0  2\n   B  0  F  1\n   E  1  0  2" in out
    assert "  crosses     true" in out and "  within      false" in out
    for name in ("intersects", "disjoint", "touches", "overlaps", "contains", "covers",
                 "covered_by", "equals"):  # fmt: skip
        assert f"  {name}" in out


def test_json_output_is_an_expected_record(capsys):
    status, out, _ = run(capsys, SQ, LINE, "--json")
    rec = json.loads(out)
    assert status == 0
    assert rec["relate"] == "1020F1102" and rec["status"] == "ok" and rec["id"] == "cli"
    assert rec["predicates"]["crosses"] is True and rec["conventions"] == []
    assert rec["dimensions"]["b"] == {"dimension": 1, "real_dimension": 1}
    assert rec["validity"]["a"]["valid"] is True
    pytest.importorskip("jsonschema")
    from geotruth import schemas

    schemas.validate("expected", rec)


def test_pattern_dual_and_explain(capsys):
    status, out, _ = run(capsys, SQ, LINE, "--pattern", "T*T******", "--dual", "--explain")
    assert status == 0
    assert "pattern T*T******: true" in out
    assert "witness route: 1020F1102 agrees" in out
    assert "   IB = 0: vertex (1 1)" in out and "   EE = 2: the unbounded face" in out
    status, out, _ = run(capsys, SQ, LINE, "--json", "--pattern", "T*F**F***", "--dual",
                         "--explain")  # fmt: skip
    rec = json.loads(out)
    assert rec["pattern"] == {"pattern": "T*F**F***", "matches": False}
    assert rec["witness"] == {"relate": "1020F1102", "agree": True}
    assert rec["cells"]["BI"] == {"dim": 0, "cell": "vertex (2 1)"}


def test_dual_disagreement_exits_1(capsys, monkeypatch):
    from geotruth import relate_witness

    class Fake:
        matrix = "FFFFFFFF2"

    monkeypatch.setattr(relate_witness, "relate_witness", lambda a, b: Fake())
    status, out, _ = run(capsys, SQ, LINE, "--dual")
    assert status == cmd.EXIT_DISAGREE and "DISAGREES" in out


def test_conventions_are_shown(capsys):
    status, out, _ = run(capsys, "POINT EMPTY", "LINESTRING EMPTY")
    assert status == 0 and "relate: FFFFFFFF2" in out
    assert "  equals      true   (convention; alternative false" in out
    status, out, _ = run(capsys, "POINT EMPTY", "LINESTRING EMPTY", "--json")
    assert "predicates.equals" in json.loads(out)["conventions"]


def test_files_json_and_cases(capsys, tmp_path):
    a = tmp_path / "a.wkt"
    a.write_text(SQ + "\n")
    b = tmp_path / "b.json"
    b.write_text(json.dumps({"type": "LineString", "coordinates": [[1, 1], [3, 1]]}))
    assert run(capsys, f"@{a}", f"@{b}", "--json")[0] == 0
    # inline typed JSON
    status, out, _ = run(capsys, SQ, '{"type": "Point", "coordinates": [1, 1]}', "--json")
    assert json.loads(out)["relate"] == "0F2FF1FF2"
    # a single case object supplies both operands, with its id
    case = tmp_path / "case.json"
    case.write_text(json.dumps({"id": "c1", "a": {"type": "Point", "coordinates": [1, 1]},
                                "b": {"type": "Point", "coordinates": [1, 1]}}))  # fmt: skip
    status, out, _ = run(capsys, f"@{case}", "--json")
    rec = json.loads(out)
    assert status == 0 and rec["id"] == "c1" and rec["relate"] == "0FFFFFFF2"
    # JSON lines: pick a case with --id; legacy FORMAT-v1 operands are accepted
    lines = tmp_path / "cases.jsonl"
    sq = [[[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]]
    far = [[[[5, 5], [6, 5], [6, 6], [5, 5]]]]
    records = [{"id": "x", "a": sq, "b": sq}, {"id": "y", "a": sq, "b": far}]
    lines.write_text("\n".join(json.dumps(r) for r in records))
    status, out, _ = run(capsys, f"@{lines}", "--id", "y", "--json")
    assert status == 0 and json.loads(out)["relate"] == "FF2FF1212"
    status, _, err = run(capsys, f"@{lines}")
    assert status == cmd.EXIT_INPUT and "--id" in err
    status, _, err = run(capsys, f"@{lines}", "--id", "nope")
    assert status == cmd.EXIT_INPUT and "no case with id 'nope'" in err


def test_seed_case_by_id(capsys, repo_root):
    path = repo_root / "corpus" / "cases" / "seed.jsonl"
    first = json.loads(path.read_text().splitlines()[0])["id"]
    status, out, _ = run(capsys, f"@{path}", "--id", first, "--dual")
    assert status == 0 and "agrees" in out


def test_stdin(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(SQ))
    status, out, _ = run(capsys, "-", "POINT (1 1)", "--json")
    assert status == 0 and json.loads(out)["relate"] == "0F2FF1FF2"
    monkeypatch.setattr("sys.stdin", io.StringIO(SQ))
    status, _, err = run(capsys, "-", "-")
    assert status == cmd.EXIT_INPUT and "one operand" in err


@pytest.mark.parametrize(
    ("argv", "fragment"),
    [
        (["POLYGON ((0 0, 1 0", "POINT (0 0)"], "bad WKT"),
        (["{not json", "POINT (0 0)"], "bad JSON"),
        (['{"type": "Blob", "coordinates": []}', "POINT (0 0)"], "bad geometry"),
        (["POINT (0 0)"], "B is missing"),
        (["@/no/such/file.wkt", "POINT (0 0)"], "cannot read"),
        (["", "POINT (0 0)"], "no geometry"),
        ([SQ, "POINT (0 0)", "--pattern", "XYZ"], "pattern"),
        (['{"a": {"type": "Point", "coordinates": [0, 0]}, "b": {"type": "Point", '
          '"coordinates": [0, 0]}}', "POINT (0 0)"], "give it alone"),
        (["POINT (0 0)", '{"a": {"type": "Point", "coordinates": [0, 0]}, "b": {"type": '
          '"Point", "coordinates": [0, 0]}}'], "B is a case"),
    ],
)  # fmt: skip
def test_bad_input(capsys, argv, fragment):
    status, _, err = run(capsys, *argv)
    assert status == cmd.EXIT_INPUT
    assert fragment in err


def test_invalid_input_is_noted_or_refused(capsys):
    # outside the engine's contract: a bow-tie has zero signed area
    status, _, err = run(capsys, "POLYGON ((0 0, 2 2, 2 0, 0 2, 0 0))", "POINT (1 1)")
    assert status == cmd.EXIT_INPUT
    assert "A is invalid (Self-intersection)" in err and "outside the engine's contract" in err
    # invalid but accepted (parts of a MultiPolygon sharing an edge): answered, with a note
    mp = "MULTIPOLYGON (((0 0, 1 0, 1 1, 0 1, 0 0)), ((1 0, 2 0, 2 1, 1 1, 1 0)))"
    status, out, err = run(capsys, mp, "POINT (1 0.5)", "--json")
    assert status == 0 and "B is invalid" not in err and "A is invalid" in err
    assert json.loads(out)["validity"]["a"]["valid"] is False


def test_budget_options(capsys):
    comb = "POLYGON ((0 0, 1 0, 1 5, 2 5, 2 0, 3 0, 3 5, 4 5, 4 0, 5 0, 5 -1, 0 -1, 0 0))"
    rot = "POLYGON ((-1 1, -1 2, 4 2, 4 3, -1 3, -1 4, 4 4, 4 5, -1 5, -1 6, -2 6, -2 1, -1 1))"
    status, out, _ = run(capsys, comb, rot, "--max-size", "10")
    assert status == cmd.EXIT_SKIPPED and "status: engine_skipped" in out
    status, out, _ = run(capsys, comb, rot, "--max-size", "10", "--json")
    rec = json.loads(out)
    assert rec["status"] == "engine_skipped" and "size" in rec["reason"] and "relate" not in rec
    assert run(capsys, comb, rot, "--max-size", "10", "--no-budget")[0] == 0
    assert run(capsys, comb, rot, "--max-seconds", "1e-9")[0] == cmd.EXIT_SKIPPED


def test_engine_error_exits_1(capsys, monkeypatch):
    import geotruth.relate as R

    def boom(a, b, **kw):
        raise RuntimeError("internal")

    monkeypatch.setattr(R, "build_arrangement", boom)
    status, out, _ = run(capsys, SQ, LINE)
    assert status == cmd.EXIT_DISAGREE and "engine_error" in out


def test_load_operands_api():
    cid, a, b = cmd.load_operands(SQ, LINE)
    assert cid == "cli" and a.geom_type == "Polygon" and b.geom_type == "LineString"
