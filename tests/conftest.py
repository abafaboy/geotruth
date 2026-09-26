"""Shared pytest configuration for geotruth.

- Tests are marked by directory: everything under ``tests/unit/`` gets the ``unit``
  marker, ``tests/crosscheck/`` gets ``crosscheck`` and ``tests/slow/`` gets ``slow``
  (unless a test already carries one of them), so ``pytest -m unit`` selects the fast
  suite without per-file boilerplate.
- ``src/`` is importable without installing the package (also set in pyproject.toml).
- ``tests/`` is importable too, so other test directories can reuse the hand-built
  arrangement fixtures: ``from unit.fixtures_arrangement import FIXTURES, build``.
- Hypothesis profiles: ``quick`` (the default, keeps ``-m unit`` under a minute), ``ci``
  (more examples) and ``thorough``; select with ``HYPOTHESIS_PROFILE``.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
ROOT = TESTS.parent
SRC = ROOT / "src"
for _p in (SRC, TESTS):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

_DIR_MARKERS = ("unit", "crosscheck", "slow")

try:
    from hypothesis import HealthCheck, settings
except ImportError:  # hypothesis is optional; property tests skip without it
    pass
else:
    settings.register_profile(
        "quick",
        max_examples=150,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    settings.register_profile("ci", max_examples=400, deadline=None)
    settings.register_profile("thorough", max_examples=5000, deadline=None)
    settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "quick"))


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        try:
            rel = Path(str(item.fspath)).resolve().relative_to(TESTS)
        except ValueError:
            continue
        top = rel.parts[0] if len(rel.parts) > 1 else ""
        if top in _DIR_MARKERS and not any(item.get_closest_marker(m) for m in _DIR_MARKERS):
            item.add_marker(getattr(pytest.mark, top))


@pytest.fixture(scope="session")
def repo_root() -> Path:
    """The repository root."""
    return ROOT
