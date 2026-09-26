"""The overlay certificate: an independent check of an overlay result (DESIGN §2.6).

:func:`certify` decides whether a geometry R is the exact result of ``op(A, B)`` under
the closure semantics of DESIGN §1 "Overlay". It shares nothing with the overlay builder
(:mod:`geotruth.overlay`) or the arrangement (:mod:`geotruth.arrangement`): it nodes A, B
and R from scratch, generates witness points that meet every cell of their common
refinement, and locates each witness in the **original** A, B and R with the standalone
RelateNG-style point locator (:mod:`geotruth.locate`). Only the primitives of DESIGN §2.1
are shared.

The refinement and its witnesses
--------------------------------
Every segment of every ring and line of A, B and R (and every isolated point: Point
elements and zero-length lines) is split at every contact with every other segment or
point, in exact integer arithmetic. Then, as in the witness relate (§2.4):

- every vertex and intersection point is a **vertex witness** (dimension 0);
- the midpoint of every open sub-segment between consecutive split points is an **edge
  witness** (dimension 1): no ring, line or point of A, B or R meets the sub-segment,
  so every location is constant along it;
- on each side of every sub-segment, the **face witness** ``m +- s n`` (midpoint ``m``,
  normal ``n``, step ``s = 2**-k`` shorter than the exact distance from ``m`` to every
  feature not through ``m``) lies strictly inside the face on that side; an isolated
  point gets one face witness the same way.

The labels of A and B give the *selection* of every cell, ``sel = op(in A, in B)``, where
*in X* means Interior or Boundary of X. The closure semantics then fix R's location in
every cell from the selection of the cell and of the cells around it:

- a **face** is Interior of R if selected, else Exterior;
- an **edge** with both side faces selected is Interior of R; with one, Boundary; with
  none, Interior if the edge itself is selected (a line of R), else Exterior;
- a **vertex** whose surrounding faces (the side faces of its incident sub-segments, or
  the face around an isolated point) are all selected is Interior; if some are, Boundary;
  otherwise, with ``k`` incident selected edges (lines of R), Boundary if ``k`` is odd and
  Interior if ``k`` is even and positive (the Mod-2 rule on noded lines: a vertex's
  endpoint count and its line degree have the same parity), and with ``k == 0`` Interior
  if the vertex is selected (a point of R), else Exterior.

For the ``"areal"`` variant lines and points drop out: an unselected-face edge or vertex is
Exterior. A point beyond every coordinate must be Exterior to A, B and R.

Structure
---------
With ``structure=True`` (the default) R must also be the canonical form of the result:
its polygonal part is a valid (Multi)Polygon (:mod:`geotruth.validity`), its lines have
positive length and do not overlap each other or lie on or in its polygonal part, its
points are distinct and uncovered, it has no empty parts, its type is the most specific
one (a GeometryCollection only for mixed dimensions), an empty result has the type of
``OverlayUtil.resultDimension``, the areal variant is polygonal, and R is in canonical
order (:func:`geotruth.io.canonicalize`). ``structure=False`` checks the point set only,
and then accepts Interior or Boundary at the vertices of R's lines.

Cost
----
O(S^2) for S segments in the worst case, plus one nearest-feature search per sub-segment
and a point location per witness and geometry: meant for small and medium cases (tests,
cross-checks, ``--certify``), like the witness relate. :func:`certify_many` checks several
results of one pair of operands against a single refinement.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from itertools import pairwise
from typing import Any

from geotruth.exact import (
    OVERLAP,
    POINT,
    HPoint,
    hp_midpoint,
    hpoint,
    intersect_segments,
    on_segment,
    sort_along,
    sqdist_point_segment,
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
    build_geometry,
)
from geotruth.locate import (
    BOUNDARY,
    EXTERIOR,
    INTERIOR,
    LOCATION_CHARS,
    Frame,
    PointLocator,
    safe_step_exponent,
)
from geotruth.numbers import NonFiniteError, format_rational

__all__ = [
    "OPS",
    "VARIANTS",
    "Certificate",
    "CertificateError",
    "Mismatch",
    "certify",
    "certify_many",
]

#: The operations and variants (spelled as in :mod:`geotruth.overlay`).
OPS: tuple[str, ...] = ("intersection", "union", "difference", "symdifference")
VARIANTS: tuple[str, ...] = ("non_strict", "areal")

_SELECT = {
    "intersection": lambda a, b: a and b,
    "union": lambda a, b: a or b,
    "difference": lambda a, b: a and not b,
    "symdifference": lambda a, b: a != b,
}

_EMPTY_TYPES = {-1: "GeometryCollection", 0: "Point", 1: "LineString", 2: "Polygon"}

IntPoint = tuple[int, int]
Segment = tuple[IntPoint, IntPoint]


def _result_dimension(op: str, dim_a: int, dim_b: int) -> int:
    if op == "intersection":
        return min(dim_a, dim_b)
    if op == "difference":
        return dim_a
    return max(dim_a, dim_b)


# ============================================================================ reports


@dataclass(frozen=True)
class Mismatch:
    """A witness whose location in R contradicts the closure semantics.

    ``cell`` is ``"vertex"``, ``"edge"``, ``"face"`` or ``"far"``; ``point`` its exact real
    coordinates; ``loc_a``/``loc_b`` its locations in A and B; ``expected`` the location(s)
    R must give it (``"I"``, ``"B"``, ``"E"``, or ``"IB"`` when either is allowed) and
    ``got`` what R gives.
    """

    cell: str
    point: tuple[Fraction, Fraction]
    loc_a: str
    loc_b: str
    expected: str
    got: str

    def __str__(self) -> str:
        x, y = (format_rational(c) for c in self.point)
        want = " or ".join(self.expected)
        return (
            f"{self.cell} at ({x} {y}), located {self.loc_a} in A and {self.loc_b} in B: "
            f"R must give {want}, but gives {self.got}"
        )


@dataclass
class Certificate:
    """The verdict of :func:`certify` for one result.

    ``ok`` is True when every witness is located as the closure semantics require and (with
    ``structure``) R is in canonical form. ``mismatches`` lists wrongly located witnesses
    (up to ``max_problems``), ``problems`` every other failure (structure, unreadable R),
    ``counts`` the number of witnesses by cell kind.
    """

    op: str
    variant: str
    ok: bool
    mismatches: list[Mismatch] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    num_mismatches: int = 0

    @property
    def witnesses(self) -> int:
        return sum(self.counts.values())

    def summary(self) -> str:
        """One line: ok, or the first few failures."""
        if self.ok:
            return f"ok ({self.witnesses} witnesses)"
        parts = list(self.problems[:3]) + [str(m) for m in self.mismatches[:3]]
        more = len(self.problems) + self.num_mismatches - len(parts)
        tail = f" (+{more} more)" if more > 0 else ""
        return "; ".join(parts) + tail

    def to_json(self) -> dict[str, Any]:
        return {
            "op": self.op,
            "variant": self.variant,
            "ok": self.ok,
            "witnesses": self.witnesses,
            "counts": dict(sorted(self.counts.items())),
            "mismatches": self.num_mismatches,
            "problems": list(self.problems) + [str(m) for m in self.mismatches],
        }

    def raise_if_failed(self) -> None:
        if not self.ok:
            raise CertificateError(self)


class CertificateError(RuntimeError):
    """An overlay result failed its certificate (an engine bug for the engine's own
    results); ``certificate`` holds the details."""

    def __init__(self, certificate: Certificate) -> None:
        self.certificate = certificate
        super().__init__(
            f"overlay certificate failed for {certificate.op} ({certificate.variant}): "
            f"{certificate.summary()}"
        )


# ============================================================================ refinement


@dataclass
class _Sub:
    """An open sub-segment of the refinement."""

    start: HPoint
    end: HPoint
    mid: HPoint
    direction: IntPoint
    #: (geometry index, is_line) of every input segment covering it, with multiplicity
    sources: list[tuple[int, bool]] = field(default_factory=list)
    left: HPoint = (0, 0, 1)
    right: HPoint = (0, 0, 1)


def _less(r: tuple[int, int], s: tuple[int, int]) -> bool:
    """Exact ``r[0] / r[1] < s[0] / s[1]`` for non-negative numerators and positive
    denominators. Bit lengths decide most comparisons of huge values without a
    multiplication (``2**(n - 1) <= x < 2**n`` for an ``n``-bit ``x > 0``)."""
    a0, a1, b0, b1 = r[0], r[1], s[0], s[1]
    if a0 == 0:
        return b0 > 0
    if b0 == 0:
        return False
    la = a0.bit_length() + b1.bit_length()  # a0 * b1 < 2**la, >= 2**(la - 2)
    lb = b0.bit_length() + a1.bit_length()
    if la + 1 < lb:
        return True
    if lb + 1 < la:
        return False
    return a0 * b1 < b0 * a1


def _closed(coords: list[IntPoint]) -> list[IntPoint]:
    if coords and coords[0] != coords[-1]:
        coords = [*coords, coords[0]]
    return coords


class _Refinement:
    """The common refinement of several geometries and its witnesses (see the module
    docstring). Independent of :mod:`geotruth.arrangement`."""

    def __init__(self, geoms: Sequence[Geometry]) -> None:
        self.frame = frame = Frame.for_geometries(*geoms)
        to_pt = frame.to_int_point
        segsrc: dict[Segment, list[tuple[int, bool]]] = {}
        points: set[IntPoint] = set()
        for gi, g in enumerate(geoms):
            for e in g.elements():
                if e.is_empty:
                    continue
                if isinstance(e, Polygon):
                    chains = [(_closed([to_pt(c) for c in r]), False) for r in e.rings if r]
                elif isinstance(e, LineString):
                    cs = [to_pt(c) for c in e.coords]
                    if all(p == cs[0] for p in cs):  # a zero-length line is a point
                        points.add(cs[0])
                        continue
                    chains = [(cs, True)]
                else:
                    points.add(to_pt(e.coord))  # type: ignore[union-attr]
                    continue
                for chain, is_line in chains:
                    for p, q in pairwise(chain):
                        if p != q:
                            key = (p, q) if p < q else (q, p)
                            segsrc.setdefault(key, []).append((gi, is_line))
                    if len(set(chain)) == 1:
                        points.add(chain[0])
        self.segs: list[Segment] = sorted(segsrc)
        endpoints = {p for s in self.segs for p in s}
        candidates = sorted(points - endpoints)
        split = self._node(candidates)
        self.subs: list[_Sub] = []
        by_mid: dict[HPoint, int] = {}
        for (p, q), pts in zip(self.segs, split, strict=True):
            ordered = sort_along(p, q, [(p[0], p[1], 1), (q[0], q[1], 1), *pts])
            d = (q[0] - p[0], q[1] - p[1])
            for u, v in pairwise(ordered):
                m = hp_midpoint(u, v)
                i = by_mid.get(m)
                if i is None:
                    i = by_mid[m] = len(self.subs)
                    self.subs.append(_Sub(u, v, m, d))
                self.subs[i].sources.extend(segsrc[(p, q)])
        incident: dict[HPoint, list[int]] = {}
        for i, s in enumerate(self.subs):
            incident.setdefault(s.start, []).append(i)
            incident.setdefault(s.end, []).append(i)
        for c in candidates:
            incident.setdefault((c[0], c[1], 1), [])
        self.vertices: list[HPoint] = sorted(incident)
        self.incident = [incident[v] for v in self.vertices]
        self.isolated: list[IntPoint] = [c for c in candidates if not incident[(c[0], c[1], 1)]]
        self._boxes = [
            (min(p[0], q[0]), min(p[1], q[1]), max(p[0], q[0]), max(p[1], q[1]))
            for p, q in self.segs
        ]
        for s in self.subs:
            s.left, s.right = self._offsets(s)
        self.iso_faces = [self._iso_face(c) for c in self.isolated]
        if self.vertices:
            mx = max(v[0] // v[2] for v in self.vertices) + 1
            my = max(v[1] // v[2] for v in self.vertices) + 1
        else:
            mx = my = 0
        self.far: HPoint = (mx, my, 1)

    # -- noding -------------------------------------------------------------------------

    def _node(self, points: list[IntPoint]) -> list[set[HPoint]]:
        """Split points of every segment beyond its endpoints: every contact with another
        segment (crossings, touches, T-junctions, overlap ends) and every point on it."""
        items = []
        for i, (p, q) in enumerate(self.segs):
            items.append((p[0], q[0], min(p[1], q[1]), max(p[1], q[1]), p, q, i))
        for v in points:
            items.append((v[0], v[0], v[1], v[1], v, v, -1))
        items.sort(key=lambda t: t[0])
        split: list[set[HPoint]] = [set() for _ in self.segs]
        n = len(items)
        for i in range(n):
            _, xmax_i, ymin_i, ymax_i, p, q, si = items[i]
            for j in range(i + 1, n):
                xmin_j, _, ymin_j, ymax_j, r, s, sj = items[j]
                if xmin_j > xmax_i:
                    break
                if ymin_j > ymax_i or ymin_i > ymax_j or (si < 0 and sj < 0):
                    continue
                if si < 0 or sj < 0:
                    pt, seg = (p, sj) if si < 0 else (r, si)
                    a, b = self.segs[seg]
                    if pt != a and pt != b and on_segment(pt, a, b):
                        split[seg].add((pt[0], pt[1], 1))
                    continue
                res = intersect_segments(p, q, r, s)
                if res.kind == POINT or res.kind == OVERLAP:
                    for pt in res.points:
                        split[si].add(pt)
                        split[sj].add(pt)
        return split

    # -- face witnesses -----------------------------------------------------------------

    def _nearest(self, m: HPoint) -> tuple[int, int] | None:
        """``(W * d)**2`` as ``(num, den)``, ``d`` the distance from ``m`` to the nearest
        feature not through ``m``; None if there is none."""
        x, y, w = m
        best: tuple[int, int] | None = None
        for v in self.isolated:
            dx, dy = v[0] * w - x, v[1] * w - y
            d2 = dx * dx + dy * dy
            if d2 and (best is None or _less((d2, 1), best)):
                best = (d2, 1)
        for (a, b), (x0, y0, x1, y1) in zip(self.segs, self._boxes, strict=True):
            if best is not None:
                bx = max(x0 * w - x, 0, x - x1 * w)
                by = max(y0 * w - y, 0, y - y1 * w)
                if not _less((bx * bx + by * by, 1), best):
                    continue
            cand = sqdist_point_segment((x, y), (a[0] * w, a[1] * w), (b[0] * w, b[1] * w))
            if cand[0] == 0:
                continue  # a segment through m (collinear with its sub-segment)
            if best is None or _less(cand, best):
                best = cand
        return best

    @staticmethod
    def _step(m: HPoint, d: IntPoint, best: tuple[int, int] | None) -> HPoint:
        """``m + 2**-k d`` with ``|2**-k d| < sqrt(best) / W``."""
        x, y, w = m
        k = 0 if best is None else safe_step_exponent(d[0] ** 2 + d[1] ** 2, (best[0], best[1] * w * w))
        return hpoint((x << k) + d[0] * w, (y << k) + d[1] * w, w << k)

    def _offsets(self, s: _Sub) -> tuple[HPoint, HPoint]:
        best = self._nearest(s.mid)
        nx, ny = -s.direction[1], s.direction[0]  # left normal
        return self._step(s.mid, (nx, ny), best), self._step(s.mid, (-nx, -ny), best)

    def _iso_face(self, c: IntPoint) -> HPoint:
        return self._step((c[0], c[1], 1), (1, 0), self._nearest((c[0], c[1], 1)))

    def real(self, p: HPoint) -> tuple[Fraction, Fraction]:
        return self.frame.to_fractions(p)


# ============================================================================ checking


class _Labels:
    """Locations (0, 1, 2) of every witness in one geometry."""

    def __init__(self, ref: _Refinement, geom: Geometry) -> None:
        loc = PointLocator(geom, ref.frame).locate
        self.vertex = [loc(v) for v in ref.vertices]
        self.mid = [loc(s.mid) for s in ref.subs]
        self.left = [loc(s.left) for s in ref.subs]
        self.right = [loc(s.right) for s in ref.subs]
        self.iso = [loc(p) for p in ref.iso_faces]
        self.far = loc(ref.far)


def _check(
    ref: _Refinement,
    la: _Labels,
    lb: _Labels,
    lr: _Labels,
    op: str,
    areal: bool,
    exact_boundary: bool,
    max_problems: int,
) -> tuple[list[Mismatch], int]:
    sel = _SELECT[op]
    mism: list[Mismatch] = []
    count = 0
    ch = LOCATION_CHARS

    def bad(cell: str, p: HPoint, a: int, b: int, want: str, got: int) -> None:
        nonlocal count
        count += 1
        if len(mism) < max_problems:
            mism.append(Mismatch(cell, ref.real(p), ch[a], ch[b], want, ch[got]))

    def s_(a: int, b: int) -> bool:
        return sel(a != EXTERIOR, b != EXTERIOR)

    subs = ref.subs
    fl = [s_(a, b) for a, b in zip(la.left, lb.left, strict=True)]
    fr = [s_(a, b) for a, b in zip(la.right, lb.right, strict=True)]
    fe = [s_(a, b) for a, b in zip(la.mid, lb.mid, strict=True)]
    for i, s in enumerate(subs):
        for side, p, f, got in (("left", s.left, fl[i], lr.left[i]), ("right", s.right, fr[i], lr.right[i])):
            want = INTERIOR if f else EXTERIOR
            if got != want:
                a, b = (la.left[i], lb.left[i]) if side == "left" else (la.right[i], lb.right[i])
                bad("face", p, a, b, ch[want], got)
        if fl[i] and fr[i]:
            want = INTERIOR
        elif fl[i] or fr[i]:
            want = BOUNDARY
        elif fe[i] and not areal:
            want = INTERIOR
        else:
            want = EXTERIOR
        if lr.mid[i] != want:
            bad("edge", s.mid, la.mid[i], lb.mid[i], ch[want], lr.mid[i])
    for j, p in enumerate(ref.iso_faces):
        want = INTERIOR if s_(la.iso[j], lb.iso[j]) else EXTERIOR
        if lr.iso[j] != want:
            bad("face", p, la.iso[j], lb.iso[j], ch[want], lr.iso[j])
    iso_index = {(c[0], c[1], 1): j for j, c in enumerate(ref.isolated)}
    iso_sel = [s_(a, b) for a, b in zip(la.iso, lb.iso, strict=True)]
    for k, v in enumerate(ref.vertices):
        inc = ref.incident[k]
        if inc:
            any_face = any(fl[i] or fr[i] for i in inc)
            all_face = all(fl[i] and fr[i] for i in inc)
        else:
            any_face = all_face = iso_sel[iso_index[v]]
        if all_face:
            want = "I"
        elif any_face:
            want = "B"
        elif areal:
            want = "E"
        else:
            lines = sum(1 for i in inc if fe[i])
            if lines:
                want = ("B" if lines % 2 else "I") if exact_boundary else "IB"
            else:
                want = "I" if s_(la.vertex[k], lb.vertex[k]) else "E"
        got = lr.vertex[k]
        if ch[got] not in want:
            bad("vertex", v, la.vertex[k], lb.vertex[k], want, got)
    if lr.far != EXTERIOR or la.far != EXTERIOR or lb.far != EXTERIOR:
        bad("far", ref.far, la.far, lb.far, "E", lr.far)
    return mism, count


# ============================================================================ structure


def _structure(
    ref: _Refinement, gi: int, r: Geometry, op: str, variant: str, dims: tuple[int, int]
) -> list[str]:
    """Canonical-form problems of result ``r`` (geometry index ``gi`` of the refinement)."""
    from geotruth.io import canonicalize, geometry_to_json
    from geotruth.validity import validate

    problems: list[str] = []
    elems = list(r.elements())
    if r.is_empty:
        want = _EMPTY_TYPES[_result_dimension(op, *dims)]
        nested = isinstance(r, GeometryCollection) and bool(r.geometries)
        if r.geom_type != want or nested:
            problems.append(f"an empty result must be {want.upper()} EMPTY, not {r.geom_type}")
        return problems
    if any(e.is_empty for e in elems):
        problems.append("the result has empty parts")
        elems = [e for e in elems if not e.is_empty]
    if variant == "areal" and not all(isinstance(e, Polygon) for e in elems):
        problems.append("the areal result has lines or points")
    specific = build_geometry(elems).geom_type
    if r.geom_type != specific:
        problems.append(f"the result is a {r.geom_type}; its parts make a {specific}")
    if isinstance(r, GeometryCollection) and any(
        isinstance(g, (GeometryCollection, MultiPolygon, MultiLineString, MultiPoint))
        for g in r.geometries
    ):
        problems.append("the result collection nests collections or multi-geometries")
    polys = [e for e in elems if isinstance(e, Polygon)]
    lines = [e for e in elems if isinstance(e, LineString)]
    points = [e for e in elems if isinstance(e, Point)]
    if polys:
        rep = validate(MultiPolygon(tuple(polys)))
        if not rep.valid:
            problems.append(f"the polygonal part is invalid: {rep.message}")
    for ln in lines:
        if ln.is_zero_length:
            problems.append("a result line has zero length")
    frame = ref.frame
    poly_loc = PointLocator(MultiPolygon(tuple(polys)), frame) if polys else None
    line_loc = PointLocator(MultiLineString(tuple(lines)), frame) if lines else None
    for s in ref.subs:
        n_lines = sum(1 for g, is_line in s.sources if g == gi and is_line)
        if n_lines > 1:
            x, y = ref.real(s.mid)
            problems.append(
                f"result lines overlap near ({format_rational(x)} {format_rational(y)})"
            )
            break
    for s in ref.subs:
        if poly_loc is not None and any(g == gi and is_line for g, is_line in s.sources):
            if poly_loc.locate(s.mid) != EXTERIOR:
                x, y = ref.real(s.mid)
                problems.append(
                    "a result line lies on or in the polygonal part near "
                    f"({format_rational(x)} {format_rational(y)})"
                )
                break
    seen: set[HPoint] = set()
    for pt in points:
        p = frame.hpoint(pt.coord)
        if p in seen:
            problems.append("the result repeats a point")
        seen.add(p)
        covered = (poly_loc is not None and poly_loc.locate(p) != EXTERIOR) or (
            line_loc is not None and line_loc.locate(p) != EXTERIOR
        )
        if covered:
            x, y = frame.to_fractions(p)
            problems.append(
                f"the result point ({format_rational(x)} {format_rational(y)}) is covered "
                "by its polygons or lines"
            )
    if geometry_to_json(canonicalize(r), exact=True) != geometry_to_json(r, exact=True):
        problems.append("the result is not in canonical order")
    return problems


# ============================================================================ API


def _normalize(op: str, variant: str) -> tuple[str, str]:
    o = str(op).strip().lower().replace("-", "_")
    o = {"symmetric_difference": "symdifference", "sym_difference": "symdifference"}.get(o, o)
    if o not in _SELECT:
        raise ValueError(f"unknown overlay operation {op!r}; expected one of {OPS}")
    v = {"nonstrict": "non_strict", "non-strict": "non_strict"}.get(variant, variant)
    if v not in VARIANTS:
        raise ValueError(f"unknown overlay variant {variant!r}; expected one of {VARIANTS}")
    return o, v


def certify_many(
    a: Geometry,
    b: Geometry,
    results: Iterable[tuple[str, str, Geometry]],
    *,
    structure: bool = True,
    max_problems: int = 20,
) -> list[Certificate]:
    """Certify several results ``(op, variant, R)`` of one pair of operands against a
    single common refinement of A, B and every R. Returns one :class:`Certificate` per
    result, in order. Never raises on a wrong or malformed R (that is a failed
    certificate); raises ``ValueError`` for an unknown operation or variant."""
    items = [(*_normalize(op, v), r) for op, v, r in results]
    if not items:
        return []
    unique: list[Geometry] = []
    index: list[int] = []
    for _, _, r in items:
        for j, u in enumerate(unique):
            if u is r or u == r:
                index.append(j)
                break
        else:
            index.append(len(unique))
            unique.append(r)
    try:
        ref = _Refinement([a, b, *unique])
    except (NonFiniteError, ValueError, TypeError) as exc:
        why = f"cannot refine A, B and the results: {type(exc).__name__}: {exc}"
        return [Certificate(op, v, False, problems=[why]) for op, v, _ in items]
    la, lb = _Labels(ref, a), _Labels(ref, b)
    labels = [_Labels(ref, r) for r in unique]
    counts = {
        "vertex": len(ref.vertices),
        "edge": len(ref.subs),
        "face": 2 * len(ref.subs) + len(ref.iso_faces),
        "far": 1,
    }
    dims = (a.dimension, b.dimension)
    out = []
    for (op, variant, r), j in zip(items, index, strict=True):
        mism, n = _check(
            ref, la, lb, labels[j], op, variant == "areal", structure, max_problems
        )
        problems = _structure(ref, 2 + j, r, op, variant, dims) if structure else []
        out.append(
            Certificate(
                op,
                variant,
                not mism and not problems,
                mismatches=mism,
                problems=problems,
                counts=dict(counts),
                num_mismatches=n,
            )
        )
    return out


def certify(
    a: Geometry,
    b: Geometry,
    op: str,
    result: Geometry,
    variant: str = "non_strict",
    *,
    structure: bool = True,
    max_problems: int = 20,
) -> Certificate:
    """Certify that ``result`` is ``op(a, b)`` in ``variant`` (see the module
    docstring). ``result`` may hold exact rationals or doubles (a library's output)."""
    return certify_many(
        a, b, [(op, variant, result)], structure=structure, max_problems=max_problems
    )[0]
