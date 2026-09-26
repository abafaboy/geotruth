"""``geotruth expect`` (:mod:`geotruth.expect`): records, abstentions, the checks between
the two relate routes and overlay, determinism, the cache and the version lock."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from geotruth import cli
from geotruth import expect as X
from geotruth.arrangement import Budget
from geotruth.io import Case, read_wkt

pytestmark = pytest.mark.unit

SQUARES = Case(
    id="squares",
    a=read_wkt("POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))"),
    b=read_wkt("POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1))"),
)


def _schema_valid(rec):
    jsonschema = pytest.importorskip("jsonschema")
    from geotruth import schemas

    try:
        schemas.validate("expected", rec)
    except jsonschema.ValidationError as exc:  # pragma: no cover - a failure message
        pytest.fail(f"not schema-valid: {exc.message}")


def test_record_of_two_overlapping_squares():
    rec = X.expected_record(SQUARES)
    _schema_valid(rec)
    assert rec["status"] == "ok"
    assert rec["engine"] == {"version": X.ENGINE_VERSION, "expected_version": "2"}
    assert rec["relate"] == "212101212"
    assert rec["predicates"]["overlaps"] and not rec["predicates"]["touches"]
    assert rec["validity"]["a"] == {"valid": True, "reasons": [], "first_reason": None}
    areas = {op: rec["overlay"][op]["areal"]["area"] for op in rec["overlay"]}
    assert areas == {"intersection": "1", "union": "7", "difference": "3", "symdifference": "6"}
    inter = rec["overlay"]["intersection"]["non_strict"]
    assert inter["wkt"] == "POLYGON ((1 1, 2 1, 2 2, 1 2, 1 1))"
    assert inter["exact"]["coordinates"][0][0] == ["1", "1"]
    assert rec["measures"]["area_a"] == "4" and rec["measures"]["distance2"] == "0"
    assert rec["measures"]["length_a"] == {"lo": "8", "hi": "8", "rounded": 8.0}
    assert "conventions" not in rec


def test_invalid_operand_gets_validity_and_measures_only():
    case = Case("zero-length", read_wkt("LINESTRING (1 1, 1 1)"), SQUARES.b)
    rec = X.expected_record(case)
    _schema_valid(rec)
    assert rec["status"] == "ok"
    assert rec["validity"]["a"]["valid"] is False
    assert rec["validity"]["a"]["first_reason"] == "too_few_points"
    assert rec["dimensions"]["a"] == {"dimension": 1, "real_dimension": 0}
    assert not {"relate", "predicates", "overlay"} & set(rec)
    assert "distance2" not in rec["measures"] and rec["measures"]["area_b"] == "4"


def test_empty_operand_records_the_conventions():
    case = Case("empty", read_wkt("POINT EMPTY"), read_wkt("POINT EMPTY"))
    rec = X.expected_record(case)
    _schema_valid(rec)
    assert rec["relate"] == "FFFFFFFF2"
    assert "predicates.equals" in rec["conventions"]
    assert rec["overlay"]["union"]["non_strict"]["wkt"] == "POINT EMPTY"


def test_the_two_relate_routes_must_agree(monkeypatch):
    import geotruth.relate_witness as W

    monkeypatch.setattr(
        W, "relate_witness", lambda a, b, check=True: SimpleNamespace(matrix="FF2FF1212")
    )
    rec = X.expected_record(SQUARES)
    _schema_valid(rec)
    assert rec["status"] == "engine_error"
    assert rec["reason"] == (
        "relate: the two routes disagree: arrangement 212101212, witness FF2FF1212"
    )
    assert rec["validity"]["a"]["valid"] and rec["measures"]["area_a"] == "4"
    assert not {"relate", "predicates", "overlay"} & set(rec)


def test_an_engine_exception_is_an_engine_error(monkeypatch):
    import geotruth.relate as R

    def boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(R, "relate", boom)
    rec = X.expected_record(SQUARES)
    assert rec["status"] == "engine_error"
    assert rec["reason"] == "relate: RuntimeError: boom"


def _patch_overlay(monkeypatch, change):
    import geotruth.overlay as O

    real = O.overlay_all

    def patched(*args, **kwargs):
        res = real(*args, **kwargs)
        change(res)
        return res

    monkeypatch.setattr(O, "overlay_all", patched)


def test_a_failed_certificate_is_an_engine_error(monkeypatch):
    def fail(res):
        r = res["union"]["areal"]
        r.status, r.reason = "engine_error", "certificate failed: 1 mismatch"

    _patch_overlay(monkeypatch, fail)
    rec = X.expected_record(SQUARES)
    assert rec["status"] == "engine_error"
    assert rec["reason"] == "overlay union (areal): certificate failed: 1 mismatch"


def test_the_cross_checks_catch_a_wrong_overlay(monkeypatch):
    def swap(res):
        res["intersection"], res["union"] = res["union"], res["intersection"]

    _patch_overlay(monkeypatch, swap)
    rec = X.expected_record(SQUARES)
    assert rec["status"] == "engine_error"
    assert rec["reason"].startswith("relate/overlay/area check: ")
    assert "|A| != |A n B| + |A - B|" in rec["reason"]


def test_the_cross_checks_catch_a_wrong_matrix():
    from geotruth.measures import area
    from geotruth.overlay import overlay_all

    a, b = SQUARES.a, SQUARES.b
    ovl = overlay_all(a, b)
    assert X.consistency_problems("212101212", ovl, a, b, area(a), area(b)) == []
    touches = X.consistency_problems("FF2F11212", ovl, a, b, area(a), area(b))
    assert "intersection: the non-strict result has dimension 2, relate FF2F11212 implies 1" in (
        touches
    )
    contains = X.consistency_problems("2FF11F212", ovl, a, b, area(a), area(b))
    assert any(p.startswith("difference:") for p in contains)


def test_over_budget_is_engine_skipped():
    rec = X.expected_record(SQUARES, budget=Budget(max_size=4, max_seconds=None))
    _schema_valid(rec)
    assert rec["status"] == "engine_skipped"
    assert rec["reason"].startswith("relate: arrangement over budget: size")
    assert rec["validity"]["b"]["valid"]


def test_witness_route_budget(monkeypatch):
    monkeypatch.setattr(X, "WITNESS_MAX_COORDS", 9)
    rec = X.expected_record(SQUARES)
    assert rec["status"] == "engine_skipped"
    assert rec["reason"] == "relate (witness route) over budget: 10 input coordinates > 9"


def test_a_record_that_fails_the_schema_becomes_an_engine_error(monkeypatch):
    pytest.importorskip("jsonschema")
    real = X.expected_record

    def bad(case, **kwargs):
        rec = real(case, **kwargs)
        rec["relate"] = "212101212X"
        return rec

    monkeypatch.setattr(X, "expected_record", bad)
    line = X.expected_line(
        json.dumps(
            {
                "id": "squares",
                "a": {"type": "Point", "coordinates": [0, 0]},
                "b": {"type": "Point", "coordinates": [1, 1]},
            }
        )
    )
    rec = json.loads(line)
    _schema_valid(rec)
    assert rec["status"] == "engine_error"
    assert rec["reason"].startswith("the record failed schema validation: relate: ")


# ----------------------------------------------------------------------- tiers, cache


@pytest.fixture
def small_corpus(tmp_path):
    """A corpus with a 6-case curated tier: polygons, a GC, empties, an invalid line."""
    real = X.corpus_dir()
    curated = X.read_case_lines([real / "cases" / "curated.jsonl"])
    invalid = X.read_case_lines([real / "cases" / "core" / "invalid-zero-length-line.jsonl"])
    lines = [curated[i] for i in (0, 3, 5, 11, 16)] + invalid[:1]
    corpus = tmp_path / "corpus"
    (corpus / "cases").mkdir(parents=True)
    (corpus / "cases" / "curated.jsonl").write_text("".join(x + "\n" for x in lines))
    return corpus


def test_rerun_is_byte_identical_and_the_cache_is_transparent(small_corpus, tmp_path):
    out = small_corpus / "expected"
    cache = X.AnswerCache(tmp_path / "cache")
    first = X.write_tier("curated", corpus=small_corpus, out_dir=out, cache=cache)
    cache.close()
    assert first.written and first.stats.computed == 6
    assert first.stats.status == {"ok": 6}
    text = (out / "curated.jsonl").read_bytes()
    manifest = (out / "MANIFEST.json").read_bytes()
    entry = json.loads(manifest)["files"]["curated.jsonl"]
    assert entry["records"] == 6 and entry["status"]["ok"] == 6
    assert entry["computed_with"]["engine_source_sha256"] == X.engine_fingerprint()

    cache = X.AnswerCache(tmp_path / "cache")
    assert len(cache) == 6
    again = X.write_tier("curated", corpus=small_corpus, out_dir=out, cache=cache, jobs=2)
    cache.close()
    assert again.stats.cached == 6 and not again.written
    fresh = X.write_tier("curated", corpus=small_corpus, out_dir=out, cache=None, jobs=2)
    assert fresh.stats.computed == 6 and not fresh.written
    assert (out / "curated.jsonl").read_bytes() == text
    assert (out / "MANIFEST.json").read_bytes() == manifest
    check = X.write_tier("curated", corpus=small_corpus, out_dir=out, check_only=True)
    assert check.same_as_file


def test_changed_answers_need_an_engine_version_bump(small_corpus, monkeypatch):
    out = small_corpus / "expected"
    X.write_tier("curated", corpus=small_corpus, out_dir=out)
    before = (out / "curated.jsonl").read_bytes()
    real = X.expected_record

    def changed(case, **kwargs):
        rec = real(case, **kwargs)
        if "relate" in rec:
            rec["relate"] = "FF2FF1212"
        return rec

    monkeypatch.setattr(X, "expected_record", changed)
    with pytest.raises(X.ExpectedChangedError, match=r"bump geotruth\.ENGINE_VERSION"):
        X.write_tier("curated", corpus=small_corpus, out_dir=out)
    assert (out / "curated.jsonl").read_bytes() == before
    check = X.write_tier("curated", corpus=small_corpus, out_dir=out, check_only=True)
    assert not check.same_as_file

    monkeypatch.setattr(X, "ENGINE_VERSION", "0.0.0-test")
    res = X.write_tier("curated", corpus=small_corpus, out_dir=out)
    assert res.written
    entry = X.load_manifest(out)["files"]["curated.jsonl"]
    assert entry["engine_version"] == "0.0.0-test"
    assert json.loads((out / "curated.jsonl").read_text().splitlines()[0])["engine"] == {
        "version": "0.0.0-test",
        "expected_version": "2",
    }


def test_lock_violation():
    base = {"sha256": "1", "engine_version": "0.1.0", "cases": {"cases/x.jsonl": "c"}}
    assert not X.lock_violation(None, base)
    assert not X.lock_violation(base, dict(base))
    assert X.lock_violation(base, {**base, "sha256": "2"})
    assert not X.lock_violation(base, {**base, "sha256": "2", "engine_version": "0.2.0"})
    assert not X.lock_violation(base, {**base, "sha256": "2", "cases": {"cases/x.jsonl": "d"}})


def test_a_hand_edited_file_is_restored(small_corpus):
    out = small_corpus / "expected"
    X.write_tier("curated", corpus=small_corpus, out_dir=out)
    path = out / "curated.jsonl"
    good, manifest = path.read_bytes(), (out / "MANIFEST.json").read_bytes()
    path.write_bytes(good.replace(b'"relate":"', b'"relate":"X', 1))
    res = X.write_tier("curated", corpus=small_corpus, out_dir=out)
    assert res.written
    assert path.read_bytes() == good and (out / "MANIFEST.json").read_bytes() == manifest


def test_new_cases_need_no_bump(small_corpus):
    out = small_corpus / "expected"
    X.write_tier("curated", corpus=small_corpus, out_dir=out)
    path = small_corpus / "cases" / "curated.jsonl"
    path.write_text("".join(x + "\n" for x in X.read_case_lines([path])[:4]))
    res = X.write_tier("curated", corpus=small_corpus, out_dir=out)
    assert res.written and res.stats.cases == 4
    assert X.load_manifest(out)["files"]["curated.jsonl"]["records"] == 4


def test_cache_key_names_engine_version_and_source(tmp_path):
    cache = X.AnswerCache(tmp_path)
    key = f"engine-{X.ENGINE_VERSION}-{X.engine_fingerprint()[:16]}"
    assert cache.path == tmp_path / "expected" / key / "answers.jsonl"


def test_cli(small_corpus, tmp_path, capsys):
    cases = small_corpus / "cases" / "curated.jsonl"
    out = tmp_path / "answers.jsonl"
    assert cli.main(["expect", "--cases", str(cases), "-o", str(out), "--no-cache"]) == 0
    lines = out.read_text().splitlines()
    assert len(lines) == 6 and all(json.loads(x)["status"] == "ok" for x in lines)
    assert "6 cases: ok 6, engine_skipped 0, engine_error 0" in capsys.readouterr().err
    assert cli.main(["expect"]) == 2
    assert cli.main(["expect", "--tier", "core", "--cases", str(cases)]) == 2
    assert cli.main(["expect", "--cases", str(cases), "--check"]) == 2
    assert cli.main(["expect", "--tier", "core", "-o", str(out)]) == 2
    args = ["expect", "--tier", "curated", "--corpus", str(small_corpus), "--no-cache"]
    assert cli.main([*args, "--quiet"]) == 0
    assert cli.main([*args, "--check", "--quiet"]) == 0
