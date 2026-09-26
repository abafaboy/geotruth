"""DE-9IM and the named predicates from the labelled arrangement (DESIGN §2.3).

:func:`relate` builds the planar arrangement of the two operands
(:func:`geotruth.arrangement.build_arrangement`), whose every vertex, edge and face is
labelled with its location in A and in B by the point-location rules of DESIGN §1
(polygonal union first, then the Mod-2 lines, then points). The matrix is read off the
cells:

    M[a][b] = max { dim(c) : c a cell labelled a in A and b in B },    F if there is none.

Face 0 is the unbounded face, always labelled (E, E), so EE = 2 for every input. The named
predicates are dispatched on the operands' *real* dimensions (RelateNG
``getDimensionReal``) by :func:`geotruth.predicates.evaluate`, with the empty-geometry
convention table applied.

Assertions on every matrix
--------------------------
A failed assertion is an engine bug (``engine_error``), never a library failure:

- **EE = 2.**
- **Transpose.** ``relate(B, A)`` is computed from a *second*, independent arrangement
  built with the operands swapped (different tags, numbering and rotation order), and
  must be the transpose of ``relate(A, B)``.
- **Dimension sanity** (:func:`matrix_sanity`), from the geometric dimension of each
  operand (:func:`effective_dimension`): an entry never exceeds the dimension of either
  point set it intersects (interior: the operand's dimension; boundary: one less for an
  areal operand, at most 0 for a linear one, empty for a puntal one); the interior of a
  non-empty operand is met by *something* at its full dimension (so a non-empty areal A
  has II, IB or IE non-F, and in fact II or IE = 2), and the boundary of a non-empty areal
  operand has dimension 1.

Statuses
--------
``"ok"``; ``"engine_skipped"`` when the arrangement is over its budget
(:class:`~geotruth.arrangement.BudgetExceeded`, or ``MemoryError``);
``"engine_error"`` when the engine raised or an assertion failed (unless
``strict=True``, which re-raises). Input outside the engine's contract (non-finite
coordinates, unclosed or zero-area rings, impossible polygon coverage) raises
:class:`~geotruth.arrangement.InvalidInputError` (a ``ValueError``): relate is defined
for valid input, so the caller checks validity first (:mod:`geotruth.validity`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from fractions import Fraction
from typing import Any

from geotruth.arrangement import (
    DEFAULT_BUDGET,
    Budget,
    BudgetExceeded,
    InvalidInputError,
    build_arrangement,
)
from geotruth.arrangement_api import Arrangement, ArrangementError, Cell
from geotruth.geom import DIM_A, DIM_FALSE, DIM_L, DIM_P, Geometry, LineString, Point, Polygon
from geotruth.numbers import format_rational
from geotruth.predicates import (
    PREDICATE_NAMES,
    PredicateValue,
    convention_fields,
    evaluate,
    relate_pattern,
    transpose,
)

__all__ = [
    "ENTRY_NAMES",
    "STATUS_ERROR",
    "STATUS_OK",
    "STATUS_SKIPPED",
    "RelateAssertionError",
    "RelateResult",
    "cell_realizers",
    "describe_cell",
    "effective_dimension",
    "matrix_from_arrangement",
    "matrix_sanity",
    "relate",
    "relate_matrix",
]

STATUS_OK = "ok"
STATUS_SKIPPED = "engine_skipped"
STATUS_ERROR = "engine_error"

#: Names of the nine matrix entries in row order (A's I, B, E rows; B's columns).
ENTRY_NAMES: tuple[str, ...] = tuple(r + c for r in "IBE" for c in "IBE")

_LABELS = (0, 1, 2)


class RelateAssertionError(RuntimeError):
    """A matrix assertion of DESIGN §2.3 failed (an engine bug); ``problems`` lists
    what was found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(problems)
        super().__init__("relate assertion failed: " + "; ".join(self.problems))


# ============================================================================ matrix


def _dims_from_labels(arr: Arrangement) -> list[int]:
    dims = [-1] * 9
    for dim, la, lb in (
        (0, arr.vertex_loc_a, arr.vertex_loc_b),
        (1, arr.edge_loc_a, arr.edge_loc_b),
        (2, arr.face_loc_a, arr.face_loc_b),
    ):
        for x, y in set(zip(la, lb, strict=True)):
            if x not in _LABELS or y not in _LABELS:
                raise ArrangementError([f"a cell of dimension {dim} is labelled ({x}, {y})"])
            k = 3 * x + y
            if dim > dims[k]:
                dims[k] = dim
    return dims


def matrix_from_arrangement(arr: Arrangement) -> str:
    """The DE-9IM matrix of a labelled arrangement: the maximum cell dimension over the
    cells of each (location in A, location in B) pair, ``F`` where there is none.

    Raises :class:`~geotruth.arrangement_api.ArrangementError` if a cell is unlabelled.
    """
    return "".join("F" if d < 0 else str(d) for d in _dims_from_labels(arr))


def cell_realizers(arr: Arrangement, matrix: str | None = None) -> dict[str, Cell]:
    """For every non-``F`` entry (``"II"``, ``"IB"``, ...), the lowest-numbered cell of
    the entry's dimension that realises it."""
    m = matrix if matrix is not None else matrix_from_arrangement(arr)
    want = {k: int(ch) for k, ch in enumerate(m) if ch != "F"}
    found: dict[int, Cell] = {}
    for c in arr.cells():
        k = 3 * int(c.loc_a) + int(c.loc_b)
        if want.get(k) == c.dim and k not in found:
            found[k] = c
    return {ENTRY_NAMES[k]: found[k] for k in sorted(found)}


def _fmt(q: Fraction) -> str:
    """An exact value: the shortest double when it is one, else ``n/d``."""
    try:
        f = float(q)
    except OverflowError:
        return format_rational(q)
    if Fraction(f) == q:
        s = repr(f)
        return s[:-2] if s.endswith(".0") else s
    return format_rational(q)


def _vertex_text(arr: Arrangement, v: int) -> str:
    x, y = arr.vertex_fractions(v)
    return f"({_fmt(x)} {_fmt(y)})"


def describe_cell(arr: Arrangement, cell: Cell) -> str:
    """A human-readable description of a cell, with exact real coordinates."""
    if cell.dim == 0:
        return f"vertex {_vertex_text(arr, cell.index)}"
    if cell.dim == 1:
        h = 2 * cell.index
        u, v = arr.he_origin[h], arr.he_origin[h + 1]
        return f"edge {_vertex_text(arr, u)}-{_vertex_text(arr, v)}"
    f = cell.index
    if f == 0:
        return "the unbounded face"
    h = arr.face_outer[f]
    u, v = arr.he_origin[h], arr.he_origin[h ^ 1]
    return f"face left of {_vertex_text(arr, u)}->{_vertex_text(arr, v)}"


# ============================================================================ sanity


def effective_dimension(g: Geometry) -> int:
    """The topological dimension of the point set of ``g``: 2 with a non-empty polygon
    element, 1 with a line element of positive length, 0 with a point or a zero-length
    line, -1 when empty.

    It differs from :attr:`~geotruth.geom.Geometry.real_dimension` only on RelateNG's
    quirk: a collection whose type dimension is 2 because of an *empty* polygon keeps real
    dimension 1 for zero-length lines. The predicates use the real dimension (as GEOS);
    the sanity assertions use this one.
    """
    dim = DIM_FALSE
    for e in g.elements():
        if e.is_empty:
            continue
        if isinstance(e, Polygon):
            return DIM_A
        if isinstance(e, LineString):
            dim = max(dim, DIM_P if e.is_zero_length else DIM_L)
        elif isinstance(e, Point):
            dim = max(dim, DIM_P)
    return dim


def _part_dims(eff: int) -> tuple[int, int, int]:
    """Upper bounds on the dimension of the interior, boundary and exterior."""
    if eff == DIM_A:
        return 2, 1, 2
    if eff == DIM_L:
        return 1, 0, 2
    if eff == DIM_P:
        return 0, -1, 2
    return -1, -1, 2


def matrix_sanity(matrix: str, eff_a: int, eff_b: int) -> list[str]:
    """Problems of a matrix given the operands' :func:`effective_dimension` (empty list
    if none); see the module docstring. Every rule holds for any input the arrangement
    accepts, valid or not."""
    problems = []
    d = [-1 if ch == "F" else int(ch) for ch in matrix]
    if matrix[8] != "2":
        problems.append(f"EE is {matrix[8]}, not 2")
    pa, pb = _part_dims(eff_a), _part_dims(eff_b)
    for r in range(3):
        for c in range(3):
            bound = min(pa[r], pb[c])
            if d[3 * r + c] > bound:
                problems.append(
                    f"{ENTRY_NAMES[3 * r + c]} = {matrix[3 * r + c]} exceeds the dimension "
                    f"{bound} of the point sets it intersects"
                )
    for name, eff, rows in (
        ("A", eff_a, [[d[0], d[1], d[2]], [d[3], d[4], d[5]]]),
        ("B", eff_b, [[d[0], d[3], d[6]], [d[1], d[4], d[7]]]),
    ):
        interior, boundary = max(rows[0]), max(rows[1])
        if interior != eff:
            problems.append(
                f"the interior of {name} has dimension {eff} but meets the other operand's "
                f"cells only up to dimension {interior}"
            )
        if eff == DIM_A and boundary != DIM_L:
            problems.append(f"{name} is areal but its boundary has dimension {boundary}, not 1")
    return problems


# ============================================================================ result


@dataclass
class RelateResult:
    """The exact relate of an ordered pair (A, B).

    ``status`` is ``"ok"``, ``"engine_skipped"`` or ``"engine_error"`` (then ``reason``
    says why and the answer fields are None). ``matrix`` is the DE-9IM string (row order
    II IB IE BI BB BE EI EB EE); ``predicates`` maps each schema predicate to the reported
    boolean (conventions applied) and ``predicate_values`` to its full
    :class:`~geotruth.predicates.PredicateValue`; ``conventions`` lists the
    ``"predicates.<name>"`` fields decided by the convention table. ``dim_a``/``dim_b``
    are the real dimensions the predicates were dispatched on, ``type_dim_a``/``type_dim_b``
    the type dimensions (JTS ``getDimension``). ``stats`` holds the arrangement sizes and
    timings; ``arrangement`` is kept on request.
    """

    status: str
    matrix: str | None
    predicates: dict[str, bool] | None
    predicate_values: dict[str, PredicateValue] | None
    conventions: list[str]
    dim_a: int
    dim_b: int
    type_dim_a: int
    type_dim_b: int
    reason: str | None = None
    stats: dict[str, Any] = field(default_factory=dict)
    arrangement: Arrangement | None = field(default=None, repr=False)

    @property
    def ok(self) -> bool:
        return self.status == STATUS_OK

    @property
    def relate(self) -> str | None:
        """Alias of :attr:`matrix` (the expected-answer field name)."""
        return self.matrix

    def entry(self, name: str) -> int:
        """The entry ``name`` (``"II"``, ``"BE"``, ...) as a dimension, -1 for ``F``."""
        if self.matrix is None:
            raise ValueError(f"no matrix: the engine status is {self.status}")
        ch = self.matrix[ENTRY_NAMES.index(name.upper())]
        return -1 if ch == "F" else int(ch)

    def matches(self, pattern: str) -> bool:
        """True if the matrix matches a DE-9IM pattern (``T``, ``F``, ``*``, ``0-2``)."""
        if self.matrix is None:
            raise ValueError(f"no matrix: the engine status is {self.status}")
        return relate_pattern(self.matrix, pattern)

    def realizers(self) -> dict[str, Cell]:
        """A realising cell for every non-``F`` entry (needs ``keep_arrangement``)."""
        if self.arrangement is None:
            raise ValueError("the arrangement was not kept (relate(..., keep_arrangement=True))")
        return cell_realizers(self.arrangement, self.matrix)

    def to_json(self) -> dict[str, Any]:
        """The relate fields of an expected answer (``schemas/expected.v2``): ``status``,
        ``reason`` (when not ok), ``dimensions``, ``relate``, ``predicates`` and
        ``conventions``. The caller adds ``id``, ``engine`` and ``validity``."""
        out: dict[str, Any] = {"status": self.status}
        if self.reason is not None:
            out["reason"] = self.reason
        out["dimensions"] = {
            "a": {"dimension": self.type_dim_a, "real_dimension": self.dim_a},
            "b": {"dimension": self.type_dim_b, "real_dimension": self.dim_b},
        }
        if self.ok:
            out["relate"] = self.matrix
            out["predicates"] = dict(self.predicates or {})
            out["conventions"] = list(self.conventions)
        return out


# ============================================================================ relate


def _remaining(budget: Budget, t0: float, phase: str) -> Budget:
    """The budget left for the transposed build (the wall-clock limit is shared)."""
    if budget.max_seconds is None:
        return budget
    used = time.perf_counter() - t0
    left = budget.max_seconds - used
    if left <= 0:
        raise BudgetExceeded("time", budget.max_seconds, round(used, 3), phase)
    return replace(budget, max_seconds=left)


def relate(
    a: Geometry,
    b: Geometry,
    *,
    budget: Budget | None = DEFAULT_BUDGET,
    check: bool = True,
    transpose_check: bool = True,
    strict: bool = False,
    keep_arrangement: bool = False,
) -> RelateResult:
    """The exact DE-9IM matrix and named predicates of ``(a, b)`` (DESIGN §2.3).

    ``budget`` bounds each arrangement (``None``: unlimited; the wall-clock limit covers
    both builds); over budget gives status ``"engine_skipped"``. ``check`` runs the
    arrangement's topology and label invariants; ``transpose_check`` builds the swapped
    arrangement and asserts the transpose (it doubles the cost). ``strict=True`` re-raises
    engine errors and failed assertions instead of returning ``"engine_error"``.
    ``keep_arrangement`` keeps the (A, B) arrangement in the result.

    Raises :class:`~geotruth.arrangement.InvalidInputError` for input outside the
    engine's contract.
    """
    dim_a, dim_b = a.real_dimension, b.real_dimension
    base = {
        "conventions": convention_fields(dim_a, dim_b),
        "dim_a": dim_a,
        "dim_b": dim_b,
        "type_dim_a": a.dimension,
        "type_dim_b": b.dimension,
    }
    bud = budget if budget is not None else Budget(None, None, None)
    t0 = time.perf_counter()
    stats: dict[str, Any] = {}
    try:
        arr = build_arrangement(a, b, budget=bud, check=check, stats=stats)
        matrix = matrix_from_arrangement(arr)
        problems = matrix_sanity(matrix, effective_dimension(a), effective_dimension(b))
        if transpose_check:
            tstats: dict[str, Any] = {}
            rest = _remaining(bud, t0, "transpose")
            swapped = matrix_from_arrangement(
                build_arrangement(b, a, budget=rest, check=check, stats=tstats)
            )
            stats["t_transpose"] = tstats.get("t_total")
            if transpose(swapped) != matrix:
                problems.append(
                    f"relate(B, A) = {swapped} is not the transpose of relate(A, B) = {matrix}"
                )
        if problems:
            raise RelateAssertionError(problems)
    except InvalidInputError:
        raise
    except BudgetExceeded as exc:
        return RelateResult(STATUS_SKIPPED, None, None, None, reason=str(exc), stats=stats, **base)
    except MemoryError:
        return RelateResult(
            STATUS_SKIPPED, None, None, None, reason="out of memory", stats=stats, **base
        )
    except Exception as exc:
        if strict:
            raise
        reason = f"{type(exc).__name__}: {exc}"
        return RelateResult(STATUS_ERROR, None, None, None, reason=reason, stats=stats, **base)
    stats["t_relate"] = round(time.perf_counter() - t0, 6)
    values = evaluate(matrix, dim_a, dim_b, PREDICATE_NAMES)
    return RelateResult(
        STATUS_OK,
        matrix,
        {k: v.value for k, v in values.items()},
        values,
        stats=stats,
        arrangement=arr if keep_arrangement else None,
        **base,
    )


def relate_matrix(a: Geometry, b: Geometry, **kwargs: Any) -> str:
    """The DE-9IM matrix string of ``(a, b)``; raises ``RuntimeError`` when the engine
    abstains (status not ``"ok"``). Keyword arguments go to :func:`relate`."""
    res = relate(a, b, **kwargs)
    if not res.ok or res.matrix is None:
        raise RuntimeError(f"relate: {res.status}: {res.reason}")
    return res.matrix
