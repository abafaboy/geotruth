"""Tiers: stratified core selection, curated provenance, MANIFEST, checksums, CLI."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from collections import Counter

import pytest
from corpus_testlib import REPO, read_jsonl

from geotruth import schemas
from geotruth.cli import main as cli_main
from geotruth.io import geometry_from_json
from geotruth.validity import is_valid

pytestmark = pytest.mark.unit

CORPUS = REPO / "corpus"


def _rec(i, variant, deg="lattice"):
    return {
        "id": f"f-1-{i:06d}-{variant}",
        "tags": {
            "variant": variant,
            "degeneracy": deg,
            "range": "normal",
            "types": ["Polygon", "Polygon"],
        },
    }


def test_select_core_is_stratified_and_deterministic(tiers):
    recs = [_rec(i, "big") for i in range(900)] + [_rec(900 + i, f"v{i % 7}") for i in range(100)]
    core = tiers.select_core(recs, 200)
    assert len(core) == 200
    assert core == tiers.select_core(list(recs), 200)
    got = Counter(r["tags"]["variant"] for r in core)
    assert set(got) == {"big"} | {f"v{i}" for i in range(7)}  # every stratum represented
    assert 170 <= got["big"] <= 185  # the rest proportional
    ids = [r["id"] for r in core]
    assert ids == sorted(ids)  # original order kept


def test_select_core_small_and_many_strata(tiers):
    recs = [_rec(i, f"v{i}") for i in range(50)]
    assert tiers.select_core(recs, 200) == recs
    many = [_rec(i, f"v{i}") for i in range(500)]
    core = tiers.select_core(many, 200)
    assert len(core) == 200 and len({r["tags"]["variant"] for r in core}) == 200


def test_manifest_matches_the_tracked_tiers(tiers):
    m = tiers.load_manifest()
    assert m is not None and m["manifest_version"] == 1
    assert m["tiers"]["core"]["in_git"] and not m["tiers"]["full"]["in_git"]
    per = m["parameters"]["core_per_family"]
    families = [n for n, _, _ in tiers.ALL_FAMILIES]
    core_files = m["tiers"]["core"]["files"]
    assert set(core_files) == {f"cases/core/{f}.jsonl" for f in families}
    for path, e in {**core_files, **m["tiers"]["curated"]["files"]}.items():
        data = (CORPUS / path).read_bytes()
        assert hashlib.sha256(data).hexdigest() == e["sha256"], path
        assert data.count(b"\n") == e["cases"], path
    assert all(e["cases"] == per for e in core_files.values())
    assert m["tiers"]["full"]["cases"] == len(families) * m["parameters"]["n_per_family"]


def test_sha256sums_list_the_new_tiers():
    names = {ln.split(maxsplit=1)[1] for ln in (CORPUS / "SHA256SUMS").read_text().splitlines()}
    assert "cases/curated.jsonl" in names
    core = (CORPUS / "cases" / "core").glob("*.jsonl")
    assert {p.relative_to(CORPUS).as_posix() for p in core} <= names


@pytest.mark.parametrize("family", ["hole-contact", "line-mod2"])
def test_core_regenerates_byte_for_byte(tiers, family):
    p = tiers.load_manifest()["parameters"]
    recs, _ = tiers.generate_family(family, p["n_per_family"], p["seed"])
    text = "".join(tiers.dumps(r) + "\n" for r in tiers.select_core(recs, p["core_per_family"]))
    assert text == (CORPUS / "cases" / "core" / f"{family}.jsonl").read_text()


def test_core_records_are_schema_valid_and_valid(tiers):
    for path in sorted((CORPUS / "cases" / "core").glob("*.jsonl")):
        recs = read_jsonl(path)
        for r in recs[::25]:
            schemas.validate("case", r)
            ok = is_valid(geometry_from_json(r["a"])) and is_valid(geometry_from_json(r["b"]))
            assert ok != r["family"].startswith("invalid-"), r["id"]


def test_curated_covers_every_finding_and_lead(tiers, curated_records):
    tl = tiers._toml()
    with open(REPO / "findings" / "registry.toml", "rb") as fh:
        findings = tl.load(fh)["finding"]
    with open(CORPUS / "curated" / "leads.toml", "rb") as fh:
        leads = tl.load(fh)["lead"]
    by_owner = Counter(
        r["provenance"].get("finding") or r["provenance"].get("lead") for r in curated_records
    )
    for f in findings:
        assert by_owner[f["id"]] == len(read_jsonl(REPO / f["cases"])), f["id"]
    for lead in leads:
        assert by_owner[lead["id"]] == len(lead["case"]), lead["id"]
    assert sum(by_owner.values()) == len(curated_records)
    assert "boost-develop-rotated-neighbours-230:rotated-neighbours-1-000230" in {
        r["id"] for r in curated_records
    }


def test_curated_provenance(curated_records):
    statuses = {"unreviewed", "confirmed", "by-design", "reported", "fixed"}
    for r in curated_records:
        schemas.validate("case", r)
        p = r["provenance"]
        assert p["source"] in ("curated", "minimised")
        assert p["status"] in statuses
        assert "upstream_issue" in p and "upstream_status" in p
        assert ("issue_url" in p) == bool(p["upstream_issue"])
        assert p["library"] and p["signature"]
        if p["source"] == "minimised":
            assert p["parent"] and p["minimised_with"]
        assert "curated" in r["tags"]["flags"]
        ga, gb = geometry_from_json(r["a"]), geometry_from_json(r["b"])
        assert is_valid(ga) and is_valid(gb), r["id"]


def test_curated_rebuild_is_identical(tiers, curated_records):
    assert tiers.build_curated() == curated_records


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_gitignore_keeps_core_and_curated_only():
    def ignored(path):
        r = subprocess.run(["git", "check-ignore", "-q", path], cwd=REPO, check=False)
        return r.returncode == 0

    assert ignored("corpus/cases/full/gc.jsonl")
    assert ignored("corpus/cases/some-generated-family.jsonl")
    assert not ignored("corpus/cases/core/gc.jsonl")
    assert not ignored("corpus/cases/curated.jsonl")
    assert not ignored("corpus/cases/seed.jsonl")
    assert not ignored("corpus/MANIFEST.json")


def test_cli_list_stats_verify(capsys):
    assert cli_main(["corpus", "verify"]) == 0
    assert "0 problems" in capsys.readouterr().out
    assert cli_main(["corpus", "list", "--tier", "curated"]) == 0
    assert "cases/curated.jsonl" in capsys.readouterr().out
    assert cli_main(["corpus", "stats", "--tier", "core", "--by", "degeneracy", "--json"]) == 0
    table = json.loads(capsys.readouterr().out)
    assert table["gc"]["cases"] == 200
    assert sum(v for k, v in table["gc"].items() if k.startswith("degeneracy=")) == 200
    assert cli_main(["corpus", "list", "--families"]) == 0
    assert "invalid-zero-length-line" in capsys.readouterr().out


def test_cli_build_into_a_scratch_corpus(tmp_path, capsys):
    """build writes the tiers, MANIFEST.json and SHA256SUMS into --corpus."""
    corpus = tmp_path / "corpus"
    (corpus / "cases").mkdir(parents=True)
    rc = cli_main(
        [
            "corpus",
            "build",
            "--tier",
            "core",
            "--n",
            "30",
            "--per-family",
            "10",
            "--families",
            "gc,empty",
            "--jobs",
            "1",
            "--corpus",
            str(corpus),
            "--quiet",
        ]
    )
    assert rc == 0
    m = json.loads((corpus / "MANIFEST.json").read_text())
    assert set(m["tiers"]["core"]["files"]) == {"cases/core/gc.jsonl", "cases/core/empty.jsonl"}
    assert m["parameters"] == {"seed": 1, "n_per_family": 30, "core_per_family": 10}
    assert all(e["cases"] == 10 for e in m["tiers"]["core"]["files"].values())
    assert "cases/core/gc.jsonl" in (corpus / "SHA256SUMS").read_text()
    assert cli_main(["corpus", "verify", "--corpus", str(corpus)]) == 0
