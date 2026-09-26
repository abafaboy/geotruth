"""Rust ``#[test]`` functions for georust/geo, with the operands as ``geo::wkt!`` literals.

Each case becomes one test: ``relate`` against the exact matrix
(``IntersectionMatrix::matches``), every convention-free named predicate through the
matrix accessors (``is_intersects``, ``is_within``, ...), ``Validation::is_valid`` of both
operands and, for Polygon/MultiPolygon operands, the four ``BooleanOps`` areas
(``unsigned_area``) within ``rel`` (default 1e-6) of the larger operand area (no area
checks where that is below 4 x the double-rounding floor).

Coordinates are Rust float literals in shortest round-trip form (``wkt!`` needs floats,
so ``2`` is written ``2.0``). ``wkt!`` cannot express empty points, so cases with empty
elements are skipped, as are cases with non-finite coordinates.
"""

from __future__ import annotations

from geotruth.export.common import (
    ExportCase,
    ExportFile,
    area_double,
    area_tolerance,
    header,
    slug,
)
from geotruth.geom import (
    Geometry,
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)

__all__ = ["export", "rust_wkt"]

_ACCESSOR = {
    "intersects": "is_intersects",
    "disjoint": "is_disjoint",
    "touches": "is_touches",
    "crosses": "is_crosses",
    "overlaps": "is_overlaps",
    "contains": "is_contains",
    "covers": "is_covers",
    "within": "is_within",
    "covered_by": "is_coveredby",
    "equals": "is_equal_topo",
}


def _f(v: float) -> str:
    return repr(float(v))


def _pt(c) -> str:
    return f"{_f(c[0])} {_f(c[1])}"


def _seq(cs) -> str:
    return "(" + ", ".join(_pt(c) for c in cs) + ")"


def rust_wkt(g: Geometry) -> str:
    """WKT for ``geo::wkt!`` (float literals everywhere)."""
    if isinstance(g, Point):
        return f"POINT({_pt(g.coord)})"
    if isinstance(g, LineString):
        return "LINESTRING" + _seq(g.coords)
    if isinstance(g, Polygon):
        return "POLYGON(" + ", ".join(_seq(r) for r in g.rings) + ")"
    if isinstance(g, MultiPoint):
        return "MULTIPOINT(" + ", ".join(_pt(p.coord) for p in g.points) + ")"
    if isinstance(g, MultiLineString):
        return "MULTILINESTRING(" + ", ".join(_seq(ln.coords) for ln in g.lines) + ")"
    if isinstance(g, MultiPolygon):
        return (
            "MULTIPOLYGON("
            + ", ".join("(" + ", ".join(_seq(r) for r in p.rings) + ")" for p in g.polygons)
            + ")"
        )
    if isinstance(g, GeometryCollection):
        return "GEOMETRYCOLLECTION(" + ", ".join(rust_wkt(x) for x in g.geometries) + ")"
    raise TypeError(g.geom_type)


def _supported(g: Geometry) -> bool:
    return not g.is_empty and not any(e.is_empty for e in g.elements()) and not g.has_nonfinite


def export(cases: list[ExportCase], *, rel: float = 1e-6, comment: str = "") -> list[ExportFile]:
    lines = ["// " + ln for ln in header("georust/geo #[test]", cases, comment)]
    lines += [
        "#![allow(clippy::bool_assert_comparison)]",
        "use geo::{wkt, Area, BooleanOps, Relate, Validation};",
        "",
    ]
    skipped: list[str] = []
    for c in cases:
        if not (_supported(c.a) and _supported(c.b)):
            skipped.append(c.id)
            continue
        body = [
            f"/// {c.describe()}",
            "#[test]",
            f"fn {slug(c.id)}() {{",
            f"    let a = wkt! {{ {rust_wkt(c.a)} }};",
            f"    let b = wkt! {{ {rust_wkt(c.b)} }};",
        ]
        ans = c.answer
        if ans.valid_a is not None:
            body.append(f'    assert_eq!(a.is_valid(), {str(ans.valid_a).lower()}, "valid_a");')
        if ans.valid_b is not None:
            body.append(f'    assert_eq!(b.is_valid(), {str(ans.valid_b).lower()}, "valid_b");')
        if ans.valid and (ans.relate or c.predicates()):
            body.append("    let im = a.relate(&b);")
            if ans.relate:
                body.append(
                    f'    assert!(im.matches("{ans.relate}").unwrap(), '
                    f'"relate: expected {ans.relate}, got {{:?}}", im);'
                )
            for name, value in c.predicates().items():
                body.append(
                    f'    assert_eq!(im.{_ACCESSOR[name]}(), {str(value).lower()}, "{name}");'
                )
        ar = ans.areas
        tol = area_tolerance(c, rel) if ar is not None else None
        if ans.valid and tol is not None and c.polygonal:
            body.append(f"    let tol: f64 = {tol!r};")
            for op, call in (
                ("intersection", "a.intersection(&b)"),
                ("union", "a.union(&b)"),
                ("difference", "a.difference(&b)"),
                ("symdifference", "a.xor(&b)"),
            ):
                want = area_double(ar[op])
                body.append(
                    f"    let got: f64 = {call}.unsigned_area();\n"
                    f'    assert!((got - {want}).abs() <= tol, "{op} area: expected {want}, '
                    f'got {{}}", got);'
                )
        body.append("}")
        lines += [*body, ""]
    if skipped:
        lines.append("// skipped (empty elements or non-finite coordinates): " + ", ".join(skipped))
    return [ExportFile("\n".join(lines) + "\n", skipped=skipped)]
