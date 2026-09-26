"""The ``engine_control`` and ``mutant`` adapters (DESIGN §7): geotruth's own exact
answers wrapped in adapter contract v2.

**engine_control** answers every field from the exact engine through the shim of
:mod:`geotruth.harness.engine` (the engine's documented API when it exists, the audited
references until then): relate and the predicates, validity, the non-strict overlay
results, and the parse-echo canary. Overlay output is the exact result with every
coordinate correctly rounded to a double (ties to even), so it grades as exact or within
the correctly rounded floor (tiers 1-2). When rounding makes the output invalid (a hole
within an ulp of its shell crosses it, a sliver collapses), the polygonal part is replaced
by the exact regularization (positive winding number) of its own rounded rings and rounded
again (:mod:`geotruth.harness.regularize`): the boundary moves by a few ulps only (the
manifest's delta is 3 ulp(M), so such output grades within the budget, tier 3), and parts
that collapse fit in the tube, which DESIGN §4.3 lets vanish. Relate, predicates and
overlay are ``"unsupported"`` when an input is invalid (the engine defines them for valid
input only) and ``null`` when the engine abstains. The control must score 100% (no
headline failure): anything else is a bug in the harness (runner, adapter runtime or
scorer), not in a library.

**mutant** is the control with deliberate faults, applied in input order: every 17th
reported predicate is negated (the 1st, 18th, 35th, ...), and every 17th non-empty
polygonal overlay output (the 1st, 18th, ...) has one vertex moved off its neighbours' chord
by 1/256 of the ring's extent or 2^-20 of its largest ordinate, whichever is larger (beyond
every library's δ). The scorer must catch every one of them.
"""

from __future__ import annotations

from typing import Any

from geotruth import ENGINE_VERSION
from geotruth.geom import Geometry
from geotruth.harness.pyadapter import OVERLAY_OPS, PREDICATES, Library, Session, Unsupported
from geotruth.io import geometry_from_json, geometry_to_json

__all__ = ["ControlLibrary", "MutantLibrary", "rounded_json"]


def _valid(g: Geometry) -> bool:
    from geotruth.validity import validate

    return validate(g).valid


def rounded_json(g: Geometry) -> dict[str, Any]:
    """Typed JSON of an exact geometry with every coordinate correctly rounded to a
    double, made valid where rounding broke validity (see
    :func:`geotruth.harness.regularize.round_valid`)."""
    from geotruth.harness.regularize import round_valid

    return round_valid(g)


class ControlSession(Session):
    def __init__(self, case: dict[str, Any]) -> None:
        self.a = geometry_from_json(case["a"])
        self.b = geometry_from_json(case["b"])
        self._validity: dict[str, bool] = {}
        self._relate: Any = None
        self._overlay: Any = None

    def _is_valid(self, which: str) -> bool:
        if which not in self._validity:
            self._validity[which] = _valid(self.a if which == "a" else self.b)
        return self._validity[which]

    def _require_valid(self) -> None:
        if not (self._is_valid("a") and self._is_valid("b")):
            raise Unsupported

    def run(self, path: str) -> Any:
        from geotruth.harness import engine

        if path == "echo":
            return {"a": geometry_to_json(self.a), "b": geometry_to_json(self.b)}
        if path in ("valid_a", "valid_b"):
            return self._is_valid(path[-1])
        self._require_valid()
        if path == "relate" or path.startswith("predicates."):
            if self._relate is None:
                self._relate = engine.relate_answer(self.a, self.b)
            ans = self._relate
            if ans.status != engine.STATUS_OK:
                return None
            if path == "relate":
                return ans.matrix
            return (ans.predicates or {}).get(path.split(".", 1)[1])
        if path.startswith("overlay."):
            if self._overlay is None:
                self._overlay = engine.overlay_answers(self.a, self.b)
            ans = self._overlay[path.split(".", 1)[1]]["non_strict"]
            if ans.status != engine.STATUS_OK or ans.geometry is None:
                return None
            return rounded_json(ans.geometry)
        return None


class ControlLibrary(Library):
    """geotruth's exact engine as an adapter."""

    lib = f"geotruth-control@{ENGINE_VERSION}"
    timeout_env = "CONTROL_ADAPTER_TIMEOUT"

    def session(self, case: dict[str, Any]) -> Session:
        return ControlSession(case)

    def version(self) -> str:
        return self.lib


def _first_ring(g: Any) -> list | None:
    """The first polygon ring with at least 4 positions of a typed-JSON geometry."""
    t = g.get("type") if isinstance(g, dict) else None
    if t == "Polygon":
        for r in g["coordinates"]:
            if len(r) >= 4:
                return r
    elif t == "MultiPolygon":
        for p in g["coordinates"]:
            for r in p:
                if len(r) >= 4:
                    return r
    elif t == "GeometryCollection":
        for e in g["geometries"]:
            r = _first_ring(e)
            if r is not None:
                return r
    return None


def _displaced(ring: list) -> list[float]:
    """``ring[1]`` moved off the chord ``ring[0]``-``ring[2]`` (perpendicular to it, so the
    ring's point set changes even where ``ring[1]`` is a collinear vertex) by the larger of
    1/256 of the ring's extent and 2^-20 of its largest ordinate: beyond every library's δ
    (the loosest, GEOS and JTS, is 1e-8 of the largest ordinate), so it cannot grade as
    within tolerance."""
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    extent = max(max(xs) - min(xs), max(ys) - min(ys))
    big = max(max(abs(v) for v in xs), max(abs(v) for v in ys))
    d = max(extent / 256, big * 2.0**-20)
    (x0, y0), (x1, y1), (x2, y2) = ring[0][:2], ring[1][:2], ring[2][:2]
    cx, cy = x2 - x0, y2 - y0
    norm = (cx * cx + cy * cy) ** 0.5
    if not norm or norm != norm or norm == float("inf"):
        return [x1 + d, y1]
    return [x1 - cy / norm * d, y1 + cx / norm * d]


class MutantLibrary(ControlLibrary):
    """The control with every 17th predicate negated and every 17th polygonal overlay
    output perturbed."""

    lib = f"geotruth-mutant@{ENGINE_VERSION}"
    timeout_env = "MUTANT_ADAPTER_TIMEOUT"
    EVERY = 17

    def __init__(self) -> None:
        self.n_predicates = 0
        self.n_overlays = 0
        #: (case id, field path) of every mutation, for tests
        self.mutations: list[tuple[str, str]] = []

    def postprocess(self, record: dict[str, Any], case: dict[str, Any] | None) -> dict[str, Any]:
        cid = record.get("id")
        preds = record.get("predicates")
        if isinstance(preds, dict):
            for name in PREDICATES:
                v = preds.get(name)
                if isinstance(v, bool):
                    if self.n_predicates % self.EVERY == 0:
                        preds[name] = not v
                        self.mutations.append((cid, f"predicates.{name}"))
                    self.n_predicates += 1
        ovl = record.get("overlay")
        if isinstance(ovl, dict):
            for op in OVERLAY_OPS:
                ring = _first_ring(ovl.get(op))
                if ring is None:
                    continue
                if self.n_overlays % self.EVERY == 0:
                    ring[1] = _displaced(ring)
                    self.mutations.append((cid, f"overlay.{op}"))
                self.n_overlays += 1
        return record
