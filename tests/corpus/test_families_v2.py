"""The v2 families: deterministic, valid (or invalid by name), schema-valid, tagged."""

from __future__ import annotations

import pytest

from geotruth import schemas
from geotruth.io import geometry_from_json
from geotruth.validity import is_valid

pytestmark = pytest.mark.unit

N = 40


@pytest.fixture(scope="module")
def generated(tiers):
    from families_v2 import FAMILIES_V2

    return {name: tiers.generate_family(name, N, 3)[0] for name, _ in FAMILIES_V2}


def test_every_v2_family_generates(generated):
    assert set(generated) == {
        "line-line",
        "line-mod2",
        "point-geometry",
        "line-polygon",
        "gc",
        "empty",
        "invalid-zero-length-line",
    }
    for name, recs in generated.items():
        assert len(recs) == N, name
        assert len({r["id"] for r in recs}) == N
        assert all(r["id"].startswith(f"{name}-3-") for r in recs)
        assert all(r["family"] == name for r in recs)


def test_deterministic(tiers, generated):
    again, _ = tiers.generate_family("line-polygon", N, 3)
    assert again == generated["line-polygon"]
    other, _ = tiers.generate_family("line-polygon", N, 4)
    assert other != generated["line-polygon"]


def test_validity_follows_the_family_name(generated):
    for name, recs in generated.items():
        for r in recs:
            va = is_valid(geometry_from_json(r["a"]))
            vb = is_valid(geometry_from_json(r["b"]))
            if name.startswith("invalid-"):
                assert not (va and vb), r["id"]
            else:
                assert va and vb, r["id"]


def test_schema_and_provenance(generated):
    for recs in generated.values():
        for r in recs[:10]:
            schemas.validate("case", r)
            p = r["provenance"]
            assert p["source"] == "generator"
            assert p["generator"] == "corpus/generators/families_v2.py"
            assert p["seed"] == 3
            assert {"degeneracy", "range", "n", "k", "types", "variant"} <= set(r["tags"])


def test_family_flags(generated):
    def flags(name):
        return [set(r["tags"].get("flags", ())) for r in generated[name]]

    assert all("mod2" in f for f in flags("line-mod2"))
    assert all("gc" in f for f in flags("gc"))
    zero = flags("invalid-zero-length-line")
    assert all({"zero-length-line", "invalid-input"} <= f for f in zero)
    empty = flags("empty")
    assert all("empty" in f for f in empty)
    assert any("convention" in f for f in empty)


def test_types_cover_lines_points_and_collections(generated):
    types = {t for recs in generated.values() for r in recs for t in r["tags"]["types"]}
    assert {
        "Point",
        "LineString",
        "MultiLineString",
        "MultiPoint",
        "Polygon",
        "GeometryCollection",
    } <= types


def test_extreme_and_rotated_variants(tiers):
    recs, _ = tiers.generate_family("line-line", 200, 1)
    extreme = [r for r in recs if ".extreme" in r["id"]]
    assert extreme and all(r["tags"]["range"] == "extreme" for r in extreme)
    assert any(".rot" in r["id"] for r in recs)
    assert {r["tags"]["degeneracy"] for r in recs} == {"lattice", "ulp", "generic"}


def test_legacy_families_match_the_v1_writer(tiers):
    """The v2 conversion of a legacy family is the v1 generator's output, case by case."""
    import random

    import common
    from families import FAMILIES

    fn = dict(FAMILIES)["vertex-on-edge"]
    rng = random.Random("vertex-on-edge:1")
    v1 = []
    while len(v1) < 5:
        try:
            v, a, b = fn(rng)
            a, b = common.finalize(rng, a), common.finalize(rng, b)
        except common.Reject:
            continue
        if all(common.check_valid(g)[0] for g in (a, b)):
            v1.append((v, a, b))
    v2, _ = tiers.generate_family("vertex-on-edge", 5, 1)
    for (v, a, b), rec in zip(v1, v2, strict=True):
        assert rec["tags"]["variant"] == v
        assert rec["a"] == {"type": "Polygon", "coordinates": a[0]} or rec["a"]["coordinates"] == a
        assert rec["b"] == {"type": "Polygon", "coordinates": b[0]} or rec["b"]["coordinates"] == b
