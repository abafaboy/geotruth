"""Fixtures for the corpus, minimiser and export tests (tests/corpus/)."""

from __future__ import annotations

import pytest
from corpus_testlib import REPO, read_jsonl


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
