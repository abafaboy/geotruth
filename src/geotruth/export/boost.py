"""Boost.Geometry test snippets in the style of ``test/algorithms/overlay/overlay_cases.hpp``.

For every case with polygonal operands:

- a ``static std::string geotruth_<id>[2]`` definition (for ``overlay_cases.hpp``), with
  shells clockwise and holes counter-clockwise, closed: Boost's default
  ``model::polygon<point_xy<double>>``;
- test lines for the set-operation tests, with counts unchecked (``-1``) and the exact
  areas as the expectation (Boost's ``expectation_limits`` compare within the test's
  percentage):
  ``TEST_INTERSECTION(case, -1, -1, area)`` (intersection.cpp),
  ``TEST_UNION(case, -1, -1, -1, area)`` (union.cpp),
  ``TEST_DIFFERENCE(case, -1, area(A-B), -1, area(B-A), -1)`` (difference.cpp);
- a relate test line ``test_geometry<poly, poly>(a, b, "matrix")`` (relate tests).

Cases with other operand types get the relate line only, with the type names the relate
tests use (``pt``, ``ls``, ``poly``, ``mpt``, ``mls``, ``mpoly``); GeometryCollections and
empty operands are skipped (Boost has no GeometryCollection relate).
"""

from __future__ import annotations

from geotruth.export.common import (
    ExportCase,
    ExportFile,
    area_double,
    header,
    signed_ring_area,
    slug,
)
from geotruth.geom import (
    Geometry,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from geotruth.io import format_double

__all__ = ["export"]

_TYPE = {
    Point: "pt",
    LineString: "ls",
    Polygon: "poly",
    MultiPoint: "mpt",
    MultiLineString: "mls",
    MultiPolygon: "mpoly",
}


def _num(v: float) -> str:
    return format_double(float(v), trim=True)


def _ring(ring: tuple, clockwise: bool) -> str:
    pts = list(ring)
    if (signed_ring_area(tuple(pts)) > 0) == clockwise:
        pts = pts[::-1]
    return "(" + ",".join(f"{_num(x)} {_num(y)}" for x, y in pts) + ")"


def _poly(p: Polygon) -> str:
    rings = [_ring(p.rings[0], True)] + [_ring(h, False) for h in p.rings[1:]]
    return "(" + ",".join(rings) + ")"


def boost_wkt(g: Geometry) -> str:
    """Boost-style WKT (no space after the type, no space after commas) with the
    orientation of Boost's default polygon type."""
    if isinstance(g, Polygon):
        return "POLYGON" + _poly(g)
    if isinstance(g, MultiPolygon):
        return "MULTIPOLYGON(" + ",".join(_poly(p) for p in g.polygons) + ")"
    if isinstance(g, Point):
        return f"POINT({_num(g.coord[0])} {_num(g.coord[1])})"
    if isinstance(g, LineString):
        return "LINESTRING(" + ",".join(f"{_num(x)} {_num(y)}" for x, y in g.coords) + ")"
    if isinstance(g, MultiPoint):
        return (
            "MULTIPOINT("
            + ",".join(f"({_num(p.coord[0])} {_num(p.coord[1])})" for p in g.points)
            + ")"
        )
    if isinstance(g, MultiLineString):
        return (
            "MULTILINESTRING("
            + ",".join(
                "(" + ",".join(f"{_num(x)} {_num(y)}" for x, y in ln.coords) + ")" for ln in g.lines
            )
            + ")"
        )
    raise TypeError(g.geom_type)


def _supported(g: Geometry) -> bool:
    return type(g) in _TYPE and not g.is_empty and not any(e.is_empty for e in g.elements())


def export(cases: list[ExportCase], *, comment: str = "") -> list[ExportFile]:
    lines = ["// " + ln for ln in header("Boost.Geometry", cases, comment)]
    lines.append("// Paste the definitions into test/algorithms/overlay/overlay_cases.hpp and the")
    lines.append("// test lines into the named test files. Areas are the exact areas rounded to")
    lines.append("// double; counts are not checked (-1).")
    skipped: list[str] = []
    defs, inter, union, diff, relate = [], [], [], [], []
    for c in cases:
        if not (_supported(c.a) and _supported(c.b)) or not c.answer.valid:
            skipped.append(c.id)
            continue
        name = slug(c.id)
        ar = c.answer.areas
        if c.polygonal and ar is not None:
            defs += [
                f"// {c.describe()}",
                f"static std::string {name}[2] = {{",
                f'        "{boost_wkt(c.a)}",',
                f'        "{boost_wkt(c.b)}" }};',
                "",
            ]
            inter.append(
                f"    TEST_INTERSECTION({name}, -1, -1, {area_double(ar['intersection'])});"
            )
            union.append(f"    TEST_UNION({name}, -1, -1, -1, {area_double(ar['union'])});")
            diff.append(
                f"    TEST_DIFFERENCE({name}, -1, {area_double(ar['difference'])}, -1, "
                f"{area_double(ar['b'] - ar['intersection'])}, -1);"
            )
        if c.answer.relate:
            relate += [
                f"    // {c.id}",
                f"    test_geometry<{_TYPE[type(c.a)]}, {_TYPE[type(c.b)]}>(",
                f'        "{boost_wkt(c.a)}",',
                f'        "{boost_wkt(c.b)}",',
                f'        "{c.answer.relate}");',
            ]
    if defs:
        lines += ["", "// ---- test/algorithms/overlay/overlay_cases.hpp", "", *defs]
        lines += [
            "// ---- test/algorithms/set_operations/intersection/intersection.cpp",
            *inter,
            "",
        ]
        lines += ["// ---- test/algorithms/set_operations/union/union.cpp", *union, ""]
        lines += ["// ---- test/algorithms/set_operations/difference/difference.cpp", *diff, ""]
    if relate:
        lines += ["// ---- test/algorithms/relate/relate_*.cpp (inside test_all<P>())", *relate, ""]
    if skipped:
        lines.append(
            "// skipped (GeometryCollection, empty or invalid operands): " + ", ".join(skipped)
        )
    return [ExportFile("\n".join(lines) + "\n", skipped=skipped)]
