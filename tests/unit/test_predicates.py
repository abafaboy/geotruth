"""Unit tests of the dimension-dispatched named predicates and the convention table."""

from __future__ import annotations

import itertools

import pytest

from geotruth.predicates import (
    CONVENTIONS,
    PREDICATE_NAMES,
    contains,
    contains_properly,
    convention_fields,
    covered_by,
    covers,
    crosses,
    disjoint,
    equals,
    evaluate,
    intersects,
    matrix_dim,
    matrix_problems,
    overlaps,
    predicate,
    predicates,
    relate_pattern,
    touches,
    transpose,
    validate_matrix,
    validate_pattern,
    within,
)

P, L, A, EMPTY = 0, 1, 2, -1
DIMS = (EMPTY, P, L, A)


# ========================================================================= patterns


@pytest.mark.parametrize(
    ("matrix", "pattern", "expected"),
    [
        ("212101212", "T*T***T**", True),
        ("212101212", "T*F**FFF*", False),
        ("212101212", "212101212", True),
        ("212101212", "*********", True),
        ("FF2FF1212", "FF*FF****", True),
        ("0FFFFFFF2", "0********", True),
        ("1FFFFFFF2", "0********", False),
        ("1FFFFFFF2", "T********", True),
        ("FFFFFFFF2", "F********", True),
        ("2FFF1FFF2", "t*f**fff*", True),  # lower-case T/F accepted
        ("2fff1fff2", "T*F**FFF*", True),  # lower-case f in the matrix accepted
    ],
)
def test_relate_pattern(matrix, pattern, expected):
    assert relate_pattern(matrix, pattern) is expected


@pytest.mark.parametrize("bad", ["", "21210121", "2121012122", "21210121X", "T12101212", 212101212])
def test_bad_matrix(bad):
    with pytest.raises((ValueError, TypeError)):
        validate_matrix(bad)


@pytest.mark.parametrize("bad", ["", "T*T***T*", "T*T***T*X", "T*T***T*3", None])
def test_bad_pattern(bad):
    with pytest.raises((ValueError, TypeError)):
        validate_pattern(bad)


def test_transpose_and_entries():
    assert transpose("012F12FF2") == "0FF11F222"
    assert transpose(transpose("212101212")) == "212101212"
    m = "0F1FF0102"
    assert matrix_dim(m, 0, 0) == 0
    assert matrix_dim(m, 0, 1) == -1
    assert matrix_dim(m, 2, 2) == 2
    assert matrix_dim(m, 1, 2) == 0


# ======================================================= dimension-dispatched rules


def test_crosses_dispatch_table():
    m_ii_ie = "1F1FFFFF2"  # T*T****** but not T*****T**
    m_ii_ei = "1FFFFF1F2"  # T*****T** but not T*T******
    for da, db in [(P, L), (P, A), (L, A)]:
        assert crosses(m_ii_ie, da, db)
        assert not crosses(m_ii_ei, da, db)
    for da, db in [(L, P), (A, P), (A, L)]:
        assert crosses(m_ii_ei, da, db)
        assert not crosses(m_ii_ie, da, db)
    # L/L: II must be exactly 0 (lines crossing at a point)
    assert crosses("0F1FF0102", L, L)
    assert not crosses("1F1FF0102", L, L)
    # every other pair: false
    for da, db in [(P, P), (A, A), (EMPTY, L), (L, EMPTY), (EMPTY, EMPTY)]:
        assert not crosses("212101212", da, db)
        assert not crosses("0F1FF0102", da, db)


def test_polygon_containing_line_does_not_cross():
    # design review: a polygon with a line inside matches T*T****** but A/L uses T*****T**
    assert relate_pattern("102FF1FF2", "T*T******")
    assert not crosses("102FF1FF2", A, L)
    assert not crosses("1FF0FF212", L, A)


def test_overlaps_dispatch_table():
    assert overlaps("0F0FFF0F2", P, P)
    assert overlaps("212101212", A, A)
    assert overlaps("1010F0102", L, L)
    assert not overlaps("0F1FF0102", L, L)  # lines crossing at a point do not overlap
    for da, db in [(P, L), (L, P), (P, A), (A, P), (L, A), (A, L), (EMPTY, A)]:
        assert not overlaps("212101212", da, db)


def test_touches_dispatch_table():
    assert not touches("FF0FFF0F2", P, P)
    assert not touches("F0FFFF0F2", P, P)  # P/P touches is always false
    assert touches("FF2F11212", A, A)
    assert touches("F0FFFF102", P, L)
    assert touches("FF1F00102", L, L)
    assert touches("FF2F01212", A, A)
    assert touches("F01FF0212", L, A)
    assert touches("FF2F01102", A, L)
    assert not touches("FF2FF1212", A, A)  # disjoint
    assert not touches("212101212", A, A)  # interiors meet
    assert not touches("FFFFFFFF2", EMPTY, EMPTY)


def test_equals_requires_equal_dimensions():
    assert equals("2FFF1FFF2", A, A)
    assert equals("0FFFFFFF2", P, P)
    assert not equals("0FFFFFFF2", P, L)
    assert not equals("2FFF1FFF2", A, L)
    assert not equals("FFFFFFFF2", EMPTY, EMPTY)  # the matrix rule; see the conventions


def test_containment_family():
    m = "212FF1FF2"  # A contains B strictly inside
    assert contains(m) and covers(m) and contains_properly(m)
    assert not within(m) and not covered_by(m)
    mt = transpose(m)
    assert within(mt) and covered_by(mt) and not contains(mt)
    # covers without contains: B lies in A's boundary (a line covering a point at its end)
    m = "FF1F0FFF2"
    assert covers(m) and not contains(m)
    assert covered_by(transpose(m)) and not within(transpose(m))
    # contains_properly fails when B touches A's boundary
    assert contains("212F11FF2") and not contains_properly("212F11FF2")


def test_intersects_disjoint():
    assert disjoint("FF2FF1212") and not intersects("FF2FF1212")
    for m in ("FF2F01212", "0FFFFFFF2", "F0FFFFFF2", "FFFF0FFF2", "FFF0FFFF2"):
        assert intersects(m) and not disjoint(m)


def test_predicate_by_name():
    assert predicate("overlaps", "212101212", A, A)
    assert predicate("contains_properly", "212FF1FF2", A, A)
    with pytest.raises(KeyError):
        predicate("nearby", "212101212", A, A)
    with pytest.raises(ValueError):
        predicate("crosses", "212101212", 3, A)


# ================================================================ convention table


def test_equals_empty_empty_is_a_convention():
    res = evaluate("FFFFFFFF2", EMPTY, EMPTY)
    eq = res["equals"]
    assert eq.value is True and eq.matrix_value is False
    assert eq.convention and eq.alternative is False and "RelateNG" in eq.note
    assert bool(eq) is True


def test_empty_containment_conventions():
    # B empty: contains/covers are conventions; A empty: within/covered_by
    res = evaluate("FF2FF1FF2", A, EMPTY)
    assert {k for k, v in res.items() if v.convention} == {"contains", "covers"}
    assert res["contains"].value is False and res["contains"].alternative is True
    assert res["equals"].value is False and not res["equals"].convention
    res = evaluate("FFFFFF212", EMPTY, A)
    assert {k for k, v in res.items() if v.convention} == {"within", "covered_by"}
    res = evaluate("FFFFFFFF2", EMPTY, EMPTY)
    assert {k for k, v in res.items() if v.convention} == {
        "contains",
        "covers",
        "within",
        "covered_by",
        "equals",
    }


def test_non_empty_has_no_conventions():
    for da, db in itertools.product((P, L, A), repeat=2):
        assert convention_fields(da, db) == []
        assert not any(v.convention for v in evaluate("FF0FFF0F2", da, db).values())


def test_convention_fields():
    assert convention_fields(EMPTY, EMPTY) == [
        "predicates.contains",
        "predicates.covers",
        "predicates.within",
        "predicates.covered_by",
        "predicates.equals",
    ]
    assert convention_fields(L, EMPTY) == ["predicates.contains", "predicates.covers"]
    assert convention_fields(EMPTY, P) == ["predicates.within", "predicates.covered_by"]


def test_convention_values_are_geos_3_13_values():
    # the reported values of every convention entry (checked against GEOS 3.13.1 in the
    # crosscheck suite): true only for equals(EMPTY, EMPTY)
    for c in CONVENTIONS:
        assert c.value is (c.predicate == "equals")
        assert c.alternative is (not c.value)


@pytest.mark.parametrize(
    ("matrix", "da", "db"),
    [
        ("FFFFFFFF2", EMPTY, EMPTY),
        ("FFFFFF0F2", EMPTY, P),
        ("FFFFFF102", EMPTY, L),
        ("FFFFFF212", EMPTY, A),
        ("FF0FFFFF2", P, EMPTY),
        ("FF1FF0FF2", L, EMPTY),
        ("FF2FF1FF2", A, EMPTY),
    ],
)
def test_empty_predicate_row_matches_geos(matrix, da, db):
    # Shapely 2.1.2 / GEOS 3.13.1 (relate and the named predicates) for these pairs:
    # everything false except disjoint, and equals for empty/empty
    got = predicates(matrix, da, db)
    want = {k: k == "disjoint" or (k == "equals" and da == db == EMPTY) for k in got}
    assert got == want
    assert matrix_problems(matrix, da, db) == []


def test_evaluate_names_and_schema_order():
    res = evaluate("212101212", A, A)
    assert tuple(res) == PREDICATE_NAMES
    assert predicates("212101212", A, A) == {
        "intersects": True,
        "disjoint": False,
        "touches": False,
        "crosses": False,
        "overlaps": True,
        "contains": False,
        "covers": False,
        "within": False,
        "covered_by": False,
        "equals": False,
    }
    extra = evaluate("212FF1FF2", A, A, names=("contains_properly",))
    assert extra["contains_properly"].value is True


# ================================================================ matrix problems


@pytest.mark.parametrize(
    ("matrix", "da", "db"),
    [
        ("212101212", A, A),
        ("FF2FF1212", A, A),
        ("0F1FF0102", L, L),
        ("0FFFFFFF2", P, P),
        ("FFFFFFFF2", EMPTY, EMPTY),
        ("FFFFFF212", EMPTY, A),
        ("FF1FF0FF2", L, EMPTY),
        ("1FFF0FFF2", L, L),  # equal lines
    ],
)
def test_consistent_matrices_have_no_problems(matrix, da, db):
    assert matrix_problems(matrix, da, db) == []


@pytest.mark.parametrize(
    ("matrix", "da", "db", "fragment"),
    [
        ("212101211", A, A, "EE"),
        ("0FFFFFFF2", EMPTY, P, "A is empty"),
        ("0FFFFFFF2", P, EMPTY, "B is empty"),
        ("1FFFFFFF2", P, L, "A has real dimension 0"),
        ("FFFFFFFF2", A, EMPTY, "A has real dimension 2"),
    ],
)
def test_inconsistent_matrices(matrix, da, db, fragment):
    problems = matrix_problems(matrix, da, db)
    assert problems and any(fragment in p for p in problems), problems


def test_transpose_swaps_asymmetric_predicates():
    # contains(A,B) == within(B,A), covers == covered_by, symmetric ones unchanged
    mats = ["212FF1FF2", "FF1F0FFF2", "212101212", "0F1FF0102", "FF2F11212", "1020F1102"]
    for m, (da, db) in itertools.product(mats, itertools.product((P, L, A), repeat=2)):
        f, r = predicates(m, da, db), predicates(transpose(m), db, da)
        assert f["contains"] == r["within"] and f["covers"] == r["covered_by"]
        for k in ("intersects", "disjoint", "touches", "crosses", "overlaps", "equals"):
            assert f[k] == r[k], (m, da, db, k)
