"""Standalone RelateNG-style point locator (DESIGN §1 "Point location").

``locate(point, geometry)`` returns ``"I"``, ``"B"`` or ``"E"``: the location of an exact
point relative to any geometry -- Point, LineString, Polygon, their Multi* forms, and
(nested) GeometryCollections -- following the rules of JTS/GEOS RelateNG
(``RelatePointLocator``, Mod-2 boundary node rule), in exact arithmetic.

This module is the point-location half of the witness relate (§2.4). It deliberately
shares nothing with the arrangement (§2.2/§2.3): it never builds a DCEL, and it uses only
the primitives of :mod:`geotruth.exact` and :mod:`geotruth.numbers`.

Rules (dimension precedence: polygonal, then linear, then points)
-----------------------------------------------------------------
1. **Polygonal part** -- the union of all non-empty Polygon elements, wherever they occur
   (a Polygon, the parts of a MultiPolygon, the polygons of a GC).

   Each element is located as JTS ``SimplePointInAreaLocator.locatePointInPolygon`` does:
   exterior if outside (even-odd) or on no ring of the shell, boundary if on the shell,
   then for each hole in order: boundary if on it, exterior if inside it; otherwise
   interior. Then, as ``RelatePointLocator.locateOnPolygons``:

   - *Interior* if the point is in the interior of some element;
   - *Boundary* if it is on the boundary of exactly one element;
   - if it is on the boundary of two or more elements (shared edges or vertices of GC
     members, touching parts of a MultiPolygon), the adjacent-edge rule decides
     (``AdjacentEdgeLocator``): *Interior* if the union of the elements covers a whole
     neighbourhood of the point -- every open angular sector around it, between
     consecutive ring edges incident to it, lies in the interior of some element --
     otherwise *Boundary*.

   Elements are counted as atomic polygons (the union semantics of the design); RelateNG
   counts a MultiPolygon member of a GC once. The two agree for valid MultiPolygons.

2. **Linear part** -- every non-empty LineString element (including zero-length ones):

   - *Boundary* if the point occurs an odd number of times among the first and last
     coordinates of all line elements (a closed line contributes its start point twice).
     This test comes first, as in ``RelatePointLocator.locateOnLines``, so a point that is
     an endpoint of one line and interior to another is still Boundary.
   - otherwise *Interior* if it lies on some line (a zero-length or single-point line is
     the point it repeats).

3. **Points** -- *Interior* if the point equals a Point element.

4. Otherwise *Exterior*. An empty geometry locates every point in its exterior.

Coordinates and frames
----------------------
Locating runs on integers. A :class:`Frame` maps real coordinates to integers: the
real value of an integer ``i`` is ``i * num / den``. For double coordinates (every input
geometry) the frame is the per-case :class:`~geotruth.numbers.DyadicScale`; exact rational
coordinates (engine output, hand-made test geometries) get a common-denominator frame.
The query point may be any exact point: a pair of ints, Fractions, ``mpq`` or finite
floats, a homogeneous triple ``(X, Y, W)`` of ints (``W != 0``), or a non-empty
:class:`~geotruth.geom.Point`. It needs no particular denominator.

:class:`PointLocator` is the prepared form for many queries in one frame (the witness
relate locates thousands of points); its ``locate`` takes a canonical homogeneous point
already expressed in the frame. Non-finite coordinates raise
:class:`~geotruth.numbers.NonFiniteError`.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from geotruth.exact import (
    INSIDE,
    ON_BOUNDARY,
    OUTSIDE,
    HPoint,
    angle_cmp,
    angle_key,
    cross,
    hp_in_ring,
    hp_on_segment,
    hpoint,
    hpoint_of,
    ratio_cmp,
    sqdist_point_segment,
)
from geotruth.geom import Geometry, LineString, Point, Polygon
from geotruth.numbers import DyadicScale, NonFiniteError

__all__ = [
    "BOUNDARY",
    "DIM_EXTERIOR",
    "EXTERIOR",
    "INTERIOR",
    "LOCATION_CHARS",
    "Frame",
    "PointLocator",
    "direction_between",
    "exact_value",
    "locate",
    "locate_with_dim",
    "location_char",
    "safe_step_exponent",
]

#: Locations, with the values of JTS ``Location`` (they double as DE-9IM indices).
INTERIOR, BOUNDARY, EXTERIOR = 0, 1, 2

#: ``LOCATION_CHARS[loc]`` is ``"I"``, ``"B"`` or ``"E"``.
LOCATION_CHARS = "IBE"

#: The "dimension" reported with an Exterior location (no part of the geometry decided).
DIM_EXTERIOR = -1


def location_char(loc: int) -> str:
    """``"I"``, ``"B"`` or ``"E"`` for a location value."""
    return LOCATION_CHARS[loc]


# ============================================================================ numbers


def exact_value(v: Any) -> Fraction:
    """The exact value of a coordinate as a :class:`~fractions.Fraction`.

    Accepts ``int``, finite ``float`` (converted exactly), ``Fraction``, and anything with
    integer ``numerator``/``denominator`` (``gmpy2.mpq``). Raises
    :class:`~geotruth.numbers.NonFiniteError` for NaN/inf and ``TypeError`` otherwise.
    """
    if isinstance(v, bool):
        raise TypeError("a boolean is not a coordinate")
    if isinstance(v, Fraction):
        return v
    if isinstance(v, int):
        return Fraction(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise NonFiniteError(f"non-finite coordinate {v!r}")
        return Fraction(v)
    if hasattr(v, "numerator") and hasattr(v, "denominator"):
        return Fraction(int(v.numerator), int(v.denominator))
    raise TypeError(f"not an exact number: {v!r}")


def _is_power_of_two(d: int) -> bool:
    return d > 0 and d & (d - 1) == 0


def _valuation(f: Fraction) -> int:
    """The 2-adic valuation of a non-zero dyadic rational."""
    n = f.numerator
    return ((n & -n).bit_length() - 1) - (f.denominator.bit_length() - 1)


@dataclass(frozen=True)
class Frame:
    """An integer frame: the integer ``i`` stands for the real value ``i * num / den``.

    ``scale`` is set when the frame is a :class:`~geotruth.numbers.DyadicScale` (every
    coordinate is dyadic: doubles, ints, dyadic rationals); its fast exact conversion is
    then used for doubles.
    """

    num: int = 1
    den: int = 1
    scale: DyadicScale | None = None

    # -- construction --------------------------------------------------------------

    @classmethod
    def from_scale(cls, scale: DyadicScale) -> Frame:
        """The frame of a dyadic scale ``2**exp``."""
        if scale.exp >= 0:
            return cls(1 << scale.exp, 1, scale)
        return cls(1, 1 << -scale.exp, scale)

    @classmethod
    def for_values(cls, values: Iterable[Any]) -> Frame:
        """The coarsest frame in which every value is an integer.

        Doubles get the per-case dyadic scale; exact rationals the frame
        ``gcd(values)``. Raises :class:`~geotruth.numbers.NonFiniteError` on NaN/inf.
        """
        vals = list(values)
        if all(isinstance(v, float) for v in vals):
            for v in vals:
                if not math.isfinite(v):
                    raise NonFiniteError(f"non-finite coordinate {v!r}")
            return cls.from_scale(DyadicScale.for_values(vals))
        fr = [exact_value(v) for v in vals]
        nonzero = [f for f in fr if f != 0]
        if not nonzero:
            return cls(1, 1)
        if all(_is_power_of_two(f.denominator) for f in nonzero):
            # dyadic values (ints, doubles, dyadic rationals): the per-case dyadic scale,
            # with the minimum 2-adic valuation computed exactly (no float conversion)
            return cls.from_scale(DyadicScale(min(_valuation(f) for f in nonzero)))
        den = 1
        for f in nonzero:
            den = den * f.denominator // math.gcd(den, f.denominator)
        num = 0
        for f in nonzero:
            num = math.gcd(num, f.numerator * (den // f.denominator))
        g = math.gcd(num, den)
        return cls(num // g, den // g)

    @classmethod
    def for_geometries(cls, *geoms: Geometry) -> Frame:
        """The frame of a case: one frame for all coordinates of all operands."""
        return cls.for_values(v for g in geoms for v in g.iter_values())

    # -- conversions ---------------------------------------------------------------------

    def to_int(self, v: Any) -> int:
        """The integer standing for the real value ``v`` (which must be representable)."""
        if self.scale is not None and isinstance(v, float):
            return self.scale.to_int(v)
        f = exact_value(v) * self.den / self.num
        if f.denominator != 1:
            raise ValueError(f"{v!r} is not an integer in frame {self.num}/{self.den}")
        return f.numerator

    def to_int_point(self, c: Sequence[Any]) -> tuple[int, int]:
        """A coordinate pair as an integer point of the frame."""
        return self.to_int(c[0]), self.to_int(c[1])

    def hpoint(self, point: Any) -> HPoint:
        """The canonical homogeneous point of the frame for an exact real point.

        ``point`` is a pair of exact numbers, a homogeneous triple of ints ``(X, Y, W)``
        with ``W != 0``, or a non-empty :class:`~geotruth.geom.Point`.
        """
        if isinstance(point, Point):
            if point.coord is None:
                raise ValueError("cannot locate an empty point")
            point = point.coord
        if len(point) == 3:
            x_, y_, w_ = point
            if not all(isinstance(t, int) and not isinstance(t, bool) for t in point):
                raise TypeError(f"a homogeneous point needs three ints: {point!r}")
            if w_ == 0:
                raise ZeroDivisionError("homogeneous weight W must be non-zero")
            x, y = Fraction(x_, w_), Fraction(y_, w_)
        elif len(point) == 2:
            x, y = exact_value(point[0]), exact_value(point[1])
        else:
            raise ValueError(f"a point has 2 coordinates or 3 homogeneous ones: {point!r}")
        k = Fraction(self.den, self.num)
        return hpoint_of((x * k, y * k))

    def to_fractions(self, p: HPoint) -> tuple[Fraction, Fraction]:
        """The real coordinates of a homogeneous point of the frame."""
        x, y, w = p
        return Fraction(x * self.num, w * self.den), Fraction(y * self.num, w * self.den)


# ============================================================================ helpers


def _hp_in_bbox(p: HPoint, bbox: tuple[int, int, int, int]) -> bool:
    x, y, w = p
    return bbox[0] * w <= x <= bbox[2] * w and bbox[1] * w <= y <= bbox[3] * w


def _bbox(points: Iterable[tuple[int, int]]) -> tuple[int, int, int, int]:
    xs, ys = zip(*points, strict=True)
    return min(xs), min(ys), max(xs), max(ys)


def direction_between(u: Sequence[int], v: Sequence[int], single: bool = False) -> tuple[int, int]:
    """An integer direction strictly inside the open counter-clockwise sector from
    direction ``u`` to direction ``v`` (``u`` and ``v`` distinct directions).

    With ``single=True`` the sector is the whole plane minus the ray ``u`` (``v`` is
    ignored) and ``-u`` is returned.
    """
    if single:
        return -u[0], -u[1]
    c = cross(u[0], u[1], v[0], v[1])
    if c > 0:  # convex sector: any positive combination lies strictly inside
        return u[0] + v[0], u[1] + v[1]
    if c < 0:  # reflex sector: -(u + v) is outside the closed convex cone [v, u]
        return -(u[0] + v[0]), -(u[1] + v[1])
    return -u[1], u[0]  # opposite directions: a half-plane; turn u by +90 degrees


def safe_step_exponent(d2: int, dist2: tuple[int, int]) -> int:
    """The smallest ``k >= 0`` with ``d2 / 4**k < dist2`` (``dist2 = (num, den)`` > 0).

    A step ``s = 2**-k`` along a vector of squared length ``d2`` then moves strictly less
    than the distance ``sqrt(dist2)``.
    """
    n, d = dist2
    if n <= 0:
        raise ValueError("the distance must be positive")
    # d2 * d < n * 4**k
    k = max(0, ((d2 * d).bit_length() - n.bit_length()) // 2)
    while not d2 * d < n << (2 * k):
        k += 1
    while k > 0 and d2 * d < n << (2 * (k - 1)):
        k -= 1
    return k


def _hp_sqdist_segment(p: HPoint, a: Sequence[int], b: Sequence[int]) -> tuple[int, int]:
    """Squared distance from homogeneous ``p`` to the integer segment ``ab``, times
    ``W**2`` (so distances from the same ``p`` compare directly)."""
    x, y, w = p
    if w == 1:
        return sqdist_point_segment((x, y), a, b)
    return sqdist_point_segment((x, y), (a[0] * w, a[1] * w), (b[0] * w, b[1] * w))


# ============================================================================ locator


class _Poly:
    """One non-empty polygon element in integer coordinates."""

    __slots__ = ("bbox", "rings")

    def __init__(self, rings: list[list[tuple[int, int]]]) -> None:
        self.rings = rings  # rings[0] shell, then holes; every ring closed
        self.bbox = _bbox(c for r in rings for c in r)  # holes too, even if invalid

    def locate(self, p: HPoint) -> int:
        """JTS ``SimplePointInAreaLocator.locatePointInPolygon``."""
        if not _hp_in_bbox(p, self.bbox):
            return EXTERIOR
        shell = hp_in_ring(p, self.rings[0])
        if shell == OUTSIDE:
            return EXTERIOR
        if shell == ON_BOUNDARY:
            return BOUNDARY
        for hole in self.rings[1:]:
            h = hp_in_ring(p, hole)
            if h == ON_BOUNDARY:
                return BOUNDARY
            if h == INSIDE:
                return EXTERIOR
        return INTERIOR

    def segments(self) -> Iterable[tuple[tuple[int, int], tuple[int, int]]]:
        for ring in self.rings:
            for i in range(len(ring) - 1):
                if ring[i] != ring[i + 1]:
                    yield ring[i], ring[i + 1]


class _Line:
    """One non-empty line element in integer coordinates."""

    __slots__ = ("bbox", "coords", "segments")

    def __init__(self, coords: list[tuple[int, int]]) -> None:
        self.coords = coords
        self.bbox = _bbox(coords)
        self.segments = [
            (coords[i], coords[i + 1]) for i in range(len(coords) - 1) if coords[i] != coords[i + 1]
        ]

    def contains(self, p: HPoint) -> bool:
        if not _hp_in_bbox(p, self.bbox):
            return False
        if not self.segments:  # zero-length or single-point line: the point it repeats
            x, y, w = p
            return w == 1 and (x, y) == self.coords[0]
        return any(hp_on_segment(p, a, b) for a, b in self.segments)


def _closed_ring(coords: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    ring = list(coords)
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])  # JTS cannot build an unclosed ring; close it implicitly
    return ring


class PointLocator:
    """A geometry prepared for exact point location in a fixed integer :class:`Frame`.

    :meth:`locate` and :meth:`locate_with_dim` take canonical homogeneous points
    ``(X, Y, W)`` of the frame (see :meth:`Frame.hpoint`).
    """

    def __init__(self, geometry: Geometry, frame: Frame | None = None) -> None:
        self.geometry = geometry
        self.frame = frame if frame is not None else Frame.for_geometries(geometry)
        self.is_empty = geometry.is_empty
        to_pt = self.frame.to_int_point
        self.polys: list[_Poly] = []
        self.lines: list[_Line] = []
        self.points: set[tuple[int, int]] = set()
        degree: dict[tuple[int, int], int] = {}
        for e in geometry.elements():
            if e.is_empty:
                continue
            if isinstance(e, Polygon):
                rings = [_closed_ring([to_pt(c) for c in r]) for r in e.rings if r]
                self.polys.append(_Poly(rings))
            elif isinstance(e, LineString):
                coords = [to_pt(c) for c in e.coords]
                self.lines.append(_Line(coords))
                # Mod-2 rule input: first and last coordinate of every line element
                # (a closed line contributes its start point twice)
                for c in (coords[0], coords[-1]):
                    degree[c] = degree.get(c, 0) + 1
            elif isinstance(e, Point):
                self.points.add(to_pt(e.coord))
        #: The Mod-2 boundary of the linear part: endpoints of odd degree.
        self.line_boundary: frozenset[tuple[int, int]] = frozenset(
            c for c, n in degree.items() if n % 2 == 1
        )

    # -- queries ------------------------------------------------------------------------

    def locate(self, p: HPoint) -> int:
        """Location of the canonical homogeneous point ``p``: INTERIOR, BOUNDARY or
        EXTERIOR."""
        return self.locate_with_dim(p)[0]

    def locate_with_dim(self, p: HPoint) -> tuple[int, int]:
        """``(location, dimension)``: the dimension (2, 1, 0) of the part of the geometry
        that decided the location, as JTS ``DimensionLocation``, or
        :data:`DIM_EXTERIOR` (-1) for Exterior."""
        if self.is_empty:
            return EXTERIOR, DIM_EXTERIOR
        if self.polys:
            loc = self._locate_polygonal(p)
            if loc != EXTERIOR:
                return loc, 2
        if self.lines:
            x, y, w = p
            if w == 1 and (x, y) in self.line_boundary:
                return BOUNDARY, 1
            if any(line.contains(p) for line in self.lines):
                return INTERIOR, 1
        if self.points:
            x, y, w = p
            if w == 1 and (x, y) in self.points:
                return INTERIOR, 0
        return EXTERIOR, DIM_EXTERIOR

    def locate_polygonal(self, p: HPoint) -> int:
        """Location relative to the polygonal part alone (EXTERIOR if there is none)."""
        return self._locate_polygonal(p) if self.polys else EXTERIOR

    # -- polygonal part --------------------------------------------------------------------

    def _locate_polygonal(self, p: HPoint) -> int:
        on_boundary = 0
        for poly in self.polys:
            loc = poly.locate(p)
            if loc == INTERIOR:
                return INTERIOR
            if loc == BOUNDARY:
                on_boundary += 1
        if on_boundary == 0:
            return EXTERIOR
        if on_boundary == 1:
            return BOUNDARY
        return INTERIOR if self._union_covers_neighbourhood(p) else BOUNDARY

    def incident_directions(self, p: HPoint) -> list[tuple[int, int]]:
        """Distinct directions (sorted counter-clockwise from +x) of the polygon ring
        edges leaving ``p``; empty if ``p`` is on no ring."""
        dirs: list[tuple[int, int]] = []
        x, y, w = p
        for poly in self.polys:
            if not _hp_in_bbox(p, poly.bbox):
                continue
            for a, b in poly.segments():
                if w == 1 and (x, y) == a:
                    dirs.append((b[0] - a[0], b[1] - a[1]))
                elif w == 1 and (x, y) == b:
                    dirs.append((a[0] - b[0], a[1] - b[1]))
                elif hp_on_segment(p, a, b):
                    dirs.append((b[0] - a[0], b[1] - a[1]))
                    dirs.append((a[0] - b[0], a[1] - b[1]))
        dirs.sort(key=angle_key)
        unique: list[tuple[int, int]] = []
        for d in dirs:
            if not unique or angle_cmp(unique[-1], d) != 0:
                unique.append(d)
        if len(unique) > 1 and angle_cmp(unique[0], unique[-1]) == 0:
            unique.pop()
        return unique

    def sector_samples(self, p: HPoint) -> list[HPoint]:
        """One exact point in each open angular sector around ``p`` between consecutive
        incident ring edges, closer to ``p`` than any ring edge not through ``p``.

        Every such sample lies on no ring, so each polygon element locates it strictly
        inside or outside, and it has the element memberships of its whole sector near
        ``p`` (the adjacent-edge analysis of RelateNG, done with sample points).
        """
        dirs = self.incident_directions(p)
        if not dirs:
            return []
        # squared distance (times W**2) from p to the nearest ring edge not through p
        best: tuple[int, int] | None = None
        for poly in self.polys:
            for a, b in poly.segments():
                d2 = _hp_sqdist_segment(p, a, b)
                if d2[0] == 0:
                    continue  # an edge through p (it is one of the incident rays)
                if best is None or ratio_cmp(d2, best) < 0:
                    best = d2
        x, y, w = p
        samples = []
        m = len(dirs)
        for i in range(m):
            d = direction_between(dirs[i], dirs[(i + 1) % m], single=(m == 1))
            # step s = 2**-k along d with |s d|**2 < distance**2 = best[0] / (best[1] W**2)
            k = (
                0
                if best is None
                else safe_step_exponent(d[0] * d[0] + d[1] * d[1], (best[0], best[1] * w * w))
            )
            # q = p + s d = (X 2**k + dx W, Y 2**k + dy W, W 2**k)
            samples.append(hpoint((x << k) + d[0] * w, (y << k) + d[1] * w, w << k))
        return samples

    def _union_covers_neighbourhood(self, p: HPoint) -> bool:
        """The adjacent-edge rule: True if every open sector around ``p`` lies in the
        interior of some polygon element (the union covers a neighbourhood of ``p``)."""
        samples = self.sector_samples(p)
        if not samples:  # pragma: no cover - p is on two boundaries, so on some ring
            return False
        return all(any(poly.locate(q) == INTERIOR for poly in self.polys) for q in samples)


# ============================================================================ API


def locate_with_dim(point: Any, geometry: Geometry) -> tuple[str, int]:
    """``(location char, dimension of the deciding part)`` of an exact point.

    The dimension is 2, 1 or 0 for the polygonal, linear or puntal part, -1 for
    Exterior (see :meth:`PointLocator.locate_with_dim`).
    """
    frame = Frame.for_geometries(geometry)
    loc, dim = PointLocator(geometry, frame).locate_with_dim(frame.hpoint(point))
    return LOCATION_CHARS[loc], dim


def locate(point: Any, geometry: Geometry) -> str:
    """Location of an exact point relative to a geometry: ``"I"``, ``"B"`` or ``"E"``.

    ``point``: a pair of exact numbers (ints, Fractions, ``mpq``, finite floats), a
    homogeneous triple of ints ``(X, Y, W)``, or a non-empty Point geometry, in the
    geometry's own (real) coordinates. ``geometry``: any geometry, including
    GeometryCollections. See the module docstring for the rules.
    """
    return locate_with_dim(point, geometry)[0]
