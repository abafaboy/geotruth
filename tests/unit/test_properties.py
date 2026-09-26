"""Hypothesis property tests of the primitives (skipped without hypothesis).

Exact transforms must commute with the primitives: translating, scaling by a positive
integer, swapping x/y or negating coordinates changes orientation and intersection
results in exactly the predictable way.
"""

from __future__ import annotations

from fractions import Fraction

import pytest

hypothesis = pytest.importorskip("hypothesis", reason="hypothesis not installed")
from hypothesis import assume, given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

from geotruth import exact as X  # noqa: E402
from geotruth.io import format_double, read_wkt, to_wkt  # noqa: E402
from geotruth.numbers import DyadicScale  # noqa: E402

small = st.integers(-6, 6)
big = st.integers(-(2**70), 2**70)
pt_small = st.tuples(small, small)
pt_big = st.tuples(big, big)
pt_any = st.one_of(pt_small, pt_big)
finite = st.floats(allow_nan=False, allow_infinity=False)


def _fr(hp):
    return (Fraction(hp[0], hp[2]), Fraction(hp[1], hp[2]))


def _map(result, fn):
    return [fn(_fr(p)) for p in result.points]


@given(pt_any, pt_any, pt_any, pt_any, pt_small, st.integers(1, 1000))
def test_intersection_commutes_with_affine_maps(a, b, c, d, t, k):
    r = X.intersect_segments(a, b, c, d)

    def tr(p):
        return (k * p[0] + t[0], k * p[1] + t[1])

    r2 = X.intersect_segments(tr(a), tr(b), tr(c), tr(d))
    assert r2.kind == r.kind
    assert [_fr(p) for p in r2.points] == _map(r, tr)


@given(pt_any, pt_any, pt_any, pt_any)
def test_intersection_under_reflection_and_swap(a, b, c, d):
    r = X.intersect_segments(a, b, c, d)

    def swap(p):
        return (p[1], p[0])

    def neg(p):
        return (-p[0], p[1])

    for f in (swap, neg):
        r2 = X.intersect_segments(f(a), f(b), f(c), f(d))
        assert r2.kind == r.kind and [_fr(p) for p in r2.points] == _map(r, f)
    # argument order: same point set; overlap direction follows the first segment
    r3 = X.intersect_segments(c, d, a, b)
    assert r3.kind == r.kind and set(r3.points) == set(r.points)
    r4 = X.intersect_segments(b, a, c, d)
    assert list(r4.points) == list(reversed(r.points)) or r.kind != X.OVERLAP


@given(pt_any, pt_any, pt_any)
def test_orient_transforms(a, b, c):
    o = X.orient(a, b, c)
    assert X.orient(b, c, a) == o and X.orient(a, c, b) == -o
    assert X.orient((a[1], a[0]), (b[1], b[0]), (c[1], c[0])) == -o  # a reflection


@given(pt_any, pt_any, pt_any, pt_any)
def test_intersection_point_lies_on_both_segments(a, b, c, d):
    r = X.intersect_segments(a, b, c, d)
    for p in r.points:
        assert X.hp_on_segment(p, a, b) and X.hp_on_segment(p, c, d)


@given(st.lists(finite, min_size=4, max_size=4))
def test_scaled_double_segments(vals):
    """Doubles -> integers -> intersection -> back to rationals equals Fraction math."""
    scale = DyadicScale.for_values(vals)
    a, b = scale.to_point(vals[0], vals[1]), scale.to_point(vals[2], vals[3])
    assume(a != b)
    r = X.intersect_segments(a, b, a, b)
    assert r.kind == X.OVERLAP
    assert [scale.hpoint_to_fractions(p) for p in r.points] == [
        (Fraction(vals[0]), Fraction(vals[1])),
        (Fraction(vals[2]), Fraction(vals[3])),
    ]


@given(
    st.tuples(small, small).filter(lambda v: v != (0, 0)),
    st.tuples(small, small).filter(lambda v: v != (0, 0)),
    st.integers(1, 50),
)
def test_angle_cmp_is_scale_invariant(u, v, k):
    assert X.angle_cmp(u, v) == X.angle_cmp((k * u[0], k * u[1]), v)
    assert X.angle_cmp(u, v) == -X.angle_cmp(v, u)


@given(finite)
def test_format_double_round_trips(x):
    assert float(format_double(x)) == x
    assert float(format_double(x, trim=True)) == x


@given(finite, finite)
def test_wkt_point_round_trip(x, y):
    g = read_wkt(to_wkt(read_wkt(f"POINT ({format_double(x)} {format_double(y)})")))
    assert g.coord == (x, y)
