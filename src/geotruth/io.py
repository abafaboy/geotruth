"""Readers and writers: typed JSON, WKT, the rational side-car, canonical order.

Nothing here goes through a library under test (DESIGN §2.1): the WKT reader and writer
are hand-written, and numbers are parsed with ``float()`` semantics.

Typed JSON (adapter input, case v2)
    GeoJSON-style ``{"type": "Polygon", "coordinates": [...]}`` objects, plus
    ``{"type": "GeometryCollection", "geometries": [...]}``. Empty geometries have
    empty coordinate arrays (``{"type": "Point", "coordinates": []}``). Coordinates are
    JSON numbers; extra ordinates (Z, M) are ignored. :func:`geometry_from_json` also
    accepts the legacy FORMAT-v1 case geometry: a bare MultiPolygon coordinate list,
    which becomes a Polygon when it has exactly one part.

Rational side-car (expected answers)
    The same typed JSON with every ordinate an exact rational string, ``"n"`` or
    ``"n/d"`` in lowest terms (:func:`geotruth.numbers.format_rational`). Use
    ``geometry_to_json(g, exact=True)`` / ``geometry_from_json(obj, exact=True)``.
    Combine with :func:`canonicalize` for byte-identical output.

Doubles
    :func:`format_double` is the shortest string that round-trips (``repr``), with
    ``NaN``/``Inf`` spelled for WKT. Exact rationals are rounded to the nearest double
    (ties to even) when written as doubles; such output is *display-only*.

WKT
    :func:`read_wkt` accepts the OGC types, ``EMPTY`` (also for single parts inside
    multi-geometries), Z/M/ZM (separate or suffixed: ``POINT Z``, ``POINTZ``), an
    optional EWKT ``SRID=...;`` prefix, ``LINEARRING`` (read as a LineString),
    ``MULTIPOINT`` with or without parentheses around points, and ``NaN``/``Inf``
    ordinates. :func:`to_wkt` writes GEOS-style WKT with shortest round-trip numbers.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from geotruth.geom import (
    Coord,
    Geometry,
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from geotruth.numbers import (
    as_double,
    format_rational,
    json_loads,
    parse_rational,
    rational_to_float,
)

__all__ = [
    "Case",
    "GeometryFormatError",
    "WKTError",
    "canonical_line",
    "canonical_ring",
    "canonicalize",
    "case_from_json",
    "case_sha256",
    "case_to_json",
    "dumps_canonical",
    "format_double",
    "geometry_from_json",
    "geometry_to_json",
    "read_cases",
    "read_wkt",
    "to_wkt",
    "write_jsonl",
]


class GeometryFormatError(ValueError):
    """Malformed typed-JSON geometry."""


class WKTError(ValueError):
    """Malformed WKT; the message gives the character offset."""


# ============================================================================ doubles


def format_double(x: float, *, trim: bool = False) -> str:
    """Shortest decimal string that reads back as exactly ``x`` (Python ``repr``).

    ``trim=True`` drops a trailing ``.0`` (``"2"`` instead of ``"2.0"``; ``-0.0`` stays
    signed as ``"-0"``). Non-finite values are written ``NaN``, ``Inf`` and ``-Inf``.
    """
    if x != x:
        return "NaN"
    if x in (float("inf"), float("-inf")):
        return "Inf" if x > 0 else "-Inf"
    s = repr(x)
    if trim and s.endswith(".0"):
        s = s[:-2]
    return s


def _to_double(v: Any) -> float:
    """A coordinate value as a double: floats unchanged, ints and exact rationals
    correctly rounded."""
    if isinstance(v, float):
        return v
    if isinstance(v, int) and not isinstance(v, bool):
        return as_double(v)
    if hasattr(v, "numerator") and hasattr(v, "denominator"):
        return rational_to_float(v)
    raise TypeError(f"not a coordinate value: {v!r}")


def _to_exact(v: Any) -> Fraction:
    """A coordinate value as an exact Fraction (floats converted exactly)."""
    if isinstance(v, Fraction):
        return v
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError(f"non-finite coordinate {v!r} has no exact value")
        return Fraction(v)
    if isinstance(v, int) and not isinstance(v, bool):
        return Fraction(v)
    if hasattr(v, "numerator") and hasattr(v, "denominator"):
        return Fraction(int(v.numerator), int(v.denominator))
    raise TypeError(f"not a coordinate value: {v!r}")


# ======================================================================= typed JSON


def _json_number(v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise GeometryFormatError(f"coordinate must be a JSON number, got {v!r}")
    return as_double(v)


def _json_rational(v: Any) -> Any:
    if not isinstance(v, str):
        raise GeometryFormatError(f"exact coordinate must be an 'n/d' string, got {v!r}")
    try:
        return parse_rational(v)
    except ValueError as e:
        raise GeometryFormatError(str(e)) from None


def _read_coord(c: Any, num: Callable[[Any], Any]) -> Coord:
    if not isinstance(c, list) or len(c) < 2:
        raise GeometryFormatError(f"a position needs at least 2 numbers: {c!r}")
    return (num(c[0]), num(c[1]))


def _read_coords(seq: Any, num: Callable[[Any], Any]) -> tuple[Coord, ...]:
    if not isinstance(seq, list):
        raise GeometryFormatError(f"expected a list of positions: {seq!r}")
    return tuple(_read_coord(c, num) for c in seq)


def _read_rings(rings: Any, num: Callable[[Any], Any]) -> tuple[tuple[Coord, ...], ...]:
    if not isinstance(rings, list):
        raise GeometryFormatError(f"expected a list of rings: {rings!r}")
    return tuple(_read_coords(r, num) for r in rings)


def _point_from(c: Any, num: Callable[[Any], Any]) -> Point:
    if isinstance(c, list) and not c:
        return Point()
    return Point(_read_coord(c, num))


def geometry_from_json(obj: Any, *, exact: bool = False) -> Geometry:
    """Build a geometry from typed JSON (or a legacy MultiPolygon coordinate list).

    With ``exact=False`` ordinates must be JSON numbers and become doubles with
    ``float()`` semantics; with ``exact=True`` they must be ``"n/d"`` strings and become
    rationals of the active backend (the rational side-car).
    """
    num = _json_rational if exact else _json_number
    if isinstance(obj, list):  # legacy FORMAT-v1: MultiPolygon coordinates
        polys = tuple(Polygon(_read_rings(p, num)) for p in obj)
        return polys[0] if len(polys) == 1 else MultiPolygon(polys)
    if not isinstance(obj, dict) or "type" not in obj:
        raise GeometryFormatError(f"not a typed geometry: {obj!r:.200}")
    t = obj["type"]
    if t == "GeometryCollection":
        geoms = obj.get("geometries")
        if not isinstance(geoms, list):
            raise GeometryFormatError("GeometryCollection needs a 'geometries' list")
        return GeometryCollection(tuple(geometry_from_json(g, exact=exact) for g in geoms))
    if "coordinates" not in obj:
        raise GeometryFormatError(f"{t} needs 'coordinates'")
    c = obj["coordinates"]
    if t == "Point":
        return _point_from(c, num)
    if not isinstance(c, list):
        raise GeometryFormatError(f"{t} coordinates must be a list")
    if t == "LineString":
        return LineString(_read_coords(c, num))
    if t == "Polygon":
        return Polygon(_read_rings(c, num))
    if t == "MultiPoint":
        return MultiPoint(tuple(_point_from(p, num) for p in c))
    if t == "MultiLineString":
        return MultiLineString(tuple(LineString(_read_coords(x, num)) for x in c))
    if t == "MultiPolygon":
        return MultiPolygon(tuple(Polygon(_read_rings(x, num)) for x in c))
    raise GeometryFormatError(f"unknown geometry type {t!r}")


def geometry_to_json(geom: Geometry, *, exact: bool = False) -> dict[str, Any]:
    """Typed JSON of a geometry.

    ``exact=False``: ordinates as doubles (rationals correctly rounded, display-only);
    ``json.dumps`` then writes the shortest round-trip form. ``exact=True``: ordinates as
    canonical ``"n/d"`` strings (doubles converted exactly), the rational side-car.
    """
    num: Callable[[Any], Any] = format_rational if exact else _to_double

    def pos(c: Coord) -> list[Any]:
        return [num(c[0]), num(c[1])]

    if isinstance(geom, Point):
        return {"type": "Point", "coordinates": [] if geom.coord is None else pos(geom.coord)}
    if isinstance(geom, LineString):
        return {"type": "LineString", "coordinates": [pos(c) for c in geom.coords]}
    if isinstance(geom, Polygon):
        return {"type": "Polygon", "coordinates": [[pos(c) for c in r] for r in geom.rings]}
    if isinstance(geom, MultiPoint):
        return {
            "type": "MultiPoint",
            "coordinates": [[] if p.coord is None else pos(p.coord) for p in geom.points],
        }
    if isinstance(geom, MultiLineString):
        return {
            "type": "MultiLineString",
            "coordinates": [[pos(c) for c in ln.coords] for ln in geom.lines],
        }
    if isinstance(geom, MultiPolygon):
        return {
            "type": "MultiPolygon",
            "coordinates": [[[pos(c) for c in r] for r in p.rings] for p in geom.polygons],
        }
    if isinstance(geom, GeometryCollection):
        return {
            "type": "GeometryCollection",
            "geometries": [geometry_to_json(g, exact=exact) for g in geom.geometries],
        }
    raise TypeError(f"not a geometry: {geom!r}")


# ============================================================================= cases

_CASE_KEYS = ("id", "family", "tags", "provenance", "ops", "a", "b")


@dataclass
class Case:
    """One corpus case (schema ``case.v2``): two operands and their metadata.

    ``legacy`` records that the operands were read from FORMAT-v1 MultiPolygon
    coordinate lists; :func:`case_to_json` always writes v2 typed geometries. Unknown
    top-level keys are preserved in ``extra``.
    """

    id: str
    a: Geometry
    b: Geometry
    family: str = ""
    tags: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    ops: tuple[str, ...] | None = None
    legacy: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


def case_from_json(obj: dict[str, Any]) -> Case:
    """A :class:`Case` from a decoded case record (v2 typed or legacy v1)."""
    if not isinstance(obj, dict):
        raise GeometryFormatError("a case must be a JSON object")
    for key in ("id", "a", "b"):
        if key not in obj:
            raise GeometryFormatError(f"case is missing {key!r}")
    ops = obj.get("ops")
    return Case(
        id=str(obj["id"]),
        a=geometry_from_json(obj["a"]),
        b=geometry_from_json(obj["b"]),
        family=obj.get("family", ""),
        tags=dict(obj.get("tags") or {}),
        provenance=dict(obj.get("provenance") or {}),
        ops=None if ops is None else tuple(ops),
        legacy=isinstance(obj["a"], list) or isinstance(obj["b"], list),
        extra={k: v for k, v in obj.items() if k not in _CASE_KEYS},
    )


def case_to_json(case: Case) -> dict[str, Any]:
    """The v2 JSON record of a case (typed geometries with double ordinates)."""
    out: dict[str, Any] = {"id": case.id, "family": case.family}
    out["tags"] = case.tags
    out["provenance"] = case.provenance
    if case.ops is not None:
        out["ops"] = list(case.ops)
    out["a"] = geometry_to_json(case.a)
    out["b"] = geometry_to_json(case.b)
    out.update(case.extra)
    return out


def read_cases(path: str | Path) -> Iterator[Case]:
    """Cases from a JSON-lines file (blank lines skipped)."""
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                yield case_from_json(json_loads(line))


def write_jsonl(records: Iterable[dict[str, Any]], path: str | Path) -> None:
    """Write records as JSON lines (compact separators, insertion key order)."""
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec, separators=(",", ":")) + "\n")


def dumps_canonical(obj: Any) -> str:
    """Deterministic JSON text: sorted keys, compact separators, ASCII only.

    Doubles are written in shortest round-trip form, so equal values give equal text.
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def case_sha256(case: Case) -> str:
    """SHA-256 of the canonical v2 JSON of a case (the expected-answer cache key).

    Two records that differ only in how a number was spelled (``1`` vs ``1.0``, or
    ``2^53 + 1`` vs ``2^53``) describe the same case and hash equally.
    """
    return hashlib.sha256(dumps_canonical(case_to_json(case)).encode("ascii")).hexdigest()


# ================================================================== canonical order


def _key(c: Coord) -> tuple[Fraction, Fraction]:
    return _to_exact(c[0]), _to_exact(c[1])


def _min_rotation(keys: list[tuple[Fraction, Fraction]]) -> int:
    """Start index of the lexicographically smallest rotation of a cyclic sequence."""
    lo = min(keys)
    starts = [i for i, k in enumerate(keys) if k == lo]
    if len(starts) == 1:
        return starts[0]
    return min(starts, key=lambda s: keys[s:] + keys[:s])


def _area2(keys: list[tuple[Fraction, Fraction]]) -> Fraction:
    total = Fraction(0)
    for i in range(len(keys)):
        (x0, y0), (x1, y1) = keys[i - 1], keys[i]
        total += x0 * y1 - x1 * y0
    return total


def canonical_ring(ring: Iterable[Coord], *, ccw: bool = True) -> tuple[Coord, ...]:
    """A closed ring in canonical form: oriented counter-clockwise (``ccw=True``, for
    shells) or clockwise (holes), starting -- and ending -- at its lexicographically
    smallest vertex (x first, then y; ties broken by the smallest rotation).

    Comparisons are exact; coordinate objects are kept (floats stay floats). A ring of
    zero signed area keeps the direction whose vertex sequence is smaller.
    """
    pts = list(ring)
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    if not pts:
        return ()
    keys = [_key(c) for c in pts]
    area = _area2(keys)
    if area != 0:
        if (area > 0) != ccw:
            pts.reverse()
            keys.reverse()
        s = _min_rotation(keys)
    else:
        rk = keys[::-1]
        s1, s2 = _min_rotation(keys), _min_rotation(rk)
        if rk[s2:] + rk[:s2] < keys[s1:] + keys[:s1]:
            pts.reverse()
            keys = rk
            s = s2
        else:
            s = s1
    out = pts[s:] + pts[:s]
    return (*out, out[0])


def canonical_line(coords: Iterable[Coord]) -> tuple[Coord, ...]:
    """A line in canonical direction: an open line starts at its lexicographically
    smaller endpoint; a closed line is rotated and oriented like a ring
    (counter-clockwise). The point set is unchanged."""
    pts = tuple(coords)
    if len(pts) < 2:
        return pts
    if pts[0] == pts[-1]:
        if len(pts) <= 2:
            return pts
        return canonical_ring(pts, ccw=True)
    if _key(pts[-1]) < _key(pts[0]):
        return pts[::-1]
    return pts


_TYPE_RANK = {
    "Polygon": 0,
    "MultiPolygon": 1,
    "LineString": 2,
    "MultiLineString": 3,
    "Point": 4,
    "MultiPoint": 5,
    "GeometryCollection": 6,
}


def _sort_key(g: Geometry) -> tuple:
    """Exact sort key of a canonical geometry (used to order parts)."""
    if isinstance(g, Point):
        return () if g.coord is None else (_key(g.coord),)
    if isinstance(g, LineString):
        return tuple(_key(c) for c in g.coords)
    if isinstance(g, Polygon):
        return tuple(tuple(_key(c) for c in r) for r in g.rings)
    if isinstance(g, GeometryCollection):
        return tuple((_TYPE_RANK[e.geom_type], _sort_key(e)) for e in g.geometries)
    return tuple(_sort_key(p) for p in g.children())


def _canonical_polygon(p: Polygon) -> Polygon:
    if p.is_empty:
        return Polygon()
    shell = canonical_ring(p.rings[0], ccw=True)
    holes = sorted(
        (canonical_ring(h, ccw=False) for h in p.rings[1:]), key=lambda r: tuple(_key(c) for c in r)
    )
    return Polygon((shell, *holes))


def canonicalize(geom: Geometry) -> Geometry:
    """The canonical form of a geometry, for deterministic output and comparison.

    - Polygon: shell counter-clockwise, holes clockwise, each ring starting at its
      lexicographically smallest vertex; holes sorted.
    - LineString: see :func:`canonical_line`.
    - Multi-geometries: parts canonicalised, then sorted (exactly, lexicographically);
      empty parts are dropped.
    - GeometryCollection: elements canonicalised, empty ones dropped, then sorted by
      type (polygonal, linear, puntal) and content.

    The point set never changes. Rings must be closed.
    """
    if isinstance(geom, Point):
        return geom
    if isinstance(geom, LineString):
        return LineString(canonical_line(geom.coords))
    if isinstance(geom, Polygon):
        return _canonical_polygon(geom)
    if isinstance(geom, MultiPoint):
        pts = [p for p in geom.points if not p.is_empty]
        return MultiPoint(tuple(sorted(pts, key=_sort_key)))
    if isinstance(geom, MultiLineString):
        lines = [canonicalize(x) for x in geom.lines if not x.is_empty]
        return MultiLineString(tuple(sorted(lines, key=_sort_key)))
    if isinstance(geom, MultiPolygon):
        polys = [_canonical_polygon(x) for x in geom.polygons if not x.is_empty]
        return MultiPolygon(tuple(sorted(polys, key=_sort_key)))
    if isinstance(geom, GeometryCollection):
        elems = [canonicalize(g) for g in geom.geometries if not g.is_empty]
        elems.sort(key=lambda e: (_TYPE_RANK[e.geom_type], _sort_key(e)))
        return GeometryCollection(tuple(elems))
    raise TypeError(f"not a geometry: {geom!r}")


# =============================================================================== WKT

_WKT_TOKEN = re.compile(
    r"""\s*(?:
        (?P<num>[-+]?(?:(?:[0-9]+\.?[0-9]*|\.[0-9]+)(?:[eE][-+]?[0-9]+)?
                      |(?i:infinity|inf|nan)(?![A-Za-z])))
      | (?P<word>[A-Za-z_]+)
      | (?P<sym>[(),;=])
    )""",
    re.VERBOSE,
)

_WKT_TYPES = {
    "POINT": "Point",
    "LINESTRING": "LineString",
    "LINEARRING": "LineString",
    "POLYGON": "Polygon",
    "MULTIPOINT": "MultiPoint",
    "MULTILINESTRING": "MultiLineString",
    "MULTIPOLYGON": "MultiPolygon",
    "GEOMETRYCOLLECTION": "GeometryCollection",
}


class _WKTReader:
    def __init__(self, text: str) -> None:
        self.text = text
        self.toks: list[tuple[str, str, int]] = []
        pos, n = 0, len(text)
        while True:
            while pos < n and text[pos].isspace():
                pos += 1
            if pos >= n:
                break
            m = _WKT_TOKEN.match(text, pos)
            if not m or m.end() == pos:
                raise WKTError(f"unexpected character {text[pos]!r} at offset {pos}")
            kind = m.lastgroup
            assert kind is not None
            self.toks.append((kind, m.group(kind), m.start(kind)))
            pos = m.end()
        self.i = 0

    # -- token helpers -----------------------------------------------------------------

    def _peek(self) -> tuple[str, str, int] | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def _fail(self, what: str) -> WKTError:
        tok = self._peek()
        where = f"offset {tok[2]} ({tok[1]!r})" if tok else "end of input"
        return WKTError(f"expected {what} at {where}")

    def _next(self) -> tuple[str, str, int]:
        tok = self._peek()
        if tok is None:
            raise self._fail("more input")
        self.i += 1
        return tok

    def _sym(self, s: str) -> None:
        tok = self._peek()
        if tok is None or tok[0] != "sym" or tok[1] != s:
            raise self._fail(f"{s!r}")
        self.i += 1

    def _is_sym(self, s: str) -> bool:
        tok = self._peek()
        return tok is not None and tok[0] == "sym" and tok[1] == s

    def _is_word(self, w: str) -> bool:
        tok = self._peek()
        return tok is not None and tok[0] == "word" and tok[1].upper() == w

    # -- grammar -----------------------------------------------------------------------

    def parse(self) -> Geometry:
        if self._is_word("SRID"):
            self.i += 1
            self._sym("=")
            if self._next()[0] != "num":
                raise WKTError("expected an SRID number")
            self._sym(";")
        geom = self._geometry()
        if self._peek() is not None:
            raise self._fail("end of input")
        return geom

    def _geometry(self) -> Geometry:
        tok = self._next()
        if tok[0] != "word":
            self.i -= 1
            raise self._fail("a geometry type")
        word = tok[1].upper()
        base = word
        if base not in _WKT_TYPES:
            for suffix in ("ZM", "Z", "M"):
                if word.endswith(suffix) and word[: -len(suffix)] in _WKT_TYPES:
                    base = word[: -len(suffix)]
                    break
            else:
                self.i -= 1
                raise self._fail("a geometry type")
        if base == word and any(self._is_word(f) for f in ("Z", "M", "ZM")):
            self.i += 1
        gtype = _WKT_TYPES[base]
        if self._is_word("EMPTY"):
            self.i += 1
            return _EMPTY[gtype]()
        return getattr(self, "_" + gtype)()

    def _number(self) -> float:
        tok = self._next()
        if tok[0] != "num":
            self.i -= 1
            raise self._fail("a number")
        return as_double(tok[1])

    def _coord(self) -> Coord:
        x = self._number()
        y = self._number()
        extra = 0
        while self._peek() is not None and self._peek()[0] == "num":  # type: ignore[index]
            self._number()
            extra += 1
        if extra > 2:
            raise WKTError("a coordinate has at most 4 ordinates")
        return (x, y)

    def _coord_list(self) -> tuple[Coord, ...]:
        if self._is_word("EMPTY"):
            self.i += 1
            return ()
        self._sym("(")
        out = [self._coord()]
        while self._is_sym(","):
            self.i += 1
            out.append(self._coord())
        self._sym(")")
        return tuple(out)

    def _list(self, item: Callable[[], Any]) -> list[Any]:
        self._sym("(")
        out = [item()]
        while self._is_sym(","):
            self.i += 1
            out.append(item())
        self._sym(")")
        return out

    def _Point(self) -> Point:
        self._sym("(")
        c = self._coord()
        self._sym(")")
        return Point(c)

    def _LineString(self) -> LineString:
        return LineString(self._coord_list())

    def _Polygon(self) -> Polygon:
        return Polygon(tuple(self._list(self._coord_list)))

    def _MultiPoint(self) -> MultiPoint:
        def item() -> Point:
            if self._is_word("EMPTY"):
                self.i += 1
                return Point()
            if self._is_sym("("):
                return self._Point()
            return Point(self._coord())

        return MultiPoint(tuple(self._list(item)))

    def _MultiLineString(self) -> MultiLineString:
        return MultiLineString(tuple(LineString(c) for c in self._list(self._coord_list)))

    def _MultiPolygon(self) -> MultiPolygon:
        def item() -> Polygon:
            if self._is_word("EMPTY"):
                self.i += 1
                return Polygon()
            return self._Polygon()

        return MultiPolygon(tuple(self._list(item)))

    def _GeometryCollection(self) -> GeometryCollection:
        return GeometryCollection(tuple(self._list(self._geometry)))


_EMPTY: dict[str, type[Geometry]] = {
    "Point": Point,
    "LineString": LineString,
    "Polygon": Polygon,
    "MultiPoint": MultiPoint,
    "MultiLineString": MultiLineString,
    "MultiPolygon": MultiPolygon,
    "GeometryCollection": GeometryCollection,
}


def read_wkt(text: str) -> Geometry:
    """Parse WKT (or EWKT) into a geometry; ordinates get ``float()`` semantics.

    Raises :class:`WKTError` on malformed input.
    """
    return _WKTReader(text).parse()


def _wkt_num(v: Any, trim: bool) -> str:
    return format_double(_to_double(v), trim=trim)


def to_wkt(geom: Geometry, *, trim: bool = True) -> str:
    """WKT with every ordinate in shortest round-trip form (GEOS style, 2D).

    Exact rationals are rounded to the nearest double: such WKT is display-only.
    ``trim`` drops ``.0`` from integral values (``POINT (1 2)``).
    """

    def c(p: Coord) -> str:
        return f"{_wkt_num(p[0], trim)} {_wkt_num(p[1], trim)}"

    def seq(cs: tuple[Coord, ...]) -> str:
        return "EMPTY" if not cs else "(" + ", ".join(c(p) for p in cs) + ")"

    def poly(p: Polygon) -> str:
        return "EMPTY" if not p.rings else "(" + ", ".join(seq(r) for r in p.rings) + ")"

    def mpoint(p: Point) -> str:
        return "EMPTY" if p.coord is None else f"({c(p.coord)})"

    if isinstance(geom, Point):
        return "POINT EMPTY" if geom.coord is None else f"POINT ({c(geom.coord)})"
    if isinstance(geom, LineString):
        return "LINESTRING " + seq(geom.coords)
    if isinstance(geom, Polygon):
        return "POLYGON " + poly(geom)
    if isinstance(geom, MultiPoint):
        if not geom.points:
            return "MULTIPOINT EMPTY"
        return "MULTIPOINT (" + ", ".join(mpoint(p) for p in geom.points) + ")"
    if isinstance(geom, MultiLineString):
        if not geom.lines:
            return "MULTILINESTRING EMPTY"
        return "MULTILINESTRING (" + ", ".join(seq(x.coords) for x in geom.lines) + ")"
    if isinstance(geom, MultiPolygon):
        if not geom.polygons:
            return "MULTIPOLYGON EMPTY"
        return "MULTIPOLYGON (" + ", ".join(poly(x) for x in geom.polygons) + ")"
    if isinstance(geom, GeometryCollection):
        if not geom.geometries:
            return "GEOMETRYCOLLECTION EMPTY"
        inner = ", ".join(to_wkt(g, trim=trim) for g in geom.geometries)
        return "GEOMETRYCOLLECTION (" + inner + ")"
    raise TypeError(f"not a geometry: {geom!r}")
