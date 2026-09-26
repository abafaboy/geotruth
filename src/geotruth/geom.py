"""Typed geometry model: the OGC Simple Features types (DESIGN §1).

Geometries are immutable dataclasses. Coordinates are ``(x, y)`` tuples; Z and M are
dropped by the readers. Input geometries hold doubles (``float``, possibly non-finite,
which validity reports as "Invalid Coordinate"); engine outputs hold exact rationals
(``Fraction``/``mpq``). Nothing here does arithmetic, so both work.

Structure
---------
- :class:`Point` (``coord`` is ``None`` when empty), :class:`LineString` (``coords``),
  :class:`Polygon` (``rings``: ``rings[0]`` is the shell, the rest are holes; rings are
  closed coordinate sequences, but nothing is enforced -- validity reports unclosed
  rings),
- :class:`MultiPoint` (``points``), :class:`MultiLineString` (``lines``),
  :class:`MultiPolygon` (``polygons``),
- :class:`GeometryCollection` (``geometries``; may nest).

Constructors accept lists and plain coordinate sequences and normalise them to tuples::

    Polygon([[(0, 0), (1, 0), (1, 1), (0, 0)]])
    MultiPoint([(0, 0), (1, 1)])            # coordinates are wrapped into Points

Elements
--------
The *atomic elements* of a geometry are its Points, LineStrings and Polygons in
depth-first order (the order of JTS's ``GeometryCollectionIterator``), **including empty
ones**, so an element index always refers to the same part of the input.
:class:`SourceTag` names a ring or line of an element of operand A or B; the arrangement
carries these tags on every edge. The ``iter_*`` methods enumerate rings, lines, points
and segments with their tags.

Dimensions
----------
- :attr:`Geometry.dimension` is the *type* dimension, as JTS ``getDimension()``: 0 for
  (Multi)Point, 1 for (Multi)LineString, 2 for (Multi)Polygon even when empty; for a
  collection, the maximum over its children (-1 when it has none). The typed-empty rule
  of overlay (``OverlayUtil.resultDimension``) uses this dimension.
- :attr:`Geometry.real_dimension` is RelateNG's ``getDimensionReal()``: empty elements
  are ignored, an empty geometry is -1, and a linear geometry whose lines all have
  coincident points (zero length) is 0. Relate and the named-predicate dispatch use it.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, NamedTuple, TypeAlias

__all__ = [
    "DIM_A",
    "DIM_FALSE",
    "DIM_L",
    "DIM_P",
    "GEOM_A",
    "GEOM_B",
    "LINE",
    "TYPES",
    "Coord",
    "Element",
    "Geometry",
    "GeometryCollection",
    "LineString",
    "MultiLineString",
    "MultiPoint",
    "MultiPolygon",
    "Point",
    "Polygon",
    "RingRef",
    "Segment",
    "SourceTag",
    "build_geometry",
    "empty_of_dimension",
    "flatten",
    "partition_by_dimension",
    "same_xy",
]

Coord: TypeAlias = tuple[Any, Any]

#: Operand ids used in :class:`SourceTag`.
GEOM_A, GEOM_B = 0, 1

#: The ``ring`` value of a :class:`SourceTag` that names a line element.
LINE = -1

#: Dimension constants, as JTS ``Dimension`` (FALSE = empty).
DIM_FALSE, DIM_P, DIM_L, DIM_A = -1, 0, 1, 2


class SourceTag(NamedTuple):
    """Which input ring or line a segment (or arrangement edge) comes from.

    ``geom`` is :data:`GEOM_A` (0) or :data:`GEOM_B` (1); ``element`` is the atomic
    element index (see :meth:`Geometry.elements`); ``ring`` is 0 for a polygon shell,
    ``k >= 1`` for its k-th hole, and :data:`LINE` (-1) for a line element; ``is_hole``
    is ``ring >= 1`` (kept explicit for readability of tag sets).
    """

    geom: int
    element: int
    ring: int
    is_hole: bool

    @property
    def is_line(self) -> bool:
        return self.ring == LINE

    @property
    def is_ring(self) -> bool:
        return self.ring >= 0

    def __str__(self) -> str:
        g = "AB"[self.geom] if self.geom in (0, 1) else str(self.geom)
        if self.is_line:
            return f"{g}.e{self.element}.line"
        role = "hole" if self.is_hole else "shell"
        return f"{g}.e{self.element}.r{self.ring}({role})"

    @classmethod
    def for_ring(cls, geom: int, element: int, ring: int) -> SourceTag:
        """Tag of ring ``ring`` (0 = shell) of polygon element ``element``."""
        return cls(geom, element, ring, ring >= 1)

    @classmethod
    def for_line(cls, geom: int, element: int) -> SourceTag:
        """Tag of line element ``element``."""
        return cls(geom, element, LINE, False)


class Segment(NamedTuple):
    """A non-degenerate input segment ``p -> q`` in ring/line traversal order.

    ``index`` is the position of ``p`` in its ring or line coordinate sequence.
    """

    p: Coord
    q: Coord
    tag: SourceTag
    index: int


class RingRef(NamedTuple):
    """A polygon ring with its role (``tag.ring``, ``tag.is_hole``)."""

    tag: SourceTag
    coords: tuple[Coord, ...]


class Element(NamedTuple):
    """An atomic element with its index."""

    index: int
    geometry: Point | LineString | Polygon


def _coord(c: Sequence) -> Coord:
    if len(c) < 2:
        raise ValueError(f"a coordinate needs at least x and y: {c!r}")
    return (c[0], c[1])


def _coords(seq: Iterable[Sequence]) -> tuple[Coord, ...]:
    return tuple(_coord(c) for c in seq)


def same_xy(p: Coord, q: Coord) -> bool:
    """JTS ``equals2D``: ordinate-wise ``==`` (``-0.0 == 0.0``; NaN never equal).

    Plain tuple equality is not the same thing: it short-circuits on object identity,
    so ``(nan, 0.0) == (nan, 0.0)`` can be True for the same NaN object.
    """
    return p[0] == q[0] and p[1] == q[1]


class Geometry:
    """Base class of all geometry types (never instantiated directly)."""

    __slots__ = ()

    #: OGC type name, as in WKT and GeoJSON ("Point", "MultiPolygon", ...).
    geom_type: ClassVar[str] = "Geometry"

    # -- structure -----------------------------------------------------------------

    @property
    def is_empty(self) -> bool:
        raise NotImplementedError

    def children(self) -> tuple[Geometry, ...]:
        """Direct parts of a multi-geometry or collection (``()`` for atomic types)."""
        return ()

    def elements(self) -> Iterator[Point | LineString | Polygon]:
        """Atomic elements in depth-first order, including empty ones."""
        for child in self.children():
            yield from child.elements()

    def iter_elements(self, *, skip_empty: bool = False) -> Iterator[Element]:
        """``(index, element)`` pairs; indices count empty elements too."""
        for i, e in enumerate(self.elements()):
            if not (skip_empty and e.is_empty):
                yield Element(i, e)

    # -- dimension -----------------------------------------------------------------

    @property
    def dimension(self) -> int:
        """Type dimension, as JTS ``getDimension()`` (see module docstring)."""
        raise NotImplementedError

    @property
    def has_points(self) -> bool:
        """True if some non-empty Point element exists."""
        return any(isinstance(e, Point) and not e.is_empty for e in self.elements())

    @property
    def has_lines(self) -> bool:
        """True if some non-empty LineString element exists."""
        return any(isinstance(e, LineString) and not e.is_empty for e in self.elements())

    @property
    def has_areas(self) -> bool:
        """True if some non-empty Polygon element exists."""
        return any(isinstance(e, Polygon) and not e.is_empty for e in self.elements())

    @property
    def real_dimension(self) -> int:
        """RelateNG ``RelateGeometry.getDimensionReal()``.

        -1 if empty; 0 if the geometry is linear (type dimension 1) and every line
        element has coincident points; otherwise the highest dimension among non-empty
        elements. Mirrors JTS exactly, including the quirk that a collection whose type
        dimension is 2 only because of an *empty* polygon keeps real dimension 1 for
        zero-length lines.
        """
        if self.is_empty:
            return DIM_FALSE
        if self.dimension == DIM_L and all(
            e.is_zero_length for e in self.elements() if isinstance(e, LineString)
        ):
            return DIM_P
        if self.has_areas:
            return DIM_A
        if self.has_lines:
            return DIM_L
        return DIM_P

    @property
    def is_zero_length_linear(self) -> bool:
        """True for a linear geometry whose real dimension is 0 (tagged in the corpus)."""
        return not self.is_empty and self.dimension == DIM_L and self.real_dimension == DIM_P

    # -- coordinates -----------------------------------------------------------------

    def iter_coords(self) -> Iterator[Coord]:
        """Every coordinate, in element order (ring closing points included)."""
        for e in self.elements():
            yield from e.iter_coords()

    def iter_values(self) -> Iterator[Any]:
        """Every ordinate value ``x0, y0, x1, y1, ...`` (for scaling and finiteness)."""
        for x, y in self.iter_coords():
            yield x
            yield y

    @property
    def num_coords(self) -> int:
        return sum(1 for _ in self.iter_coords())

    @property
    def has_nonfinite(self) -> bool:
        """True if some ordinate is NaN or infinite (validity: "Invalid Coordinate")."""
        return any(isinstance(v, float) and not math.isfinite(v) for v in self.iter_values())

    def map_coords(self, fn: Callable[[Coord], Coord]) -> Geometry:
        """A geometry of the same structure with every coordinate replaced by ``fn(c)``."""
        raise NotImplementedError

    # -- rings, lines, points and segments with source tags ---------------------------

    def iter_rings(self, geom: int = GEOM_A) -> Iterator[RingRef]:
        """Every polygon ring, with a :class:`SourceTag` giving element and role."""
        for i, e in enumerate(self.elements()):
            if isinstance(e, Polygon):
                for k, ring in enumerate(e.rings):
                    yield RingRef(SourceTag.for_ring(geom, i, k), ring)

    def iter_lines(self, geom: int = GEOM_A) -> Iterator[tuple[SourceTag, tuple[Coord, ...]]]:
        """Every non-empty LineString element as ``(tag, coords)``."""
        for i, e in enumerate(self.elements()):
            if isinstance(e, LineString) and e.coords:
                yield SourceTag.for_line(geom, i), e.coords

    def iter_points(self) -> Iterator[tuple[int, Coord]]:
        """Every non-empty Point element as ``(element index, coord)``."""
        for i, e in enumerate(self.elements()):
            if isinstance(e, Point) and e.coord is not None:
                yield i, e.coord

    def iter_line_endpoints(self) -> Iterator[Coord]:
        """First and last coordinate of every non-empty line element, *before* any
        zero-length segment is dropped: the input of the Mod-2 boundary rule (a closed
        line contributes its start point twice, so it has no boundary)."""
        for _, coords in self.iter_lines():
            yield coords[0]
            yield coords[-1]

    def iter_segments(self, geom: int = GEOM_A) -> Iterator[Segment]:
        """Every non-degenerate segment of every ring and line, in traversal order.

        Zero-length segments (repeated consecutive points) are skipped; ``index`` keeps
        the original position. Unclosed rings are not closed here.
        """
        for ring in self.iter_rings(geom):
            yield from _segments_of(ring.coords, ring.tag)
        for tag, coords in self.iter_lines(geom):
            yield from _segments_of(coords, tag)

    # -- conversions -----------------------------------------------------------------

    @property
    def wkt(self) -> str:
        """WKT with shortest round-trip doubles (see :func:`geotruth.io.to_wkt`)."""
        from geotruth.io import to_wkt

        return to_wkt(self)


def _segments_of(coords: tuple[Coord, ...], tag: SourceTag) -> Iterator[Segment]:
    for k in range(len(coords) - 1):
        p, q = coords[k], coords[k + 1]
        if not same_xy(p, q):
            yield Segment(p, q, tag, k)


# --------------------------------------------------------------------- atomic types


@dataclass(frozen=True, slots=True)
class Point(Geometry):
    """A point; ``coord is None`` for ``POINT EMPTY``."""

    coord: Coord | None = None

    geom_type: ClassVar[str] = "Point"

    def __post_init__(self) -> None:
        if self.coord is not None:
            object.__setattr__(self, "coord", _coord(self.coord))

    @property
    def is_empty(self) -> bool:
        return self.coord is None

    @property
    def dimension(self) -> int:
        return DIM_P

    def elements(self) -> Iterator[Point]:
        yield self

    def iter_coords(self) -> Iterator[Coord]:
        if self.coord is not None:
            yield self.coord

    def map_coords(self, fn: Callable[[Coord], Coord]) -> Point:
        return Point(None if self.coord is None else fn(self.coord))


@dataclass(frozen=True, slots=True)
class LineString(Geometry):
    """A polyline; ``coords == ()`` for ``LINESTRING EMPTY``.

    A single-point line is representable (JTS would refuse to build it); validity
    reports it ("Too few distinct points").
    """

    coords: tuple[Coord, ...] = ()

    geom_type: ClassVar[str] = "LineString"

    def __post_init__(self) -> None:
        object.__setattr__(self, "coords", _coords(self.coords))

    @property
    def is_empty(self) -> bool:
        return not self.coords

    @property
    def dimension(self) -> int:
        return DIM_L

    def elements(self) -> Iterator[LineString]:
        yield self

    def iter_coords(self) -> Iterator[Coord]:
        yield from self.coords

    @property
    def is_closed(self) -> bool:
        """JTS ``isClosed``: non-empty and the first point equals the last."""
        return bool(self.coords) and same_xy(self.coords[0], self.coords[-1])

    @property
    def is_zero_length(self) -> bool:
        """RelateNG ``isZeroLength``: fewer than 2 points, or all points coincide
        (compared as JTS ``equals2D`` does: ``-0.0 == 0.0``, NaN never equal)."""
        c = self.coords
        return len(c) < 2 or all(same_xy(p, c[0]) for p in c)

    def map_coords(self, fn: Callable[[Coord], Coord]) -> LineString:
        return LineString(tuple(fn(c) for c in self.coords))


@dataclass(frozen=True, slots=True)
class Polygon(Geometry):
    """A polygon: ``rings[0]`` is the shell, ``rings[1:]`` the holes; ``()`` if empty."""

    rings: tuple[tuple[Coord, ...], ...] = ()

    geom_type: ClassVar[str] = "Polygon"

    def __post_init__(self) -> None:
        object.__setattr__(self, "rings", tuple(_coords(r) for r in self.rings))

    @property
    def shell(self) -> tuple[Coord, ...]:
        return self.rings[0] if self.rings else ()

    @property
    def holes(self) -> tuple[tuple[Coord, ...], ...]:
        return self.rings[1:]

    @property
    def is_empty(self) -> bool:
        return not self.rings or not self.rings[0]

    @property
    def dimension(self) -> int:
        return DIM_A

    def elements(self) -> Iterator[Polygon]:
        yield self

    def iter_coords(self) -> Iterator[Coord]:
        for r in self.rings:
            yield from r

    def map_coords(self, fn: Callable[[Coord], Coord]) -> Polygon:
        return Polygon(tuple(tuple(fn(c) for c in r) for r in self.rings))


# ---------------------------------------------------------------- collection types


@dataclass(frozen=True, slots=True)
class MultiPoint(Geometry):
    """A collection of points (plain coordinates are wrapped into :class:`Point`)."""

    points: tuple[Point, ...] = ()

    geom_type: ClassVar[str] = "MultiPoint"

    def __post_init__(self) -> None:
        pts = tuple(p if isinstance(p, Point) else Point(p) for p in self.points)
        object.__setattr__(self, "points", pts)

    def children(self) -> tuple[Geometry, ...]:
        return self.points

    @property
    def is_empty(self) -> bool:
        return all(p.is_empty for p in self.points)

    @property
    def dimension(self) -> int:
        return DIM_P

    def map_coords(self, fn: Callable[[Coord], Coord]) -> MultiPoint:
        return MultiPoint(tuple(p.map_coords(fn) for p in self.points))


@dataclass(frozen=True, slots=True)
class MultiLineString(Geometry):
    """A collection of lines (coordinate sequences are wrapped into LineStrings)."""

    lines: tuple[LineString, ...] = ()

    geom_type: ClassVar[str] = "MultiLineString"

    def __post_init__(self) -> None:
        ls = tuple(x if isinstance(x, LineString) else LineString(x) for x in self.lines)
        object.__setattr__(self, "lines", ls)

    def children(self) -> tuple[Geometry, ...]:
        return self.lines

    @property
    def is_empty(self) -> bool:
        return all(x.is_empty for x in self.lines)

    @property
    def dimension(self) -> int:
        return DIM_L

    def map_coords(self, fn: Callable[[Coord], Coord]) -> MultiLineString:
        return MultiLineString(tuple(x.map_coords(fn) for x in self.lines))


@dataclass(frozen=True, slots=True)
class MultiPolygon(Geometry):
    """A collection of polygons (ring lists are wrapped into Polygons)."""

    polygons: tuple[Polygon, ...] = ()

    geom_type: ClassVar[str] = "MultiPolygon"

    def __post_init__(self) -> None:
        ps = tuple(x if isinstance(x, Polygon) else Polygon(x) for x in self.polygons)
        object.__setattr__(self, "polygons", ps)

    def children(self) -> tuple[Geometry, ...]:
        return self.polygons

    @property
    def is_empty(self) -> bool:
        return all(x.is_empty for x in self.polygons)

    @property
    def dimension(self) -> int:
        return DIM_A

    def map_coords(self, fn: Callable[[Coord], Coord]) -> MultiPolygon:
        return MultiPolygon(tuple(x.map_coords(fn) for x in self.polygons))


@dataclass(frozen=True, slots=True)
class GeometryCollection(Geometry):
    """A heterogeneous collection; may contain multi-geometries and collections."""

    geometries: tuple[Geometry, ...] = ()

    geom_type: ClassVar[str] = "GeometryCollection"

    def __post_init__(self) -> None:
        gs = tuple(self.geometries)
        for g in gs:
            if not isinstance(g, Geometry):
                raise TypeError(f"not a geometry: {g!r}")
        object.__setattr__(self, "geometries", gs)

    def children(self) -> tuple[Geometry, ...]:
        return self.geometries

    @property
    def is_empty(self) -> bool:
        return all(g.is_empty for g in self.geometries)

    @property
    def dimension(self) -> int:
        return max((g.dimension for g in self.geometries), default=DIM_FALSE)

    def map_coords(self, fn: Callable[[Coord], Coord]) -> GeometryCollection:
        return GeometryCollection(tuple(g.map_coords(fn) for g in self.geometries))


#: Every concrete geometry class by OGC type name.
TYPES: dict[str, type[Geometry]] = {
    cls.geom_type: cls
    for cls in (
        Point,
        LineString,
        Polygon,
        MultiPoint,
        MultiLineString,
        MultiPolygon,
        GeometryCollection,
    )
}

# ---------------------------------------------------------------- GC flattening helpers


def flatten(geom: Geometry, *, skip_empty: bool = True) -> list[Point | LineString | Polygon]:
    """The atomic elements of any geometry, nested collections flattened."""
    return [e for e in geom.elements() if not (skip_empty and e.is_empty)]


def partition_by_dimension(
    geom: Geometry,
) -> tuple[list[Point], list[LineString], list[Polygon]]:
    """Non-empty atomic elements split into (points, lines, polygons)."""
    pts: list[Point] = []
    lns: list[LineString] = []
    polys: list[Polygon] = []
    for e in geom.elements():
        if e.is_empty:
            continue
        if isinstance(e, Point):
            pts.append(e)
        elif isinstance(e, LineString):
            lns.append(e)
        else:
            polys.append(e)
    return pts, lns, polys


def empty_of_dimension(dim: int) -> Geometry:
    """The typed empty geometry of a dimension (as OverlayNG's ``createEmptyResult``):
    ``POINT EMPTY``, ``LINESTRING EMPTY``, ``POLYGON EMPTY``, or
    ``GEOMETRYCOLLECTION EMPTY`` for -1."""
    if dim == DIM_P:
        return Point()
    if dim == DIM_L:
        return LineString()
    if dim == DIM_A:
        return Polygon()
    if dim == DIM_FALSE:
        return GeometryCollection()
    raise ValueError(f"no geometry type has dimension {dim}")


def build_geometry(elements: Iterable[Geometry]) -> Geometry:
    """The most specific geometry holding ``elements`` (JTS ``buildGeometry``):
    nothing -> ``GEOMETRYCOLLECTION EMPTY``; one element -> itself; all Points ->
    MultiPoint; all LineStrings -> MultiLineString; all Polygons -> MultiPolygon;
    anything else -> GeometryCollection."""
    elems = list(elements)
    if not elems:
        return GeometryCollection()
    if len(elems) == 1:
        return elems[0]
    if all(isinstance(e, Point) for e in elems):
        return MultiPoint(tuple(elems))
    if all(isinstance(e, LineString) for e in elems):
        return MultiLineString(tuple(elems))
    if all(isinstance(e, Polygon) for e in elems):
        return MultiPolygon(tuple(elems))
    return GeometryCollection(tuple(elems))
