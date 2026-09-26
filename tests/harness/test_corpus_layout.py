"""corpus/: tracked cases are immutable, expected answers line up with them, CC0 licence."""

import hashlib
import json
import subprocess
import sys

import pytest


def checksums(repo):
    """{relative path: sha256} from corpus/SHA256SUMS."""
    out = {}
    for line in (repo / "corpus" / "SHA256SUMS").read_text().splitlines():
        digest, name = line.split(maxsplit=1)
        out[name] = digest
    return out


@pytest.mark.unit
def test_sha256sums_cover_and_match_every_tracked_file(repo):
    sums = checksums(repo)
    corpus = repo / "corpus"
    # corpus/cases/ may also hold generated, git-ignored files; the expected answers may not
    tracked = {"cases/seed.jsonl"} | {str(p.relative_to(corpus))
                                      for p in corpus.glob("expected-*/*.jsonl")}
    assert tracked <= set(sums)
    for name, digest in sums.items():
        assert hashlib.sha256((repo / "corpus" / name).read_bytes()).hexdigest() == digest, name


@pytest.mark.unit
def test_seed_corpus_regenerates_byte_for_byte(repo):
    out = subprocess.run([sys.executable, str(repo / "corpus/generators/seed.py"), "250", "1"],
                         capture_output=True, check=True)
    assert out.stdout == (repo / "corpus/cases/seed.jsonl").read_bytes()


@pytest.mark.unit
def test_expected_v1_lines_up_with_the_cases(repo):
    with open(repo / "corpus/cases/seed.jsonl") as f:
        cases = [json.loads(line) for line in f]
    with open(repo / "corpus/expected-v1/seed.jsonl") as f:
        expected = [json.loads(line) for line in f]
    assert [c["id"] for c in cases] == [e["id"] for e in expected]
    assert {e["lib"] for e in expected} == {"oracle"}
    assert all({"valid_a", "valid_b"} <= set(e) for e in expected)


@pytest.mark.unit
def test_corpus_is_cc0(repo):
    head = (repo / "corpus" / "LICENSE").read_text().splitlines()[:3]
    assert head == ["Creative Commons Legal Code", "", "CC0 1.0 Universal"]
