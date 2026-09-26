"""Exact numbers: doubles as rationals, JSON numbers, per-case dyadic integer scaling.

Every finite IEEE-754 double is a dyadic rational ``m * 2**e`` (``m`` odd, or zero).
geotruth never rounds a decision, so it needs three things from this module
(DESIGN §0.1, §2.1):

1. **Read numbers the way libraries read them.** A JSON number becomes a double first:
   ``9007199254740993`` (2^53 + 1) is the double 2^53, and an integer literal too large
   for a double is ``inf`` -- exactly what ``float()`` (and C ``strtod``) produce
   (review finding F4). :func:`as_double` and :func:`json_loads` implement this.

2. **Exact rationals.** :func:`to_rational` converts a double exactly. The rational type is
   ``gmpy2.mpq`` (fast) or :class:`fractions.Fraction` (slow, independent, kept for
   cross-checks); :func:`set_backend` / :func:`use_backend` select it, and the
   ``GEOTRUTH_RATIONAL`` environment variable sets the default. gmpy2 is required for
   producing expected answers (:func:`require_gmpy2`).

3. **Per-case dyadic scaling.** All coordinates of a case are multiplied by the same power
   of two, ``2**-exp``, where ``exp`` is the smallest 2-adic valuation among them. Every
   coordinate then becomes an exact Python :class:`int` and the geometric primitives
   (:mod:`geotruth.exact`) run in pure integer arithmetic. :class:`DyadicScale` maps
   doubles to integers and exact results back to rationals or correctly rounded doubles.

Non-finite values (NaN, +-inf) are *carried*, never raised on while reading: they are
legal doubles, and validity reports them as "Invalid Coordinate". Only an attempt to use
one in exact arithmetic raises :class:`NonFiniteError`.
"""

from __future__ import annotations

import json
import math
import os
import re
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

try:  # gmpy2 is a hard dependency, but the fractions backend must work without it.
    import gmpy2 as _gmpy2
except ImportError:  # pragma: no cover - exercised only in the no-gmpy2 CI job
    _gmpy2 = None

__all__ = [
    "BACKENDS",
    "HAVE_GMPY2",
    "DyadicScale",
    "NonFiniteError",
    "all_finite",
    "as_double",
    "dyadic",
    "format_rational",
    "get_backend",
    "is_finite",
    "json_loads",
    "parse_rational",
    "rational",
    "rational_to_float",
    "rational_type",
    "require_gmpy2",
    "set_backend",
    "to_fraction",
    "to_rational",
    "use_backend",
    "valuation",
]

#: True when gmpy2 is importable.
HAVE_GMPY2: bool = _gmpy2 is not None

#: Names of the rational backends.
BACKENDS: tuple[str, ...] = ("gmpy2", "fractions")


class NonFiniteError(ValueError):
    """A NaN or infinite value reached exact arithmetic.

    Readers never raise this: non-finite coordinates are carried as ordinary floats and
    reported by validity ("Invalid Coordinate"). Code that scales or converts coordinates
    must check :func:`is_finite` (or ``Geometry.has_nonfinite``) first.
    """


# --------------------------------------------------------------------------- backends


def _default_backend() -> str:
    env = os.environ.get("GEOTRUTH_RATIONAL", "").strip().lower()
    if env:
        if env not in BACKENDS:
            raise ValueError(f"GEOTRUTH_RATIONAL must be one of {BACKENDS}, got {env!r}")
        if env == "gmpy2" and not HAVE_GMPY2:
            raise ImportError("GEOTRUTH_RATIONAL=gmpy2 but gmpy2 is not installed")
        return env
    return "gmpy2" if HAVE_GMPY2 else "fractions"


_backend: str = _default_backend()


def get_backend() -> str:
    """Name of the active rational backend: ``"gmpy2"`` or ``"fractions"``."""
    return _backend


def set_backend(name: str) -> None:
    """Select the rational backend used by :func:`rational` and :func:`to_rational`."""
    global _backend
    if name not in BACKENDS:
        raise ValueError(f"unknown rational backend {name!r}; expected one of {BACKENDS}")
    if name == "gmpy2" and not HAVE_GMPY2:
        raise ImportError("the gmpy2 backend was requested but gmpy2 is not installed")
    _backend = name


@contextmanager
def use_backend(name: str) -> Iterator[None]:
    """Temporarily select a rational backend (for cross-checks)::

    with use_backend("fractions"):
        answer = engine(case)
    """
    previous = _backend
    set_backend(name)
    try:
        yield
    finally:
        set_backend(previous)


def require_gmpy2() -> None:
    """Raise unless gmpy2 is installed and active (required for expected answers)."""
    if not HAVE_GMPY2:
        raise RuntimeError("gmpy2 is required to produce expected answers")
    if _backend != "gmpy2":
        raise RuntimeError(f"expected answers must use the gmpy2 backend, not {_backend!r}")


def rational_type() -> type:
    """The class of rationals produced by the active backend."""
    return _gmpy2.mpq if _backend == "gmpy2" else Fraction


def rational(numerator: int, denominator: int = 1) -> Any:
    """The exact rational ``numerator / denominator`` in the active backend."""
    if _backend == "gmpy2":
        return _gmpy2.mpq(numerator, denominator)
    return Fraction(numerator, denominator)


# ----------------------------------------------------------------------- JSON numbers


def is_finite(x: float) -> bool:
    """True unless ``x`` is NaN or infinite."""
    return math.isfinite(x)


def all_finite(values: Iterable[float]) -> bool:
    """True if every value is finite (the "Invalid Coordinate" flag is its negation)."""
    return all(math.isfinite(v) for v in values)


def as_double(value: Any) -> float:
    """The double a library sees for a JSON number (``float()`` / ``strtod`` semantics).

    - ``float``: returned unchanged (including NaN, +-inf and -0.0).
    - ``int``: correctly rounded to nearest-even, so ``2**53 + 1`` becomes ``2**53``;
      integers beyond the double range become +-inf instead of raising.
    - ``str``: parsed with ``float()``, so ``"1e400"`` is ``inf`` and ``"NaN"`` is NaN.

    ``bool`` is rejected even though it is an ``int`` subclass: ``true`` is not a number.
    """
    if isinstance(value, float):
        return value
    if isinstance(value, bool):
        raise TypeError("a boolean is not a coordinate")
    if isinstance(value, int):
        try:
            return float(value)  # CPython rounds int -> float correctly (half to even)
        except OverflowError:
            return math.inf if value > 0 else -math.inf
    if isinstance(value, str):
        return float(value)
    raise TypeError(f"not a JSON number: {value!r}")


# int() refuses decimal literals longer than sys.get_int_max_str_digits() (4300 by
# default); anything that long is far outside the double range anyway.
_MAX_INT_LITERAL = 4000


def _parse_int_literal(literal: str) -> int | float:
    if len(literal) > _MAX_INT_LITERAL:
        return float(literal)  # +-inf: the literal exceeds 1e308
    return int(literal)


def json_loads(text: str | bytes) -> Any:
    """``json.loads`` that never loses or rejects a number.

    Integer literals stay exact Python ``int`` values (so ids and counts are not turned
    into floats); coordinates are converted with :func:`as_double` by the geometry reader,
    which applies float semantics. Integer literals too long for ``int()`` become +-inf.
    ``NaN``, ``Infinity`` and ``-Infinity`` are accepted (Python's JSON dialect), so
    invalid-coordinate cases can be stored.
    """
    return json.loads(text, parse_int=_parse_int_literal)


# ------------------------------------------------------------------ exact conversion


def to_fraction(x: float) -> Fraction:
    """The exact value of a finite double as a :class:`~fractions.Fraction`."""
    if not math.isfinite(x):
        raise NonFiniteError(f"non-finite value {x!r} has no exact rational value")
    return Fraction(x)


def to_rational(x: float) -> Any:
    """The exact value of a finite double in the active rational backend."""
    if not math.isfinite(x):
        raise NonFiniteError(f"non-finite value {x!r} has no exact rational value")
    if _backend == "gmpy2":
        return _gmpy2.mpq(x)
    return Fraction(x)


def dyadic(x: float) -> tuple[int, int]:
    """Decompose a finite double as ``x == m * 2**e`` with ``m`` odd, or ``(0, 0)``."""
    if not math.isfinite(x):
        raise NonFiniteError(f"non-finite value {x!r} is not dyadic")
    n, d = x.as_integer_ratio()  # reduced; d is a power of two
    if n == 0:
        return 0, 0
    if d == 1:
        tz = (n & -n).bit_length() - 1
        return n >> tz, tz
    return n, 1 - d.bit_length()


def valuation(x: float) -> int | None:
    """The 2-adic valuation of a finite double (``e`` in :func:`dyadic`); None for 0."""
    m, e = dyadic(x)
    return None if m == 0 else e


def rational_to_float(q: Any) -> float:
    """Correctly rounded (nearest, ties to even) double of an exact rational.

    Works for ``int``, ``Fraction``, ``mpq`` and anything with integer
    ``numerator``/``denominator``. Python's ``int / int`` is correctly rounded, which is
    *not* true of every library (``mpq_get_d`` truncates). Values beyond the double range
    become +-inf; values below the smallest subnormal round to +-0.0.
    """
    if isinstance(q, float):
        return q
    n, d = int(q.numerator), int(q.denominator)
    return _div_to_float(n, d)


def _div_to_float(n: int, d: int) -> float:
    try:
        return n / d
    except OverflowError:
        return math.inf if (n > 0) == (d > 0) else -math.inf


# ------------------------------------------------------------- rational side-car text

_RATIONAL_RE = re.compile(r"-?[0-9]+(?:/[0-9]+)?")


def format_rational(q: Any) -> str:
    """Canonical text of an exact rational: ``"n/d"`` in lowest terms with ``d > 1``, or
    ``"n"`` when the value is an integer. Floats are converted exactly first."""
    if isinstance(q, float):
        q = to_fraction(q)
    if isinstance(q, int):
        return str(q)
    n, d = int(q.numerator), int(q.denominator)
    g = math.gcd(n, d)
    if g != 1:
        n, d = n // g, d // g
    if d < 0:
        n, d = -n, -d
    return str(n) if d == 1 else f"{n}/{d}"


def parse_rational(text: str) -> Any:
    """Parse ``"n"`` or ``"n/d"`` (the side-car format) into the active backend.

    Stricter than ``Fraction(str)``: no whitespace, no decimal point, no exponent, and
    the denominator must be positive.
    """
    if not isinstance(text, str) or not _RATIONAL_RE.fullmatch(text):
        raise ValueError(f"not a rational of the form 'n' or 'n/d': {text!r}")
    num, _, den = text.partition("/")
    d = int(den) if den else 1
    if d == 0:
        raise ValueError(f"zero denominator in {text!r}")
    return rational(int(num), d)


# ------------------------------------------------------------------ dyadic scaling


@dataclass(frozen=True)
class DyadicScale:
    """The per-case scale ``2**exp`` that turns every coordinate into an exact integer.

    A real value ``v`` corresponds to the integer ``v * 2**-exp``; an integer ``i``
    (or a rational ``n/d`` computed from integers) corresponds to ``i * 2**exp``.
    ``exp`` is the minimum 2-adic valuation over the case's non-zero finite coordinates,
    so the integers are as small as possible; it may be positive (all coordinates even)
    or as low as -1074 (subnormals). A case without non-zero coordinates has ``exp == 0``.

    Relate and every predicate are invariant under this scaling; lengths scale by
    ``2**exp`` and areas by ``4**exp``.
    """

    exp: int = 0

    # -- construction --------------------------------------------------------------

    @classmethod
    def for_values(cls, values: Iterable[float]) -> DyadicScale:
        """The scale for a collection of doubles. Non-finite values are ignored: they
        cannot be scaled, and the caller reports them as invalid coordinates."""
        best: int | None = None
        for v in values:
            if v == 0 or not math.isfinite(v):
                continue
            n, d = v.as_integer_ratio()
            e = (n & -n).bit_length() - 1 if d == 1 else 1 - d.bit_length()
            if best is None or e < best:
                best = e
        return cls(0 if best is None else best)

    # -- doubles -> integers -------------------------------------------------------

    def to_int(self, x: float) -> int:
        """The exact integer ``x * 2**-exp``.

        Raises :class:`NonFiniteError` for NaN/inf, and :class:`ValueError` if ``x`` is
        finer than this scale (its valuation is below ``exp``).
        """
        if not math.isfinite(x):
            raise NonFiniteError(f"cannot scale non-finite coordinate {x!r}")
        n, d = x.as_integer_ratio()
        shift = -self.exp - (d.bit_length() - 1)
        if shift >= 0:
            return n << shift
        if n & ((1 << -shift) - 1):
            raise ValueError(f"{x!r} is not a multiple of 2**{self.exp}")
        return n >> -shift

    def to_point(self, x: float, y: float) -> tuple[int, int]:
        """A coordinate pair as an integer point."""
        return self.to_int(x), self.to_int(y)

    # -- integers / rationals -> values ------------------------------------------------

    def _num_den(self, n: int, d: int) -> tuple[int, int]:
        if self.exp >= 0:
            return n << self.exp, d
        return n, d << -self.exp

    def to_fraction(self, n: int, d: int = 1) -> Fraction:
        """The real value ``(n / d) * 2**exp`` as a :class:`~fractions.Fraction`."""
        num, den = self._num_den(int(n), int(d))
        return Fraction(num, den)

    def to_rational(self, n: int, d: int = 1) -> Any:
        """The real value ``(n / d) * 2**exp`` in the active rational backend."""
        num, den = self._num_den(int(n), int(d))
        return rational(num, den)

    def to_float(self, n: int, d: int = 1) -> float:
        """The correctly rounded double of ``(n / d) * 2**exp`` (see
        :func:`rational_to_float`)."""
        num, den = self._num_den(int(n), int(d))
        return _div_to_float(num, den)

    def hpoint_to_fractions(self, p: tuple[int, int, int]) -> tuple[Fraction, Fraction]:
        """A homogeneous integer point ``(X, Y, W)`` as real coordinates (Fractions)."""
        x, y, w = p
        return self.to_fraction(x, w), self.to_fraction(y, w)

    def hpoint_to_rationals(self, p: tuple[int, int, int]) -> tuple[Any, Any]:
        """A homogeneous integer point as real coordinates in the active backend."""
        x, y, w = p
        return self.to_rational(x, w), self.to_rational(y, w)

    def hpoint_to_floats(self, p: tuple[int, int, int]) -> tuple[float, float]:
        """A homogeneous integer point rounded to the nearest doubles (display only)."""
        x, y, w = p
        return self.to_float(x, w), self.to_float(y, w)

    def length_to_fraction(self, n: int, d: int = 1) -> Fraction:
        """Alias of :meth:`to_fraction`, for lengths (which scale by ``2**exp``)."""
        return self.to_fraction(n, d)

    def area_to_fraction(self, n: int, d: int = 1) -> Fraction:
        """A scaled area ``n / d`` (square units of the integer grid) in real units:
        ``(n / d) * 4**exp``. Squared distances scale the same way."""
        e2 = 2 * self.exp
        n, d = int(n), int(d)
        return Fraction(n << e2, d) if e2 >= 0 else Fraction(n, d << -e2)
