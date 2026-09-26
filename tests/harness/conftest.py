"""Fixtures for the tests of the v1 harness, the adapter manifests, the triage registry and
the repository layout.

The v1 harness (harness/*.py) is a set of scripts, not a package, so its modules are loaded
from their files.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    tomllib = pytest.importorskip("tomli")


def load_script(path, name):
    """Import a standalone script as a module named `name`."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses and pickling look modules up by name
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def repo():
    return REPO


@pytest.fixture(scope="session")
def toml():
    """The TOML parser: tomllib, or tomli on Python 3.10."""
    return tomllib


@pytest.fixture(scope="session")
def compare_mod():
    return load_script(REPO / "harness" / "compare.py", "geotruth_v1_compare")


@pytest.fixture(scope="session")
def tally_mod():
    return load_script(REPO / "harness" / "tally.py", "geotruth_v1_tally")


@pytest.fixture(scope="session")
def manifests(toml):
    """Map adapter directory name -> parsed adapter.toml, for every adapter with one."""
    out = {}
    for path in sorted((REPO / "adapters").glob("*/adapter.toml")):
        with open(path, "rb") as f:
            out[path.parent.name] = toml.load(f)
    return out
