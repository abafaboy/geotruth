"""Fixtures for the corpus, minimiser and export tests (tests/corpus/).

The corpus code lives in corpus/generators/ (outside the package); it is imported from
there, the way ``geotruth corpus`` does.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
GEN = REPO / "corpus" / "generators"
DATA = Path(__file__).resolve().parent / "data"
if str(GEN) not in sys.path:
    sys.path.insert(0, str(GEN))


def read_jsonl(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as fh:
        return [json.loads(ln) for ln in fh if ln.strip()]


def id_list(name: str) -> list[str]:
    """Ids (first tab-separated field) of a tests/corpus/data list, comments skipped."""
    out = []
    for ln in (DATA / name).read_text().splitlines():
        if ln.strip() and not ln.startswith("#"):
            out.append(ln.split("\t")[0].strip())
    return out


def records_by_id(ids: list[str]) -> list[dict]:
    """The core/curated records with these ids, in the given order."""
    want = set(ids)
    found: dict[str, dict] = {}
    paths = sorted((REPO / "corpus" / "cases" / "core").glob("*.jsonl"))
    for p in [*paths, REPO / "corpus" / "cases" / "curated.jsonl"]:
        for r in read_jsonl(p):
            if r["id"] in want:
                found[r["id"]] = r
    missing = want - set(found)
    assert not missing, f"cases not in the corpus: {sorted(missing)}"
    return [found[i] for i in ids]


@pytest.fixture(scope="session")
def tiers():
    import tiers as mod

    return mod


@pytest.fixture(scope="session")
def casev2():
    import casev2 as mod

    return mod


@pytest.fixture(scope="session")
def curated_records() -> list[dict]:
    return read_jsonl(REPO / "corpus" / "cases" / "curated.jsonl")
