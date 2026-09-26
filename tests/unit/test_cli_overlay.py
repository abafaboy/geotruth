"""Tests of ``geotruth overlay`` (src/geotruth/commands/overlay.py)."""

from __future__ import annotations

import io
import json

import pytest

from geotruth import cli
from geotruth.io import geometry_from_json, read_wkt

SQ = "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"
LINE = "LINESTRING (-1 1, 3 1)"


def run(capsys, *argv: str) -> tuple[int, str, str]:
    status = cli.main(["overlay", *argv])
    out = capsys.readouterr()
    return status, out.out, out.err


def test_registered():
    commands = cli.discover()
    assert "overlay" in commands and commands["overlay"].error is None
    assert commands["overlay"].help.startswith("print the exact overlay")


def test_text_output(capsys):
    status, out, err = run(capsys, SQ, LINE, "union")
    assert status == 0 and err == ""
    assert "A: Polygon (5 coordinates; dimension 2)" in out
    assert "union (non-strict): GeometryCollection, 10 vertices" in out
    assert (
        "  wkt:   GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 1, 2 2, 0 2, 0 1, 0 0)), "
        "LINESTRING (-1 1, 0 1), LINESTRING (2 1, 3 1))" in out
    )
    exact = json.loads(out.split("  exact: ")[1].splitlines()[0])
    assert geometry_from_json(exact, exact=True).geom_type == "GeometryCollection"
    assert "  area:  4\n" in out


def test_areal_and_rational_area(capsys):
    status, out, _ = run(capsys, SQ, "POLYGON ((1 0, 3 1, 1 1, 1 0))", "intersection", "--areal")
    assert status == 0
    assert "intersection (areal): Polygon" in out
    assert "area:  3/4 (~0.75)" in out or "area:  3/4" in out


def test_json_single_result(capsys):
    status, out, err = run(capsys, "LINESTRING (0 0, 3 1)", "LINESTRING (0 1, 2 0)",
                           "intersection", "--json")  # fmt: skip
    assert status == 0 and err == ""
    rec = json.loads(out)
    assert rec["status"] == "ok" and rec["op"] == "intersection"
    assert rec["variant"] == "non_strict" and rec["id"] == "cli"
    assert rec["result"]["exact"] == {"type": "Point", "coordinates": ["6/5", "2/5"]}
    assert rec["result"]["wkt"] == "POINT (1.2 0.4)" and rec["result"]["area"] == "0"
    assert rec["validity"]["a"]["valid"] and rec["dimensions"]["b"]["dimension"] == 1


def test_json_all_is_an_expected_overlay_block(capsys):
    pytest.importorskip("jsonschema")
    from geotruth import schemas
    from geotruth.relate import relate

    status, out, _ = run(capsys, SQ, LINE, "all", "--json", "--certify")
    assert status == 0
    rec = json.loads(out)
    assert set(rec["overlay"]) == {"intersection", "union", "difference", "symdifference"}
    assert all(set(v) == {"non_strict", "areal"} for v in rec["overlay"].values())
    assert all(c["ok"] for c in rec["certificates"].values()) and len(rec["certificates"]) == 8
    certs = rec.pop("certificates")
    assert certs["union/non_strict"]["witnesses"] > 0
    rec.update(relate(read_wkt(SQ), read_wkt(LINE)).to_json())
    schemas.validate("expected", rec)


def test_certify_text(capsys):
    status, out, _ = run(capsys, SQ, LINE, "difference", "--certify")
    assert status == 0 and "  certificate: ok (" in out


def test_all_ops_text(capsys):
    status, out, _ = run(capsys, SQ, "POINT (1 1)", "all")
    assert status == 0
    for op in ("intersection", "union", "difference", "symdifference"):
        assert f"{op} (non-strict):" in out
    assert "intersection (non-strict): Point, 1 vertex" in out


@pytest.mark.parametrize("alias", ["symmetric_difference", "symdiff", "SymDifference", "xor"])
def test_op_aliases(capsys, alias):
    status, out, _ = run(capsys, "POINT (0 0)", "POINT (1 1)", alias)
    assert status == 0 and "symdifference (non-strict): MultiPoint" in out


def test_case_file_and_id(capsys, tmp_path):
    f = tmp_path / "cases.jsonl"
    cases = [
        {"id": "one", "a": {"type": "Point", "coordinates": [0, 0]},
         "b": {"type": "Point", "coordinates": [0, 0]}},
        {"id": "two", "a": {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 0]]]},
         "b": {"type": "Point", "coordinates": [5, 5]}},
    ]  # fmt: skip
    f.write_text("\n".join(json.dumps(c) for c in cases) + "\n")
    status, out, _ = run(capsys, f"@{f}", "union", "--id", "two", "--json")
    rec = json.loads(out)
    assert status == 0 and rec["id"] == "two"
    want = "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 0)), POINT (5 5))"
    assert rec["result"]["wkt"] == want
    single = tmp_path / "case.json"
    single.write_text(json.dumps({"a": cases[0]["a"], "b": cases[0]["b"]}))
    status, out, _ = run(capsys, f"@{single}", "intersection")
    assert status == 0 and "intersection (non-strict): Point" in out


def test_stdin(capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(SQ))
    status, out, _ = run(capsys, "-", "POINT (1 1)", "difference")
    assert status == 0 and "difference (non-strict): Polygon" in out


@pytest.mark.parametrize(
    "argv",
    [
        (SQ, LINE, "clip"),
        (SQ, LINE),
        (SQ,),
        ("POLYGON ((0 0, 1 0", LINE, "union"),
        ("@/nonexistent/file.wkt", LINE, "union"),
    ],
)
def test_bad_input(capsys, argv):
    status, _, err = run(capsys, *argv)
    assert status == 2 and err.startswith("geotruth overlay:")


def test_invalid_input_note_and_refusal(capsys):
    # a bow tie: invalid, and outside the engine's contract (zero area)
    status, _, err = run(capsys, "POLYGON ((0 0, 1 1, 1 0, 0 1, 0 0))", "POINT (1 1)", "union")
    assert status == 2
    assert "note: A is invalid" in err and "outside the engine's contract" in err
    # an invalid input the engine still answers (a self-touching ring): a note only
    status, _, err = run(capsys, "POLYGON ((0 0, 4 0, 4 4, 2 0, 0 4, 0 0))", "POINT (9 9)",
                         "union")  # fmt: skip
    assert status == 0 and "note: A is invalid" in err


def test_budget(capsys):
    status, out, _ = run(capsys, SQ, LINE, "union", "--max-size", "1")
    assert status == 3 and "engine_skipped" in out
    status, out, _ = run(capsys, SQ, LINE, "union", "--max-size", "1", "--json")
    assert status == 3 and json.loads(out)["status"] == "engine_skipped"
    status, _, _ = run(capsys, SQ, LINE, "union", "--no-budget", "--max-seconds", "100")
    assert status == 0


def test_engine_error_and_failed_certificate(capsys, monkeypatch):
    import geotruth.overlay as O

    monkeypatch.setattr(O, "select", lambda op, a, b: a or b)
    status, out, _ = run(capsys, SQ, "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))", "intersection",
                         "--certify")  # fmt: skip
    assert status == 1 and "engine_error: certificate failed" in out
    status, out, _ = run(capsys, SQ, "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))", "all", "--json",
                         "--certify")  # fmt: skip
    rec = json.loads(out)
    assert status == 1 and rec["status"] == "engine_error" and "certificate" in rec["reason"]
