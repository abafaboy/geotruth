"""The v2 JSON Schemas: well-formed, examples accepted/rejected, and io output conforms."""

from __future__ import annotations

import json
import sys
from fractions import Fraction

import pytest

from geotruth import schemas
from geotruth.io import case_from_json, case_to_json, geometry_to_json, read_wkt
from geotruth.numbers import json_loads

jsonschema = pytest.importorskip("jsonschema", reason="jsonschema not installed")

EXAMPLES = schemas.schema_dir() / "examples"
RECORDS = [n for n in schemas.SCHEMA_NAMES if n != "geometry"]


def _load_toml(path):
    if sys.version_info >= (3, 11):
        import tomllib
    else:  # pragma: no cover
        tomllib = pytest.importorskip("tomli")
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def valid_examples(name):
    path = EXAMPLES / f"{name}.v2.valid.json"
    if path.exists():
        return json_loads(path.read_text())
    return [_load_toml(EXAMPLES / f"{name}.v2.valid.toml")]


@pytest.mark.parametrize("name", schemas.SCHEMA_NAMES)
def test_schema_is_well_formed(name):
    doc = schemas.load_schema(name)
    jsonschema.Draft202012Validator.check_schema(doc)
    assert doc["$id"].endswith(f"/{name}.v2.schema.json")
    assert doc["$schema"] == "https://json-schema.org/draft/2020-12/schema"


def test_schema_ids_are_unique():
    ids = [schemas.load_schema(n)["$id"] for n in schemas.SCHEMA_NAMES]
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("name", RECORDS)
def test_valid_examples_are_accepted(name):
    examples = valid_examples(name)
    assert examples
    for inst in examples:
        schemas.validate(name, inst)


@pytest.mark.parametrize("name", RECORDS)
def test_invalid_examples_are_rejected(name):
    items = json.loads((EXAMPLES / f"{name}.v2.invalid.json").read_text())
    assert items
    for item in items:
        with pytest.raises(jsonschema.ValidationError):
            schemas.validate(name, item["instance"])


def test_unknown_schema_name():
    with pytest.raises(KeyError):
        schemas.schema_path("nope")


def test_schema_dir_override(monkeypatch, tmp_path):
    monkeypatch.setenv("GEOTRUTH_SCHEMA_DIR", str(tmp_path))
    assert schemas.schema_dir() == tmp_path


# ------------------------------------------------------------ io output conforms

GEOMETRY_WKT = [
    "POINT EMPTY",
    "POINT (1 2)",
    "LINESTRING (0 0, 1 1)",
    "LINESTRING EMPTY",
    "POLYGON ((0 0, 4 0, 4 4, 0 0), (1 1, 2 1, 2 2, 1 1))",
    "POLYGON EMPTY",
    "MULTIPOINT ((0 0), EMPTY)",
    "MULTILINESTRING ((0 0, 1 1), EMPTY)",
    "MULTIPOLYGON (((0 0, 1 0, 0 1, 0 0)), EMPTY)",
    "GEOMETRYCOLLECTION EMPTY",
    "GEOMETRYCOLLECTION (POINT (1 2), GEOMETRYCOLLECTION (LINESTRING (0 0, 1 1)))",
]


def _geometry_validator(defn):
    from jsonschema import Draft202012Validator

    doc = schemas.load_schema("geometry")
    return Draft202012Validator(
        {"$ref": f"{doc['$id']}#/$defs/{defn}"}, registry=schemas._registry()
    )


@pytest.mark.parametrize("wkt", GEOMETRY_WKT)
def test_geometry_json_conforms(wkt):
    g = read_wkt(wkt)
    _geometry_validator("Geometry").validate(geometry_to_json(g))
    _geometry_validator("ExactGeometry").validate(geometry_to_json(g, exact=True))
    if not g.is_empty:  # ordinates of one kind are rejected by the other definition
        with pytest.raises(jsonschema.ValidationError):
            _geometry_validator("Geometry").validate(geometry_to_json(g, exact=True))
        with pytest.raises(jsonschema.ValidationError):
            _geometry_validator("ExactGeometry").validate(geometry_to_json(g))


def test_rational_pattern_matches_format_rational():
    from geotruth.numbers import format_rational

    v = _geometry_validator("Rational")
    for q in [Fraction(0), Fraction(-3), Fraction(7, 2), Fraction(-1, 10**30), Fraction(10**40)]:
        v.validate(format_rational(q))
    for bad in ["-0", "01", "1/1", "1/01", "1/-2", "1.5", "+2"]:
        with pytest.raises(jsonschema.ValidationError):
            v.validate(bad)


def test_case_round_trip_conforms():
    for inst in valid_examples("case"):
        schemas.validate("case", case_to_json(case_from_json(inst)))


def test_repository_adapter_manifests_conform(repo_root):
    """Every adapters/*/adapter.toml in the tree matches the frozen manifest schema."""
    manifests = sorted((repo_root / "adapters").glob("*/adapter.toml"))
    if not manifests:
        pytest.skip("no adapter manifests in this checkout")
    for path in manifests:
        schemas.validate("adapter", _load_toml(path))
