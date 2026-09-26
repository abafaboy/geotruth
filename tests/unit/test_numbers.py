"""Unit tests for geotruth.numbers: float semantics, exact rationals, dyadic scaling."""

from __future__ import annotations

import json
import math
import random
import struct
from fractions import Fraction

import pytest

from geotruth import numbers as N
from geotruth.numbers import DyadicScale, NonFiniteError

TWO53 = 2**53
MAX = 1.7976931348623157e308
MIN_SUB = 5e-324


def random_double(rng: random.Random) -> float:
    """A random finite double over the whole range (uniform bit patterns)."""
    while True:
        (x,) = struct.unpack("<d", rng.getrandbits(64).to_bytes(8, "little"))
        if math.isfinite(x):
            return x


def mixed_doubles(rng: random.Random, n: int) -> list[float]:
    out = []
    for _ in range(n):
        kind = rng.random()
        if kind < 0.3:
            out.append(random_double(rng))
        elif kind < 0.6:
            out.append(rng.uniform(-1e3, 1e3))
        elif kind < 0.8:
            out.append(float(rng.randint(-(2**60), 2**60)))
        else:
            out.append(
                rng.choice(
                    [
                        0.0,
                        -0.0,
                        MIN_SUB,
                        -MIN_SUB,
                        MAX,
                        -MAX,
                        0.1,
                        0.30000000000000004,
                        2.2250738585072014e-308,
                    ]
                )
            )
    return out


# ------------------------------------------------------------------ float semantics


class TestAsDouble:
    def test_integers_round_like_doubles(self):
        assert N.as_double(TWO53 + 1) == float(TWO53)  # ties to even
        assert N.as_double(TWO53 + 3) == float(TWO53 + 4)
        assert N.as_double(-(TWO53 + 1)) == -float(TWO53)
        assert N.as_double(7) == 7.0 and isinstance(N.as_double(7), float)

    def test_int_matches_strtod_of_the_literal(self):
        rng = random.Random(1)
        for _ in range(2000):
            n = rng.randint(-(2**80), 2**80)
            assert N.as_double(n) == float(str(n))

    def test_huge_integers_become_infinite(self):
        assert N.as_double(10**400) == math.inf
        assert N.as_double(-(10**400)) == -math.inf

    def test_floats_pass_through(self):
        assert math.copysign(1.0, N.as_double(-0.0)) == -1.0
        assert math.isnan(N.as_double(math.nan))
        assert N.as_double(MIN_SUB) == MIN_SUB

    def test_strings(self):
        assert N.as_double("1e400") == math.inf
        assert N.as_double("9007199254740993") == float(TWO53)
        assert math.isnan(N.as_double("NaN"))

    @pytest.mark.parametrize("bad", [True, None, [1], Fraction(1, 3)])
    def test_rejects_non_numbers(self, bad):
        with pytest.raises(TypeError):
            N.as_double(bad)


class TestJsonLoads:
    def test_integers_stay_exact(self):
        obj = N.json_loads('{"id": 12, "x": 9007199254740993}')
        assert obj["id"] == 12 and isinstance(obj["id"], int)
        assert obj["x"] == TWO53 + 1  # exact; float semantics come from as_double
        assert N.as_double(obj["x"]) == float(TWO53)

    def test_giant_integer_literal_does_not_raise(self):
        text = "[" + "9" * 5000 + "]"
        with pytest.raises(ValueError):
            json.loads(text)  # the stdlib refuses (int max str digits)
        assert N.json_loads(text) == [math.inf]
        assert N.json_loads("[-" + "9" * 5000 + "]") == [-math.inf]

    def test_nonfinite_tokens(self):
        a, b, c = N.json_loads("[NaN, Infinity, -Infinity]")
        assert math.isnan(a) and b == math.inf and c == -math.inf

    def test_floats(self):
        assert N.json_loads("[1e400, 0.30000000000000004]") == [math.inf, 0.30000000000000004]


def test_finiteness_flags():
    assert N.is_finite(1.0) and not N.is_finite(math.nan) and not N.is_finite(-math.inf)
    assert N.all_finite([0.0, MAX, MIN_SUB])
    assert not N.all_finite([0.0, math.inf])


# -------------------------------------------------------------------- backends


class TestBackends:
    def test_default_backend_and_env_override(self, monkeypatch):
        monkeypatch.delenv("GEOTRUTH_RATIONAL", raising=False)
        assert N._default_backend() == ("gmpy2" if N.HAVE_GMPY2 else "fractions")
        monkeypatch.setenv("GEOTRUTH_RATIONAL", "fractions")
        assert N._default_backend() == "fractions"
        monkeypatch.setenv("GEOTRUTH_RATIONAL", "bogus")
        with pytest.raises(ValueError, match="GEOTRUTH_RATIONAL"):
            N._default_backend()

    def test_use_backend_restores(self):
        before = N.get_backend()
        with N.use_backend("fractions"):
            assert N.get_backend() == "fractions"
            assert isinstance(N.rational(1, 3), Fraction)
            assert N.rational_type() is Fraction
        assert N.get_backend() == before

    def test_unknown_backend(self):
        with pytest.raises(ValueError, match="unknown rational backend"):
            N.set_backend("decimal")

    @pytest.mark.skipif(not N.HAVE_GMPY2, reason="gmpy2 not installed")
    def test_gmpy2_backend(self):
        import gmpy2

        with N.use_backend("gmpy2"):
            q = N.rational(2, 6)
            assert isinstance(q, gmpy2.mpq) and q == Fraction(1, 3)
            N.require_gmpy2()
        with N.use_backend("fractions"), pytest.raises(RuntimeError):
            N.require_gmpy2()

    @pytest.mark.parametrize("backend", ["fractions", "gmpy2"])
    def test_to_rational_is_exact(self, backend):
        if backend == "gmpy2" and not N.HAVE_GMPY2:
            pytest.skip("gmpy2 not installed")
        rng = random.Random(2)
        with N.use_backend(backend):
            for x in mixed_doubles(rng, 3000):
                q = N.to_rational(x)
                assert Fraction(int(q.numerator), int(q.denominator)) == Fraction(x)

    @pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
    def test_nonfinite_has_no_rational(self, bad):
        with pytest.raises(NonFiniteError):
            N.to_rational(bad)
        with pytest.raises(NonFiniteError):
            N.to_fraction(bad)
        with pytest.raises(NonFiniteError):
            N.dyadic(bad)


# ------------------------------------------------------------------ dyadic parts


def test_dyadic_decomposition():
    rng = random.Random(3)
    for x in mixed_doubles(rng, 5000):
        m, e = N.dyadic(x)
        if x == 0:
            assert (m, e) == (0, 0)
            assert N.valuation(x) is None
            continue
        assert m % 2 == 1 or m % 2 == -1
        exact = Fraction(m) * (Fraction(2) ** e)
        assert exact == Fraction(x)
        assert N.valuation(x) == e


def test_dyadic_extremes():
    assert N.dyadic(MIN_SUB) == (1, -1074)
    assert N.dyadic(1.0) == (1, 0)
    assert N.dyadic(12.0) == (3, 2)
    assert N.dyadic(0.75) == (3, -2)
    m, e = N.dyadic(MAX)
    assert m == 2**53 - 1 and e == 971


# ------------------------------------------------------------------ dyadic scaling


class TestDyadicScale:
    def test_exponent_is_minimal_valuation(self):
        assert DyadicScale.for_values([0.5, 3.0, 0.25]).exp == -2
        assert DyadicScale.for_values([4.0, 12.0]).exp == 2
        assert DyadicScale.for_values([]).exp == 0
        assert DyadicScale.for_values([0.0, -0.0]).exp == 0
        assert DyadicScale.for_values([math.nan, math.inf, 0.5]).exp == -1
        assert DyadicScale.for_values([MIN_SUB, MAX]).exp == -1074

    def test_to_int_is_exact_and_minimal(self):
        rng = random.Random(4)
        for _ in range(300):
            values = mixed_doubles(rng, rng.randint(1, 12))
            scale = DyadicScale.for_values(values)
            ints = [scale.to_int(v) for v in values]
            for v, i in zip(values, ints, strict=True):
                assert isinstance(i, int)
                assert scale.to_fraction(i) == Fraction(v)
                assert scale.to_float(i) == v
            if any(v != 0 for v in values):
                # the scale is as coarse as possible: some integer is odd
                assert any(i % 2 for i in ints)

    def test_to_point_and_negative_zero(self):
        s = DyadicScale.for_values([0.5, -0.0])
        assert s.to_point(-0.0, 0.5) == (0, 1)

    def test_rejects_finer_values_and_nonfinite(self):
        with pytest.raises(ValueError, match="not a multiple"):
            DyadicScale(0).to_int(0.5)
        with pytest.raises(NonFiniteError):
            DyadicScale(0).to_int(math.nan)

    def test_positive_exponent(self):
        s = DyadicScale.for_values([1024.0, 3072.0])
        assert s.exp == 10
        assert s.to_int(3072.0) == 3
        assert s.to_fraction(3, 2) == Fraction(1536)
        assert s.area_to_fraction(1) == Fraction(2**20)

    def test_negative_exponent_areas(self):
        s = DyadicScale(-3)
        assert s.to_fraction(1) == Fraction(1, 8)
        assert s.area_to_fraction(5, 3) == Fraction(5, 3 * 64)
        assert s.length_to_fraction(8) == 1

    def test_hpoint_conversions(self):
        s = DyadicScale(-1)
        p = (6, 2, 5)
        assert s.hpoint_to_fractions(p) == (Fraction(3, 5), Fraction(1, 5))
        x, y = s.hpoint_to_rationals(p)
        assert Fraction(int(x.numerator), int(x.denominator)) == Fraction(3, 5)
        assert Fraction(int(y.numerator), int(y.denominator)) == Fraction(1, 5)
        assert s.hpoint_to_floats(p) == (0.6, 0.2)


# ------------------------------------------------------------- rounding to doubles


def _neighbours(r: float) -> list[float]:
    return [math.nextafter(r, -math.inf), r, math.nextafter(r, math.inf)]


def test_rational_to_float_is_correctly_rounded():
    rng = random.Random(5)
    for _ in range(3000):
        n = rng.randint(-(10**40), 10**40)
        d = rng.randint(1, 10**30)
        q = Fraction(n, d)
        r = N.rational_to_float(q)
        err = abs(Fraction(r) - q)
        for other in _neighbours(r):
            if math.isfinite(other):
                assert err <= abs(Fraction(other) - q)


def test_rational_to_float_ties_to_even():
    rng = random.Random(6)
    for _ in range(2000):
        x = abs(random_double(rng))
        y = math.nextafter(x, math.inf)
        if not math.isfinite(y):
            continue
        mid = (Fraction(x) + Fraction(y)) / 2
        r = N.rational_to_float(mid)
        assert r in (x, y)
        # the chosen neighbour has an even significand (lowest bit clear)
        bits = struct.unpack("<q", struct.pack("<d", r))[0]
        assert bits & 1 == 0, (x, y)


def test_rational_to_float_extremes():
    assert N.rational_to_float(Fraction(10**400)) == math.inf
    assert N.rational_to_float(Fraction(-(10**400))) == -math.inf
    assert N.rational_to_float(Fraction(1, 10**400)) == 0.0
    assert N.rational_to_float(Fraction(1, 2**1075)) == 0.0  # half the smallest: ties to 0
    assert N.rational_to_float(Fraction(3, 2**1076)) == MIN_SUB
    assert N.rational_to_float(7) == 7.0
    if N.HAVE_GMPY2:
        import gmpy2

        assert N.rational_to_float(gmpy2.mpq(1, 3)) == 1 / 3


# ------------------------------------------------------------- rational side-car


class TestRationalText:
    @pytest.mark.parametrize(
        ("value", "text"),
        [
            (Fraction(2, 3), "2/3"),
            (Fraction(-4, 6), "-2/3"),
            (Fraction(5), "5"),
            (0, "0"),
            (-0.0, "0"),
            (0.5, "1/2"),
            (Fraction(0), "0"),
            (-7, "-7"),
        ],
    )
    def test_format(self, value, text):
        assert N.format_rational(value) == text

    def test_format_gmpy2(self):
        if not N.HAVE_GMPY2:
            pytest.skip("gmpy2 not installed")
        import gmpy2

        assert N.format_rational(gmpy2.mpq(-6, 4)) == "-3/2"

    def test_round_trip(self):
        rng = random.Random(7)
        for backend in ("fractions", "gmpy2") if N.HAVE_GMPY2 else ("fractions",):
            with N.use_backend(backend):
                for _ in range(500):
                    q = Fraction(rng.randint(-(10**30), 10**30), rng.randint(1, 10**25))
                    back = N.parse_rational(N.format_rational(q))
                    assert Fraction(int(back.numerator), int(back.denominator)) == q

    @pytest.mark.parametrize(
        "bad", ["1.5", " 1/2", "1/0", "1/-2", "", "1e3", "+1", "1/2/3", "0x10"]
    )
    def test_parse_rejects(self, bad):
        with pytest.raises(ValueError):
            N.parse_rational(bad)

    def test_parse_accepts_non_reduced(self):
        assert N.parse_rational("6/4") == Fraction(3, 2)
        assert N.parse_rational("-0") == 0

    def test_float_formats_exactly(self):
        assert N.format_rational(0.1) == "3602879701896397/36028797018963968"
