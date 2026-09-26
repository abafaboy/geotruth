"""geotruth minimize on real disagreements of the seed corpus, with the real adapters
(skipped when a library is not built under $GEOTRUTH_BUILD_DIR)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from corpus_testlib import REPO

from geotruth.minimize import AdapterRunner, find_target, load_case, minimize

pytestmark = pytest.mark.crosscheck


def _build(*parts):
    return Path(os.environ.get("GEOTRUTH_BUILD_DIR", Path.home() / ".cache" / "geotruth"), *parts)


REAL = [
    (
        "boost-develop",
        "rotated-neighbours-1-000230",
        "predicates.within",
        _build("boost-geometry", "bin"),
    ),
    ("turf", "tiny-rotation-1-000001", "touches", _build("js-libs", "node_modules")),
    (
        "polygon-clipping",
        "rotated-neighbours-1-000005",
        "area_inter",
        _build("js-libs", "node_modules"),
    ),
]


@pytest.mark.parametrize(("lib", "case_id", "fieldname", "needs"), REAL)
def test_real_disagreements_shrink(lib, case_id, fieldname, needs):
    if not needs.exists():
        pytest.skip(f"{lib} is not built under {needs}")
    runner = AdapterRunner(find_target(lib), op_timeout=5)
    case = load_case(str(REPO / "corpus" / "cases" / "seed.jsonl"), case_id)
    res = minimize(case, runner, fieldname)
    assert res.after < res.before
    assert res.adapter_calls <= res.rounds + 1
