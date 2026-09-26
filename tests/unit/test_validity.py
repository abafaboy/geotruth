"""Unit tests of exact validity (DESIGN §1 "Validity", §2.7).

Expected answers in the tables were checked against GEOS 3.13.1 (Shapely 2.1.2
``is_valid`` / ``explain_validity``) when they were written; the live comparison is
``tests/crosscheck/test_validity_geos.py``.
"""

from __future__ import annotations

import json
import math
from fractions import Fraction as F

import pytest

from geotruth import cli
from geotruth.geom import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from geotruth.io import read_wkt
from geotruth.validity import (
    CODES,
    MESSAGES,
    Site,
    _std_sort,
    _strtree,
    code_of_message,
    is_valid,
    validate,
)

NAN, INF = math.nan, math.inf

# (wkt, valid, GEOS first reason, full set of reasons)
CASES = [
    # --- empties and trivial types
    ("POINT EMPTY", True, None, ()),
    ("LINESTRING EMPTY", True, None, ()),
    ("POLYGON EMPTY", True, None, ()),
    ("MULTIPOINT EMPTY", True, None, ()),
    ("MULTILINESTRING EMPTY", True, None, ()),
    ("MULTIPOLYGON EMPTY", True, None, ()),
    ("GEOMETRYCOLLECTION EMPTY", True, None, ()),
    ("GEOMETRYCOLLECTION (POINT EMPTY, LINESTRING EMPTY, POLYGON EMPTY)", True, None, ()),
    ("POINT (1 2)", True, None, ()),
    ("MULTIPOINT ((0 0), (0 0))", True, None, ()),
    # --- lines: at least two distinct points; self-crossing lines are valid
    ("LINESTRING (0 0, 0 0)", False, "too_few_points", ("too_few_points",)),
    ("LINESTRING (0 0, 0 0, 0 0)", False, "too_few_points", ("too_few_points",)),
    ("LINESTRING (0 0, 1 1, 0 0)", True, None, ()),
    ("LINESTRING (0 0, 2 2, 2 0, 0 2)", True, None, ()),
    ("LINESTRING (0 0, 2 0, 1 0, 3 0)", True, None, ()),
    ("MULTILINESTRING ((0 0, 1 1), (2 2, 2 2))", False, "too_few_points", ("too_few_points",)),
    # --- single rings
    ("POLYGON ((0 0, 1 0, 2 0, 2 2, 0 2, 0 0))", True, None, ()),
    ("POLYGON ((0 0, 2 0, 2 0, 2 2, 0 2, 0 0))", True, None, ()),
    ("POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0))", True, None, ()),
    ("POLYGON ((0 0, 2 2, 2 0, 0 2, 0 0))", False, "self_intersection", ("self_intersection",)),
    (
        "POLYGON ((0 0, 1 1, 2 2, 2 0, 1 1, 0 2, 0 0))",
        False,
        "ring_self_intersection",
        ("ring_self_intersection",),
    ),
    (
        "POLYGON ((0 0, 2 0, 1 1, 2 2, 0 2, 1 1, 0 0))",
        False,
        "ring_self_intersection",
        ("ring_self_intersection",),
    ),
    (
        "POLYGON ((0 0, 4 0, 4 4, 2 0, 0 4, 0 0))",
        False,
        "ring_self_intersection",
        ("ring_self_intersection",),
    ),
    (
        "POLYGON ((0 0, 2 0, 2 2, 2 3, 2 2, 0 2, 0 0))",
        False,
        "ring_self_intersection",
        ("self_intersection", "ring_self_intersection"),
    ),
    (
        "POLYGON ((2 2, 2 3, 2 2, 0 2, 0 0, 2 0, 2 2))",
        False,
        "self_intersection",
        ("self_intersection", "ring_self_intersection"),
    ),
    (
        "POLYGON ((0 0, 4 0, 4 4, 2 0, 1 4, 3 -1, 0 0))",
        False,
        "ring_self_intersection",
        ("self_intersection", "ring_self_intersection"),
    ),
    ("POLYGON ((0 0, 1 1, 1 1, 0 0))", False, "too_few_points", ("too_few_points",)),
    ("POLYGON ((0 0, 1 0, 0 0))", False, "too_few_points", ("too_few_points",)),
    ("POLYGON ((0 0, 3 0, 1 0, 0 0))", False, "self_intersection", ("self_intersection",)),
    # --- holes
    ("POLYGON ((0 0, 1 0, 1 1, 0 0), EMPTY)", True, None, ()),
    (
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (0 1, 2 1, 2 3, 0 3, 0 1))",
        False,
        "self_intersection",
        ("self_intersection",),
    ),
    (
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (4 4, 6 4, 6 6, 4 4))",
        False,
        "hole_outside_shell",
        ("hole_outside_shell",),
    ),
    (
        "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (1 1, 9 1, 9 9, 1 9, 1 1), "
        "(2 2, 3 2, 3 3, 2 3, 2 2))",
        False,
        "nested_holes",
        ("nested_holes",),
    ),
    (
        "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (1 1, 9 1, 9 9, 1 9, 1 1), (1 1, 3 2, 2 3, 1 1))",
        False,
        "nested_holes",
        ("nested_holes",),
    ),
    (
        "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (0 5, 5 0, 5 5, 0 5))",
        False,
        "disconnected_interior",
        ("disconnected_interior",),
    ),
    (
        "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (0 5, 5 2, 5 5, 0 5), (5 5, 10 5, 5 8, 5 5))",
        False,
        "disconnected_interior",
        ("disconnected_interior",),
    ),
    (
        "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 5 2, 5 5, 2 5, 2 2), "
        "(5 5, 8 5, 8 8, 5 8, 5 5), (5 2, 8 2, 8 5, 5 2))",
        False,
        "disconnected_interior",
        ("disconnected_interior",),
    ),
    ("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 1 1, 3 1, 2 0))", True, None, ()),
    (
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (1 1, 2 2, 1 3, 1 1), (2 2, 3 1, 3 3, 2 2))",
        True,
        None,
        (),
    ),
    (
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (2 0, 3 -1, 3 1, 1 1, 1 -1, 2 0))",
        False,
        "self_intersection",
        ("self_intersection", "hole_outside_shell"),
    ),
    # GEOS stops at the double touch before seeing the crossing (noding order)
    (
        "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (0 5, 5 0, 5 5, 0 5), "
        "(7 7, 12 7, 12 8, 7 8, 7 7))",
        False,
        "hole_outside_shell",
        ("self_intersection", "hole_outside_shell", "disconnected_interior"),
    ),
    # ...but here a later chain pair still records a self-intersection
    (
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (4 3, 2 4, 3 2, 1 0, 1 4, 4 3))",
        False,
        "self_intersection",
        ("self_intersection", "disconnected_interior"),
    ),
    # --- multipolygons
    (
        "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((1 1, 3 1, 3 3, 1 3, 1 1)))",
        False,
        "self_intersection",
        ("self_intersection",),
    ),
    (
        "MULTIPOLYGON (((0 0, 10 0, 10 10, 0 10, 0 0)), ((1 1, 3 1, 3 3, 1 3, 1 1)))",
        False,
        "nested_shells",
        ("nested_shells",),
    ),
    (
        "MULTIPOLYGON (((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 8 2, 8 8, 2 8, 2 2)), "
        "((2 2, 5 3, 3 5, 2 2)))",
        True,
        None,
        (),
    ),
    (
        "MULTIPOLYGON (((0 0, 10 0, 10 10, 0 10, 0 0), (2 2, 8 2, 8 8, 2 8, 2 2)), "
        "((2 2, 8 2, 8 8, 2 8, 2 2)))",
        False,
        "self_intersection",
        ("self_intersection",),
    ),
    (
        "MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), ((2 2, 4 2, 4 4, 2 4, 2 2)), "
        "((2 0, 4 0, 4 2, 2 0)))",
        True,
        None,
        (),
    ),
    ("MULTIPOLYGON (EMPTY, ((0 0, 1 0, 1 1, 0 0)))", True, None, ()),
    # --- collections: per child
    (
        "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0)), "
        "POLYGON ((1 1, 3 1, 3 3, 1 3, 1 1)))",
        True,
        None,
        (),
    ),
    (
        "GEOMETRYCOLLECTION (MULTIPOLYGON (((0 0, 2 0, 2 2, 0 2, 0 0)), "
        "((1 1, 3 1, 3 3, 1 3, 1 1))))",
        False,
        "self_intersection",
        ("self_intersection",),
    ),
    (
        "GEOMETRYCOLLECTION (POINT (1 1), GEOMETRYCOLLECTION (LINESTRING (0 0, 0 0)))",
        False,
        "too_few_points",
        ("too_few_points",),
    ),
    ("POINT (NaN NaN)", False, "invalid_coordinate", ("invalid_coordinate",)),
    ("POINT (Inf 1)", False, "invalid_coordinate", ("invalid_coordinate",)),
    ("MULTIPOINT ((0 0), (1 -Inf))", False, "invalid_coordinate", ("invalid_coordinate",)),
]


@pytest.mark.parametrize(
    ("wkt", "valid", "first", "reasons"), CASES, ids=[c[0][:60] for c in CASES]
)
def test_table(wkt, valid, first, reasons):
    r = validate(read_wkt(wkt))
    assert r.valid is valid
    assert is_valid(read_wkt(wkt)) is valid
    assert r.first_reason == first
    assert set(r.reasons) == set(reasons)
    assert list(r.reasons) == [c for c in CODES if c in r.reasons]  # precedence order
    if first is not None:
        assert r.message == MESSAGES[first]
        assert r.first in r.defects or r.first_basis == "geos-order"
    else:
        assert r.message == "Valid Geometry" and r.first is None and not r.defects


def _exact_locations(wkt, code):
    return [d.location for d in validate(read_wkt(wkt)).defects if d.code == code]


def test_locations_are_exact_rationals():
    locs = _exact_locations("POLYGON ((0 0, 2 2, 2 0, 0 2, 0 0))", "self_intersection")
    assert locs == [((1, 1),)]
    locs = _exact_locations("POLYGON ((0 0, 4 0, 4 4, 2 0, 1 4, 3 -1, 0 0))", "self_intersection")
    assert sorted(locs) == [((F(7, 3), F(2, 3)),), ((F(13, 5), 0),)]
    # a collinear overlap is reported by its two endpoints
    locs = _exact_locations(
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (0 1, 2 1, 2 3, 0 3, 0 1))", "self_intersection"
    )
    assert locs == [((0, 1), (0, 3))]
    # every touch point on a cycle
    locs = _exact_locations(
        "POLYGON ((0 0, 10 0, 10 10, 0 10, 0 0), (0 5, 5 2, 5 5, 0 5), (5 5, 10 5, 5 8, 5 5))",
        "disconnected_interior",
    )
    assert locs == [((0, 5), (5, 5), (10, 5))]
    # the witness of a hole outside its shell is strictly outside
    locs = _exact_locations(
        "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (4 4, 6 4, 6 6, 4 4))", "hole_outside_shell"
    )
    assert locs == [((6, 4),)]


def test_sites_name_the_rings():
    r = validate(
        read_wkt("MULTIPOLYGON (((0 0, 10 0, 10 10, 0 10, 0 0)), ((1 1, 3 1, 3 3, 1 3, 1 1)))")
    )
    (d,) = r.defects
    assert d.sites == (Site((1,), 0), Site((0,), 0))
    r = validate(read_wkt("GEOMETRYCOLLECTION (POINT (1 1), MULTIPOINT ((0 0), (NaN 2)))"))
    (d,) = r.defects
    assert d.sites == (Site((1, 1), None, 0),)
    assert d.location == () and math.isnan(d.coordinate[0]) and d.coordinate[1] == 2.0


def test_every_defect_is_reported():
    # two bowties and a nested part: all defects, not only the first
    g = read_wkt(
        "MULTIPOLYGON (((0 0, 2 2, 2 0, 0 2, 0 0)), ((10 0, 12 2, 12 0, 10 2, 10 0)), "
        "((20 0, 30 0, 30 10, 20 10, 20 0)), ((21 1, 22 1, 22 2, 21 2, 21 1)))"
    )
    r = validate(g)
    crossings = [d for d in r.defects if d.code == "self_intersection"]
    assert sorted(d.location for d in crossings) == [((1, 1),), ((11, 1),)]
    assert [d.code for d in r.defects].count("nested_shells") == 1


def test_unconstructible_rings_and_lines():
    # GEOS cannot build these; the exact answer still names the defect
    r = validate(Polygon([[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]]))
    assert r.first_reason == "ring_not_closed"
    assert set(r.reasons) == {"ring_not_closed", "too_few_points"}
    assert validate(LineString([(1.0, 1.0)])).first_reason == "too_few_points"
    r = validate(Polygon([[], [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 0.0)]]))
    assert r.reasons == ("hole_outside_shell",)


def test_precedence_within_units():
    # Polygon: coordinates of every ring before closure of any ring
    p = Polygon(
        [
            [(0.0, 0.0), (4.0, 0.0), (4.0, 4.0), (0.0, 4.0)],  # not closed
            [(1.0, 1.0), (NAN, 1.0), (2.0, 2.0), (1.0, 1.0)],  # invalid coordinate
        ]
    )
    assert validate(p).first_reason == "invalid_coordinate"
    # MultiPolygon: coordinates, closure and size part by part
    mp = MultiPolygon(
        [
            Polygon([[(0.0, 0.0), (1.0, 1.0), (1.0, 1.0), (0.0, 0.0)]]),  # too few points
            Polygon([[(5.0, 5.0), (INF, 5.0), (6.0, 6.0), (5.0, 5.0)]]),  # invalid coordinate
        ]
    )
    r = validate(mp)
    assert r.first_reason == "too_few_points"
    assert set(r.reasons) == {"too_few_points", "invalid_coordinate"}
    # collections: the first invalid child
    gc = GeometryCollection([LineString([(0.0, 0.0), (0.0, 0.0)]), Point((NAN, 0.0))])
    assert validate(gc).first_reason == "too_few_points"


def test_gc_is_checked_per_child():
    a = Polygon([[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 2.0), (0.0, 0.0)]])
    b = Polygon([[(1.0, 1.0), (3.0, 1.0), (3.0, 3.0), (1.0, 3.0), (1.0, 1.0)]])
    assert validate(GeometryCollection([a, b])).valid
    assert not validate(GeometryCollection([MultiPolygon([a, b])])).valid
    assert not validate(MultiPolygon([a, b])).valid
    assert validate(MultiLineString([LineString([(0.0, 0.0), (1.0, 1.0)])])).valid


def test_orientation_start_and_repeats_do_not_matter():
    for wkt, valid, _, reasons in CASES:
        g = read_wkt(wkt)
        if not isinstance(g, (Polygon, MultiPolygon)) or g.is_empty:
            continue

        def transform(ring):
            if len(ring) < 4:
                return ring
            body = list(ring[:-1])
            body = body[1:] + body[:1]  # rotate the start
            body.insert(1, body[1])  # a repeated point
            body = body[::-1]  # reverse the orientation
            return (*body, body[0])

        polys = [g] if isinstance(g, Polygon) else list(g.polygons)
        polys = [Polygon([transform(r) for r in p.rings]) for p in polys]
        h = polys[0] if isinstance(g, Polygon) else MultiPolygon(polys)
        r = validate(h)
        assert r.valid is valid, wkt
        assert set(r.reasons) == set(reasons), wkt


@pytest.mark.parametrize("k", [-1074 + 40, -600, -20, 3, 500])
def test_exact_scaling_invariance(k):
    for wkt, valid, _, reasons in CASES:
        g = read_wkt(wkt)
        if g.has_nonfinite:
            continue
        h = g.map_coords(lambda c: (math.ldexp(c[0], k), math.ldexp(c[1], k)))
        back = h.map_coords(lambda c: (math.ldexp(c[0], -k), math.ldexp(c[1], -k)))
        if list(back.iter_values()) != list(g.iter_values()):
            continue  # not exactly representable at this scale
        r = validate(h)
        assert r.valid is valid, (wkt, k)
        assert set(r.reasons) == set(reasons), (wkt, k)


def test_rational_coordinates():
    # exact engine output: rational vertices, validity by the same rules
    tri = Polygon([[(F(0), F(0)), (F(1, 3), F(0)), (F(1, 3), F(1, 7)), (F(0), F(0))]])
    assert validate(tri).valid
    bow = Polygon(
        [[(F(0), F(0)), (F(2, 3), F(2, 3)), (F(2, 3), F(0)), (F(0), F(2, 3)), (F(0), F(0))]]
    )
    r = validate(bow)
    assert r.reasons == ("self_intersection",)
    assert r.defects[0].location == ((F(1, 3), F(1, 3)),)
    # no doubles, so the GEOS noding order is not emulated for ties
    both = Polygon(
        [
            [
                (F(0), F(0)),
                (F(2), F(0)),
                (F(2), F(2)),
                (F(2), F(3)),
                (F(2), F(2)),
                (F(0), F(2)),
                (F(0), F(0)),
            ]
        ]
    )
    r = validate(both)
    assert not r.first_certain and r.first_basis == "heuristic"
    assert set(r.first_alternatives) == {"self_intersection", "ring_self_intersection"}


def test_report_json_matches_schema():
    pytest.importorskip("jsonschema")
    from jsonschema import Draft202012Validator

    from geotruth import schemas

    ref = schemas.load_schema("expected")["$id"] + "#/$defs/Validity"
    check = Draft202012Validator({"$ref": ref}, registry=schemas._registry())
    for wkt, *_ in CASES:
        report = validate(read_wkt(wkt))
        obj = report.to_json()
        check.validate(obj)
        detail = report.to_json(detail=True)
        json.dumps(detail)  # plain JSON
        assert set(obj) <= set(detail)


def test_code_of_message():
    assert code_of_message("Self-intersection[1 1]") == "self_intersection"
    assert code_of_message("Ring Self-intersection[2 0]") == "ring_self_intersection"
    assert code_of_message("Too few points in geometry component[0 0]") == "too_few_points"
    assert code_of_message("Too few distinct points in geometry component[0 0]") == "too_few_points"
    assert code_of_message("Valid Geometry") is None
    for code in CODES:
        assert code_of_message(MESSAGES[code] + "[0 0]") == code


def test_std_sort_emulation():
    import random

    rng = random.Random(4)
    for n in (0, 1, 2, 5, 16, 17, 40, 200):
        keys = [rng.randrange(6) for _ in range(n)]
        items = list(range(n))
        _std_sort(items, key=keys.__getitem__)
        assert [keys[i] for i in items] == sorted(keys)
        if n <= 16:  # insertion sort: stable
            assert items == sorted(range(n), key=keys.__getitem__)


def test_strtree_leaf_order_small():
    # at most 10 items: one node, sorted by x-sum, then (stably) by y-sum:
    # x-sums 4, 5, 1, 0 give 3, 2, 0, 1; y-sums 4, 0, 4, 4 then give 1, 3, 2, 0
    boxes = [(0.0, 0.0, 4.0, 4.0), (1.0, 0.0, 4.0, 0.0), (0.0, 2.0, 1.0, 2.0), (0.0, 0.0, 0.0, 4.0)]
    leaves, root = _strtree(boxes)
    assert [leaf.item for leaf in leaves] == [1, 3, 2, 0]
    assert [c.item for c in root.children] == [1, 3, 2, 0]
    # 11..16 items: two vertical slices, and a root over their parents
    boxes = [(float(i % 4), float(i // 4), float(i % 4), float(i // 4)) for i in range(12)]
    leaves, root = _strtree(boxes)
    assert sorted(leaf.item for leaf in leaves) == list(range(12))
    assert len(root.children) == 2 and all(c.children for c in root.children)


def test_cli_text_and_json(capsys):
    assert cli.main(["valid", "POLYGON ((0 0, 2 2, 2 0, 0 2, 0 0))"]) == 0
    out = capsys.readouterr().out
    assert "INVALID" in out and "Self-intersection at (1, 1)" in out
    assert cli.main(["valid", "POINT (1 2)", "--json"]) == 0
    obj = json.loads(capsys.readouterr().out)
    assert obj["valid"] is True and obj["defects"] == [] and obj["geometry_type"] == "Point"
    case = json.dumps(
        {
            "id": "x",
            "a": [[[[0, 0], [1, 0], [1, 1], [0, 0]]]],
            "b": {"type": "LineString", "coordinates": [[0, 0], [0, 0]]},
        }
    )
    assert cli.main(["valid", case, "--operand", "b", "--json"]) == 0
    obj = json.loads(capsys.readouterr().out)
    assert obj["reasons"] == ["too_few_points"] and obj["first_reason_basis"] == "precedence"
    assert cli.main(["valid", "POLYGON ((0 0"]) == 2
    assert "cannot read" in capsys.readouterr().err


def test_cli_reads_files(tmp_path, capsys):
    path = tmp_path / "g.wkt"
    path.write_text("LINESTRING (0 0, 0 0)\n")
    assert cli.main(["valid", str(path)]) == 0
    assert "Too few points" in capsys.readouterr().out
    jl = tmp_path / "cases.jsonl"
    jl.write_text(json.dumps({"id": "c", "a": {"type": "Point", "coordinates": [1, 2]}}) + "\n")
    assert cli.main(["valid", str(jl), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_multipoint_and_empty_parts():
    assert validate(MultiPoint([Point(), Point((1.0, 2.0))])).valid
    assert validate(MultiPolygon([Polygon(), Polygon()])).valid
    assert validate(GeometryCollection([GeometryCollection()])).valid
