"""Long overlay cross-checks (DESIGN §2.5, §2.6): the whole exhaustive 3x3 grid and larger
random runs of ``tools/crosscheck_overlay.py``. See tests/crosscheck/test_overlay_crosscheck.py
for what each case checks."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

REPO = Path(__file__).resolve().parents[2]


def _load_tool():
    name = "crosscheck_overlay"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / "crosscheck_overlay.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


X = _load_tool()


def _check(reports) -> None:
    failures = [(r.id, r.wkt, r.problems) for r in reports if r.failed]
    assert failures == []
    assert all(r.certified == r.results == 8 for r in reports)
    assert not any(v == "UNEXPLAINED" for r in reports for v in r.geos.values())


def test_full_exhaustive_grid():
    """Every (triangle, point | segment | triangle) pair on the 3x3 grid and the GC and
    path pairs: all four operations, both variants, certified, GEOS compared."""
    cases = list(X.R.exhaustive_cases(0))
    assert len(cases) == 23732
    reports = X.run(cases, jobs=2, properties=False)
    _check(reports)
    assert sum(r.oracle_agree is True for r in reports) > 5000


@pytest.mark.parametrize("seed", [21, 22])
def test_random_sources_with_properties(seed):
    cases = (
        list(X.R.lattice_cases(1500, seed))
        + list(X.R.adversarial_cases(1500, seed))
        + list(X.R.dense_cases(300, seed))
        + list(X.R.transformed_cases(300, seed))
    )
    reports = X.run(cases, jobs=2)
    _check(reports)
    assert all(r.identities for r in reports)
    assert all(r.transform_agree is not False for r in reports)
