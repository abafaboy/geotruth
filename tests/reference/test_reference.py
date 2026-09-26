"""The vendored references stay importable and keep giving the audited answers.

The legacy expected answers (corpus/expected-v1/seed.jsonl) were produced by the oracle
before it moved here, so reproducing them shows the move changed nothing.
"""

import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

from . import indep, oracle, validity

REPO = Path(__file__).resolve().parents[2]
SEED = REPO / "corpus" / "cases" / "seed.jsonl"
EXPECTED = REPO / "corpus" / "expected-v1" / "seed.jsonl"
REVIEW_CASES = REPO / "tools" / "oracle_review" / "findings_cases.jsonl"


def read_jsonl(path):
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def square(x0, y0, s):
    """A closed CCW square ring."""
    return [[x0, y0], [x0 + s, y0], [x0 + s, y0 + s], [x0, y0 + s], [x0, y0]]


@pytest.mark.unit
def test_package_import_shares_modules():
    # imported as a package, oracle must use the package's validity (no sys.path hack)
    assert oracle.validity is validity
    assert validity.indep is indep


@pytest.mark.unit
def test_importable_from_repository_root():
    code = (
        "from tests.reference import oracle, validity, indep\n"
        "assert oracle.validity is validity and validity.indep is indep\n"
        "print(oracle.__name__)"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True,
                         text=True, check=True)
    assert out.stdout.strip() == "tests.reference.oracle"


@pytest.mark.unit
def test_oracle_runs_as_script_on_review_findings():
    # the review's minimal cases include invalid inputs and area overflow (F1-F4)
    out = subprocess.run([sys.executable, str(REPO / "tests" / "reference" / "oracle.py"),
                          str(REVIEW_CASES)], capture_output=True, text=True, check=True)
    lines = [json.loads(line) for line in out.stdout.splitlines()]
    assert [r["id"] for r in lines] == [c["id"] for c in read_jsonl(REVIEW_CASES)]
    assert not any("oracle_error" in r for r in lines)


@pytest.mark.unit
def test_oracle_reproduces_expected_v1_sample():
    cases, expected = read_jsonl(SEED), read_jsonl(EXPECTED)
    assert [c["id"] for c in cases] == [e["id"] for e in expected]
    for case, exp in list(zip(cases, expected, strict=True))[::25]:
        assert oracle.evaluate(case) == exp, case["id"]


@pytest.mark.crosscheck
def test_oracle_script_reproduces_expected_v1_byte_for_byte():
    out = subprocess.run([sys.executable, str(REPO / "tests" / "reference" / "oracle.py"),
                          str(SEED)], capture_output=True, check=True)
    assert out.stdout == EXPECTED.read_bytes()


@pytest.mark.crosscheck
def test_indep_agrees_with_expected_v1_exact_areas():
    cases, expected = read_jsonl(SEED), read_jsonl(EXPECTED)
    checked = 0
    for case, exp in list(zip(cases, expected, strict=True))[::10]:
        if "exact" not in exp:  # an invalid input: nothing but validity is defined
            continue
        checked += 1
        got = indep.evaluate_geoms(case["a"], case["b"])
        for key in ("inter", "diff_ab", "diff_ba"):
            assert got[key] == Fraction(exp["exact"][key]), (case["id"], key)
        for p in ("intersects", "touches", "overlaps", "contains", "within", "equals"):
            assert got[p] == exp[p], (case["id"], p)
    assert checked > 50


@pytest.mark.unit
@pytest.mark.parametrize(
    ("geom", "valid"),
    [
        ([[square(0, 0, 4)]], True),
        ([[square(0, 0, 4), square(1, 1, 1)[::-1]]], True),  # a hole inside the shell
        ([[[[0, 0], [2, 2], [2, 0], [0, 2], [0, 0]]]], False),  # bowtie (R1)
        ([[square(0, 0, 4), square(5, 5, 1)]], False),  # hole outside the shell (R3)
        ([[square(0, 0, 2)], [square(2, 0, 2)]], False),  # parts share an edge (R6)
        ([[square(0, 0, 2)], [square(2, 2, 2)]], True),  # parts touch at one point
        ([[[[0, 0], [1, 0], [float("nan"), 1], [0, 0]]]], False),  # invalid coordinate (R0)
    ],
)
def test_validity_rules(geom, valid):
    assert validity.valid_geometry(geom) is valid
