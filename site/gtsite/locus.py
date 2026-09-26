"""Where to look: the view windows of the figures.

Each failure example gets an overview of both operands and, where the discrepancy is
smaller than the case, a view zoomed to it. How the zoomed window is chosen depends on
what is known about the discrepancy, and the figure caption says which rule was used:

- **overlay output** - the point of the library's output farthest from the exact result,
  or the point of the exact result farthest from the output (exact squared distances over
  the vertices and edge midpoints of both), whichever is farther; for invalid output, the
  first exact defect of the output;
- **relate** - for an entry the exact matrix has and the library misses, the arrangement
  cell that realises it (vertex, edge or face, exact coordinates), or the closest approach
  between A and B when that lies inside the cell's window and is much smaller; for an
  entry the library reports and the exact matrix lacks, the closest approach between A and B;
- **validity** - an exact defect of the operand when the library calls it valid; the
  closest approach between non-adjacent parts of the operand when the library calls a
  valid operand invalid;
- otherwise (predicates without a matrix, errors) - the closest approach between A and B
  (a heuristic: the corpus is built around one near-degenerate spot per case).

All distances are exact; the window size is a dyadic approximation of a square root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from fractions import Fraction

from gtsite.exact2d import P, Parts, bbox, closest_on_segment, dist2, nearest_in, sqrt_frac


@dataclass
class View:
    """A square window centred at (cx, cy) with half-width ``half``."""

    cx: Fraction
    cy: Fraction
    half: Fraction
    what: str = ""  # what the window shows and why (plain text)
    focus: list[P] = field(default_factory=list)  # points to ring in the figures
    heuristic: bool = False  # chosen by the closest-approach heuristic, not an exact locus

    @property
    def box(self) -> tuple[Fraction, Fraction, Fraction, Fraction]:
        return (self.cx - self.half, self.cy - self.half, self.cx + self.half, self.cy + self.half)


def overview(parts_list: list[Parts]) -> View | None:
    """The whole case with an 8% margin (None when nothing is drawable)."""
    bb = bbox(parts_list)
    if bb is None:
        return None
    x0, y0, x1, y1 = bb
    half = max(x1 - x0, y1 - y0) / 2
    if half == 0:
        half = max(abs(x0), abs(y0), Fraction(1)) / 4
    half = half * Fraction(27, 25)
    return View((x0 + x1) / 2, (y0 + y1) / 2, half, "the whole case")


def local_size(pt: P, parts_list: list[Parts]) -> Fraction | None:
    """Distance from pt to the nearest vertex different from it (None if there is none)."""
    best = None
    for parts in parts_list:
        for v in parts.vertices():
            if v == pt:
                continue
            d = dist2(pt, v)
            if best is None or d < best:
                best = d
    return None if best is None else sqrt_frac(best)


def around_point(pt: P, parts_list: list[Parts], what: str) -> View:
    size = local_size(pt, parts_list)
    ov = overview(parts_list)
    half = size / 3 if size else (ov.half / 4 if ov else Fraction(1))
    return View(pt[0], pt[1], half, what, [pt])


def around_points(pts: list[P], parts_list: list[Parts], what: str) -> View:
    if len(set(pts)) <= 1:
        return around_point(pts[0], parts_list, what)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    half = max(max(xs) - min(xs), max(ys) - min(ys)) / 2 * Fraction(13, 10)
    return View((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, half, what, list(pts))


def around_gap(
    p: P, q: P, d2: Fraction, what: str, factor: Fraction = Fraction(3), heuristic: bool = False
) -> View:
    """A window centred between p and q, ``factor`` times their distance wide (half)."""
    d = sqrt_frac(d2)
    return View((p[0] + q[0]) / 2, (p[1] + q[1]) / 2, d * factor, what, [p, q], heuristic)


# ============================================================================ searches


def closest_approach(pa: Parts, pb: Parts) -> tuple[Fraction, P, P] | None:
    """The smallest positive distance between A and B: ``(d², point of A, point of B)``;
    None when they are at distance 0 everywhere they come close, or one is empty. The
    minimum distance between two disjoint segments is attained at an endpoint of one of
    them, so vertex-to-segment and vertex-to-point distances suffice."""
    best: tuple[Fraction, P, P] | None = None

    def scan(src: Parts, dst: Parts, flip: bool) -> None:
        nonlocal best
        segs = dst.segments()
        pts = dst.points + [v for ln in dst.lines for v in (ln[0], ln[-1])]
        for v in src.vertices():
            for a, b in segs:
                q = closest_on_segment(v, a, b)
                d = dist2(v, q)
                if d > 0 and (best is None or d < best[0]):
                    best = (d, q, v) if flip else (d, v, q)
            for q in pts:
                d = dist2(v, q)
                if d > 0 and (best is None or d < best[0]):
                    best = (d, q, v) if flip else (d, v, q)

    scan(pa, pb, False)
    scan(pb, pa, True)
    return best


def contacts(pa: Parts, pb: Parts) -> list[P]:
    """Vertices of A on B's segments or points, and vice versa (exact)."""
    out: list[P] = []
    for src, dst in ((pa, pb), (pb, pa)):
        segs = dst.segments()
        pts = set(dst.points)
        for v in src.vertices():
            on = v in pts or any(dist2(v, closest_on_segment(v, a, b)) == 0 for a, b in segs)
            if on and v not in out:
                out.append(v)
    return out


def self_approach(parts: Parts) -> tuple[Fraction, P, P] | None:
    """The smallest positive distance between a vertex and a segment of the same geometry
    that does not end at that vertex: where a library may see a self-intersection."""
    best: tuple[Fraction, P, P] | None = None
    segs = parts.ring_segments()
    for v in parts.vertices():
        for _, _, _, (a, b) in segs:
            if a == v or b == v:
                continue
            q = closest_on_segment(v, a, b)
            d = dist2(v, q)
            if d > 0 and (best is None or d < best[0]):
                best = (d, v, q)
    return best


def _probe_points(parts: Parts) -> list[P]:
    pts = list(parts.vertices())
    for a, b in parts.segments():
        pts.append(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    return pts


def deviation(exact: Parts, lib: Parts) -> tuple[Fraction, P, P, str] | None:
    """The largest distance from a vertex or edge midpoint of one geometry to the point
    set of the other: ``(d², point, nearest point of the other, "library" | "exact")``,
    where the last item names the geometry the point belongs to. None if either is empty."""
    if exact.empty or lib.empty:
        return None
    best: tuple[Fraction, P, P, str] | None = None
    for src, dst, name in ((lib, exact, "library"), (exact, lib, "exact")):
        for p in _probe_points(src):
            near = nearest_in(p, dst)
            if near is None:
                continue
            d, q = near
            if best is None or d > best[0]:
                best = (d, p, q, name)
    return best
