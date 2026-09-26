"""DE-9IM from witness points: the independent second relate (DESIGN §2.4).

The arrangement route (§2.3) labels the cells of a DCEL. This route never builds one. It
generates a finite set of *witness points* that meets every cell of the planar
subdivision induced by A and B, locates each witness directly in the **original** A and B
with the standalone point locator (:mod:`geotruth.locate`), and takes

    M[a][b] = max { dim(w) : w a witness located a in A and b in B },    EE = 2,

where ``dim(w)`` is the dimension of the cell the witness stands for. It shares only the
primitives of §2.1 (:mod:`geotruth.exact`, :mod:`geotruth.numbers`, :mod:`geotruth.geom`)
with the arrangement route; every expected matrix must match between the two.

Why the witnesses see every cell
--------------------------------
Pool the segments of every ring and line of both operands and the isolated vertices
(Point elements, zero-length lines). Split every segment at its endpoints, at every
intersection with another segment (proper crossings, touches, T-junctions, the ends of
collinear overlaps) and at every isolated vertex lying on it. Then:

- **0-cells** are the input vertices and the intersection points: each is a witness of
  dimension 0.
- **1-cells** are the open sub-segments between consecutive split points. A sub-segment
  contains no split point, so no ring or line of either operand crosses, touches or
  ends inside it, and both locations are constant along it: its midpoint is a witness of
  dimension 1. Collinear overlapping segments yield the same sub-segments (they are split
  at each other's endpoints), so midpoints are deduplicated.
- **2-cells** (faces) all have a sub-segment on their boundary (unless there are no
  segments at all, and then only EE exists). Each sub-segment gets a witness of
  dimension 2 on *each* side, found in two independent exact ways:

  * **normal offset** -- ``m +- s n`` for the sub-segment's midpoint ``m`` and normal
    ``n``, with the step ``s = 2**-k`` chosen so that ``|s n|`` is smaller than the exact
    distance from ``m`` to every feature not through ``m`` (all other segments and
    isolated vertices). The open disk around ``m`` of that radius meets only the
    sub-segment's own line, so each offset point lies strictly inside the face on its
    side.
  * **axis ray** -- a ray from ``m`` along +x and -x (along +y and -y for a horizontal
    sub-segment), the nearest exact hit of any feature along it, and the midpoint of
    ``m`` and that hit (or a unit step when nothing is hit). The open ray segment is
    free of features, so this point lies in the same face as the offset point on the
    same side.

  With ``check=True`` (the default) both are generated and must be located identically
  on each side; a mismatch raises :class:`WitnessRelateError` (an engine bug, never a
  library failure). A point beyond the bounding box of both operands must locate
  Exterior/Exterior, which is checked too.

Locations are constant on faces as well: a face meets no ring, line or point of either
operand, so under the rules of DESIGN §1 (polygonal union, Mod-2 lines, points) its
location in each operand cannot change inside it.

Coordinates are integers of one per-case :class:`~geotruth.locate.Frame` (the dyadic
scale for double input); witnesses are canonical homogeneous triples. Everything is
exact. The cost is O(S^2) for S segments plus O((S + K) S) for K split points (pairs are
pruned by an x-sorted sweep): meant for the small and medium cases of the cross-checks,
not for the large tier.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import pairwise
from typing import Any

from geotruth.exact import (
    OVERLAP,
    POINT,
    HPoint,
    hp_midpoint,
    hp_orient,
    hpoint,
    intersect_segments,
    ratio_cmp,
    sort_along,
    sqdist_point_segment,
)
from geotruth.geom import Geometry, LineString, Point, Polygon
from geotruth.locate import (
    EXTERIOR,
    LOCATION_CHARS,
    Frame,
    PointLocator,
    safe_step_exponent,
)
from geotruth.numbers import format_rational
from geotruth.predicates import PredicateValue, evaluate

__all__ = [
    "ENTRY_NAMES",
    "KIND_EDGE",
    "KIND_FACE_NORMAL",
    "KIND_FACE_RAY",
    "KIND_FAR",
    "KIND_INTERSECTION",
    "KIND_VERTEX",
    "SubSegment",
    "Witness",
    "WitnessRelate",
    "WitnessRelateError",
    "relate",
    "relate_witness",
]

KIND_VERTEX = "vertex"
KIND_INTERSECTION = "intersection"
KIND_EDGE = "edge"
KIND_FACE_NORMAL = "face-normal"
KIND_FACE_RAY = "face-ray"
KIND_FAR = "far"

#: Names of the nine matrix entries in row order.
ENTRY_NAMES: tuple[str, ...] = tuple(r + c for r in "IBE" for c in "IBE")

IntPoint = tuple[int, int]
Segment = tuple[IntPoint, IntPoint]


class WitnessRelateError(RuntimeError):
    """An internal consistency check of the witness route failed (an engine bug)."""


@dataclass(frozen=True)
class Witness:
    """A located witness: a canonical homogeneous point of the frame, the dimension of
    the cell it stands for, how it was made, and its locations in A and in B
    (0 = Interior, 1 = Boundary, 2 = Exterior)."""

    point: HPoint
    dim: int
    kind: str
    loc_a: int
    loc_b: int

    @property
    def label(self) -> str:
        """Two letters: the location in A, then in B (``"IE"``, ...)."""
        return LOCATION_CHARS[self.loc_a] + LOCATION_CHARS[self.loc_b]


@dataclass(frozen=True)
class SubSegment:
    """An open sub-segment between consecutive split points, with its midpoint and the
    integer direction of the source segment it lies on."""

    start: HPoint
    end: HPoint
    mid: HPoint
    direction: IntPoint


@dataclass
class WitnessRelate:
    """The result of :func:`relate_witness`.

    ``matrix`` is the DE-9IM string; ``dim_a``/``dim_b`` the operands' real dimensions;
    ``realizers`` maps every non-``F`` entry name (``"II"``, ``"IB"``, ...) to a witness
    that realises its dimension (EE may be realised by the far point); ``counts`` counts
    the witnesses by kind; ``witnesses`` holds all of them when requested.
    """

    matrix: str
    dim_a: int
    dim_b: int
    frame: Frame
    realizers: dict[str, Witness]
    counts: dict[str, int]
    num_segments: int
    num_subsegments: int
    num_intersections: int
    witnesses: tuple[Witness, ...] = field(default=(), repr=False)

    def entry(self, name: str) -> int:
        """The entry ``name`` (e.g. ``"BI"``) as a dimension, -1 for ``F``."""
        ch = self.matrix[ENTRY_NAMES.index(name)]
        return -1 if ch == "F" else int(ch)

    def real_point(self, w: Witness) -> tuple[Fraction, Fraction]:
        """The real coordinates of a witness."""
        return self.frame.to_fractions(w.point)

    def predicates(self) -> dict[str, PredicateValue]:
        """The named predicates (DESIGN §1 dispatch and convention table)."""
        return evaluate(self.matrix, self.dim_a, self.dim_b)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready summary: matrix, real dimensions, a realising witness per entry
        (exact coordinates as ``"n/d"`` strings) and witness counts."""
        entries = {}
        for name, w in sorted(self.realizers.items()):
            x, y = self.real_point(w)
            entries[name] = {
                "dim": w.dim,
                "kind": w.kind,
                "point": [format_rational(x), format_rational(y)],
            }
        return {
            "matrix": self.matrix,
            "dim_a": self.dim_a,
            "dim_b": self.dim_b,
            "entries": entries,
            "counts": dict(sorted(self.counts.items())),
            "segments": self.num_segments,
            "subsegments": self.num_subsegments,
            "intersections": self.num_intersections,
        }


# ============================================================================ inputs


def _closed(coords: list[IntPoint]) -> list[IntPoint]:
    if coords and coords[0] != coords[-1]:
        coords = [*coords, coords[0]]
    return coords


def _collect(frame: Frame, geoms: Iterable[Geometry]) -> tuple[list[Segment], set[IntPoint]]:
    """Unique non-degenerate segments (endpoints in lexicographic order) and every
    vertex of the operands, in frame integers."""
    segs: set[Segment] = set()
    verts: set[IntPoint] = set()
    to_pt = frame.to_int_point
    for g in geoms:
        for e in g.elements():
            if e.is_empty:
                continue
            if isinstance(e, Polygon):
                chains = [_closed([to_pt(c) for c in r]) for r in e.rings if r]
            elif isinstance(e, LineString):
                chains = [[to_pt(c) for c in e.coords]]
            elif isinstance(e, Point):
                verts.add(to_pt(e.coord))
                continue
            else:  # pragma: no cover - elements() yields only atomic types
                raise TypeError(f"unexpected element {e!r}")
            for chain in chains:
                verts.update(chain)
                for p, q in pairwise(chain):
                    if p != q:
                        segs.add((p, q) if p < q else (q, p))
    return sorted(segs), verts


# ============================================================================ noding


def _node(
    segs: list[Segment], isolated: list[IntPoint], vertices: set[IntPoint]
) -> tuple[list[set[HPoint]], set[HPoint]]:
    """Split points of every segment (beyond its endpoints) and the intersection points
    that are not input vertices, from all pairs of segments and isolated vertices."""
    items = []  # (xmin, xmax, ymin, ymax, p, q, index or -1 for an isolated vertex)
    for i, (p, q) in enumerate(segs):
        items.append((p[0], q[0], min(p[1], q[1]), max(p[1], q[1]), p, q, i))
    for v in isolated:
        items.append((v[0], v[0], v[1], v[1], v, v, -1))
    items.sort(key=lambda t: t[0])
    split: list[set[HPoint]] = [set() for _ in segs]
    crossings: set[HPoint] = set()
    n = len(items)
    for i in range(n):
        _, xmax_i, ymin_i, ymax_i, p, q, si = items[i]
        for j in range(i + 1, n):
            xmin_j, _, ymin_j, ymax_j, r, s, sj = items[j]
            if xmin_j > xmax_i:
                break
            if ymin_j > ymax_i or ymin_i > ymax_j or (si < 0 and sj < 0):
                continue
            res = intersect_segments(p, q, r, s)
            if res.kind == POINT:
                pt = res.points[0]
                if si >= 0:
                    split[si].add(pt)
                if sj >= 0:
                    split[sj].add(pt)
                if not (pt[2] == 1 and (pt[0], pt[1]) in vertices):
                    crossings.add(pt)
            elif res.kind == OVERLAP:
                for pt in res.points:
                    split[si].add(pt)
                    split[sj].add(pt)
    return split, crossings


def _subsegments(segs: list[Segment], split: list[set[HPoint]]) -> list[SubSegment]:
    """Every open sub-segment between consecutive split points, deduplicated."""
    out: dict[HPoint, SubSegment] = {}
    for (p, q), pts in zip(segs, split, strict=True):
        ordered = sort_along(p, q, [(p[0], p[1], 1), (q[0], q[1], 1), *pts])
        d = (q[0] - p[0], q[1] - p[1])
        for u, v in pairwise(ordered):
            m = hp_midpoint(u, v)
            if m not in out:
                out[m] = SubSegment(u, v, m, d)
    return list(out.values())


# ============================================================================ faces


class _Features:
    """Every segment and isolated vertex, for exact nearest-feature queries."""

    def __init__(self, segs: list[Segment], isolated: list[IntPoint]) -> None:
        self.segs = segs
        self.boxes = [
            (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1])) for p, q in segs
        ]
        self.isolated = isolated

    def nearest_sqdist(self, m: HPoint) -> tuple[int, int] | None:
        """``(W * d)**2`` as ``(num, den)`` for the distance ``d`` from ``m`` to the
        nearest feature not through ``m`` (None if every feature passes through ``m``)."""
        x, y, w = m
        best: tuple[int, int] | None = None
        for v in self.isolated:
            dx, dy = v[0] * w - x, v[1] * w - y
            cand = (dx * dx + dy * dy, 1)
            if best is None or ratio_cmp(cand, best) < 0:
                best = cand
        for (a, b), (x0, y0, x1, y1) in zip(self.segs, self.boxes, strict=True):
            if best is not None:  # prune by the distance to the bounding box
                bx = max(x0 * w - x, 0, x - x1 * w)
                by = max(y0 * w - y, 0, y - y1 * w)
                if ratio_cmp((bx * bx + by * by, 1), best) >= 0:
                    continue
            cand = _sqdist_scaled(m, a, b)
            if cand[0] == 0:
                continue  # a segment through m: it carries the sub-segment itself
            if best is None or ratio_cmp(cand, best) < 0:
                best = cand
        return best

    def ray_hit(self, m: HPoint, axis: int, sign: int) -> tuple[int, int] | None:
        """The nearest ``t > 0`` at which the ray ``m + t * sign * e_axis`` meets a
        feature, as ``t * W = num / den`` (``den > 0``), or None if it meets none."""
        w = m[2]
        k, j = axis, 1 - axis
        mk, mj = m[k], m[j]
        best: tuple[int, int] | None = None

        def offer(num: int, den: int) -> None:
            nonlocal best
            if num > 0 and (best is None or ratio_cmp((num, den), best) < 0):
                best = (num, den)

        for v in self.isolated:
            if v[j] * w == mj:
                offer(sign * (v[k] * w - mk), 1)
        for (a, b), box in zip(self.segs, self.boxes, strict=True):
            lo_j, hi_j = box[j] * w, box[j + 2] * w
            if not lo_j <= mj <= hi_j:
                continue
            if (sign > 0 and box[k + 2] * w <= mk) or (sign < 0 and box[k] * w >= mk):
                continue  # entirely behind the ray origin
            dj = b[j] - a[j]
            if dj == 0:  # on the ray's line: its nearest endpoint ahead
                offer(sign * (a[k] * w - mk), 1)
                offer(sign * (b[k] * w - mk), 1)
                continue
            # the segment meets the line through m at k-coordinate c_k; t W = sign (c_k W - mk)
            num = a[k] * w * dj + (mj - a[j] * w) * (b[k] - a[k]) - mk * dj
            den = dj
            if den < 0:
                num, den = -num, -den
            offer(sign * num, den)
        return best


def _sqdist_scaled(m: HPoint, a: IntPoint, b: IntPoint) -> tuple[int, int]:
    """``(W * dist(m, ab))**2`` as ``(num, den)``: exact squared distance with the
    homogeneous weight multiplied out, so distances from one ``m`` compare directly."""
    x, y, w = m
    return sqdist_point_segment((x, y), (a[0] * w, a[1] * w), (b[0] * w, b[1] * w))


def _normal_offsets(s: SubSegment, features: _Features) -> list[HPoint]:
    """The two normal-offset face witnesses of a sub-segment (left first)."""
    x, y, w = s.mid
    nx, ny = -s.direction[1], s.direction[0]  # left normal of the source direction
    best = features.nearest_sqdist(s.mid)
    if best is None:
        k = 0
    else:  # |n|**2 / 4**k < dist**2 = best[0] / (best[1] W**2)
        k = safe_step_exponent(nx * nx + ny * ny, (best[0], best[1] * w * w))
    xs, ys, ws = x << k, y << k, w << k
    return [
        hpoint(xs + nx * w, ys + ny * w, ws),
        hpoint(xs - nx * w, ys - ny * w, ws),
    ]


def _ray_points(s: SubSegment, features: _Features) -> list[HPoint]:
    """The two axis-ray face witnesses of a sub-segment (x-rays unless horizontal)."""
    axis = 0 if s.direction[1] != 0 else 1
    out = []
    m = s.mid
    for sign in (1, -1):
        hit = features.ray_hit(m, axis, sign)
        coords = [m[0], m[1]]
        if hit is None:  # nothing ahead: a unit step along the ray
            coords[axis] += sign * m[2]
            out.append(hpoint(coords[0], coords[1], m[2]))
            continue
        num, den = hit  # t W = num / den; the witness is m + (t / 2) sign e_axis
        c = [2 * den * m[0], 2 * den * m[1]]
        c[axis] += sign * num
        out.append(hpoint(c[0], c[1], 2 * den * m[2]))
    return out


# ============================================================================ relate


def relate_witness(
    a: Geometry, b: Geometry, *, check: bool = True, keep_witnesses: bool = False
) -> WitnessRelate:
    """The DE-9IM matrix of ``(a, b)`` from witness points (see the module docstring).

    ``check=True`` generates face witnesses in two independent ways and requires them to
    agree (``check=False`` uses only the normal offsets, about half the face work).
    ``keep_witnesses=True`` keeps every located witness in the result.

    Raises :class:`~geotruth.numbers.NonFiniteError` for NaN/inf coordinates and
    :class:`WitnessRelateError` if an internal check fails.
    """
    frame = Frame.for_geometries(a, b)
    loc_a, loc_b = PointLocator(a, frame), PointLocator(b, frame)
    segs, vertices = _collect(frame, (a, b))
    endpoints = {p for s in segs for p in s}
    isolated = sorted(vertices - endpoints)
    split, crossings = _node(segs, isolated, vertices)
    subsegs = _subsegments(segs, split)
    features = _Features(segs, isolated)

    dims = [[-1] * 3 for _ in range(3)]
    realizers: dict[str, Witness] = {}
    counts: dict[str, int] = {}
    kept: list[Witness] = []

    def add(p: HPoint, dim: int, kind: str) -> Witness:
        la, lb = loc_a.locate(p), loc_b.locate(p)
        wit = Witness(p, dim, kind, la, lb)
        counts[kind] = counts.get(kind, 0) + 1
        if dim > dims[la][lb]:
            dims[la][lb] = dim
            realizers[LOCATION_CHARS[la] + LOCATION_CHARS[lb]] = wit
        if keep_witnesses:
            kept.append(wit)
        return wit

    for v in sorted(vertices):
        add((v[0], v[1], 1), 0, KIND_VERTEX)
    for p in sorted(crossings):
        add(p, 0, KIND_INTERSECTION)
    for s in subsegs:
        add(s.mid, 1, KIND_EDGE)
        left, right = (add(p, 2, KIND_FACE_NORMAL) for p in _normal_offsets(s, features))
        if check:
            by_side = {1: left, -1: right}
            for p in _ray_points(s, features):
                side = hp_orient(s.start, s.end, p)
                ray = add(p, 2, KIND_FACE_RAY)
                ref = by_side.get(side)
                if ref is None or (ref.loc_a, ref.loc_b) != (ray.loc_a, ray.loc_b):
                    raise WitnessRelateError(
                        f"face witnesses disagree beside sub-segment {s}: normal offset "
                        f"{ref} vs axis ray {ray}"
                    )

    # a point beyond everything is Exterior/Exterior (EE = 2 for bounded operands)
    if vertices:
        far = (max(v[0] for v in vertices) + 1, max(v[1] for v in vertices) + 1, 1)
    else:
        far = (0, 0, 1)
    far_w = add(far, 2, KIND_FAR)
    if (far_w.loc_a, far_w.loc_b) != (EXTERIOR, EXTERIOR):
        raise WitnessRelateError(f"the far point {far} is not exterior to both: {far_w}")
    dims[EXTERIOR][EXTERIOR] = 2

    matrix = "".join("F" if d < 0 else str(d) for row in dims for d in row)
    return WitnessRelate(
        matrix=matrix,
        dim_a=a.real_dimension,
        dim_b=b.real_dimension,
        frame=frame,
        realizers=realizers,
        counts=counts,
        num_segments=len(segs),
        num_subsegments=len(subsegs),
        num_intersections=len(crossings),
        witnesses=tuple(kept),
    )


def relate(a: Geometry, b: Geometry) -> str:
    """The DE-9IM matrix string of ``(a, b)`` by the witness route."""
    return relate_witness(a, b).matrix
