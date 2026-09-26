"""Unit tests of relate from the arrangement (DESIGN §2.3): the matrix reduction, the
named predicates, the assertions, the statuses and the expected-answer record."""

from __future__ import annotations

import random
from fractions import Fraction

import pytest

import geotruth.relate as R
from geotruth.arrangement import Budget, InvalidInputError, build_arrangement
from geotruth.arrangement_api import ArrangementError, Location
from geotruth.geom import GeometryCollection, LineString, Point, Polygon
from geotruth.io import read_wkt
from geotruth.predicates import PREDICATE_NAMES, predicates, transpose
from geotruth.relate import (
    ENTRY_NAMES,
    STATUS_ERROR,
    STATUS_OK,
    STATUS_SKIPPED,
    RelateAssertionError,
    cell_realizers,
    describe_cell,
    effective_dimension,
    matrix_from_arrangement,
    matrix_sanity,
    relate,
    relate_matrix,
)
from unit.fixtures_arrangement import FIXTURES, fixture
from unit.test_relate_witness import HAND_CASES

SQ = "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))"


def W(text: str):
    return read_wkt(text)


def comb(teeth: int, dx: int = 0) -> Polygon:
    """A comb polygon; two combs rotated against each other cross teeth**2 times."""
    pts = [(0, 0)]
    for i in range(teeth):
        pts += [(2 * i + 1, 0), (2 * i + 1, 10), (2 * i + 2, 10), (2 * i + 2, 0)]
    pts += [(2 * teeth + 1, 0), (2 * teeth + 1, -1), (0, -1), (0, 0)]
    return Polygon([[(float(x + dx), float(y)) for x, y in pts]])


# ============================================================ matrix from labels


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_matrix_of_hand_built_fixtures(name):
    """The reduction alone, on the Phase-0 hand-built arrangements (not built by E1)."""
    assert matrix_from_arrangement(fixture(name)) == FIXTURES[name].relate


@pytest.mark.parametrize("name", sorted(FIXTURES))
def test_relate_reproduces_fixture_matrices(name):
    spec = FIXTURES[name]
    a, b = W(spec.a), W(spec.b)
    res = relate(a, b, strict=True)
    assert res.status == STATUS_OK and res.matrix == spec.relate
    assert relate(b, a, strict=True).matrix == transpose(spec.relate)


@pytest.mark.parametrize(("a", "b", "expected"), HAND_CASES)
def test_hand_cases(a, b, expected):
    """E2's hand table (every P/L/A x P/L/A pair, mod-2, GC union, zero-length lines,
    known GEOS defects, empties), each checked against its written matrix."""
    ga, gb = W(a), W(b)
    assert relate(ga, gb, strict=True).matrix == expected
    assert relate(gb, ga, strict=True).matrix == transpose(expected)


def test_unlabelled_cell_is_an_arrangement_error():
    arr = fixture("overlapping_squares")
    arr.edge_loc_a[3] = int(Location.NONE)
    with pytest.raises(ArrangementError, match="labelled"):
        matrix_from_arrangement(arr)


def test_matrix_uses_the_maximum_dimension_per_entry():
    arr = fixture("dangling_line")  # II is realised by an edge, not only by the vertex
    assert matrix_from_arrangement(arr)[0] == "1"
    arr.edge_loc_a[5] = arr.edge_loc_b[5] = int(Location.EXTERIOR)  # the II edge -> EE
    assert matrix_from_arrangement(arr)[0] == "F"
    arr.vertex_loc_b[5] = int(Location.INTERIOR)  # vertex (2 2): IB -> II
    assert matrix_from_arrangement(arr)[:2] == "0F"


# ============================================================ named predicates


@pytest.mark.parametrize(
    ("a", "b", "true"),
    [
        (SQ, "POINT (1 1)", {"intersects", "contains", "covers"}),
        (SQ, "POINT (0 1)", {"intersects", "touches", "covers"}),
        (SQ, "LINESTRING (1 1, 3 1)", {"intersects", "contains", "covers"}),
        (SQ, "LINESTRING (1 1, 5 1)", {"intersects", "crosses"}),
        ("LINESTRING (1 1, 5 1)", SQ, {"intersects", "crosses"}),
        (SQ, "LINESTRING (0 0, 4 0)", {"intersects", "touches", "covers"}),
        (SQ, "POLYGON ((2 2, 6 2, 6 6, 2 6, 2 2))", {"intersects", "overlaps"}),
        (SQ, "POLYGON ((4 0, 6 0, 6 4, 4 4, 4 0))", {"intersects", "touches"}),
        (SQ, "POLYGON ((0 0, 0 4, 4 4, 4 0, 0 0))",
         {"intersects", "contains", "covers", "within", "covered_by", "equals"}),
        ("LINESTRING (0 0, 2 2)", "LINESTRING (0 2, 2 0)", {"intersects", "crosses"}),
        ("LINESTRING (0 0, 2 0)", "LINESTRING (1 0, 3 0)", {"intersects", "overlaps"}),
        ("LINESTRING (0 0, 2 0)", "LINESTRING (2 0, 0 0)",
         {"intersects", "contains", "covers", "within", "covered_by", "equals"}),
        ("MULTIPOINT ((0 0), (1 1))", "MULTIPOINT ((1 1), (2 2))", {"intersects", "overlaps"}),
        ("POINT (0 0)", "POINT (5 5)", {"disjoint"}),
        ("POINT (0 0)", "POINT (0 0)",
         {"intersects", "contains", "covers", "within", "covered_by", "equals"}),
        # a zero-length line is a point: equals holds across the type
        ("LINESTRING (1 1, 1 1)", "POINT (1 1)",
         {"intersects", "contains", "covers", "within", "covered_by", "equals"}),
    ],
)  # fmt: skip
def test_named_predicates(a, b, true):
    res = relate(W(a), W(b), strict=True)
    assert {k for k, v in res.predicates.items() if v} == true
    assert list(res.predicates) == list(PREDICATE_NAMES)
    assert res.predicates == predicates(res.matrix, res.dim_a, res.dim_b)
    assert all(res.predicate_values[k].value == v for k, v in res.predicates.items())
    assert res.conventions == []


def test_empty_conventions_are_tagged():
    res = relate(W("POINT EMPTY"), W("LINESTRING EMPTY"), strict=True)
    assert res.matrix == "FFFFFFFF2"
    assert res.predicates["equals"] is True and res.predicates["disjoint"] is True
    assert res.predicate_values["equals"].convention
    assert res.predicate_values["equals"].matrix_value is False
    assert res.conventions == [
        "predicates.contains",
        "predicates.covers",
        "predicates.within",
        "predicates.covered_by",
        "predicates.equals",
    ]
    one = relate(W(SQ), W("POLYGON EMPTY"), strict=True)
    assert one.matrix == "FF2FF1FF2"
    assert one.conventions == ["predicates.contains", "predicates.covers"]
    assert one.predicates["contains"] is False and one.predicates["equals"] is False


def test_real_dimensions_drive_the_dispatch():
    # a zero-length line has real dimension 0: L/P dispatch becomes P/P
    res = relate(W("LINESTRING (1 1, 1 1)"), W("MULTIPOINT ((1 1), (2 2))"), strict=True)
    assert (res.dim_a, res.dim_b, res.type_dim_a, res.type_dim_b) == (0, 0, 1, 0)
    assert res.predicates["within"] and not res.predicates["touches"]
    # RelateNG's quirk: an empty polygon keeps a zero-length line at real dimension 1
    gc = GeometryCollection([Polygon(), LineString([(1.0, 1.0), (1.0, 1.0)])])
    assert gc.real_dimension == 1 and effective_dimension(gc) == 0
    res = relate(gc, W("POINT (1 1)"), strict=True)
    assert res.matrix == "0FFFFFFF2" and res.dim_a == 1 and res.status == STATUS_OK


# ============================================================ assertions


@pytest.mark.parametrize(
    ("wkt", "dim"),
    [
        ("POINT EMPTY", -1),
        ("GEOMETRYCOLLECTION (POLYGON EMPTY, POINT EMPTY)", -1),
        ("POINT (1 2)", 0),
        ("LINESTRING (1 1, 1 1)", 0),
        ("LINESTRING (1 1, 2 1)", 1),
        ("MULTILINESTRING ((1 1, 1 1), (0 0, 1 0))", 1),
        ("GEOMETRYCOLLECTION (POINT (0 0), POLYGON ((0 0, 1 0, 1 1, 0 0)))", 2),
    ],
)
def test_effective_dimension(wkt, dim):
    assert effective_dimension(W(wkt)) == dim


def test_matrix_sanity_accepts_every_correct_matrix():
    for a, b, m in HAND_CASES:
        ga, gb = W(a), W(b)
        assert matrix_sanity(m, effective_dimension(ga), effective_dimension(gb)) == [], (a, b)


@pytest.mark.parametrize(
    ("matrix", "da", "db", "fragment"),
    [
        ("212101211", 2, 2, "EE is 1"),
        ("FF1FF0212", 2, 2, "interior of A"),  # a non-empty areal A met by nothing at dim 2
        ("2FFF0FFF2", 2, 2, "boundary has dimension 0"),
        ("1FFF1FFF2", 1, 1, "BB"),  # a line's boundary is a finite point set
        ("0F2FF1FF2", 0, 2, "BE"),  # a point set has no boundary
        ("FFFFFFFF2", 0, -1, "interior of A"),
        ("FF0FFFFF2", -1, 0, "IE"),
        ("2F2FF1FF2", 2, 1, "II = 2 exceeds"),
    ],
)
def test_matrix_sanity_rejects(matrix, da, db, fragment):
    problems = matrix_sanity(matrix, da, db)
    assert any(fragment in p for p in problems), problems


def test_areal_operand_always_meets_something_at_dimension_2():
    rng = random.Random(5)
    from unit.witness_lattice import random_pair

    for i in range(200):
        _, _, a, b = random_pair(rng, i)
        res = relate(a, b, strict=True)
        for g, idx in ((a, (0, 1, 2)), (b, (0, 3, 6))):
            if effective_dimension(g) == 2:
                assert "2" in {res.matrix[k] for k in idx}


def test_transpose_assertion_catches_an_inconsistent_second_build(monkeypatch):
    calls = []
    real = R.build_arrangement

    def fake(a, b, **kw):
        arr = real(a, b, **kw)
        calls.append(arr)
        if len(calls) == 2:  # corrupt the swapped arrangement: a face becomes II
            f = next(f for f in range(1, arr.num_faces) if arr.face_loc_a[f] == 0)
            arr.face_loc_b[f] = 0
        return arr

    monkeypatch.setattr(R, "build_arrangement", fake)
    a, b = W(SQ), W("POLYGON ((8 8, 9 8, 9 9, 8 8))")
    res = relate(a, b)
    assert res.status == STATUS_ERROR and "not the transpose" in res.reason
    assert res.matrix is None and res.predicates is None
    calls.clear()
    with pytest.raises(RelateAssertionError, match="transpose"):
        relate(a, b, strict=True)
    calls.clear()
    assert relate(a, b, transpose_check=False).status == STATUS_OK


def test_sanity_assertion_catches_a_mislabelled_arrangement(monkeypatch):
    real = R.build_arrangement

    def fake(a, b, **kw):
        arr = real(a, b, **kw)
        for f in range(arr.num_faces):  # A's interior vanishes
            arr.face_loc_a[f] = int(Location.EXTERIOR)
        return arr

    monkeypatch.setattr(R, "build_arrangement", fake)
    res = relate(W(SQ), W("POINT (9 9)"), transpose_check=False)
    assert res.status == STATUS_ERROR
    assert "RelateAssertionError" in res.reason and "interior of A" in res.reason


def test_engine_exceptions_become_engine_error(monkeypatch):
    def boom(a, b, **kw):
        raise ArrangementError(["T4: broken"])

    monkeypatch.setattr(R, "build_arrangement", boom)
    res = relate(W(SQ), W("POINT (1 1)"))
    assert res.status == STATUS_ERROR and res.reason.startswith("ArrangementError")
    assert res.to_json()["status"] == "engine_error" and "relate" not in res.to_json()
    with pytest.raises(ArrangementError):
        relate(W(SQ), W("POINT (1 1)"), strict=True)
    with pytest.raises(RuntimeError, match="engine_error"):
        relate_matrix(W(SQ), W("POINT (1 1)"))


def test_memory_error_is_engine_skipped(monkeypatch):
    def oom(a, b, **kw):
        raise MemoryError

    monkeypatch.setattr(R, "build_arrangement", oom)
    res = relate(W(SQ), W("POINT (1 1)"), strict=True)
    assert res.status == STATUS_SKIPPED and res.reason == "out of memory"


# ============================================================ budget and statuses


def test_size_budget_gives_engine_skipped():
    a, b = comb(12), comb(12).map_coords(lambda c: (c[1] + 1.5, c[0] - 3))
    res = relate(a, b, budget=Budget(max_size=100))
    assert res.status == STATUS_SKIPPED and not res.ok
    assert "size" in res.reason
    assert res.matrix is None and res.predicates is None
    rec = res.to_json()
    assert rec["status"] == "engine_skipped" and rec["reason"] == res.reason
    assert "relate" not in rec and "predicates" not in rec
    assert rec["dimensions"]["a"] == {"dimension": 2, "real_dimension": 2}
    with pytest.raises(RuntimeError, match="engine_skipped"):
        relate_matrix(a, b, budget=Budget(max_size=100))
    # unlimited: the same case is answered (and both routes agree)
    from geotruth.relate_witness import relate as witness

    assert relate(a, b, budget=None, strict=True).matrix == witness(a, b) == "212111212"


def test_time_budget_gives_engine_skipped():
    a, b = comb(6), comb(6).map_coords(lambda c: (c[1] + 1.5, c[0] - 3))
    res = relate(a, b, budget=Budget(max_seconds=1e-9))
    assert res.status == STATUS_SKIPPED and "time" in res.reason


def test_time_budget_is_shared_by_the_transposed_build(monkeypatch):
    real = R.build_arrangement
    seen = []

    def spy(a, b, *, budget, **kw):
        seen.append(budget)
        return real(a, b, budget=budget, **kw)

    monkeypatch.setattr(R, "build_arrangement", spy)
    res = relate(W(SQ), W("POINT (1 1)"), budget=Budget(max_seconds=50.0))
    assert res.ok
    assert seen[0].max_seconds == 50.0 and 0 < seen[1].max_seconds < 50.0
    assert seen[1].max_size == seen[0].max_size


def test_exhausted_time_before_the_transposed_build(monkeypatch):
    class Clock:  # relate's own clock: 0 at the start, 10 s later afterwards
        calls = 0

        @classmethod
        def perf_counter(cls) -> float:
            cls.calls += 1
            return 0.0 if cls.calls == 1 else 10.0

    monkeypatch.setattr(R, "time", Clock)
    res = relate(W(SQ), W("POINT (1 1)"), budget=Budget(max_seconds=5.0))
    assert res.status == STATUS_SKIPPED and "transpose" in res.reason


def test_invalid_input_raises():
    with pytest.raises(InvalidInputError, match="not closed"):
        relate(Polygon([[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)]]), W("POINT (0 0)"))
    with pytest.raises(InvalidInputError, match="coordinate"):
        relate(W("POINT (NaN 1)"), W("POINT (0 0)"))
    with pytest.raises(InvalidInputError, match="zero area"):
        relate(W("POLYGON ((0 0, 2 2, 2 0, 0 2, 0 0))"), W("POINT (1 1)"))
    # a ring folding back on itself inside its own interior (an inward spike) has no
    # defined sides: the coverage count would say Interior, even-odd location Boundary
    spike = "POLYGON ((2 6, 2 2, 0 0, 6 2, 6 4, 2 4, 6 4, 2 6))"
    for a, b in ((spike, "POINT (4 4)"), ("POINT (4 4)", spike)):
        with pytest.raises(InvalidInputError, match="lies twice on the rings of polygon"):
            relate(W(a), W(b))
    # identical polygons as two GC elements are valid (union semantics): still answered
    twice = "GEOMETRYCOLLECTION (POLYGON ((0 0, 2 0, 2 2, 0 0)), POLYGON ((0 0, 2 0, 2 2, 0 0)))"
    assert relate(W(twice), W("POINT (1 0)"), strict=True).matrix == "FF20F1FF2"
    # the transposed build refuses too: invalid input never becomes engine_error
    with pytest.raises(InvalidInputError):
        relate(W("POINT (0 0)"), W("POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0), (5 5, 6 5, 6 6, 5 5))"))


# ============================================================ result object


def test_result_accessors_and_json():
    res = relate(W(SQ), W("LINESTRING (2 2, 6 2)"), keep_arrangement=True, strict=True)
    assert res.ok and res.relate == res.matrix == "1020F1102"
    assert res.entry("II") == 1 and res.entry("bi") == 0 and res.entry("BB") == -1
    assert res.matches("T*T******") and not res.matches("T*F**F***")
    rec = res.to_json()
    assert rec == {
        "status": "ok",
        "dimensions": {
            "a": {"dimension": 2, "real_dimension": 2},
            "b": {"dimension": 1, "real_dimension": 1},
        },
        "relate": "1020F1102",
        "predicates": res.predicates,
        "conventions": [],
    }
    assert set(res.stats) >= {"V", "E", "F", "t_total", "t_transpose", "t_relate"}
    cells = res.realizers()
    assert list(cells) == [n for n in ENTRY_NAMES if res.entry(n) >= 0]
    for name, c in cells.items():
        assert c.dim == res.entry(name)
        assert (int(c.loc_a), int(c.loc_b)) == ("IBE".index(name[0]), "IBE".index(name[1]))
    arr = res.arrangement
    assert describe_cell(arr, cells["IB"]) == "vertex (2 2)"
    assert describe_cell(arr, cells["BI"]) == "vertex (4 2)"
    assert describe_cell(arr, cells["EE"]) == "the unbounded face"
    assert describe_cell(arr, cells["II"]) in ("edge (2 2)-(4 2)", "edge (4 2)-(2 2)")
    assert describe_cell(arr, cells["IE"]).startswith("face left of ")
    with pytest.raises(ValueError, match="kept"):
        relate(W(SQ), W("POINT (1 1)")).realizers()


def test_describe_cell_uses_exact_rationals():
    res = relate(W("LINESTRING (0 0, 3 1)"), W("LINESTRING (0 1, 2 0)"), keep_arrangement=True)
    cells = cell_realizers(res.arrangement)
    assert describe_cell(res.arrangement, cells["II"]) == "vertex (6/5 2/5)"
    assert res.matrix == "0F1FF0102"


def test_expected_record_validates_against_the_schema():
    pytest.importorskip("jsonschema")
    from geotruth import ENGINE_VERSION, schemas
    from geotruth.validity import validate

    for a, b in ((SQ, "POINT (1 1)"), ("POINT EMPTY", "POLYGON EMPTY")):
        ga, gb = W(a), W(b)
        rec = {
            "id": "unit-1",
            "engine": {"version": ENGINE_VERSION},
            **relate(ga, gb).to_json(),
            "validity": {"a": validate(ga).to_json(), "b": validate(gb).to_json()},
        }
        schemas.validate("expected", rec)
    skipped = relate(comb(8), comb(8, 1), budget=Budget(max_size=10)).to_json()
    schemas.validate("expected", {"id": "unit-2", "engine": {"version": ENGINE_VERSION},
                                  **skipped})  # fmt: skip


# ============================================================ exactness and invariance


def test_rational_and_extreme_coordinates():
    third = Fraction(1, 3)
    a = Polygon([[(0, 0), (third, 0), (third, third), (0, third), (0, 0)]])
    b = LineString([(Fraction(1, 6), Fraction(1, 6)), (Fraction(1, 2), Fraction(1, 6))])
    assert relate(a, b, strict=True).matrix == "1020F1102"
    tiny = W(SQ).map_coords(lambda c: (c[0] * 2.0**-1070, c[1] * 2.0**-1070))
    on_edge = W("POINT (4 2)").map_coords(lambda c: (c[0] * 2.0**-1070, c[1] * 2.0**-1070))
    assert relate(tiny, on_edge, strict=True).matrix == "FF20F1FF2"
    big = W(SQ).map_coords(lambda c: (c[0] * 1e300, c[1] * 1e300))
    assert relate(big, W("POINT (5e-324 5e-324)"), strict=True).matrix == "0F2FF1FF2"


def test_affine_invariance_on_random_cases():
    from unit.witness_lattice import random_pair

    rng = random.Random(11)
    for i in range(120):
        _, _, a, b = random_pair(rng, i)
        m = relate(a, b, strict=True).matrix

        def f(c):
            x, y = Fraction(c[0]), Fraction(c[1])
            return (2 * x - y / 3 + Fraction(1, 7), x / 5 + y)

        assert relate(a.map_coords(f), b.map_coords(f), strict=True).matrix == m


def test_deterministic():
    a = W("GEOMETRYCOLLECTION (POLYGON ((0 0, 3 0, 3 3, 0 3, 0 0)), LINESTRING (1 1, 5 1))")
    b = W("MULTIPOLYGON (((1 -1, 2 -1, 2 4, 1 4, 1 -1)), ((5 5, 6 5, 6 6, 5 5)))")
    first = relate(a, b, strict=True)
    for _ in range(3):
        again = relate(a, b, strict=True)
        assert (again.matrix, again.predicates) == (first.matrix, first.predicates)


def test_agrees_with_the_arrangement_built_directly():
    rng = random.Random(2)
    from unit.witness_lattice import random_pair

    for i in range(64):
        _, _, a, b = random_pair(rng, i)
        assert relate(a, b, strict=True).matrix == matrix_from_arrangement(build_arrangement(a, b))


def test_measures_uses_this_engine():
    from geotruth import measures

    assert measures.engine_backends()["relate"] == "geotruth.relate"
    preds = measures.relate_predicates(W(SQ), W("POLYGON ((2 2, 6 2, 6 6, 2 6, 2 2))"))
    assert preds["overlaps"] is True and preds["within"] is False


def test_point_and_empty_operands():
    assert relate(Point(), Point(), strict=True).matrix == "FFFFFFFF2"
    assert relate(W("GEOMETRYCOLLECTION EMPTY"), W(SQ), strict=True).matrix == "FFFFFF212"
    assert relate(W("MULTIPOINT ((1 1), (1 1))"), W(SQ), strict=True).matrix == "0FFFFF212"
