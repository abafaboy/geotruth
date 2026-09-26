"""Exact OGC / GEOS-default validity for every geometry type (DESIGN §1 "Validity", §2.7).

geotruth models GEOS ``IsValidOp`` with its default ``isInvertedRingValid = false``: the
validity that Shapely's ``is_valid``, the GEOS C API and every adapter use. Every decision
is exact (integer arithmetic on the input values after common-denominator scaling), so the
answer is the one GEOS gives on exact input. :func:`validate` returns the **full exact set
of defects** with their locations as exact rationals, plus the reason GEOS would report
first. Scoring uses only the boolean (DESIGN §4.3); reasons are informational.

What GEOS checks, per type
--------------------------
GEOS validates a geometry as one *unit* or, for collections, child by child:

- empty geometries are valid (a Point, LineString or Polygon is empty when it has no
  coordinates, resp. an empty shell; a collection when all its children are empty);
- **Point, MultiPoint**: every coordinate is finite;
- **LineString**: every coordinate is finite and it has at least 2 distinct points; a
  self-crossing or self-overlapping line is valid;
- **Polygon, MultiPolygon**: rules R0-R6 of ``tests/reference/validity.py``, extended to
  every GEOS error kind (below). A MultiPolygon is ONE unit: its parts are checked against
  each other;
- **MultiLineString, GeometryCollection**: every child is validated on its own, so
  overlapping polygons in a GC are valid, while a GC holding one MultiPolygon whose parts
  overlap is not. Children are validated recursively (a GC may nest).

Defects of a polygonal unit
---------------------------
``invalid_coordinate``
    a NaN or infinite ordinate (every one is reported).
``ring_not_closed``
    a non-empty ring whose first and last points differ (JTS ``equals2D``).
``too_few_points``
    a non-empty ring with fewer than 4 points after dropping consecutive repeats, or a
    non-empty LineString with fewer than 2. Rings with a defect so far are *malformed*
    and take no part in the topology checks below (GEOS stops before them). Rings with
    non-finite ordinates are not checked for closure or size.
``self_intersection``
    between two segments of the unit's well-formed rings: a proper crossing (location:
    the exact crossing point), a collinear overlap of positive length, including a
    fold-back of adjacent segments of one ring (location: both overlap endpoints), or a
    vertex contact of two *different* rings at which their boundaries cross
    (``PolygonNodeTopology.isCrossing``; location: the vertex).
``ring_self_intersection``
    a single-point contact of two non-adjacent segments of the *same* ring that is not a
    proper crossing: a self-touch or a crossing through a vertex (GEOS classifies both
    this way, before any crossing test).
``hole_outside_shell``
    some point of a hole's boundary lies strictly outside its shell (also every
    non-empty hole of a polygon whose shell is empty, which GEOS refuses to construct).
``nested_holes``
    hole *i* of a polygon lies inside hole *j*: no point of *i* is strictly outside *j*,
    and *i* is not entirely on *j*'s boundary.
``nested_shells``
    part *i* of a MultiPolygon lies inside part *j* (inside *j*'s shell and not in one of
    *j*'s holes), with the same "not entirely on the boundary" proviso.
``disconnected_interior``
    in the bipartite graph *rings - touch points* of one polygon (touch points: isolated,
    non-crossing single-point contacts between two different rings) there is a cycle.
    This covers GEOS's "double touch" (two rings touching twice) and its hole cycles.
    Location: every touch point on a cycle.

When no defect of an earlier kind is present, each definition coincides with the GEOS
test (which checks a single point or corner and relies on the earlier checks having
passed); the definitions above stay meaningful when earlier defects are present, so the
defect set is complete and does not depend on any processing order.

The first reason
----------------
GEOS reports only its first error, in this order per unit: invalid coordinate, ring not
closed, too few points (for a MultiPolygon: those three per part, part by part), area
intersections (self-intersection or ring self-intersection), hole outside shell, nested
holes, nested shells, disconnected interior; a collection reports its first invalid child.

Only the area-intersection step depends on processing order: GEOS's ``MCIndexNoder``
presents segment pairs in an order fixed by its monotone chains and ``TemplateSTRtree``
(``queryPairs``), a later invalid pair overwrites an earlier one, and the noder stops early
at a "double touch", after which GEOS runs its later single-point checks on a geometry
whose remaining intersections it never examined. ``first_certain`` is False when that
order matters (both self-intersection kinds present, or area intersections together with a
double touch); ``first_alternatives`` lists the codes GEOS could then report. For double
coordinates, :class:`_GeosOrder` replays GEOS 3.13's noding order exactly (including
libstdc++'s ``std::sort`` tie order and the early-exit behaviour) and ``first_basis`` is
``"geos-order"``: ``first`` is then the defect GEOS stops on. Otherwise ``first_basis`` is
``"precedence"`` (the order-free steps decide) or ``"heuristic"`` (exact rational input,
where no GEOS order exists). The boolean never depends on any of this.

Checked against GEOS 3.13.1 (Shapely) in ``tests/crosscheck/test_validity_geos.py``: the
boolean, the first reason and, for (ring) self-intersections, its location agree on every
lattice case; the emulated pair order was also compared call by call with the GEOS 3.15.0
noder. For hole/shell nesting GEOS reports the ring's first coordinate as the location,
while ``location`` here is an exact witness point (strictly outside, resp. inside).

Coordinates may be doubles (input geometries) or exact rationals (engine output); both are
scaled exactly to integers by a common denominator (:class:`geotruth.measures.CoordScale`).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Any, NamedTuple

from geotruth import exact as X
from geotruth.geom import (
    Geometry,
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    same_xy,
)
from geotruth.measures import CoordScale, _is_ccw
from geotruth.numbers import format_rational

__all__ = [
    "CODES",
    "DISCONNECTED_INTERIOR",
    "HOLE_OUTSIDE_SHELL",
    "INVALID_COORDINATE",
    "MESSAGES",
    "NESTED_HOLES",
    "NESTED_SHELLS",
    "RING_NOT_CLOSED",
    "RING_SELF_INTERSECTION",
    "SELF_INTERSECTION",
    "TOO_FEW_POINTS",
    "Defect",
    "Site",
    "ValidityReport",
    "code_of_message",
    "is_valid",
    "validate",
]

INVALID_COORDINATE = "invalid_coordinate"
RING_NOT_CLOSED = "ring_not_closed"
TOO_FEW_POINTS = "too_few_points"
SELF_INTERSECTION = "self_intersection"
RING_SELF_INTERSECTION = "ring_self_intersection"
HOLE_OUTSIDE_SHELL = "hole_outside_shell"
NESTED_HOLES = "nested_holes"
NESTED_SHELLS = "nested_shells"
DISCONNECTED_INTERIOR = "disconnected_interior"

#: Defect codes in GEOS ``IsValidOp`` precedence order (schema ``ValidityCode``; the
#: legacy ``duplicate_rings`` is never produced: GEOS >= 3.10 reports those rings as a
#: self-intersection).
CODES: tuple[str, ...] = (
    INVALID_COORDINATE,
    RING_NOT_CLOSED,
    TOO_FEW_POINTS,
    SELF_INTERSECTION,
    RING_SELF_INTERSECTION,
    HOLE_OUTSIDE_SHELL,
    NESTED_HOLES,
    NESTED_SHELLS,
    DISCONNECTED_INTERIOR,
)

#: GEOS ``TopologyValidationError`` messages (what ``explain_validity`` prints before
#: the ``[x y]`` location).
MESSAGES: dict[str, str] = {
    INVALID_COORDINATE: "Invalid Coordinate",
    RING_NOT_CLOSED: "Ring is not closed",
    TOO_FEW_POINTS: "Too few points in geometry component",
    SELF_INTERSECTION: "Self-intersection",
    RING_SELF_INTERSECTION: "Ring Self-intersection",
    HOLE_OUTSIDE_SHELL: "Hole lies outside shell",
    NESTED_HOLES: "Holes are nested",
    NESTED_SHELLS: "Nested shells",
    DISCONNECTED_INTERIOR: "Interior is disconnected",
    "duplicate_rings": "Duplicate Rings",
}

_RANK = {c: i for i, c in enumerate(CODES)}
_AREA_CODES = (SELF_INTERSECTION, RING_SELF_INTERSECTION)
_LATER_CODES = (HOLE_OUTSIDE_SHELL, NESTED_HOLES, NESTED_SHELLS, DISCONNECTED_INTERIOR)


def code_of_message(message: str) -> str | None:
    """The defect code of a GEOS validity message such as ``explain_validity`` output
    (``"Self-intersection[1 1]"`` -> ``"self_intersection"``); None for "Valid Geometry"
    or an unknown message."""
    text = message.split("[", 1)[0].strip()
    for code, msg in MESSAGES.items():
        if text == msg:
            return code
    if text.startswith("Too few"):  # older GEOS: "Too few distinct points in ..."
        return TOO_FEW_POINTS
    return None


# ============================================================================ reports


class Site(NamedTuple):
    """Where a defect is: an atomic element and, for polygons, one of its rings.

    ``path`` holds child indices from the validated geometry down to the Point,
    LineString or Polygon (``()`` for the geometry itself; ``(2, 0)`` is part 0 of child
    2 of a collection). ``ring`` is 0 for a shell and ``k >= 1`` for hole *k* (None for
    points and lines); ``vertex`` indexes the input coordinate sequence when a single
    coordinate is meant.
    """

    path: tuple[int, ...]
    ring: int | None = None
    vertex: int | None = None

    def __str__(self) -> str:
        parts = ["/" + "/".join(map(str, self.path)) if self.path else "/"]
        if self.ring is not None:
            parts.append("shell" if self.ring == 0 else f"hole {self.ring}")
        if self.vertex is not None:
            parts.append(f"vertex {self.vertex}")
        return " ".join(parts)

    def to_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"path": list(self.path)}
        if self.ring is not None:
            out["ring"] = self.ring
        if self.vertex is not None:
            out["vertex"] = self.vertex
        return out


def _fmt_point(p: tuple[Any, Any]) -> str:
    return f"({format_rational(p[0])}, {format_rational(p[1])})"


def _fmt_double(v: float) -> str:
    if v != v:
        return "NaN"
    if v in (math.inf, -math.inf):
        return "Inf" if v > 0 else "-Inf"
    return repr(float(v))


@dataclass(frozen=True)
class Defect:
    """One exact defect.

    ``location`` holds exact points (pairs of rationals of the active backend): one point,
    two points for a collinear overlap (its endpoints), or every touch point on a cycle
    for ``disconnected_interior``. An ``invalid_coordinate`` has no exact location; its
    raw input ordinates are in ``coordinate``.
    """

    code: str
    sites: tuple[Site, ...]
    location: tuple[tuple[Any, Any], ...] = ()
    coordinate: tuple[float, float] | None = None
    detail: str = ""

    @property
    def message(self) -> str:
        """The GEOS message of this defect's kind."""
        return MESSAGES[self.code]

    def to_json(self) -> dict[str, Any]:
        """A JSON object with rationals as ``"n/d"`` strings."""
        out: dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "sites": [s.to_json() for s in self.sites],
            "location": [[format_rational(x), format_rational(y)] for x, y in self.location],
        }
        if self.coordinate is not None:
            out["coordinate"] = [_fmt_double(v) for v in self.coordinate]
        if self.detail:
            out["detail"] = self.detail
        return out

    def describe(self) -> str:
        """One line of text: message, where, and the exact location."""
        where = "; ".join(str(s) for s in self.sites)
        if self.coordinate is not None:
            loc = " at (" + ", ".join(_fmt_double(v) for v in self.coordinate) + ")"
        elif len(self.location) == 1:
            loc = " at " + _fmt_point(self.location[0])
        elif self.location:
            joiner = " - " if self.code == SELF_INTERSECTION else ", "
            loc = " at " + joiner.join(_fmt_point(p) for p in self.location)
        else:
            loc = ""
        extra = f" ({self.detail})" if self.detail else ""
        return f"{self.message}{loc} [{where}]{extra}"


@dataclass(frozen=True)
class ValidityReport:
    """The exact validity of a geometry.

    ``defects`` is the complete defect set, ordered by precedence (code), then site,
    then location. ``first`` is the defect GEOS reports first (see the module docstring).
    ``first_certain`` is False when GEOS's choice depends on its noding order, which can
    then yield any code in ``first_alternatives``; ``first_basis`` says how ``first`` was
    chosen: ``"precedence"``, ``"geos-order"`` (GEOS's noding order replayed) or
    ``"heuristic"`` (no double coordinates to replay it on).
    """

    defects: tuple[Defect, ...] = ()
    first: Defect | None = None
    first_certain: bool = True
    first_alternatives: tuple[str, ...] = ()
    first_basis: str = "precedence"

    @property
    def valid(self) -> bool:
        return not self.defects

    def __bool__(self) -> bool:
        return self.valid

    @property
    def reasons(self) -> tuple[str, ...]:
        """Every defect code present, in precedence order."""
        present = {d.code for d in self.defects}
        return tuple(c for c in CODES if c in present)

    @property
    def first_reason(self) -> str | None:
        return None if self.first is None else self.first.code

    @property
    def message(self) -> str:
        """GEOS-style message of the first reason ("Valid Geometry" if valid)."""
        return "Valid Geometry" if self.first is None else self.first.message

    def to_json(self, *, detail: bool = False) -> dict[str, Any]:
        """The expected-answer ``Validity`` object (schemas/expected.v2.schema.json).

        ``detail=True`` adds the defects with exact locations and the certainty of the
        first reason (not part of the schema; for the CLI and debugging).
        """
        out: dict[str, Any] = {
            "valid": self.valid,
            "reasons": list(self.reasons),
            "first_reason": self.first_reason,
        }
        if not self.valid:
            out["message"] = self.message
        if detail:
            out["first_reason_certain"] = self.first_certain
            out["first_reason_basis"] = self.first_basis
            out["first_reason_alternatives"] = list(self.first_alternatives)
            out["first_defect"] = None if self.first is None else self.first.to_json()
            out["defects"] = [d.to_json() for d in self.defects]
        return out


# ============================================================================ helpers


def _finite(c: Sequence) -> bool:
    x, y = c[0], c[1]
    return (not isinstance(x, float) or math.isfinite(x)) and (
        not isinstance(y, float) or math.isfinite(y)
    )


def _nonrepeated_count(coords: Sequence) -> int:
    """JTS ``isNonRepeatedSizeAtLeast``: points left after dropping consecutive repeats."""
    n = 0
    prev = None
    for c in coords:
        if prev is None or not same_xy(c, prev):
            n += 1
        prev = c
    return n


def _as_double(v: Any) -> float | None:
    """``v`` as the double GEOS would hold, or None if it is not exactly a double."""
    if isinstance(v, float):
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        try:
            f = float(v)
        except OverflowError:
            return None
        return f if f == v else None
    return None


def _polygon_truly_empty(p: Polygon) -> bool:
    """No coordinates at all (a Polygon with an empty shell but non-empty holes is
    *not* empty here: GEOS refuses to build it, and we report its holes)."""
    return all(not r for r in p.rings)


def _is_crossing(node, a0, a1, b0, b1) -> bool:
    """``PolygonNodeTopology.isCrossing``: do the corners ``a0-node-a1`` and
    ``b0-node-b1`` cross at ``node``? False when an edge of b is collinear (same ray)
    with an edge of a. All points are integer pairs distinct from ``node``."""
    nx, ny = node
    lo = (a0[0] - nx, a0[1] - ny)
    hi = (a1[0] - nx, a1[1] - ny)
    if X.angle_cmp(lo, hi) > 0:
        lo, hi = hi, lo

    def between(p) -> int:
        v = (p[0] - nx, p[1] - ny)
        c0 = X.angle_cmp(v, lo)
        if c0 == 0:
            return 0
        c1 = X.angle_cmp(v, hi)
        if c1 == 0:
            return 0
        return 1 if (c0 > 0 and c1 < 0) else -1

    w0 = between(b0)
    if w0 == 0:
        return False
    w1 = between(b1)
    if w1 == 0:
        return False
    return w0 != w1


def _bbox(pts: Sequence[tuple[int, int]]) -> tuple[int, int, int, int]:
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _bbox_covers(outer, inner) -> bool:
    return (
        outer[0] <= inner[0]
        and outer[1] <= inner[1]
        and outer[2] >= inner[2]
        and (outer[3] >= inner[3])
    )


def _hp(p: tuple[int, int]) -> X.HPoint:
    return (p[0], p[1], 1)


def _cycle_points(edges: Sequence[tuple[int, X.HPoint]]) -> list[X.HPoint]:
    """Touch points lying on a cycle of the bipartite graph given by ``(ring, point)``
    edges (distinct): the points with an incident edge that is not a bridge."""
    adj: dict[tuple, list[tuple[tuple, int]]] = defaultdict(list)
    for e, (r, p) in enumerate(edges):
        adj[("r", r)].append((("p", p), e))
        adj[("p", p)].append((("r", r), e))
    disc: dict[tuple, int] = {}
    low: dict[tuple, int] = {}
    bridges: set[int] = set()
    timer = 0
    for root in adj:
        if root in disc:
            continue
        disc[root] = low[root] = timer
        timer += 1
        stack: list[tuple[tuple, int, Iterator]] = [(root, -1, iter(adj[root]))]
        while stack:
            node, parent_edge, it = stack[-1]
            advanced = False
            for nbr, e in it:
                if e == parent_edge:
                    continue
                if nbr in disc:
                    low[node] = min(low[node], disc[nbr])
                else:
                    disc[nbr] = low[nbr] = timer
                    timer += 1
                    stack.append((nbr, e, iter(adj[nbr])))
                    advanced = True
                    break
            if not advanced:
                stack.pop()
                if stack:
                    parent = stack[-1][0]
                    low[parent] = min(low[parent], low[node])
                    if low[node] > disc[parent]:
                        bridges.add(parent_edge)
    on_cycle = {p for e, (_, p) in enumerate(edges) if e not in bridges}
    return sorted(on_cycle, key=X.hp_key)


# ============================================================================ units


@dataclass
class _Unit:
    """Defects of one GEOS validation unit and its first reason."""

    defects: list[Defect] = field(default_factory=list)
    first: Defect | None = None
    certain: bool = True
    alternatives: tuple[str, ...] = ()
    basis: str = "precedence"


def _coordinate_defects(coords: Sequence, site: Site) -> list[Defect]:
    out = []
    for v, c in enumerate(coords):
        if not _finite(c):
            out.append(
                Defect(
                    INVALID_COORDINATE,
                    (Site(site.path, site.ring, v),),
                    coordinate=(float(c[0]), float(c[1])),
                )
            )
    return out


def _check_points(points: Sequence[tuple[tuple[int, ...], Point]]) -> _Unit:
    unit = _Unit()
    for path, p in points:
        if p.coord is not None:
            unit.defects.extend(_coordinate_defects([p.coord], Site(path)))
    unit.first = unit.defects[0] if unit.defects else None
    return unit


def _check_line(path: tuple[int, ...], line: LineString, scale: CoordScale) -> _Unit:
    unit = _Unit()
    unit.defects.extend(_coordinate_defects(line.coords, Site(path)))
    if not unit.defects and _nonrepeated_count(line.coords) < 2:
        unit.defects.append(
            Defect(TOO_FEW_POINTS, (Site(path),), (scale.rational_point(line.coords[0]),))
        )
    unit.first = unit.defects[0] if unit.defects else None
    return unit


class _Ring:
    """A well-formed ring of a polygonal unit: ``pts`` is the closed ring with
    consecutive repeats removed, in scaled integers; ``raw`` keeps every input point
    (scaled); ``fpts`` holds the input doubles matching ``pts`` (None when some
    coordinate is not a double)."""

    __slots__ = ("bbox", "fpts", "id", "k", "nseg", "part", "pts", "raw", "seg0", "site")

    def __init__(
        self,
        rid: int,
        part: int,
        k: int,
        site: Site,
        raw: list[tuple[int, int]],
        coords: Sequence,
    ):
        self.id = rid
        self.part = part
        self.k = k
        self.site = site
        self.raw = raw
        pts: list[tuple[int, int]] = []
        fpts: list[tuple[float, float]] | None = []
        for p, c in zip(raw, coords, strict=True):
            if pts and pts[-1] == p:
                continue
            pts.append(p)
            if fpts is not None:
                fx, fy = _as_double(c[0]), _as_double(c[1])
                if fx is None or fy is None:
                    fpts = None
                else:
                    fpts.append((fx, fy))
        self.pts = pts
        self.fpts = fpts
        self.nseg = len(pts) - 1
        self.bbox = _bbox(pts)
        self.seg0 = 0  # global index of segment 0, set when segments are built


class _Polygonal:
    """Exact analysis of one Polygon or MultiPolygon (one GEOS validation unit)."""

    def __init__(
        self, parts: list[tuple[tuple[int, ...], Polygon]], multi: bool, scale: CoordScale
    ):
        self.parts = parts
        self.multi = multi
        self.scale = scale
        self.rings: list[_Ring] = []
        self.shell_of: list[_Ring | None] = [None] * len(parts)
        self.part_has_holes = [len(p.rings) > 1 for _, p in parts]
        self.holes_of: list[list[_Ring]] = [[] for _ in parts]
        self.pre: list[tuple[list[Defect], list[Defect], list[Defect]]] = []
        # area intersections: key -> (order, Defect)
        self.area: dict[tuple, tuple[tuple[int, int], Defect]] = {}
        # contacts of global segment s with ring r (different rings only): split points
        self.contacts: dict[tuple[int, int], list[X.HPoint]] = defaultdict(list)
        # same-part ring pairs: single-point non-crossing contacts and overlaps
        self.touches: dict[tuple[int, int], set[tuple[int, int]]] = defaultdict(set)
        self.overlaps: dict[tuple[int, int], list[tuple[X.HPoint, X.HPoint]]] = defaultdict(list)
        self.later: list[Defect] = []

    # -------------------------------------------------------------- coordinate checks

    def check_rings(self) -> None:
        scale = self.scale
        for pi, (path, poly) in enumerate(self.parts):
            coords_d: list[Defect] = []
            closure_d: list[Defect] = []
            size_d: list[Defect] = []
            shell_empty = not poly.rings or not poly.rings[0]
            for k, ring in enumerate(poly.rings):
                if not ring:
                    continue
                site = Site(path, k)
                bad = _coordinate_defects(ring, site)
                if bad:
                    coords_d.extend(bad)
                    continue
                first = scale.rational_point(ring[0])
                ok = True
                if not same_xy(ring[0], ring[-1]):
                    closure_d.append(Defect(RING_NOT_CLOSED, (site,), (first,)))
                    ok = False
                if _nonrepeated_count(ring) < 4:
                    size_d.append(Defect(TOO_FEW_POINTS, (site,), (first,)))
                    ok = False
                if shell_empty:
                    # GEOS: "shell is empty but holes are not" cannot be constructed;
                    # IsValidOp.checkHolesInShell reports every such hole.
                    self.later.append(
                        Defect(HOLE_OUTSIDE_SHELL, (site,), (first,), detail="the shell is empty")
                    )
                    continue
                if not ok:
                    continue
                r = _Ring(len(self.rings), pi, k, site, [scale.point(c) for c in ring], ring)
                self.rings.append(r)
                if k == 0:
                    self.shell_of[pi] = r
                else:
                    self.holes_of[pi].append(r)
            self.pre.append((coords_d, closure_d, size_d))

    # ------------------------------------------------------------ area intersections

    def _sites(self, ra: _Ring, rb: _Ring) -> tuple[Site, ...]:
        if ra is rb:
            return (ra.site,)
        if (ra.part, ra.k) > (rb.part, rb.k):
            ra, rb = rb, ra
        return (ra.site, rb.site)

    def _add_area(self, code, ra, rb, loc: tuple[X.HPoint, ...], order, detail="") -> None:
        key = (code, ra.id, rb.id, loc) if ra.id <= rb.id else (code, rb.id, ra.id, loc)
        if key in self.area:
            return
        d = Defect(
            code,
            self._sites(ra, rb),
            tuple(self.scale.rational_hpoint(p) for p in loc),
            detail=detail,
        )
        self.area[key] = (order, d)

    def intersections(self) -> None:
        segs: list[tuple[_Ring, int, tuple[int, int], tuple[int, int]]] = []
        for r in self.rings:
            r.seg0 = len(segs)
            pts = r.pts
            for i in range(r.nseg):
                segs.append((r, i, pts[i], pts[i + 1]))
        n = len(segs)
        if n < 2:
            return
        xlo = [min(s[2][0], s[3][0]) for s in segs]
        xhi = [max(s[2][0], s[3][0]) for s in segs]
        ylo = [min(s[2][1], s[3][1]) for s in segs]
        yhi = [max(s[2][1], s[3][1]) for s in segs]
        order = sorted(range(n), key=xlo.__getitem__)
        active: list[int] = []
        for s in order:
            x0 = xlo[s]
            active = [t for t in active if xhi[t] >= x0]
            y0, y1 = ylo[s], yhi[s]
            for t in active:
                if yhi[t] >= y0 and ylo[t] <= y1:
                    if t < s:
                        self._pair(t, s, segs[t], segs[s])
                    else:
                        self._pair(s, t, segs[s], segs[t])
            active.append(s)

    def _pair(self, gi: int, gj: int, si, sj) -> None:
        """GEOS ``PolygonIntersectionAnalyzer.findInvalidIntersection`` for one segment
        pair, exactly, but recording every defect and contact instead of stopping."""
        ra, i, a, b = si
        rb, j, c, d = sj
        res = X.intersect_segments(a, b, c, d)
        if not res:
            return
        same = ra is rb
        if not same:
            for p in res.points:
                self.contacts[(gi, rb.id)].append(p)
                self.contacts[(gj, ra.id)].append(p)
        order = (gi, gj)
        if res.kind == X.OVERLAP:
            p, q = sorted(res.points, key=X.hp_key)
            self._add_area(SELF_INTERSECTION, ra, rb, (p, q), order, "collinear overlap")
            if not same and ra.part == rb.part:
                self.overlaps[self._pairkey(ra, rb)].append((p, q))
            return
        p = res.points[0]
        pp = (p[0], p[1])
        if p[2] != 1 or pp not in (a, b, c, d):
            self._add_area(SELF_INTERSECTION, ra, rb, (p,), order, "proper crossing")
            return
        if same:
            dd = abs(i - j)
            if dd <= 1 or dd >= ra.nseg - 1:  # JTS isAdjacentInRing
                return
            self._add_area(RING_SELF_INTERSECTION, ra, ra, (p,), order)
            return
        if pp in (b, d):  # GEOS evaluates this node from the pair starting there
            return
        ca = (ra.pts[i - 1] if i > 0 else ra.pts[ra.nseg - 1], b) if pp == a else (a, b)
        cb = (rb.pts[j - 1] if j > 0 else rb.pts[rb.nseg - 1], d) if pp == c else (c, d)
        if _is_crossing(pp, ca[0], ca[1], cb[0], cb[1]):
            self._add_area(SELF_INTERSECTION, ra, rb, (p,), order, "rings cross at a vertex")
        elif ra.part == rb.part:
            self.touches[self._pairkey(ra, rb)].add(pp)

    @staticmethod
    def _pairkey(ra: _Ring, rb: _Ring) -> tuple[int, int]:
        return (ra.id, rb.id) if ra.id < rb.id else (rb.id, ra.id)

    # ------------------------------------------------------- ring-in-region checks

    def _locator(self, region: Sequence[_Ring]) -> Callable[[X.HPoint], int]:
        """Location of a point in the region of ``region[0]`` minus the open regions of
        ``region[1:]``: INSIDE, ON_BOUNDARY or OUTSIDE (even-odd per ring)."""
        outer, holes = region[0], region[1:]

        def locate(p: X.HPoint) -> int:
            loc = X.hp_in_ring(p, outer.pts)
            if loc != X.INSIDE:
                return loc
            for h in holes:
                lh = X.hp_in_ring(p, h.pts)
                if lh == X.INSIDE:
                    return X.OUTSIDE
                if lh == X.ON_BOUNDARY:
                    return X.ON_BOUNDARY
            return X.INSIDE

        return locate

    def _ring_vs_region(
        self, ring: _Ring, region: Sequence[_Ring], *, need_inside: bool
    ) -> tuple[X.HPoint | None, X.HPoint | None]:
        """A point of ``ring`` strictly outside the region and one strictly inside
        (None when there is none). Each segment is split at its contacts with the
        region's rings; every open piece then lies wholly inside, outside or on the
        boundary, so the vertices and the piece midpoints decide. Stops early once an
        outside point is found (and, if ``need_inside``, an inside point too)."""
        locate = self._locator(region)
        ids = [r.id for r in region]
        pts = ring.pts
        out_pt: X.HPoint | None = None
        in_pt: X.HPoint | None = None
        loc = locate(_hp(pts[0]))
        for i in range(ring.nseg):
            a, b = pts[i], pts[i + 1]
            if loc == X.OUTSIDE and out_pt is None:
                out_pt = _hp(a)
            elif loc == X.INSIDE and in_pt is None:
                in_pt = _hp(a)
            if out_pt is not None and (in_pt is not None or not need_inside):
                break
            g = ring.seg0 + i
            splits: list[X.HPoint] = []
            for rid in ids:
                splits.extend(self.contacts.get((g, rid), ()))
            if not splits:
                continue  # the whole segment and b share a's location
            hb = _hp(b)
            seq = X.sort_along(a, b, [_hp(a), hb, *splits])
            last = loc
            for u, v in pairwise(seq):
                m = X.hp_midpoint(u, v)
                last = locate(m)
                if last == X.OUTSIDE and out_pt is None:
                    out_pt = m
                elif last == X.INSIDE and in_pt is None:
                    in_pt = m
            loc = X.ON_BOUNDARY if any(X.hp_eq(s, hb) for s in splits) else last
        return out_pt, in_pt

    def holes_in_shells(self) -> None:
        for pi, shell in enumerate(self.shell_of):
            if shell is None:
                continue
            for h in self.holes_of[pi]:
                if not _bbox_covers(shell.bbox, h.bbox):
                    sb = shell.bbox
                    v = next(
                        p for p in h.pts if not (sb[0] <= p[0] <= sb[2] and sb[1] <= p[1] <= sb[3])
                    )
                    out = _hp(v)
                else:
                    out, _ = self._ring_vs_region(h, [shell], need_inside=False)
                if out is not None:
                    self.later.append(
                        Defect(
                            HOLE_OUTSIDE_SHELL,
                            (h.site,),
                            (self.scale.rational_hpoint(out),),
                        )
                    )

    def _nested(self, inner: _Ring, region: Sequence[_Ring]) -> X.HPoint | None:
        if not _bbox_covers(region[0].bbox, inner.bbox):
            return None
        out, inside = self._ring_vs_region(inner, region, need_inside=True)
        return inside if out is None else None

    def nested_holes(self) -> None:
        for holes in self.holes_of:
            for x in range(len(holes)):
                for y in range(x + 1, len(holes)):
                    hi, hj = holes[x], holes[y]
                    for inner, outer in ((hi, hj), (hj, hi)):
                        w = self._nested(inner, [outer])
                        if w is not None:
                            self.later.append(
                                Defect(
                                    NESTED_HOLES,
                                    (inner.site, outer.site),
                                    (self.scale.rational_hpoint(w),),
                                    detail=f"hole {inner.k} lies in hole {outer.k}",
                                )
                            )
                            break

    def nested_shells(self) -> None:
        if not self.multi:
            return
        for i, si in enumerate(self.shell_of):
            if si is None:
                continue
            for j, sj in enumerate(self.shell_of):
                if j == i or sj is None:
                    continue
                w = self._nested(si, [sj, *self.holes_of[j]])
                if w is not None:
                    self.later.append(
                        Defect(
                            NESTED_SHELLS,
                            (si.site, sj.site),
                            (self.scale.rational_hpoint(w),),
                            detail=f"part {i} lies in part {j}",
                        )
                    )

    def disconnected(self) -> None:
        by_part: dict[int, list[tuple[int, X.HPoint]]] = defaultdict(list)
        for (ra, rb), pts in self.touches.items():
            part = self.rings[ra].part
            ovs = self.overlaps.get((ra, rb), ())
            for p in pts:
                if any(X.hp_on_segment(_hp(p), q0[:2], q1[:2]) for q0, q1 in ovs):
                    continue  # an endpoint of a shared segment, not an isolated touch
                by_part[part].append((ra, _hp(p)))
                by_part[part].append((rb, _hp(p)))
        for part in sorted(by_part):
            edges = sorted(set(by_part[part]), key=lambda e: (e[0], X.hp_key(e[1])))
            cyc = _cycle_points(edges)
            if cyc:
                path = self.parts[part][0]
                self.later.append(
                    Defect(
                        DISCONNECTED_INTERIOR,
                        (Site(path),),
                        tuple(self.scale.rational_hpoint(p) for p in cyc),
                    )
                )

    def double_touch(self) -> bool:
        """GEOS's early-exit condition: two rings of one polygon touching at two
        distinct points (collinear-overlap endpoints included, as GEOS may see them)."""
        return any(len(pts) >= 2 for pts in self.touches.values())

    def geos_first(self) -> Defect | None:
        """The defect GEOS reports first, by emulating its noding order (None when the
        coordinates are not all doubles, or if the emulation finds no defect, which
        would contradict the exact analysis)."""
        if any(r.fpts is None for r in self.rings):
            return None
        emu = _GeosOrder(self)
        emu.node()
        if emu.code is not None:
            ra, rb, res = emu.code_pair
            if res.kind == X.OVERLAP:
                loc = tuple(sorted(res.points, key=X.hp_key))
            else:
                loc = (res.points[0],)
            lo, hi = (ra.id, rb.id) if ra.id <= rb.id else (rb.id, ra.id)
            hit = self.area.get((emu.code, lo, hi, loc))
            return None if hit is None else hit[1]
        if emu.double_touch is not None:
            code, ring, pt = emu.later()
            for d in self.later:
                if d.code == code and (ring is None or ring.site in d.sites):
                    return d
            site = ring.site if ring is not None else Site(self.parts[emu.double_touch_part][0])
            return Defect(
                code,
                (site,),
                (self.scale.rational_hpoint(_hp(pt)),),
                detail="GEOS's single-point test after its noder stopped at a double touch",
            )
        return None

    # ------------------------------------------------------------------- the unit

    def run(self) -> _Unit:
        self.check_rings()
        self.intersections()
        self.holes_in_shells()
        self.nested_holes()
        self.nested_shells()
        self.disconnected()
        unit = _Unit()
        for coords_d, closure_d, size_d in self.pre:
            unit.defects.extend(coords_d + closure_d + size_d)
        area = sorted(self.area.values(), key=lambda t: t[0])
        unit.defects.extend(d for _, d in area)
        unit.defects.extend(self.later)
        # first reason, GEOS order
        if self.multi:
            for coords_d, closure_d, size_d in self.pre:
                lst = coords_d or closure_d or size_d
                if lst:
                    unit.first = lst[0]
                    return unit
        else:
            for kind in range(3):
                for triple in self.pre:
                    if triple[kind]:
                        unit.first = triple[kind][0]
                        return unit
        if area:
            kinds = [c for c in _AREA_CODES if any(d.code == c for _, d in area)]
            alts = list(kinds)
            if self.double_touch():
                later = _LATER_CODES if self.multi else _LATER_CODES[:2] + _LATER_CODES[3:]
                alts.extend(later)
            unit.alternatives = tuple(alts)
            unit.certain = len(alts) == 1
            unit.first = area[0][1]
            emulated = self.geos_first()
            if emulated is not None:
                unit.first, unit.basis = emulated, "geos-order"
            elif not unit.certain:
                unit.basis = "heuristic"
            return unit
        for code in _LATER_CODES:
            for d in self.later:
                if d.code == code:
                    unit.first = d
                    return unit
        return unit


# ============================================================================ GEOS order
#
# The noding order of GEOS 3.13 ``IsValidOp`` (MCIndexNoder over MonotoneChains in a
# TemplateSTRtree, with ``PolygonIntersectionAnalyzer`` stopping at the first invalid
# intersection or double touch). Only the *first reason* depends on it, and only when the
# unit has area intersections of both kinds or a double touch; the emulation reproduces
# GEOS's choice there. Decisions are exact; the tree is sorted on the double sums
# ``minX + maxX`` as GEOS does, with libstdc++'s ``std::sort`` (whose tie order matters).

_STD_SORT_THRESHOLD = 16


def _std_sort(a: list, key: Callable[[Any], Any]) -> None:
    """libstdc++ ``std::sort(first, last, comp)`` with ``comp(x, y) = key(x) < key(y)``,
    reproducing its exact (unstable) order of equal keys."""
    n = len(a)
    if n < 2:
        return
    ks = [key(x) for x in a]
    idx = list(range(n))  # sort positions; values compared through ks

    def less(i: int, j: int) -> bool:
        return ks[i] < ks[j]

    def adjust_heap(first: int, hole: int, length: int, value: int) -> None:
        top = hole
        second = hole
        while second < (length - 1) // 2:
            second = 2 * (second + 1)
            if less(idx[first + second], idx[first + second - 1]):
                second -= 1
            idx[first + hole] = idx[first + second]
            hole = second
        if (length & 1) == 0 and second == (length - 2) // 2:
            second = 2 * (second + 1)
            idx[first + hole] = idx[first + second - 1]
            hole = second - 1
        parent = (hole - 1) // 2
        while hole > top and less(idx[first + parent], value):
            idx[first + hole] = idx[first + parent]
            hole = parent
            parent = (hole - 1) // 2
        idx[first + hole] = value

    def heap_sort(first: int, last: int) -> None:
        length = last - first
        if length >= 2:
            parent = (length - 2) // 2
            while True:
                adjust_heap(first, parent, length, idx[first + parent])
                if parent == 0:
                    break
                parent -= 1
        while last - first > 1:
            last -= 1
            value = idx[last]
            idx[last] = idx[first]
            adjust_heap(first, 0, last - first, value)

    def median_to_first(result: int, x: int, y: int, z: int) -> None:
        if less(idx[x], idx[y]):
            if less(idx[y], idx[z]):
                m = y
            elif less(idx[x], idx[z]):
                m = z
            else:
                m = x
        elif less(idx[x], idx[z]):
            m = x
        elif less(idx[y], idx[z]):
            m = z
        else:
            m = y
        idx[result], idx[m] = idx[m], idx[result]

    def partition(first: int, last: int, pivot: int) -> int:
        while True:
            while less(idx[first], idx[pivot]):
                first += 1
            last -= 1
            while less(idx[pivot], idx[last]):
                last -= 1
            if not first < last:
                return first
            idx[first], idx[last] = idx[last], idx[first]
            first += 1

    def introsort(first: int, last: int, depth: int) -> None:
        while last - first > _STD_SORT_THRESHOLD:
            if depth == 0:
                heap_sort(first, last)
                return
            depth -= 1
            mid = first + (last - first) // 2
            median_to_first(first, first + 1, mid, last - 1)
            cut = partition(first + 1, last, first)
            introsort(cut, last, depth)
            last = cut

    def linear_insert(last: int) -> None:
        val = idx[last]
        nxt = last - 1
        while less(val, idx[nxt]):
            idx[last] = idx[nxt]
            last = nxt
            nxt -= 1
        idx[last] = val

    def insertion_sort(first: int, last: int) -> None:
        for i in range(first + 1, last):
            if less(idx[i], idx[first]):
                val = idx[i]
                idx[first + 1 : i + 1] = idx[first:i]
                idx[first] = val
            else:
                linear_insert(i)

    introsort(0, n, 2 * (n.bit_length() - 1))
    if n > _STD_SORT_THRESHOLD:
        insertion_sort(0, _STD_SORT_THRESHOLD)
        for i in range(_STD_SORT_THRESHOLD, n):
            linear_insert(i)
    else:
        insertion_sort(0, n)
    a[:] = [a[i] for i in idx]


class _STRNode:
    """A node of an emulated ``TemplateSTRtree``: a leaf (``item >= 0``, ``pos`` its
    index in the sorted leaf array) or a branch with ordered ``children``."""

    __slots__ = ("bounds", "children", "item", "pos")

    def __init__(self, bounds, item: int = -1, children: list | None = None):
        self.bounds = bounds
        self.item = item
        self.children = children
        self.pos = -1


def _strtree(boxes: Sequence[tuple[float, float, float, float]]) -> tuple[list[_STRNode], Any]:
    """GEOS ``TemplateSTRtree::build`` (node capacity 10) over items inserted in order
    with bounds ``(minx, miny, maxx, maxy)``: returns the leaves in their final array
    order (sorted in place by the first level) and the root."""
    cap = 10
    level = [_STRNode(b, i) for i, b in enumerate(boxes)]
    leaves = level
    first = True
    while len(level) > 1:
        n = len(level)
        slices = math.ceil(math.sqrt(math.ceil(n / cap)))
        per = math.ceil(n / slices)
        _std_sort(level, key=lambda node: node.bounds[0] + node.bounds[2])
        arranged: list[_STRNode] = []
        parents: list[_STRNode] = []
        start = 0
        for _ in range(slices):
            chunk = level[start : start + min(n - start, per)]
            start += len(chunk)
            _std_sort(chunk, key=lambda node: node.bounds[1] + node.bounds[3])
            arranged.extend(chunk)
            for g in range(0, len(chunk), cap):
                kids = chunk[g : g + cap]
                bounds = (
                    min(k.bounds[0] for k in kids),
                    min(k.bounds[1] for k in kids),
                    max(k.bounds[2] for k in kids),
                    max(k.bounds[3] for k in kids),
                )
                parents.append(_STRNode(bounds, children=kids))
        if first:
            leaves = arranged
            first = False
        level = parents
    for i, leaf in enumerate(leaves):
        leaf.pos = i
    return leaves, (level[0] if level else None)


def _boxes_meet(a, b) -> bool:
    return not (a[0] > b[2] or a[2] < b[0] or a[1] > b[3] or a[3] < b[1])


def _geos_quadrant(p: tuple[int, int], q: tuple[int, int]) -> int:
    """GEOS ``Quadrant::quadrant(p, q)``: NE 0, NW 1, SW 2, SE 3 (axes go to NE/NW/SE)."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    if dx >= 0:
        return 0 if dy >= 0 else 3
    return 1 if dy >= 0 else 2


def _env_meet(p0, p1, q0, q1) -> bool:
    """``Envelope::intersects(p0, p1, q0, q1)`` for two segments' bounding boxes."""
    if min(p0[0], p1[0]) > max(q0[0], q1[0]) or max(p0[0], p1[0]) < min(q0[0], q1[0]):
        return False
    return not (min(p0[1], p1[1]) > max(q0[1], q1[1]) or max(p0[1], p1[1]) < min(q0[1], q1[1]))


def _angle_greater(o, p, q) -> bool:
    """``PolygonNodeTopology.isAngleGreater``: the direction ``o -> p`` has a larger
    angle in ``[0, 2 pi)`` than ``o -> q``."""
    return X.angle_cmp((p[0] - o[0], p[1] - o[1]), (q[0] - o[0], q[1] - o[1])) > 0


def _geos_interior_segment(node, a0, a1, b) -> bool:
    """``PolygonNodeTopology.isInteriorSegment``: is ``node -> b`` inside the corner
    ``a0 - node - a1`` whose interior lies between ``a0`` and ``a1`` counter-clockwise
    (i.e. on the right of ``a0 -> node -> a1``)?"""
    lo, hi, interior_between = a0, a1, True
    if _angle_greater(node, lo, hi):
        lo, hi, interior_between = a1, a0, False
    between = _angle_greater(node, b, lo) and not _angle_greater(node, b, hi)
    return between == interior_between


def _geos_ring_nested(test: _Ring, target: _Ring) -> bool:
    """``PolygonTopologyAnalyzer.isRingNested``: GEOS's one-point (or one-corner) test
    of whether ``test`` lies inside ``target``."""
    p0 = test.pts[0]
    loc = X.point_in_ring(p0, target.pts)
    if loc != X.ON_BOUNDARY:
        return loc == X.INSIDE
    p1 = test.pts[1]
    pts = target.raw
    m = len(pts)
    index = -1
    for i in range(m - 1):
        if X.on_segment(p0, pts[i], pts[i + 1]):
            index = i + 1 if p0 == pts[i + 1] else i
            break
    i_prev = index
    while pts[i_prev] == p0:
        i_prev = m - 2 if i_prev == 0 else i_prev - 1
    i_next = index + 1
    while pts[i_next] == p0:
        i_next = 0 if i_next >= m - 2 else i_next + 1
    r_prev, r_next = pts[i_prev], pts[i_next]
    if _is_ccw(pts):
        r_prev, r_next = r_next, r_prev
    return _geos_interior_segment(p0, r_prev, r_next, p1)


class _GeosOrder:
    """GEOS 3.13 ``IsValidOp`` on one polygonal unit, in GEOS's own processing order,
    from the area-intersection phase on (the earlier checks are order-free)."""

    def __init__(self, pa: _Polygonal):
        self.pa = pa
        self.chains: list[tuple[_Ring, int, int]] = []
        for r in pa.rings:  # the segment strings, in GEOS order
            pts = r.pts
            start, quad = 0, -1
            for i in range(1, len(pts)):
                q = _geos_quadrant(pts[i - 1], pts[i])
                if quad < 0:
                    quad = q
                elif q != quad:
                    self.chains.append((r, start, i - 1))
                    start, quad = i - 1, q
            self.chains.append((r, start, len(pts) - 1))
        self.code: str | None = None
        self.code_pair: tuple | None = None
        self.double_touch: tuple[int, int] | None = None
        self.double_touch_part = -1
        self.touch_at: dict[tuple[int, int], tuple[int, int]] = {}

    @property
    def done(self) -> bool:
        return self.code is not None or self.double_touch is not None

    # ---------------------------------------------------------------- MCIndexNoder

    def node(self) -> None:
        """``MCIndexNoder::intersectChains`` via ``TemplateSTRtree::queryPairs``: for
        each leaf in array order, a depth-first walk visits the leaves at higher array
        positions whose bounds meet it; a walk stops after the first chain pair once
        the analyzer is done."""
        chains = self.chains
        boxes = []
        for r, s, e in chains:
            fa, fb = r.fpts[s], r.fpts[e]
            boxes.append(
                (min(fa[0], fb[0]), min(fa[1], fb[1]), max(fa[0], fb[0]), max(fa[1], fb[1]))
            )
        leaves, root = _strtree(boxes)
        if len(leaves) < 2:
            return

        def walk(q: _STRNode, node: _STRNode) -> bool:
            for child in node.children:
                if child.children is None:
                    if child.pos > q.pos and _boxes_meet(child.bounds, q.bounds):
                        self._overlaps(chains[q.item], chains[child.item])
                        if self.done:
                            return False
                elif _boxes_meet(child.bounds, q.bounds) and not walk(q, child):
                    return False
            return True

        # queryPairs ignores the abort in its outer loop: once the analyzer is done,
        # every later leaf still processes its first candidate chain pair, and a
        # later invalid pair overwrites the code (GEOS 3.13-3.16).
        for q in leaves:
            walk(q, root)

    def _overlaps(self, c0, c1) -> None:
        r0, s0, e0 = c0
        r1, s1, e1 = c1
        p0, p1 = r0.pts, r1.pts

        def rec(s0: int, e0: int, s1: int, e1: int) -> None:
            if e0 - s0 == 1 and e1 - s1 == 1:
                self._process(r0, s0, r1, s1)
                return
            if not _env_meet(p0[s0], p0[e0], p1[s1], p1[e1]):
                return
            m0, m1 = (s0 + e0) // 2, (s1 + e1) // 2
            if s0 < m0:
                if s1 < m1:
                    rec(s0, m0, s1, m1)
                if m1 < e1:
                    rec(s0, m0, m1, e1)
            if m0 < e0:
                if s1 < m1:
                    rec(m0, e0, s1, m1)
                if m1 < e1:
                    rec(m0, e0, m1, e1)

        rec(s0, e0, s1, e1)

    def _process(self, ra: _Ring, i: int, rb: _Ring, j: int) -> None:
        """``PolygonIntersectionAnalyzer.processIntersections``: a later invalid pair
        overwrites an earlier one (the noder only stops between chain pairs)."""
        if ra is rb and i == j:
            return
        a, b = ra.pts[i], ra.pts[i + 1]
        c, d = rb.pts[j], rb.pts[j + 1]
        res = X.intersect_segments(a, b, c, d)
        if not res:
            return
        code = None
        if res.kind == X.OVERLAP:
            code = SELF_INTERSECTION
        else:
            p = res.points[0]
            pp = (p[0], p[1])
            if p[2] != 1 or pp not in (a, b, c, d):
                code = SELF_INTERSECTION
            elif ra is rb:
                dd = abs(i - j)
                if dd <= 1 or dd >= ra.nseg - 1:
                    return
                code = RING_SELF_INTERSECTION
            else:
                if pp in (b, d):
                    return
                ca = (ra.pts[i - 1] if i > 0 else ra.pts[ra.nseg - 1], b) if pp == a else (a, b)
                cb = (rb.pts[j - 1] if j > 0 else rb.pts[rb.nseg - 1], d) if pp == c else (c, d)
                if _is_crossing(pp, ca[0], ca[1], cb[0], cb[1]):
                    code = SELF_INTERSECTION
                elif self._add_touch(ra, rb, pp):
                    self.double_touch = pp
                    self.double_touch_part = ra.part
        if code is not None:
            self.code = code
            self.code_pair = (ra, rb, res)

    def _add_touch(self, ra: _Ring, rb: _Ring, pt: tuple[int, int]) -> bool:
        """``PolygonRing.addTouch``: True for a double touch."""
        pa = self.pa
        if ra.part != rb.part or not pa.part_has_holes[ra.part]:
            return False
        for x, y in ((ra, rb), (rb, ra)):
            t = self.touch_at.get((x.id, y.id))
            if t is not None and t != pt:
                return True
        self.touch_at.setdefault((ra.id, rb.id), pt)
        self.touch_at.setdefault((rb.id, ra.id), pt)
        return False

    # ------------------------------------------------ checks after a double touch

    def _locate_in_part(self, p: tuple[int, int], part: int) -> int:
        """``IndexedPointInAreaLocator`` on a polygon: boundary if on any ring, else
        even-odd over all its rings together."""
        pa = self.pa
        rings = [pa.shell_of[part], *pa.holes_of[part]]
        inside = False
        for r in rings:
            loc = X.point_in_ring(p, r.pts)
            if loc == X.ON_BOUNDARY:
                return X.ON_BOUNDARY
            if loc == X.INSIDE:
                inside = not inside
        return X.INSIDE if inside else X.OUTSIDE

    def later(self) -> tuple[str, _Ring | None, tuple[int, int]]:
        """GEOS's remaining checks after its noder stopped at a double touch (with
        possibly unseen intersections): holes in shell, nested holes, nested shells,
        then the disconnected interior that the double touch already established."""
        pa = self.pa
        for pi, shell in enumerate(pa.shell_of):
            if shell is None:
                continue
            for h in pa.holes_of[pi]:
                if not _bbox_covers(shell.bbox, h.bbox) or not _geos_ring_nested(h, shell):
                    return HOLE_OUTSIDE_SHELL, h, h.raw[0]
        for holes in pa.holes_of:
            for hi in holes:
                for hj in holes:
                    if (
                        hj is not hi
                        and _bbox_covers(hj.bbox, hi.bbox)
                        and _geos_ring_nested(hi, hj)
                    ):
                        return NESTED_HOLES, hi, hi.raw[0]
        if pa.multi:
            for i, si in enumerate(pa.shell_of):
                if si is None:
                    continue
                for j, sj in enumerate(pa.shell_of):
                    if j == i or sj is None or not _bbox_covers(sj.bbox, si.bbox):
                        continue
                    if self._shell_nested(si, j):
                        return NESTED_SHELLS, si, si.raw[0]
        assert self.double_touch is not None
        return DISCONNECTED_INTERIOR, None, self.double_touch

    def _shell_nested(self, shell: _Ring, part: int) -> bool:
        """``IndexedNestedPolygonTester.findNestedPoint``."""
        for p in (shell.raw[0], shell.raw[1]):
            loc = self._locate_in_part(p, part)
            if loc == X.OUTSIDE:
                return False
            if loc == X.INSIDE:
                return True
        pa = self.pa
        if not _geos_ring_nested(shell, pa.shell_of[part]):
            return False
        return not any(
            _bbox_covers(h.bbox, shell.bbox) and _geos_ring_nested(shell, h)
            for h in pa.holes_of[part]
        )


# ============================================================================ walk


def _walk(geom: Geometry, path: tuple[int, ...], scale: CoordScale, units: list[_Unit]) -> None:
    if isinstance(geom, Polygon):
        if not _polygon_truly_empty(geom):
            units.append(_Polygonal([(path, geom)], False, scale).run())
    elif isinstance(geom, MultiPolygon):
        if not all(_polygon_truly_empty(p) for p in geom.polygons):
            parts = [((*path, i), p) for i, p in enumerate(geom.polygons)]
            units.append(_Polygonal(parts, True, scale).run())
    elif isinstance(geom, Point):
        if not geom.is_empty:
            units.append(_check_points([(path, geom)]))
    elif isinstance(geom, MultiPoint):
        if not geom.is_empty:
            units.append(_check_points([((*path, i), p) for i, p in enumerate(geom.points)]))
    elif isinstance(geom, LineString):
        if not geom.is_empty:
            units.append(_check_line(path, geom, scale))
    elif isinstance(geom, (MultiLineString, GeometryCollection)):
        for i, child in enumerate(geom.children()):
            _walk(child, (*path, i), scale, units)
    else:  # pragma: no cover - every concrete type is handled above
        raise TypeError(f"not a geometry: {geom!r}")


def _defect_key(d: Defect) -> tuple:
    sites = tuple(
        (s.path, -1 if s.ring is None else s.ring, -1 if s.vertex is None else s.vertex)
        for s in d.sites
    )
    return (_RANK[d.code], sites, tuple(d.location))


def validate(geom: Geometry) -> ValidityReport:
    """The exact validity of ``geom`` (any type), with every defect.

    Never raises on non-finite coordinates: they are ``invalid_coordinate`` defects.
    """
    scale = CoordScale.for_geometry(geom)
    units: list[_Unit] = []
    _walk(geom, (), scale, units)
    defects = [d for u in units for d in u.defects]
    defects.sort(key=_defect_key)
    for u in units:
        if u.first is not None:
            return ValidityReport(tuple(defects), u.first, u.certain, u.alternatives, u.basis)
    return ValidityReport(tuple(defects))


def is_valid(geom: Geometry) -> bool:
    """True if ``geom`` is valid under GEOS-default (OGC) rules, decided exactly."""
    return validate(geom).valid
