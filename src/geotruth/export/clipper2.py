"""Clipper2 ``Tests/Polygons.txt`` blocks (integer-scaled).

Clipper64 works on int64 coordinates, so each polygonal case is scaled by 2^k, the
smallest k in 0..60 that makes every coordinate an integer: exact for doubles, as in the
adapter. Cases that need k > 60 or whose scaled coordinates reach 2^62, or whose scaled
area does not fit in int64, are skipped (outside Clipper64's range, "unsupported").

One block per overlay operation (INTERSECTION, UNION, DIFFERENCE, XOR), with
``FILLRULE: EVENODD`` (for valid OGC polygons it is the OGC point set whatever the ring
orientation), ``SOL_AREA`` = the exact area in scaled units rounded to an integer and
``SOL_COUNT: 0`` (not checked). ``SUBJECTS`` are A's rings, ``CLIPS`` B's, one path per
line as ``x,y, x,y, ...`` without the closing point. The test compares areas within 1 %
(TestPolygons.cpp); a block's ``CAPTION`` numbers are informational (the loader counts
captions), so renumber when appending to the upstream file. The scale stays the minimal
one, so the integer input is the case itself (Clipper2's documented small-triangle
removal depends on it); a caption notes when the output's grid rounding (up to about the
scaled perimeter, in square units) could exceed the 1 % tolerance on a small area.
"""

from __future__ import annotations

import itertools
import math
from fractions import Fraction

from geotruth.export.common import ExportCase, ExportFile, header
from geotruth.geom import MultiPolygon, Polygon

__all__ = ["CLIP_TYPES", "export", "scale_bits"]

CLIP_TYPES = {
    "intersection": "INTERSECTION",
    "union": "UNION",
    "difference": "DIFFERENCE",
    "symdifference": "XOR",
}
MAX_BITS = 60
MAX_COORD = 2**62
INT64_MAX = 2**63 - 1


def scale_bits(values) -> int | None:
    """The smallest k in 0..60 with every value * 2^k an integer below 2^62, or None."""
    k = 0
    for v in values:
        f = Fraction(v)
        d = f.denominator
        if d & (d - 1):
            return None
        k = max(k, d.bit_length() - 1)
    if k > MAX_BITS:
        return None
    if any(abs(Fraction(v)) * 2**k >= MAX_COORD for v in values):
        return None
    return k


def _paths(g) -> list[str]:
    polys = [g] if isinstance(g, Polygon) else list(g.polygons)
    return [ring for p in polys for ring in p.rings]


def export(cases: list[ExportCase], *, start: int = 1, comment: str = "") -> list[ExportFile]:
    lines = [f"# {ln}" for ln in header("Clipper2 Tests/Polygons.txt", cases, comment)]
    lines.append("# (Polygons.txt has no comment syntax: delete these lines before appending.)")
    lines.append("")
    n = start
    skipped: list[str] = []
    for c in cases:
        ar = c.answer.areas
        if not (c.polygonal and c.answer.valid and ar is not None):
            skipped.append(c.id)
            continue
        if not isinstance(c.a, (Polygon, MultiPolygon)):
            skipped.append(c.id)
            continue
        vals = [v for g in (c.a, c.b) for p in g.iter_coords() for v in p]
        k = scale_bits(vals)
        scale = 2**k if k is not None else None
        if scale is None or any(abs(ar[op]) * scale * scale > INT64_MAX for op in CLIP_TYPES):
            skipped.append(c.id)
            continue

        def path(ring, scale=scale):
            body = ring[:-1] if len(ring) > 1 and tuple(ring[0]) == tuple(ring[-1]) else ring
            return ", ".join(
                f"{int(Fraction(x) * scale)},{int(Fraction(y) * scale)}" for x, y in body
            )

        per = (
            sum(
                math.hypot(float(q[0] - p[0]), float(q[1] - p[1]))
                for g in (c.a, c.b)
                for ring in _paths(g)
                for p, q in itertools.pairwise(ring)
            )
            * scale
        )
        for op, ct in CLIP_TYPES.items():
            area = round(ar[op] * scale * scale)
            note = ""
            if area and per > 0.01 * abs(area):
                note = "; grid rounding of the output may exceed the 1 % area tolerance"
            lines += [
                f"CAPTION: {n}. geotruth {c.id} {op} (scale 2^{k}{note})",
                f"CLIPTYPE: {ct}",
                "FILLRULE: EVENODD",
                f"SOL_AREA: {area}",
                "SOL_COUNT: 0",
                "SUBJECTS",
                *(path(r) for r in _paths(c.a)),
                "CLIPS",
                *(path(r) for r in _paths(c.b)),
                "",
            ]
            n += 1
    if skipped:
        lines.append(
            "# skipped (not polygonal, invalid, or outside Clipper64's range): "
            + ", ".join(skipped)
        )
    return [ExportFile("\n".join(lines) + "\n", skipped=skipped)]
