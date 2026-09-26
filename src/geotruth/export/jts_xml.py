"""JTS TestRunner / GEOS xmltester XML (``<run>`` files).

Each case becomes a ``<case>`` with the operands as WKT (shortest round-trip doubles, so
both readers get exactly the case's doubles) and one ``<test>`` per exact answer:

- ``relate`` with ``arg3`` = the exact DE-9IM matrix (expected ``true``);
- every named predicate whose value does not depend on the empty-geometry convention
  table: ``intersects``, ``disjoint``, ``touches``, ``crosses``, ``overlaps``,
  ``contains``, ``covers``, ``within``, ``coveredBy``, ``equalsTopo``;
- ``isValid`` of A and of B;
- overlay areas (DESIGN §5.6: overlay expectations become relate and area checks):
  ``unionArea`` of A and of B, and a companion case whose A is
  ``GEOMETRYCOLLECTION (A, B)`` with ``unionArea`` = area(A ∪ B). Together they fix all
  four overlay areas (area(A ∩ B) = area(A) + area(B) - area(A ∪ B), and so on). Both
  runners provide ``unionArea``; JTS compares doubles within the run's ``<tolerance>``
  (absolute), GEOS within a relative 1e-3.

Invalid cases get the validity tests only. JTS compares doubles within one absolute
``<tolerance>`` per run, so cases are grouped: a case's area checks admit tolerances from
4 x its double-rounding floor (ulp(max |coordinate|) x total perimeter, the most that
rounding the output vertices can change an area) up to ``rel`` (default 1e-6, as
``harness/compare.py``) x its larger operand area, or 8 x the floor where that is
larger (:func:`geotruth.export.common.area_bounds`). Cases whose ranges overlap share a
run; an export whose scales cannot share one tolerance is split into several files
(``.partN``). Cases whose tolerance would reach half their area get no area checks.
"""

from __future__ import annotations

from xml.sax.saxutils import escape

from geotruth.export.common import (
    ExportCase,
    ExportFile,
    area_bounds,
    area_double,
    header,
    wkt,
)

__all__ = ["OP_NAMES", "export"]

#: Schema predicate name -> JTS/GEOS test op name.
OP_NAMES = {
    "intersects": "intersects",
    "disjoint": "disjoint",
    "touches": "touches",
    "crosses": "crosses",
    "overlaps": "overlaps",
    "contains": "contains",
    "covers": "covers",
    "within": "within",
    "covered_by": "coveredBy",
    "equals": "equalsTopo",
}


def _bool(v: bool) -> str:
    return "true" if v else "false"


def _test(
    op: str, expected: str, arg1: str = "A", arg2: str | None = "B", arg3: str | None = None
) -> str:
    attrs = f'name="{op}"'
    if arg3 is not None:
        attrs += f' arg3="{arg3}"'
    attrs += f' arg1="{arg1}"'
    if arg2 is not None:
        attrs += f' arg2="{arg2}"'
    return f"  <test><op {attrs}>{expected}</op></test>"


def _case(c: ExportCase, with_areas: bool) -> list[str]:
    ans = c.answer
    out = ["<case>", f"  <desc>{escape(c.describe())}</desc>"]
    out.append(f"  <a>\n    {wkt(c.a)}\n  </a>")
    out.append(f"  <b>\n    {wkt(c.b)}\n  </b>")
    if ans.relate:
        out.append(_test("relate", "true", arg3=ans.relate))
    for name, value in c.predicates().items():
        out.append(_test(OP_NAMES[name], _bool(value)))
    if ans.valid_a is not None:
        out.append(_test("isValid", _bool(ans.valid_a), "A", None))
    if ans.valid_b is not None:
        out.append(_test("isValid", _bool(ans.valid_b), "B", None))
    ar = ans.areas if with_areas else None
    if ar is not None:
        if ar["a"] > 0:
            out.append(_test("unionArea", area_double(ar["a"]), "A", None))
        if ar["b"] > 0:
            out.append(_test("unionArea", area_double(ar["b"]), "B", None))
    out.append("</case>")
    if ar is not None and ar["union"] > 0:
        out += [
            "<case>",
            f"  <desc>{escape(c.id)}: area(A union B) = {escape(str(ar['union']))}, as "
            f"unionArea of GEOMETRYCOLLECTION (A, B)</desc>",
            f"  <a>\n    GEOMETRYCOLLECTION ({wkt(c.a)}, {wkt(c.b)})\n  </a>",
            _test("unionArea", area_double(ar["union"]), "A", None),
            "</case>",
        ]
    return out


def _groups(cases: list[ExportCase], rel: float) -> list[tuple[list[ExportCase], float | None]]:
    """Cases grouped under one run tolerance each: a case with area checks joins a group
    when its admissible interval [4 x rounding floor, rel x area scale] overlaps the
    group's; the group's tolerance is the smallest upper end. Cases without meaningful
    area checks join the first group."""
    bounds = {}
    for c in cases:
        if c.answer.areas is not None:
            b = area_bounds(c, rel)
            if b is not None:
                bounds[c.id] = b
    with_areas = sorted((c for c in cases if c.id in bounds), key=lambda c: bounds[c.id][1])
    groups: list[tuple[list[ExportCase], float | None]] = []
    for c in with_areas:
        lo, hi = bounds[c.id]
        if groups and lo <= groups[-1][1]:
            groups[-1][0].append(c)
        else:
            groups.append(([c], hi))
    rest = [c for c in cases if c.id not in bounds]
    if not groups:
        groups = [(rest, None)]
    else:
        groups[0] = (rest + groups[0][0], groups[0][1])
    order = {c.id: i for i, c in enumerate(cases)}
    return [(sorted(g, key=lambda c: order[c.id]), tol) for g, tol in groups]


def export(cases: list[ExportCase], *, rel: float = 1e-6, comment: str = "") -> list[ExportFile]:
    files = []
    groups = _groups(cases, rel)
    for k, (group, tol) in enumerate(groups):
        lines = ["<run>"]
        desc = header("JTS/GEOS XML", group, comment)
        if tol is not None:
            desc.append(
                f"Area checks: unionArea within the run tolerance {tol!r} (JTS; admissible "
                "for every case here: at least 4x its double-rounding floor, at most "
                f"max({rel!r} x its larger operand area, 8x the floor)) or 1e-3 relative "
                "(GEOS xmltester)."
            )
        lines.append("  <desc>\n    " + "\n    ".join(escape(d) for d in desc) + "\n  </desc>")
        lines.append('  <precisionModel type="FLOATING"/>')
        if tol is not None:
            lines.append(f"  <tolerance>{tol!r}</tolerance>")
        for c in group:
            meaningful = (
                tol is not None and c.answer.areas is not None and (area_bounds(c, rel) is not None)
            )
            lines += ["  " + ln if ln else ln for ln in _case(c, meaningful)]
        lines.append("</run>")
        suffix = "" if len(groups) == 1 else f".part{k + 1}"
        files.append(ExportFile("\n".join(lines) + "\n", suffix))
    return files
