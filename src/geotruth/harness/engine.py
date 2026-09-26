"""Exact answers for the harness, behind an import shim.

The engine's documented API (DESIGN §2) is used as soon as it exists:

- ``geotruth.relate.relate(a, b)`` -> an object with ``status``, ``matrix`` (or
  ``relate``), ``predicates``, ``conventions`` and ``reason`` (DESIGN §2.3);
- ``geotruth.overlay.overlay(a, b, op, variant)`` -> exact geometry, rational side-car and
  area (DESIGN §2.5), ``variant`` being ``"non_strict"`` or ``"areal"``.

Until then (or when a module is missing or its API does not match) it falls back to:

- relate: the witness-point relate (``geotruth.relate_witness``, DESIGN §2.4) with the
  dimension-dispatched predicates of ``geotruth.predicates``; for valid polygon/polygon
  input without it, the predicates of the audited ``tests/reference/oracle.py``;
- overlay: :mod:`geotruth.harness.fallback_overlay`, the exact overlay of valid polygonal
  operands from the boundary pieces of ``tests/reference/indep.py``, area-checked against
  it; other inputs get no exact overlay (``engine_skipped``).

Validity always comes from ``geotruth.validity`` (DESIGN §1, §2.7).

``GEOTRUTH_EXACT_BACKEND`` selects the route: ``auto`` (the default: the engine when it
answers through its documented API, else the fallbacks), ``engine`` (the engine only) or
``reference`` (the fallbacks only; ``oracle`` is accepted as an alias). The engine may
abstain (``engine_skipped``) or fail (``engine_error``); in ``auto`` mode that is reported,
never replaced by a fallback answer, because an abstention is an answer (DESIGN §0.5).

:func:`expected_record` assembles an ``expected.v2`` record for a case.
"""

from __future__ import annotations

import dataclasses
import importlib
import os
import subprocess
from dataclasses import dataclass, field
from fractions import Fraction
from functools import cache
from pathlib import Path
from typing import Any

from geotruth import ENGINE_VERSION
from geotruth.geom import Geometry, MultiPolygon, Polygon, empty_of_dimension
from geotruth.io import (
    Case,
    canonicalize,
    case_sha256,
    geometry_from_json,
    geometry_to_json,
    to_wkt,
)
from geotruth.numbers import format_rational, get_backend

__all__ = [
    "OVERLAY_OPS",
    "STATUS_ERROR",
    "STATUS_OK",
    "STATUS_SKIPPED",
    "VARIANTS",
    "OverlayAnswer",
    "RelateAnswer",
    "backends",
    "engine_info",
    "expected_record",
    "overlay_answers",
    "relate_answer",
    "route",
    "validity_answer",
]

OVERLAY_OPS = ("intersection", "union", "difference", "symdifference")
VARIANTS = ("non_strict", "areal")
STATUS_OK, STATUS_SKIPPED, STATUS_ERROR = "ok", "engine_skipped", "engine_error"
_ROUTES = ("auto", "engine", "reference")


def route() -> str:
    """The route chosen by ``GEOTRUTH_EXACT_BACKEND`` (auto, engine or reference)."""
    want = os.environ.get("GEOTRUTH_EXACT_BACKEND", "auto").strip().lower() or "auto"
    if want == "oracle":
        want = "reference"
    if want not in _ROUTES:
        raise ValueError(f"GEOTRUTH_EXACT_BACKEND={want!r}: use auto, engine or reference")
    return want


def _engine_fn(module: str, name: str) -> Any | None:
    try:
        mod = importlib.import_module(f"geotruth.{module}")
    except ImportError:
        return None
    fn = getattr(mod, name, None)
    return fn if callable(fn) else None


def backends() -> dict[str, str]:
    """Which implementation answers relate and overlay under the current route."""
    r = route()
    eng_rel = r != "reference" and _engine_fn("relate", "relate") is not None
    eng_ovl = r != "reference" and _engine_fn("overlay", "overlay") is not None
    return {
        "route": r,
        "relate": "geotruth.relate" if eng_rel else "geotruth.relate_witness (+ oracle)",
        "overlay": "geotruth.overlay" if eng_ovl else "fallback_overlay (tests/reference/indep)",
        "validity": "geotruth.validity",
    }


@cache
def _git_sha() -> str | None:
    root = Path(__file__).resolve().parents[3]
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and len(sha) >= 7 else None


def engine_info() -> dict[str, str]:
    """The ``engine`` object of expected records: version, git sha, rational backend."""
    info = {"version": ENGINE_VERSION, "backend": get_backend()}
    sha = _git_sha()
    if sha:
        info["sha"] = sha
    return info


def _field(obj: Any, *names: str) -> Any:
    for n in names:
        if isinstance(obj, dict):
            if n in obj:
                return obj[n]
        elif hasattr(obj, n):
            return getattr(obj, n)
    return None


# ============================================================================ relate


@dataclass
class RelateAnswer:
    """The exact relate of (A, B): ``status``, the DE-9IM ``matrix`` (None when the route
    has none), the reported ``predicates``, the convention-decided ``conventions`` and
    the ``route`` that answered."""

    status: str
    matrix: str | None
    predicates: dict[str, bool] | None
    conventions: list[str]
    dim_a: int
    dim_b: int
    route: str
    reason: str | None = None


def _predicates_dict(p: Any) -> dict[str, bool] | None:
    if p is None:
        return None
    if dataclasses.is_dataclass(p) and not isinstance(p, type):
        p = dataclasses.asdict(p)
    return {k: bool(getattr(v, "value", v)) for k, v in dict(p).items()}


def _relate_engine(a: Geometry, b: Geometry) -> RelateAnswer | None:
    fn = _engine_fn("relate", "relate")
    if fn is None:
        return None
    dims = (a.real_dimension, b.real_dimension)
    res = fn(a, b)
    status = _field(res, "status") or STATUS_OK
    reason = _field(res, "reason")
    if status != STATUS_OK:
        return RelateAnswer(status, None, None, [], *dims, "engine", reason)
    matrix = res if isinstance(res, str) else _field(res, "matrix", "relate")
    preds = None if isinstance(res, str) else _predicates_dict(_field(res, "predicates"))
    conventions = [] if isinstance(res, str) else list(_field(res, "conventions") or [])
    if not isinstance(matrix, str):
        raise TypeError("geotruth.relate.relate returned no matrix")
    if preds is None:
        from geotruth.predicates import convention_fields, predicates

        preds = predicates(matrix, *dims)
        conventions = convention_fields(*dims)
    return RelateAnswer(STATUS_OK, matrix, preds, conventions, *dims, "engine")


def _relate_reference(a: Geometry, b: Geometry) -> RelateAnswer:
    dims = (a.real_dimension, b.real_dimension)
    witness = _engine_fn("relate_witness", "relate")
    if witness is not None:
        from geotruth.predicates import convention_fields, predicates

        matrix = witness(a, b)
        return RelateAnswer(
            STATUS_OK, matrix, predicates(matrix, *dims), convention_fields(*dims), *dims, "witness"
        )
    if isinstance(a, (Polygon, MultiPolygon)) and isinstance(b, (Polygon, MultiPolygon)):
        from geotruth.harness.fallback_overlay import _v1, reference_module

        oracle = reference_module("oracle")
        res = oracle.evaluate({"id": "shim", "a": _v1(a), "b": _v1(b)})
        if res.get("valid_a") and res.get("valid_b"):
            names = (
                "intersects",
                "disjoint",
                "touches",
                "overlaps",
                "contains",
                "covers",
                "within",
                "covered_by",
                "equals",
            )
            preds = {k: bool(res[k]) for k in names}
            preds["crosses"] = False  # areal/areal (DESIGN §1)
            return RelateAnswer(STATUS_OK, None, preds, [], *dims, "oracle")
    return RelateAnswer(
        STATUS_SKIPPED, None, None, [], *dims, "none", "no relate implementation answers this input"
    )


def relate_answer(a: Geometry, b: Geometry) -> RelateAnswer:
    """The exact relate of valid operands (the caller checks validity)."""
    r = route()
    if r != "reference":
        try:
            ans = _relate_engine(a, b)
        except (TypeError, AttributeError) as exc:  # the engine's API does not match yet
            if r == "engine":
                raise
            ans = None
            _note(f"geotruth.relate did not answer through its API ({exc!r})")
        except ValueError:
            raise  # InvalidInputError: input outside the engine's contract
        except Exception as exc:  # an engine exception is an engine_error, never a fallback
            dims = (a.real_dimension, b.real_dimension)
            return RelateAnswer(
                STATUS_ERROR, None, None, [], *dims, "engine", f"{type(exc).__name__}: {exc}"
            )
        if ans is not None:
            return ans
        if r == "engine":
            raise RuntimeError("GEOTRUTH_EXACT_BACKEND=engine but geotruth.relate is missing")
    try:
        return _relate_reference(a, b)
    except Exception as exc:
        dims = (a.real_dimension, b.real_dimension)
        return RelateAnswer(
            STATUS_ERROR, None, None, [], *dims, "reference", f"{type(exc).__name__}: {exc}"
        )


_NOTES: list[str] = []


def _note(msg: str) -> None:
    if msg not in _NOTES:
        _NOTES.append(msg)


def notes() -> list[str]:
    """Messages about fallbacks taken so far (for provenance output)."""
    return list(_NOTES)


# ============================================================================ overlay


@dataclass
class OverlayAnswer:
    """One exact overlay result: ``geometry`` with exact rational coordinates, its
    ``area``; or ``status`` engine_skipped / engine_error with a ``reason``."""

    status: str
    geometry: Geometry | None = None
    area: Fraction | None = None
    route: str = ""
    reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        """The expected-answer ``OverlayResult`` object (``exact``, ``wkt``, ``area``,
        ``num_vertices``)."""
        assert self.geometry is not None
        g = self.geometry
        out: dict[str, Any] = {"exact": geometry_to_json(g, exact=True), "wkt": to_wkt(g)}
        if self.area is not None:
            out["area"] = format_rational(self.area)
        out["num_vertices"] = _num_vertices(g)
        return out


def _num_vertices(g: Geometry) -> int:
    n = 0
    for e in g.elements():
        if isinstance(e, Polygon):
            n += sum(max(len(r) - 1, 0) for r in e.rings)
        else:
            n += sum(1 for _ in e.iter_coords())
    return n


def _as_fraction(v: Any) -> Fraction:
    if isinstance(v, str):
        return Fraction(v)
    if isinstance(v, (int, float)):
        return Fraction(v)
    return Fraction(int(v.numerator), int(v.denominator))


def _polygon_area(g: Geometry) -> Fraction:
    total = Fraction(0)
    for e in g.elements():
        if isinstance(e, Polygon) and not e.is_empty:
            for k, ring in enumerate(e.rings):
                pts = [(_as_fraction(x), _as_fraction(y)) for x, y in ring]
                a2 = sum(
                    (
                        pts[i - 1][0] * pts[i][1] - pts[i][0] * pts[i - 1][1]
                        for i in range(len(pts))
                    ),
                    Fraction(0),
                )
                total += abs(a2) / 2 if k == 0 else -abs(a2) / 2
    return total


def _engine_overlay_one(fn: Any, a: Geometry, b: Geometry, op: str, variant: str) -> OverlayAnswer:
    res = fn(a, b, op, variant)
    status = _field(res, "status") or STATUS_OK
    if status != STATUS_OK:
        return OverlayAnswer(status, route="engine", reason=_field(res, "reason"))
    geom = res if isinstance(res, Geometry) else _field(res, "geometry", "exact", "result")
    if isinstance(geom, dict):
        geom = geometry_from_json(geom, exact=True)
    if not isinstance(geom, Geometry):
        raise TypeError("geotruth.overlay.overlay returned no geometry")
    area = None if isinstance(res, Geometry) else _field(res, "area")
    area = _polygon_area(geom) if area is None else _as_fraction(area)
    return OverlayAnswer(STATUS_OK, geom, area, "engine")


def _fallback_overlays(a: Geometry, b: Geometry) -> dict[str, dict[str, OverlayAnswer]]:
    from geotruth.harness.fallback_overlay import is_polygonal, overlay_all

    if not (is_polygonal(a) and is_polygonal(b)):
        why = (
            "no exact overlay for non-polygonal operands until geotruth.overlay lands "
            "(the fallback handles Polygon/MultiPolygon only)"
        )
        skipped = OverlayAnswer(STATUS_SKIPPED, route="fallback", reason=why)
        return {op: dict.fromkeys(VARIANTS, skipped) for op in OVERLAY_OPS}
    try:
        res = overlay_all(a, b)
    except Exception as exc:
        err = OverlayAnswer(STATUS_ERROR, route="fallback", reason=f"{type(exc).__name__}: {exc}")
        return {op: dict.fromkeys(VARIANTS, err) for op in OVERLAY_OPS}
    out: dict[str, dict[str, OverlayAnswer]] = {}
    for op, variants in res.items():
        out[op] = {
            v: OverlayAnswer(STATUS_OK, g, _polygon_area(g), "fallback")
            for v, g in variants.items()
        }
    return out


def overlay_answers(a: Geometry, b: Geometry) -> dict[str, dict[str, OverlayAnswer]]:
    """``{op: {variant: OverlayAnswer}}`` for the four operations and both variants, for
    valid operands (the caller checks validity)."""
    r = route()
    fn = None if r == "reference" else _engine_fn("overlay", "overlay")
    if fn is None and r == "engine":
        raise RuntimeError("GEOTRUTH_EXACT_BACKEND=engine but geotruth.overlay is missing")
    if fn is not None:
        out: dict[str, dict[str, OverlayAnswer]] = {}
        try:
            for op in OVERLAY_OPS:
                out[op] = {}
                for v in VARIANTS:
                    try:
                        out[op][v] = _engine_overlay_one(fn, a, b, op, v)
                    except (TypeError, AttributeError):
                        raise
                    except Exception as exc:
                        out[op][v] = OverlayAnswer(
                            STATUS_ERROR, route="engine", reason=f"{type(exc).__name__}: {exc}"
                        )
            return out
        except (TypeError, AttributeError) as exc:
            if r == "engine":
                raise
            _note(f"geotruth.overlay did not answer through its API ({exc!r})")
    return _fallback_overlays(a, b)


# ============================================================================ validity


def validity_answer(g: Geometry) -> dict[str, Any]:
    """The expected-answer ``Validity`` object of one operand."""
    from geotruth.validity import validate

    return validate(g).to_json()


# ============================================================================ records


def _typed_empty_result(op: str, a: Geometry, b: Geometry) -> Geometry:
    da, db = a.dimension, b.dimension
    dim = {"intersection": min(da, db), "difference": da}.get(op, max(da, db))
    return canonicalize(empty_of_dimension(dim))


@dataclass
class ExpectedInfo:
    """Side information of :func:`expected_record`: which route answered each part."""

    relate_route: str = ""
    overlay_route: str = ""
    notes: list[str] = field(default_factory=list)


def expected_record(
    case: Case, *, overlay: bool = True, info: ExpectedInfo | None = None
) -> dict[str, Any]:
    """The ``expected.v2`` record of a case: validity of both operands; for valid
    operands the relate matrix, the predicates with their conventions and (``overlay``)
    the four overlays in both variants. The engine may abstain: ``status`` is then
    ``engine_skipped`` or ``engine_error`` with a ``reason``."""
    a, b = case.a, case.b
    rec: dict[str, Any] = {
        "id": case.id,
        "case_sha256": case_sha256(case),
        "engine": engine_info(),
        "status": STATUS_OK,
    }
    rec["dimensions"] = {
        "a": {"dimension": a.dimension, "real_dimension": a.real_dimension},
        "b": {"dimension": b.dimension, "real_dimension": b.real_dimension},
    }
    try:
        va, vb = validity_answer(a), validity_answer(b)
    except Exception as exc:
        return _abstain(rec, STATUS_ERROR, f"validity: {type(exc).__name__}: {exc}")
    rec["validity"] = {"a": va, "b": vb}
    if not (va["valid"] and vb["valid"]):
        return rec
    try:
        rel = relate_answer(a, b)
    except ValueError as exc:
        return _abstain(rec, STATUS_ERROR, f"relate: input outside the engine's contract: {exc}")
    if info is not None:
        info.relate_route = rel.route
    if rel.status != STATUS_OK or rel.matrix is None:
        why = rel.reason or "no DE-9IM matrix from this route"
        return _abstain(rec, rel.status if rel.status != STATUS_OK else STATUS_SKIPPED, why)
    rec["relate"] = rel.matrix
    rec["predicates"] = rel.predicates
    if rel.conventions:
        rec["conventions"] = rel.conventions
    if overlay:
        answers = overlay_answers(a, b)
        ovl: dict[str, Any] = {}
        for op in OVERLAY_OPS:
            pair = answers[op]
            if all(pair[v].status == STATUS_OK for v in VARIANTS):
                ovl[op] = {}
                for v in VARIANTS:
                    ans = pair[v]
                    if ans.geometry is not None and ans.geometry.is_empty:
                        ans = dataclasses.replace(ans, geometry=_typed_empty_result(op, a, b))
                    ovl[op][v] = ans.to_json()
            elif info is not None:
                bad = next(pair[v] for v in VARIANTS if pair[v].status != STATUS_OK)
                info.notes.append(f"{case.id}: overlay.{op}: {bad.status}: {bad.reason}")
            if info is not None:
                info.overlay_route = pair["areal"].route
        if ovl:
            rec["overlay"] = ovl
    if info is not None:
        info.notes += notes()
    return rec


def _abstain(rec: dict[str, Any], status: str, reason: str) -> dict[str, Any]:
    keep = ("id", "case_sha256", "engine", "dimensions", "validity")
    out = {k: rec[k] for k in keep if k in rec}
    out["status"] = status
    out["reason"] = reason
    return out
