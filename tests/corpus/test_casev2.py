"""corpus/generators/casev2.py: v2 records, exact tags."""

from __future__ import annotations

import math

import pytest

from geotruth import schemas
from geotruth.io import read_wkt

pytestmark = pytest.mark.unit


def tags(casev2, a, b, **kw):
    return casev2.compute_tags(read_wkt(a), read_wkt(b), **kw)


@pytest.mark.parametrize(
    ("a", "b", "degeneracy", "k"),
    [
        # a shared vertex
        ("POLYGON ((0 0, 2 0, 1 1, 0 0))", "POLYGON ((2 0, 3 0, 3 1, 2 0))", "lattice", 1),
        # a collinear overlap: two overlap endpoints
        ("LINESTRING (0 0, 4 0)", "LINESTRING (1 0, 6 0)", "lattice", 2),
        # a T-junction: endpoint in the other's interior
        ("LINESTRING (0 0, 4 4)", "LINESTRING (2 2, 5 0)", "lattice", 1),
        # a point exactly on a segment
        ("POINT (1 0.5)", "LINESTRING (0 0, 2 1)", "lattice", 1),
        # a proper crossing at a rational point: generic
        ("LINESTRING (0 0, 3 1)", "LINESTRING (0 1, 3 0)", "generic", 1),
        # disjoint and far apart
        ("POINT (0 0)", "LINESTRING (5 5, 6 7)", "generic", 0),
    ],
)
def test_contact_classes(casev2, a, b, degeneracy, k):
    t = tags(casev2, a, b)
    assert t["degeneracy"] == degeneracy
    assert t["k"] == k


def test_ulp_near_vertex_is_ulp_class(casev2):
    y = math.nextafter(0.5, 1.0)  # one ulp above the segment (0,0)-(2,1) at x = 1
    t = tags(casev2, f"POINT (1 {y!r})", "LINESTRING (0 0, 2 1)")
    assert t["degeneracy"] == "ulp"
    assert t["k"] == 0


def test_intra_operand_touch_is_lattice(casev2):
    # parts of A touch at (2, 2); B is far away
    a = "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 0)), ((2 2, 4 2, 4 4, 2 2)))"
    assert tags(casev2, a, "POINT (10 10)")["degeneracy"] == "lattice"


def test_range_and_counts(casev2):
    t = tags(casev2, "POINT (1e-200 0)", "LINESTRING (0 0, 1 1)")
    assert t["range"] == "extreme"
    assert t["n"] == 3
    assert t["types"] == ["Point", "LineString"]
    assert tags(casev2, "POINT (1e100 0)", "POINT (0 0)")["range"] == "normal"


def test_flags(casev2):
    t = tags(
        casev2,
        "GEOMETRYCOLLECTION (POINT EMPTY, LINESTRING (1 1, 1 1))",
        "POINT (1 1)",
        flags=["curated"],
    )
    assert set(t["flags"]) == {"curated", "empty", "gc", "zero-length-line"}


def test_make_case_is_schema_valid(casev2):
    legacy = [[[[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]]]
    rec = casev2.make_case(
        "x-1-000001-v",
        "x",
        legacy,
        {"type": "Point", "coordinates": [0.25, 0.25]},
        variant="v",
        prov=casev2.provenance("corpus/generators/test.py", 1, 10),
    )
    assert rec["a"]["type"] == "Polygon"
    assert rec["provenance"]["generator_version"] == casev2.GENERATOR_VERSION
    schemas.validate("case", rec)
