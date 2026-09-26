"""Access to the JSON Schemas in the repository's ``schemas/`` directory.

The schemas (draft 2020-12) are the frozen v2 formats: ``geometry`` (shared
definitions), ``case``, ``expected``, ``result``, ``run``, ``score`` and ``adapter``
(the parsed ``adapter.toml`` manifest). Cross-file references are relative
(``geometry.v2.schema.json#/$defs/Geometry``) and resolve through a registry built
from all of them.

Validation needs the optional ``jsonschema`` package (``pip install geotruth[dev]``)::

    from geotruth import schemas
    schemas.validate("result", record)          # raises jsonschema.ValidationError

The directory is ``$GEOTRUTH_SCHEMA_DIR`` if set, else ``schemas/`` at the root of the
source tree this package lives in.
"""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

__all__ = ["SCHEMA_NAMES", "load_schema", "schema_dir", "schema_path", "validate", "validator"]

#: Names of the v2 schemas.
SCHEMA_NAMES: tuple[str, ...] = (
    "geometry",
    "case",
    "expected",
    "result",
    "run",
    "score",
    "adapter",
)
_VERSION = "v2"


def schema_dir() -> Path:
    """The directory holding the ``*.v2.schema.json`` files."""
    env = os.environ.get("GEOTRUTH_SCHEMA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "schemas"


def schema_path(name: str) -> Path:
    """Path of the schema file for ``name`` (one of :data:`SCHEMA_NAMES`)."""
    if name not in SCHEMA_NAMES:
        raise KeyError(f"unknown schema {name!r}; expected one of {SCHEMA_NAMES}")
    return schema_dir() / f"{name}.{_VERSION}.schema.json"


@cache
def load_schema(name: str) -> dict[str, Any]:
    """The parsed schema document for ``name``."""
    with open(schema_path(name), encoding="utf-8") as fh:
        return json.load(fh)


@cache
def _registry() -> Any:
    from referencing import Registry, Resource

    resources = []
    for n in SCHEMA_NAMES:
        doc = load_schema(n)
        res = Resource.from_contents(doc)
        resources.append((doc["$id"], res))
    return Registry().with_resources(resources)


def validator(name: str) -> Any:
    """A ``jsonschema`` Draft 2020-12 validator for ``name`` (requires jsonschema)."""
    from jsonschema import Draft202012Validator

    return Draft202012Validator(load_schema(name), registry=_registry())


def validate(name: str, instance: Any) -> None:
    """Validate ``instance`` against schema ``name``; raises
    ``jsonschema.ValidationError`` (the most relevant error) on failure."""
    from jsonschema.exceptions import best_match

    error = best_match(validator(name).iter_errors(instance))
    if error is not None:
        raise error
