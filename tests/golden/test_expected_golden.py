"""Golden tests of the published expected answers (``corpus/expected/``, DESIGN §7).

The answer files may only change together with ``geotruth.ENGINE_VERSION`` (or with the
case files they answer):

- each file is the one its ``MANIFEST.json`` entry records, for the current engine version
  and the current case files (a hand edit, a stale file or a forgotten regeneration fails);
- a sample of every tier, recomputed from scratch now, is byte-identical to the file (an
  engine change that alters answers fails until the version is bumped and the files are
  regenerated; the ``slow`` tests recompute every case);
- compared with the manifest at git ``HEAD``, a file that changed while the engine version
  and the case files did not fails (``geotruth expect`` refuses to write such a file too).

The answers are also the same with the ``fractions`` rational backend (``crosscheck``).
"""

from __future__ import annotations

import json
import subprocess

import pytest

from geotruth import ENGINE_VERSION
from geotruth import expect as X
from geotruth.io import case_from_json, case_sha256
from geotruth.numbers import json_loads

CORPUS = X.corpus_dir()
OUT = CORPUS / "expected"
TRACKED = ("core", "curated")
#: About this many cases of each tier are recomputed by the unit tests.
SAMPLE = 40
BUMP = (
    "bump geotruth.ENGINE_VERSION (src/geotruth/__init__.py) and regenerate with "
    "`geotruth expect --tier core --tier curated --jobs 2`"
)


def _lines(path):
    with open(path, encoding="ascii") as fh:
        return [ln.rstrip("\n") for ln in fh]


@pytest.fixture(scope="module")
def manifest():
    m = X.load_manifest(OUT)
    assert m is not None, f"{OUT / X.MANIFEST_NAME} is missing; run `geotruth expect`"
    return m


def _sample(tier):
    """Every k-th case line of a tier and its answer line (about SAMPLE of them)."""
    cases = X.read_case_lines(X.tier_case_files(tier))
    answers = _lines(OUT / f"{tier}.jsonl")
    stale = f"{tier}.jsonl does not answer the current case files: run `geotruth expect`"
    assert len(answers) == len(cases), stale
    step = max(1, len(cases) // SAMPLE)
    cases, answers = cases[::step], answers[::step]
    for c, a in zip(cases, answers, strict=True):
        assert json_loads(c)["id"] == json.loads(a)["id"], stale
    return cases, answers


@pytest.mark.unit
def test_manifest_lists_the_tracked_files(manifest):
    assert manifest["expected_version"] == X.EXPECTED_VERSION
    assert manifest["format"] == X.SCHEMA_ID
    for tier in TRACKED:
        entry = manifest["files"][f"{tier}.jsonl"]
        assert entry["tier"] == tier and entry["in_git"] is True


@pytest.mark.unit
@pytest.mark.parametrize("tier", TRACKED)
def test_file_is_the_one_the_manifest_records(tier, manifest):
    entry = manifest["files"][f"{tier}.jsonl"]
    path = OUT / f"{tier}.jsonl"
    assert X.sha256_file(path) == entry["sha256"], (
        f"{path.name} differs from the file MANIFEST.json records: edited by hand? "
        "Regenerate it with `geotruth expect`"
    )
    assert entry["engine_version"] == ENGINE_VERSION, f"{path.name} is stale: {BUMP}"
    cases = {p.relative_to(CORPUS).as_posix(): X.sha256_file(p) for p in X.tier_case_files(tier)}
    assert entry["cases"] == cases, (
        f"the case files of tier {tier} changed: run `geotruth expect --tier {tier}`"
    )
    lines = _lines(path)
    assert entry["records"] == len(lines)
    statuses = [json.loads(ln)["status"] for ln in lines]
    assert entry["status"] == {s: statuses.count(s) for s in X.STATUSES}


@pytest.mark.unit
@pytest.mark.parametrize("tier", TRACKED)
def test_one_record_per_case_in_order(tier):
    cases = X.read_case_lines(X.tier_case_files(tier))
    lines = _lines(OUT / f"{tier}.jsonl")
    assert len(lines) == len(cases)
    engine = {"version": ENGINE_VERSION, "expected_version": X.EXPECTED_VERSION}
    for case_line, line in zip(cases, lines, strict=True):
        case = case_from_json(json_loads(case_line))
        rec = json.loads(line)
        assert rec["id"] == case.id
        assert rec["case_sha256"] == case_sha256(case), case.id
        assert rec["engine"] == engine, case.id
        assert X.dumps_record(rec) == line, f"{case.id}: not in canonical form"


@pytest.mark.unit
@pytest.mark.parametrize("tier", TRACKED)
def test_sample_recomputes_byte_for_byte(tier):
    cases, answers = _sample(tier)
    lines, stats = X.compute_lines(cases, cache=None)
    assert stats.computed == len(cases)
    for got, want in zip(lines, answers, strict=True):
        assert got == want, f"{json.loads(want)['id']}: the engine's answer changed; {BUMP}"


def _git_show(rel):
    try:
        r = subprocess.run(
            ["git", "-C", str(CORPUS.parent), "show", f"HEAD:{rel}"],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


@pytest.mark.unit
def test_no_change_without_engine_version_bump_since_head(manifest):
    text = _git_show("corpus/expected/MANIFEST.json")
    if text is None:
        pytest.skip("corpus/expected/MANIFEST.json is not committed at HEAD (or no git)")
    head = json.loads(text)
    for name, old in head.get("files", {}).items():
        new = manifest["files"].get(name)
        if new is None or not old.get("in_git"):
            continue
        assert not X.lock_violation(old, new), (
            f"{name} changed since HEAD for the same cases and engine "
            f"{new['engine_version']}; {BUMP}"
        )


@pytest.mark.unit
@pytest.mark.parametrize("tier", TRACKED)
def test_sample_is_schema_valid(tier):
    pytest.importorskip("jsonschema")
    from geotruth import schemas

    _, answers = _sample(tier)
    for line in answers:
        schemas.validate("expected", json.loads(line))


@pytest.mark.slow
@pytest.mark.parametrize("tier", TRACKED)
def test_tier_recomputes_byte_for_byte(tier):
    """Every answer recomputed from scratch in two processes equals the file."""
    cases = X.read_case_lines(X.tier_case_files(tier))
    lines, _ = X.compute_lines(cases, jobs=2, cache=None)
    answers = _lines(OUT / f"{tier}.jsonl")
    bad = [json.loads(w)["id"] for g, w in zip(lines, answers, strict=True) if g != w]
    assert not bad, f"{len(bad)} answers changed (first: {bad[:5]}); {BUMP}"


@pytest.mark.slow
@pytest.mark.parametrize("tier", TRACKED)
def test_every_record_is_schema_valid(tier):
    pytest.importorskip("jsonschema")
    from geotruth import schemas

    check = schemas.validator("expected")
    for line in _lines(OUT / f"{tier}.jsonl"):
        rec = json.loads(line)
        errors = list(check.iter_errors(rec))
        assert not errors, (rec["id"], errors[0].message)


@pytest.mark.slow
def test_untracked_files_match_the_manifest(manifest):
    """The full tier's answers are a release asset: checked when present."""
    for name, entry in manifest["files"].items():
        path = OUT / name
        if entry["in_git"] or not path.is_file():
            continue
        assert X.sha256_file(path) == entry["sha256"], name


@pytest.mark.crosscheck
@pytest.mark.parametrize("tier", TRACKED)
def test_fractions_backend_gives_the_same_bytes(tier):
    """The answers do not depend on the rational backend (gmpy2 or fractions)."""
    cases, answers = _sample(tier)
    lines, _ = X.compute_lines(cases, cache=None, backend="fractions")
    assert lines == answers
