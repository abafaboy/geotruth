"""Named spatial predicates from a DE-9IM matrix and the operands' real dimensions.

DESIGN §1: the named predicates are read off the matrix and **dispatched on dimension**,
exactly as JTS ``IntersectionMatrix`` / RelateNG ``RelatePredicate`` do. The dimensions
are RelateNG's *real* dimensions (:attr:`geotruth.geom.Geometry.real_dimension`: empty
elements are ignored, a line whose points all coincide counts as a point, an empty
geometry is -1).

=========== ======================= =========================================
predicate   rule                    applies to (dim A / dim B)
=========== ======================= =========================================
intersects  not disjoint            all
disjoint    ``FF*FF****``           all
touches     ``FT*******``,          every pair except P/P (false there)
            ``F**T*****`` or
            ``F***T****``
crosses     ``T*T******``           P/L, P/A, L/A
crosses     ``T*****T**``           L/P, A/P, A/L
crosses     ``0********``           L/L
crosses     false                   every other pair
overlaps    ``T*T***T**``           P/P, A/A
overlaps    ``1*T***T**``           L/L
overlaps    false                   every other pair
contains    ``T*****FF*``           all
covers      ``T*****FF*``, ``*T****FF*``, ``***T**FF*`` or ``****T*FF*``
within      ``T*F**F***``           all
covered_by  ``T*F**F***``, ``*TF**F***``, ``**FT*F***`` or ``**F*TF***``
equals      ``T*F**FFF*``           equal dimensions only (false otherwise)
=========== ======================= =========================================

Empty operands: the convention table
------------------------------------
With an empty operand the matrix alone does not settle every predicate: libraries follow
different conventions. :data:`CONVENTIONS` records each such case with the value
geotruth reports -- GEOS 3.13.1 / JTS RelateNG, checked through Shapely 2.1.2 -- and the
alternative a library may legitimately return. :func:`evaluate` marks those predicates
``convention=True``; the scorer counts a disagreement there as a ``convention``
disagreement, never as a wrong answer.

- ``equals(EMPTY, EMPTY)`` is **true** in RelateNG for any two empty geometries (``POINT
  EMPTY`` equals ``LINESTRING EMPTY``), although the pattern ``T*F**FFF*`` gives false.
- ``contains``/``covers(X, EMPTY)`` and ``within``/``covered_by(EMPTY, X)`` are **false**
  in GEOS (the patterns need a non-empty intersection); set inclusion of the empty set is
  vacuously true, which some libraries return.

``intersects`` (false), ``disjoint`` (true), ``touches``, ``crosses``, ``overlaps``
(false) and ``equals(X, EMPTY)`` for non-empty ``X`` (false) are not conventions: the
matrix, set theory and every known library agree on them.
"""

from __future__ import annotations

from dataclasses import dataclass

from geotruth.geom import DIM_A, DIM_FALSE, DIM_L, DIM_P

__all__ = [
    "CONVENTIONS",
    "PREDICATE_NAMES",
    "Convention",
    "PredicateValue",
    "contains",
    "contains_properly",
    "convention_fields",
    "covered_by",
    "covers",
    "crosses",
    "disjoint",
    "equals",
    "evaluate",
    "intersects",
    "matrix_dim",
    "matrix_problems",
    "overlaps",
    "predicate",
    "predicates",
    "relate_pattern",
    "touches",
    "transpose",
    "validate_matrix",
    "validate_pattern",
    "within",
]

#: The named predicates of the expected-answer schema, in schema order.
PREDICATE_NAMES: tuple[str, ...] = (
    "intersects",
    "disjoint",
    "touches",
    "crosses",
    "overlaps",
    "contains",
    "covers",
    "within",
    "covered_by",
    "equals",
)

_MATRIX_CHARS = frozenset("F012")
_PATTERN_CHARS = frozenset("TF*012")
_II, _IB, _IE, _BI, _BB, _BE, _EI, _EB, _EE = range(9)


# ============================================================================ matrices


def validate_matrix(matrix: str) -> str:
    """Check a DE-9IM matrix string (nine of ``F012``, row order II IB IE BI BB BE EI EB
    EE) and return it upper-cased."""
    if not isinstance(matrix, str):
        raise TypeError(f"a DE-9IM matrix is a string, not {type(matrix).__name__}")
    m = matrix.upper()
    if len(m) != 9 or not set(m) <= _MATRIX_CHARS:
        raise ValueError(f"not a DE-9IM matrix (nine of F, 0, 1, 2): {matrix!r}")
    return m


def validate_pattern(pattern: str) -> str:
    """Check a DE-9IM pattern (nine of ``T F * 0 1 2``, case-insensitive) and return it
    upper-cased."""
    if not isinstance(pattern, str):
        raise TypeError(f"a DE-9IM pattern is a string, not {type(pattern).__name__}")
    p = pattern.upper()
    if len(p) != 9 or not set(p) <= _PATTERN_CHARS:
        raise ValueError(f"not a DE-9IM pattern (nine of T, F, *, 0, 1, 2): {pattern!r}")
    return p


def _matches(actual: str, required: str) -> bool:
    """JTS ``IntersectionMatrix.matches(int, char)`` for one entry."""
    if required == "*":
        return True
    if required == "T":
        return actual != "F"
    return actual == required


def relate_pattern(matrix: str, pattern: str) -> bool:
    """True if ``matrix`` matches the DE-9IM ``pattern`` (``T`` = any of 0, 1, 2;
    ``F`` = empty; ``*`` = anything; ``0``/``1``/``2`` = that dimension exactly)."""
    m, p = validate_matrix(matrix), validate_pattern(pattern)
    return all(_matches(a, r) for a, r in zip(m, p, strict=True))


def transpose(matrix: str) -> str:
    """The matrix of the swapped pair: ``relate(B, A) == transpose(relate(A, B))``."""
    m = validate_matrix(matrix)
    return "".join(m[3 * c + r] for r in range(3) for c in range(3))


def matrix_dim(matrix: str, row: int, col: int) -> int:
    """The entry ``M[row][col]`` as a dimension (-1 for ``F``); rows/cols I=0, B=1, E=2."""
    ch = validate_matrix(matrix)[3 * row + col]
    return -1 if ch == "F" else int(ch)


def _t(ch: str) -> bool:
    return ch != "F"


def _check_dims(dim_a: int, dim_b: int) -> None:
    for d in (dim_a, dim_b):
        if d not in (DIM_FALSE, DIM_P, DIM_L, DIM_A):
            raise ValueError(f"a real dimension is -1, 0, 1 or 2, not {d!r}")


# ======================================================================= predicates
# Each function applies the matrix rule of the table above, dimension-dispatched where the
# design says so, with no empty-geometry convention (see evaluate()).


def disjoint(matrix: str) -> bool:
    """``FF*FF****``."""
    m = validate_matrix(matrix)
    return m[_II] == "F" and m[_IB] == "F" and m[_BI] == "F" and m[_BB] == "F"


def intersects(matrix: str) -> bool:
    """Not :func:`disjoint`."""
    return not disjoint(matrix)


def touches(matrix: str, dim_a: int, dim_b: int) -> bool:
    """II empty and some boundary contact; always false for P/P (JTS ``isTouches``)."""
    m = validate_matrix(matrix)
    _check_dims(dim_a, dim_b)
    lo, hi = sorted((dim_a, dim_b))
    if (lo, hi) not in ((DIM_A, DIM_A), (DIM_L, DIM_L), (DIM_L, DIM_A), (DIM_P, DIM_A),
                        (DIM_P, DIM_L)):  # fmt: skip
        return False
    return m[_II] == "F" and (_t(m[_IB]) or _t(m[_BI]) or _t(m[_BB]))


def crosses(matrix: str, dim_a: int, dim_b: int) -> bool:
    """JTS ``isCrosses``: ``T*T******`` for P/L, P/A, L/A; ``T*****T**`` for L/P, A/P,
    A/L; ``0********`` for L/L; false otherwise."""
    m = validate_matrix(matrix)
    _check_dims(dim_a, dim_b)
    pair = (dim_a, dim_b)
    if pair in ((DIM_P, DIM_L), (DIM_P, DIM_A), (DIM_L, DIM_A)):
        return _t(m[_II]) and _t(m[_IE])
    if pair in ((DIM_L, DIM_P), (DIM_A, DIM_P), (DIM_A, DIM_L)):
        return _t(m[_II]) and _t(m[_EI])
    if pair == (DIM_L, DIM_L):
        return m[_II] == "0"
    return False


def overlaps(matrix: str, dim_a: int, dim_b: int) -> bool:
    """JTS ``isOverlaps``: ``T*T***T**`` for P/P and A/A, ``1*T***T**`` for L/L, false
    otherwise."""
    m = validate_matrix(matrix)
    _check_dims(dim_a, dim_b)
    if (dim_a, dim_b) in ((DIM_P, DIM_P), (DIM_A, DIM_A)):
        return _t(m[_II]) and _t(m[_IE]) and _t(m[_EI])
    if (dim_a, dim_b) == (DIM_L, DIM_L):
        return m[_II] == "1" and _t(m[_IE]) and _t(m[_EI])
    return False


def contains(matrix: str) -> bool:
    """``T*****FF*``: A contains B."""
    m = validate_matrix(matrix)
    return _t(m[_II]) and m[_EI] == "F" and m[_EB] == "F"


def within(matrix: str) -> bool:
    """``T*F**F***``: A is within B."""
    m = validate_matrix(matrix)
    return _t(m[_II]) and m[_IE] == "F" and m[_BE] == "F"


def covers(matrix: str) -> bool:
    """A covers B: some point in common and no point of B outside A."""
    m = validate_matrix(matrix)
    common = _t(m[_II]) or _t(m[_IB]) or _t(m[_BI]) or _t(m[_BB])
    return common and m[_EI] == "F" and m[_EB] == "F"


def covered_by(matrix: str) -> bool:
    """A is covered by B: some point in common and no point of A outside B."""
    m = validate_matrix(matrix)
    common = _t(m[_II]) or _t(m[_IB]) or _t(m[_BI]) or _t(m[_BB])
    return common and m[_IE] == "F" and m[_BE] == "F"


def contains_properly(matrix: str) -> bool:
    """``T**FF*FF*``: B lies in the interior of A (not in the schema's predicate set)."""
    return relate_pattern(matrix, "T**FF*FF*")


def equals(matrix: str, dim_a: int, dim_b: int) -> bool:
    """Topological equality: equal real dimensions and ``T*F**FFF*`` (JTS
    ``isEquals``). Without the empty convention: ``equals(EMPTY, EMPTY)`` is false here
    (see :func:`evaluate`)."""
    m = validate_matrix(matrix)
    _check_dims(dim_a, dim_b)
    if dim_a != dim_b:
        return False
    return relate_pattern(m, "T*F**FFF*")


def predicate(name: str, matrix: str, dim_a: int, dim_b: int) -> bool:
    """The named predicate by its matrix/dimension rule alone (no convention table)."""
    if name in ("touches", "crosses", "overlaps", "equals"):
        return _DIM_FUNCS[name](matrix, dim_a, dim_b)
    if name in _PLAIN_FUNCS:
        _check_dims(dim_a, dim_b)
        return _PLAIN_FUNCS[name](matrix)
    raise KeyError(f"unknown predicate {name!r}; expected one of {PREDICATE_NAMES}")


_DIM_FUNCS = {"touches": touches, "crosses": crosses, "overlaps": overlaps, "equals": equals}
_PLAIN_FUNCS = {
    "intersects": intersects,
    "disjoint": disjoint,
    "contains": contains,
    "covers": covers,
    "within": within,
    "covered_by": covered_by,
    "contains_properly": contains_properly,
}


# ================================================================== convention table


@dataclass(frozen=True)
class Convention:
    """One entry of the empty-geometry convention table.

    ``when`` is ``"both"`` (both operands empty), ``"a"`` (A empty, B not), ``"b"``
    (B empty, A not) or ``"a_any"``/``"b_any"`` (that operand empty, the other anything).
    ``value`` is what geotruth reports (GEOS 3.13.1 / RelateNG); ``alternative`` is the
    other answer a library may give by convention; ``note`` explains both.
    """

    predicate: str
    when: str
    value: bool
    alternative: bool
    note: str

    def applies(self, empty_a: bool, empty_b: bool) -> bool:
        if self.when == "both":
            return empty_a and empty_b
        if self.when == "a_any":
            return empty_a
        if self.when == "b_any":
            return empty_b
        if self.when == "a":
            return empty_a and not empty_b
        if self.when == "b":
            return empty_b and not empty_a
        raise ValueError(f"bad convention condition {self.when!r}")  # pragma: no cover


#: The convention table (DESIGN §1 "Empty/empty conventions").
CONVENTIONS: tuple[Convention, ...] = (
    Convention(
        "equals", "both", True, False,
        "RelateNG (JTS >= 1.20, GEOS 3.13) returns true for any two empty geometries, "
        "e.g. POINT EMPTY equals LINESTRING EMPTY; the pattern T*F**FFF* gives false.",
    ),
    Convention(
        "contains", "b_any", False, True,
        "GEOS 3.13.1 returns false (T*****FF* needs II non-empty); the empty set is "
        "vacuously a subset of A.",
    ),
    Convention(
        "covers", "b_any", False, True,
        "GEOS 3.13.1 returns false (covers needs a common point); the empty set is "
        "vacuously covered.",
    ),
    Convention(
        "within", "a_any", False, True,
        "GEOS 3.13.1 returns false (T*F**F*** needs II non-empty); the empty set is "
        "vacuously within B.",
    ),
    Convention(
        "covered_by", "a_any", False, True,
        "GEOS 3.13.1 returns false (coveredBy needs a common point); the empty set is "
        "vacuously covered by B.",
    ),
)  # fmt: skip


@dataclass(frozen=True)
class PredicateValue:
    """A named predicate's answer.

    ``value`` is the answer geotruth reports; ``matrix_value`` what the matrix rule
    alone gives; ``convention`` is True when the answer depends on an empty-geometry
    convention (then ``alternative`` is the other conventional answer and ``note`` says
    why).
    """

    name: str
    value: bool
    matrix_value: bool
    convention: bool = False
    alternative: bool | None = None
    note: str = ""

    def __bool__(self) -> bool:
        return self.value


def evaluate(
    matrix: str,
    dim_a: int,
    dim_b: int,
    names: tuple[str, ...] = PREDICATE_NAMES,
) -> dict[str, PredicateValue]:
    """Every named predicate of ``(A, B)`` from their matrix and real dimensions, with
    the convention table applied (an operand is empty iff its real dimension is -1).

    See :func:`matrix_problems` for a consistency check of the matrix itself.
    """
    m = validate_matrix(matrix)
    _check_dims(dim_a, dim_b)
    empty_a, empty_b = dim_a == DIM_FALSE, dim_b == DIM_FALSE
    out: dict[str, PredicateValue] = {}
    for name in names:
        mv = predicate(name, m, dim_a, dim_b)
        conv = next(
            (c for c in CONVENTIONS if c.predicate == name and c.applies(empty_a, empty_b)),
            None,
        )
        if conv is None:
            out[name] = PredicateValue(name, mv, mv)
        else:
            out[name] = PredicateValue(name, conv.value, mv, True, conv.alternative, conv.note)
    return out


def predicates(matrix: str, dim_a: int, dim_b: int) -> dict[str, bool]:
    """The schema's ``predicates`` object: name -> reported boolean (conventions applied)."""
    return {k: v.value for k, v in evaluate(matrix, dim_a, dim_b).items()}


def convention_fields(dim_a: int, dim_b: int) -> list[str]:
    """The expected-answer ``conventions`` list for operands of these real dimensions:
    ``"predicates.<name>"`` for every predicate the convention table decides."""
    _check_dims(dim_a, dim_b)
    empty_a, empty_b = dim_a == DIM_FALSE, dim_b == DIM_FALSE
    return [
        f"predicates.{c.predicate}"
        for name in PREDICATE_NAMES
        for c in CONVENTIONS
        if c.predicate == name and c.applies(empty_a, empty_b)
    ]


def matrix_problems(matrix: str, dim_a: int, dim_b: int) -> list[str]:
    """Consistency problems of a matrix with its operands' real dimensions (empty list if
    none). For valid operands a correct matrix has none:

    - EE is 2;
    - an empty operand has only ``F`` in its interior and boundary row (column);
    - a non-empty operand of real dimension d has an interior of dimension d, so the
      maximum of its interior row (column) is d.

    Degenerate invalid inputs can break the last rule legitimately (a zero-area polygon
    has no interior), so this is an assertion helper, not part of :func:`evaluate`.
    """
    m = validate_matrix(matrix)
    _check_dims(dim_a, dim_b)
    problems = []
    if m[_EE] != "2":
        problems.append(f"EE is {m[_EE]}, not 2")
    rows = {
        "A": (dim_a, [m[i] for i in (_II, _IB, _IE)], [m[i] for i in (_BI, _BB, _BE)]),
        "B": (dim_b, [m[i] for i in (_II, _BI, _EI)], [m[i] for i in (_IB, _BB, _EB)]),
    }
    for name, (dim, interior, boundary) in rows.items():
        if dim == DIM_FALSE:
            if any(c != "F" for c in interior + boundary):
                problems.append(f"{name} is empty but its interior or boundary meets something")
        else:
            top = max(-1 if c == "F" else int(c) for c in interior)
            if top != dim:
                problems.append(
                    f"{name} has real dimension {dim} but its interior has dimension {top}"
                )
    return problems
