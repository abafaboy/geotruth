"""harness/tally.py: per-library totals of a hunt round's compare output."""

import json

import pytest


def write_round(root, lib, cases_dir, families):
    """Fake the compare-<lib> output hunt.sh leaves: {family: (n_cases, [records])}."""
    d = root / f"results-{cases_dir}" / f"compare-{lib}"
    d.mkdir(parents=True)
    for fam, (n_cases, recs) in families.items():
        (d / f"{fam}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in recs))
        (d / f"{fam}.log").write_text(f"# {len(recs)} disagreements over {n_cases} cases\n")


def rec(cid, kind, key):
    return {"id": cid, "family": cid.split("-")[0], "lib": "x", "kind": kind, "key": key,
            "exact": None, "got": None}


@pytest.fixture
def round_dir(tmp_path):
    write_round(tmp_path, "clipper2", "cases", {
        "seed": (1000, [rec(f"seed-{i}", "error", "unsupported") for i in range(15)]),
        "int": (204, [rec("int-1", "area", "area_inter"), rec("int-1", "area", "area_union")]),
    })
    write_round(tmp_path, "shapely", "cases", {"seed": (1000, [])})
    write_round(tmp_path, "turf", "cases-small", {
        "seed": (150, [rec("seed-1", "predicate", "touches")])})
    return tmp_path


@pytest.mark.unit
def test_tally_counts(tally_mod, round_dir):
    libs = tally_mod.tally(round_dir)
    assert list(libs) == ["clipper2", "shapely", "turf"]
    c = libs["clipper2"].as_dict()
    assert c["cases"] == 1204
    assert c["records"] == 17
    assert c["cases_hit"] == 16
    assert c["kinds"] == {"predicate": 0, "area": 2, "validity": 0, "error": 15}
    assert c["error_keys"] == {"unsupported": 15}
    assert libs["shapely"].as_dict()["records"] == 0
    assert libs["turf"].as_dict()["cases"] == 150


@pytest.mark.unit
def test_table_and_json_output(tally_mod, round_dir, capsys):
    assert tally_mod.main([str(round_dir)]) == 0
    table = capsys.readouterr().out.splitlines()
    assert table[0].split()[:4] == ["library", "cases", "records", "cases_hit"]
    assert table[1].split()[:4] == ["clipper2", "1204", "17", "16"]
    assert table[1].endswith("unsupported 15")
    assert tally_mod.main([str(round_dir), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["turf"]["kinds"]["predicate"] == 1


@pytest.mark.unit
def test_empty_directory_is_an_error(tally_mod, tmp_path, capsys):
    assert tally_mod.main([str(tmp_path)]) == 1
    assert "no compare-<lib> output" in capsys.readouterr().err
