"""The exact answer for a case, behind a small import shim (DESIGN §2).

The minimiser and the exporters need the exact answer of every case they touch: validity
of each operand, the DE-9IM matrix, the named predicates and the overlay areas. The
engine modules answer where they exist; while parts of the engine are still being written,
the audited references in ``tests/reference/`` answer instead, so this module works now
and switches automatically when the engine lands:

========== ======================================= ==========================================
answer     first choice                            fallback
========== ======================================= ==========================================
validity   ``geotruth.validity.is_valid``          ``tests/reference/validity.py``
                                                   (polygonal input)
relate     ``geotruth.relate.relate`` (arrangement, ``geotruth.relate_witness`` (witness
           DESIGN §2.3)                            points, §2.4), then
                                                   ``tests/reference/oracle.py`` (predicates
                                                   only, polygon/polygon)
areas      ``geotruth.overlay.overlay(a, b, op,    ``tests/reference/oracle.py`` (valid
           "areal")`` (§2.5)                       polygon/polygon), or the operand area
                                                   when the other operand has no area
========== ======================================= ==========================================

:attr:`ExactAnswer.sources` records which implementation produced each part, so a
consumer can cite it. Nothing here uses a tolerance.
"""

from __future__ import annotations

import importlib
import importlib.util
import itertools
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from geotruth.geom import Geometry, MultiPolygon, Polygon

__all__ = [
    "OVERLAY_OPS",
    "PREDICATES",
    "EngineUnavailable",
    "ExactAnswer",
    "exact_answer",
    "geometry_area",
    "is_valid",
    "reference_module",
]

#: Overlay operations, as in schemas/expected.v2.
OVERLAY_OPS = ("intersection", "union", "difference", "symdifference")
#: Named predicates, as in schemas/expected.v2 (``contains`` = A contains B).
PREDICATES = (
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


class EngineUnavailable(RuntimeError):
    """Neither the engine nor a reference can answer this part for this input."""


# ============================================================================ imports


def _engine(module: str, func: str) -> Callable | None:
    """``geotruth.<module>.<func>`` if the engine provides it (a module that fails to
    import, for example while it is being written, counts as absent)."""
    try:
        mod = importlib.import_module(f"geotruth.{module}")
    except Exception:
        return None
    fn = getattr(mod, func, None)
    return fn if callable(fn) else None


_REF: dict[str, Any] = {}


def reference_module(name: str) -> Any | None:
    """``tests/reference/<name>.py`` as a module (None when the tests are absent)."""
    if name in _REF:
        return _REF[name]
    ref = Path(__file__).resolve().parents[3] / "tests" / "reference"
    mod = None
    if (ref / f"{name}.py").is_file():
        if str(ref) not in sys.path:
            sys.path.append(str(ref))
        try:
            mod = importlib.import_module(name)
        except Exception:  # pragma: no cover - a broken reference is simply unavailable
            mod = None
    _REF[name] = mod
    return mod


# ============================================================================ helpers


def _is_polygonal(g: Geometry) -> bool:
    return isinstance(g, (Polygon, MultiPolygon)) and not g.is_empty


def _v1(g: Geometry) -> list:
    """A Polygon/MultiPolygon as FORMAT-v1 coordinates (reference input)."""
    polys = [g] if isinstance(g, Polygon) else [p for p in g.polygons if not p.is_empty]
    return [[[[float(x), float(y)] for x, y in ring] for ring in p.rings] for p in polys]


def _fraction(q: Any) -> Fraction:
    if isinstance(q, Fraction):
        return q
    if isinstance(q, str):
        num, _, den = q.partition("/")
        return Fraction(int(num), int(den or 1))
    return Fraction(int(q.numerator), int(q.denominator))


def geometry_area(g: Geometry) -> Fraction:
    """Exact area of a geometry: the sum over its polygons of |shell| - sum |holes|
    (JTS ``getArea``); 0 for points and lines."""
    fn = _engine("measures", "area")
    if fn is not None:
        return _fraction(fn(g))
    total = Fraction(0)
    for e in g.elements():
        if isinstance(e, Polygon) and not e.is_empty:
            for k, ring in enumerate(e.rings):
                s = Fraction(0)
                for (x0, y0), (x1, y1) in itertools.pairwise(ring):
                    s += Fraction(x0) * Fraction(y1) - Fraction(x1) * Fraction(y0)
                total += abs(s) / 2 if k == 0 else -abs(s) / 2
    return total


def is_valid(g: Geometry) -> bool | None:
    """Exact GEOS-default validity, or None when no implementation covers the input."""
    fn = _engine("validity", "is_valid")
    if fn is not None:
        return bool(fn(g))
    ref = reference_module("validity")
    if ref is not None and _is_polygonal(g):
        return bool(ref.valid_geometry(_v1(g)))
    return None


# ============================================================================ answer


@dataclass
class ExactAnswer:
    """The exact answer of an ordered pair (A, B). Parts that could not be computed are
    None; ``sources`` says which implementation produced each part and ``notes`` why a
    part is missing."""

    valid_a: bool | None = None
    valid_b: bool | None = None
    relate: str | None = None
    predicates: dict[str, bool] | None = None
    conventions: list[str] = field(default_factory=list)
    dim_a: int | None = None
    dim_b: int | None = None
    areas: dict[str, Fraction] | None = None
    sources: dict[str, str] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        return self.valid_a is True and self.valid_b is True

    def field(self, path: str) -> Any:
        """The exact value of a result field path: ``relate``, ``valid_a``,
        ``predicates.<name>`` (or the bare name), ``area_<op>``/``overlay.<op>`` (the
        exact area), or ``area_a``/``area_b``."""
        if path in ("valid_a", "valid_b", "relate"):
            return getattr(self, path)
        name = path.split(".", 1)[1] if path.startswith("predicates.") else path
        if name in PREDICATES:
            return None if self.predicates is None else self.predicates.get(name)
        v1_areas = {
            "area_inter": "intersection",
            "area_union": "union",
            "area_diff": "difference",
            "area_symdiff": "symdifference",
        }
        if path.startswith("overlay."):
            name = path.split(".", 1)[1]
        name = v1_areas.get(name, name)
        if self.areas is not None and name in self.areas:
            return self.areas[name]
        return None


def _relate(a: Geometry, b: Geometry, ans: ExactAnswer) -> None:
    ans.dim_a, ans.dim_b = a.real_dimension, b.real_dimension
    fn = _engine("relate", "relate")
    if fn is not None:
        try:
            res = fn(a, b)
            if getattr(res, "status", "ok") == "ok" and getattr(res, "matrix", None):
                ans.relate = res.matrix
                ans.predicates = dict(res.predicates)
                ans.conventions = list(getattr(res, "conventions", []) or [])
                ans.sources["relate"] = "geotruth.relate"
                return
            ans.notes["relate.engine"] = f"{res.status}: {getattr(res, 'reason', '')}"
        except Exception as exc:  # the engine abstains; try the next route
            ans.notes["relate.engine"] = f"{type(exc).__name__}: {exc}"
    witness = _engine("relate_witness", "relate")
    evaluate = _engine("predicates", "evaluate")
    conv = _engine("predicates", "convention_fields")
    if witness is not None and evaluate is not None:
        try:
            m = witness(a, b)
            vals = evaluate(m, ans.dim_a, ans.dim_b)
            ans.relate = m
            ans.predicates = {k: bool(v.value) for k, v in vals.items()}
            ans.conventions = list(conv(ans.dim_a, ans.dim_b)) if conv else []
            ans.sources["relate"] = "geotruth.relate_witness"
            return
        except Exception as exc:
            ans.notes["relate.witness"] = f"{type(exc).__name__}: {exc}"
    oracle = reference_module("oracle")
    if oracle is not None and _is_polygonal(a) and _is_polygonal(b):
        res = oracle.evaluate({"id": "shim", "a": _v1(a), "b": _v1(b)})
        if res.get("valid_a") and res.get("valid_b"):
            preds = {k: bool(res[k]) for k in PREDICATES if k in res}
            preds["crosses"] = False  # never true for A/A
            ans.predicates = preds
            ans.sources["relate"] = "tests/reference/oracle.py (predicates only)"
            return
    ans.notes.setdefault("relate", "no relate implementation covers this input")


def _areas(a: Geometry, b: Geometry, ans: ExactAnswer) -> None:
    fn = _engine("overlay", "overlay")
    if fn is not None:
        try:
            out: dict[str, Fraction] = {}
            for op in OVERLAY_OPS:
                res = fn(a, b, op, "areal")
                area = res.get("area") if isinstance(res, dict) else getattr(res, "area", None)
                if area is None:
                    geom = res.get("geometry") if isinstance(res, dict) else res.geometry
                    area = geometry_area(geom)
                out[op] = _fraction(area)
            out["a"], out["b"] = geometry_area(a), geometry_area(b)
            ans.areas = out
            ans.sources["areas"] = "geotruth.overlay"
            return
        except Exception as exc:
            ans.notes["areas.engine"] = f"{type(exc).__name__}: {exc}"
    has_a = any(isinstance(e, Polygon) and not e.is_empty for e in a.elements())
    has_b = any(isinstance(e, Polygon) and not e.is_empty for e in b.elements())
    if not has_a or not has_b:
        # one side has no area: the areal overlay is the other side's polygonal part,
        # whose area is exact when it is a single valid Polygon/MultiPolygon
        other = b if not has_a else a
        if not (has_a or has_b):
            aa = ab = Fraction(0)
        elif _is_polygonal(other):
            aa = geometry_area(a) if has_a else Fraction(0)
            ab = geometry_area(b) if has_b else Fraction(0)
        else:
            ans.notes["areas"] = "polygonal part is not a single Polygon/MultiPolygon"
            return
        ans.areas = {
            "a": aa,
            "b": ab,
            "intersection": Fraction(0),
            "union": aa + ab,
            "difference": aa,
            "symdifference": aa + ab,
        }
        ans.sources["areas"] = "operand area (one operand has no area)"
        return
    oracle = reference_module("oracle")
    if oracle is not None and _is_polygonal(a) and _is_polygonal(b):
        res = oracle.evaluate({"id": "shim", "a": _v1(a), "b": _v1(b)})
        if res.get("valid_a") and res.get("valid_b"):
            ex = res["exact"]
            inter, da, db = (_fraction(ex[k]) for k in ("inter", "diff_ab", "diff_ba"))
            ans.areas = {
                "a": inter + da,
                "b": inter + db,
                "intersection": inter,
                "union": inter + da + db,
                "difference": da,
                "symdifference": da + db,
            }
            ans.sources["areas"] = "tests/reference/oracle.py"
            return
    ans.notes.setdefault("areas", "no overlay implementation covers this input")


def exact_answer(
    a: Geometry, b: Geometry, *, relate: bool = True, areas: bool = True
) -> ExactAnswer:
    """The exact answer of ``(a, b)``. Relate and areas are computed only when both
    operands are valid (they are not defined otherwise)."""
    ans = ExactAnswer()
    ans.valid_a, ans.valid_b = is_valid(a), is_valid(b)
    ans.sources["validity"] = (
        "geotruth.validity" if _engine("validity", "is_valid") else "tests/reference/validity.py"
    )
    if not ans.valid:
        ans.notes["relate"] = ans.notes["areas"] = "an operand is not valid"
        return ans
    if relate:
        _relate(a, b, ans)
    if areas:
        _areas(a, b, ans)
    return ans
