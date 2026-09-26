"""What every exporter shares: cases with their exact answers, WKT, names, headers."""

from __future__ import annotations

import itertools
import math
import re
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from geotruth import ENGINE_VERSION
from geotruth.export.answers import OVERLAY_OPS, PREDICATES, ExactAnswer, exact_answer
from geotruth.geom import Geometry, MultiPolygon, Polygon
from geotruth.io import format_double, geometry_from_json, to_wkt

__all__ = [
    "ExportCase",
    "ExportFile",
    "area_bounds",
    "area_double",
    "area_tolerance",
    "header",
    "prepare",
    "rounding_floor",
    "signed_ring_area",
    "slug",
    "wkt",
]


@dataclass
class ExportFile:
    """One output file: ``suffix`` is inserted before the extension when an export needs
    several files (empty for the first/only one)."""

    text: str
    suffix: str = ""
    skipped: list[str] = field(default_factory=list)


@dataclass
class ExportCase:
    id: str
    family: str
    a: Geometry
    b: Geometry
    answer: ExactAnswer
    tags: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)

    @property
    def polygonal(self) -> bool:
        return all(
            isinstance(g, (Polygon, MultiPolygon)) and not g.is_empty for g in (self.a, self.b)
        )

    def predicates(self) -> dict[str, bool]:
        """The predicates that do not depend on the empty-geometry convention table."""
        preds = self.answer.predicates or {}
        conv = {c.split(".", 1)[-1] for c in self.answer.conventions}
        return {k: preds[k] for k in PREDICATES if k in preds and k not in conv}

    def areas(self) -> dict[str, Fraction] | None:
        return self.answer.areas

    def area_scale(self) -> Fraction:
        ar = self.answer.areas or {}
        return max(ar.get("a", Fraction(0)), ar.get("b", Fraction(0)))

    def describe(self) -> str:
        bits = [self.id]
        if self.family:
            bits.append(f"family {self.family}")
        for key in ("degeneracy", "range"):
            if self.tags.get(key):
                bits.append(f"{key} {self.tags[key]}")
        src = self.provenance.get("source")
        if src in ("curated", "minimised"):
            who = self.provenance.get("finding") or self.provenance.get("lead")
            status = self.provenance.get("status")
            if who:
                bits.append(f"{src} {who}" + (f" ({status})" if status else ""))
            if self.provenance.get("issue_url"):
                bits.append(self.provenance["issue_url"])
        return "; ".join(bits)


def _to_typed(g: Any) -> Any:
    if isinstance(g, list):
        return (
            {"type": "Polygon", "coordinates": g[0]}
            if len(g) == 1
            else {
                "type": "MultiPolygon",
                "coordinates": g,
            }
        )
    return g


def prepare(records: list[dict], *, areas: bool = True) -> list[ExportCase]:
    """Cases (v2 records or FORMAT-v1 lines) with their exact answers."""
    out = []
    for r in records:
        a = geometry_from_json(_to_typed(r["a"]))
        b = geometry_from_json(_to_typed(r["b"]))
        ans = exact_answer(a, b, areas=areas)
        out.append(
            ExportCase(
                id=str(r["id"]),
                family=r.get("family", ""),
                a=a,
                b=b,
                answer=ans,
                tags=dict(r.get("tags") or {}),
                provenance=dict(r.get("provenance") or {}),
            )
        )
    return out


def wkt(g: Geometry) -> str:
    """WKT with shortest round-trip doubles (``2`` rather than ``2.0``)."""
    return to_wkt(g, trim=True)


def area_double(q: Fraction) -> str:
    """The correctly rounded double of an exact area, in shortest round-trip form."""
    return format_double(float(q))


def slug(case_id: str, prefix: str = "geotruth_") -> str:
    """A C/Rust/Python identifier for a case id."""
    s = re.sub(r"[^A-Za-z0-9]+", "_", case_id).strip("_").lower()
    return prefix + s


def signed_ring_area(ring: tuple) -> Fraction:
    """Exact signed area of a closed ring (positive = counter-clockwise)."""
    s = Fraction(0)
    for (x0, y0), (x1, y1) in itertools.pairwise(ring):
        s += Fraction(x0) * Fraction(y1) - Fraction(x1) * Fraction(y0)
    return s / 2


def rounding_floor(c: ExportCase) -> float:
    """ulp(max |coordinate|) * (perimeter A + perimeter B): the largest area change that
    rounding every output vertex to the nearest double can cause (corpus/generators
    common.rounding_floor). An area check tighter than this would flag rounding."""
    vals = [abs(float(v)) for g in (c.a, c.b) for v in g.iter_values()]
    m = max((v for v in vals if math.isfinite(v)), default=0.0)
    per = 0.0
    for g in (c.a, c.b):
        for e in g.elements():
            seqs = e.rings if isinstance(e, Polygon) else [getattr(e, "coords", ())]
            for seq in seqs:
                for (x0, y0), (x1, y1) in itertools.pairwise(seq):
                    per += math.hypot(float(x1) - float(x0), float(y1) - float(y0))
    return math.ulp(m) * per


def area_bounds(c: ExportCase, rel: float) -> tuple[float, float] | None:
    """(lo, hi): the admissible absolute tolerances of a case's area checks. ``lo`` is 4 x
    the rounding floor (a tighter check would flag correct, rounded output); ``hi`` is
    ``rel`` x the larger operand area, raised to 2 x ``lo`` where rounding needs it.
    None when there is no area, or when ``hi`` is half the area or more (the check could
    not even see half of it vanish; such areas are not evidence)."""
    scale = float(c.area_scale())
    if scale <= 0:
        return None
    lo = 4 * rounding_floor(c)
    hi = max(rel * scale, 2 * lo)
    return (lo, hi) if hi < scale / 2 else None


def area_tolerance(c: ExportCase, rel: float) -> float | None:
    """The absolute tolerance of a case's own area checks (``area_bounds`` upper end)."""
    b = area_bounds(c, rel)
    return None if b is None else b[1]


def header(fmt: str, cases: list[ExportCase], comment: str) -> list[str]:
    """Provenance lines (without comment markers) for the top of an export."""
    srcs = sorted({f"{k}: {v}" for c in cases for k, v in c.answer.sources.items()})
    lines = [
        f"geotruth export ({fmt}), engine {ENGINE_VERSION}: exact answers on the exact input",
        "doubles (DESIGN.md), so every expected value below is the true answer. Cases are CC0.",
        "Answers by " + "; ".join(srcs) + "." if srcs else "No answers.",
    ]
    if comment:
        lines.append(comment)
    return lines


#: Overlay operation -> the op used for the exported area check.
OPS = OVERLAY_OPS
