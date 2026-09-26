"""Shapely / GEOS adapter: adapter contract v2 (DESIGN.md §4.1) and the legacy v1 contract.

usage: python3 adapters/shapely/shapely_adapter.py [--v2] [--timing] [--no-fork] CASES.jsonl
       python3 adapters/shapely/shapely_adapter.py --version

v2 lines (typed operands or "ops") get relate, the ten named predicates, validity, the
four overlays and the parse-echo canary; legacy FORMAT-v1 lines (multipolygon arrays) get
the unchanged v1 fields (harness/FORMAT-v1.md). Every operation runs in an isolated worker
process with a per-operation timeout (src/geotruth/harness/pyadapter.py).

Geometries go into GEOS as hand-written WKB built from the exact doubles (JSON numbers read
with float() semantics), and results come back as WKB read here: no coordinate ever passes
through a WKT or GeoJSON writer or reader. See README.md.
"""

import struct
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import shapely  # noqa: E402
from shapely.geometry import MultiPolygon, Polygon  # noqa: E402

from geotruth.harness.pyadapter import Library, Session, main  # noqa: E402
from geotruth.numbers import as_double  # noqa: E402

LIB = f"geos@{shapely.geos_version_string}+shapely@{shapely.__version__}"
V1_PREDICATES = ["intersects", "disjoint", "touches", "overlaps", "contains", "covers", "within",
                 "equals"]  # fmt: skip
NAN = float("nan")

# ============================================================================ WKB

_WKB_TYPE = {"Point": 1, "LineString": 2, "Polygon": 3, "MultiPoint": 4, "MultiLineString": 5,
             "MultiPolygon": 6, "GeometryCollection": 7}  # fmt: skip
_TYPE_NAME = {v: k for k, v in _WKB_TYPE.items()}


def _xy(c: list) -> bytes:
    if not isinstance(c, list) or len(c) < 2:
        raise ValueError(f"a position needs at least 2 numbers: {c!r}")
    return struct.pack("<dd", as_double(c[0]), as_double(c[1]))


def _head(t: str) -> bytes:
    return struct.pack("<BI", 1, _WKB_TYPE[t])


def to_wkb(g: Any) -> bytes:
    """Little-endian 2-D WKB of a typed JSON geometry (Z and M dropped)."""
    if not isinstance(g, dict) or "type" not in g:
        raise ValueError(f"not a typed geometry: {g!r:.200}")
    t = g["type"]
    if t == "GeometryCollection":
        parts = g["geometries"]
        return _head(t) + struct.pack("<I", len(parts)) + b"".join(to_wkb(p) for p in parts)
    if t not in _WKB_TYPE:
        raise ValueError(f"unknown geometry type {t!r}")
    c = g["coordinates"]
    if t == "Point":
        return _head(t) + (struct.pack("<dd", NAN, NAN) if not c else _xy(c))
    if t == "LineString":
        return _head(t) + struct.pack("<I", len(c)) + b"".join(_xy(p) for p in c)
    if t == "Polygon":
        return _head(t) + struct.pack("<I", len(c)) + b"".join(
            struct.pack("<I", len(r)) + b"".join(_xy(p) for p in r) for r in c
        )
    kid = {"MultiPoint": "Point", "MultiLineString": "LineString", "MultiPolygon": "Polygon"}[t]
    return _head(t) + struct.pack("<I", len(c)) + b"".join(
        to_wkb({"type": kid, "coordinates": x}) for x in c
    )


class _Reader:
    def __init__(self, b: bytes) -> None:
        self.b, self.i = b, 0

    def take(self, fmt: str) -> tuple:
        v = struct.unpack_from(fmt, self.b, self.i)
        self.i += struct.calcsize(fmt)
        return v

    def geometry(self) -> dict[str, Any]:
        (order,) = self.take("B")
        e = "<" if order == 1 else ">"
        (code,) = self.take(e + "I")
        if code & 0xE0000000:
            raise ValueError("EWKB flags are not expected")
        base, zm = code % 1000, code // 1000
        dims = {0: 2, 1: 3, 2: 3, 3: 4}[zm]
        t = _TYPE_NAME.get(base)
        if t is None:
            raise ValueError(f"unknown WKB type {code}")

        def pt() -> list[float]:
            vals = self.take(e + "d" * dims)
            return [vals[0], vals[1]]

        def seq() -> list[list[float]]:
            (n,) = self.take(e + "I")
            return [pt() for _ in range(n)]

        if t == "Point":
            x, y = pt()
            return {"type": t, "coordinates": [] if x != x and y != y else [x, y]}
        if t == "LineString":
            return {"type": t, "coordinates": seq()}
        if t == "Polygon":
            (n,) = self.take(e + "I")
            return {"type": t, "coordinates": [seq() for _ in range(n)]}
        (n,) = self.take(e + "I")
        kids = [self.geometry() for _ in range(n)]
        if t == "GeometryCollection":
            return {"type": t, "geometries": kids}
        return {"type": t, "coordinates": [k["coordinates"] for k in kids]}


def from_wkb(b: bytes) -> dict[str, Any]:
    """Typed JSON (doubles exactly as GEOS holds them) of a WKB geometry."""
    return _Reader(b).geometry()


def geos_to_json(g: Any) -> dict[str, Any]:
    return from_wkb(shapely.to_wkb(g, byte_order=1, output_dimension=2, include_srid=False))


# ============================================================================ sessions

_OVERLAY = {"intersection": shapely.intersection, "union": shapely.union,
            "difference": shapely.difference, "symdifference": shapely.symmetric_difference}  # fmt: skip
_PRED = {"intersects": shapely.intersects, "disjoint": shapely.disjoint,
         "touches": shapely.touches, "crosses": shapely.crosses, "overlaps": shapely.overlaps,
         "contains": shapely.contains, "covers": shapely.covers, "within": shapely.within,
         "covered_by": shapely.covered_by, "equals": shapely.equals}  # fmt: skip


def _build(g: Any) -> tuple[Any, Exception | None]:
    try:
        return shapely.from_wkb(to_wkb(g)), None
    except Exception as exc:  # GEOS refuses to build it (e.g. an unclosed ring)
        return None, exc


class SessionV2(Session):
    def __init__(self, case: dict[str, Any]) -> None:
        self.a, self.err_a = _build(case["a"])
        self.b, self.err_b = _build(case["b"])

    def _need(self, a: bool, b: bool) -> None:
        if a and self.a is None:
            raise RuntimeError(f"building A: {type(self.err_a).__name__}: {self.err_a}")
        if b and self.b is None:
            raise RuntimeError(f"building B: {type(self.err_b).__name__}: {self.err_b}")

    def run(self, path: str) -> Any:
        if path == "valid_a":
            self._need(True, False)
            return bool(shapely.is_valid(self.a))
        if path == "valid_b":
            self._need(False, True)
            return bool(shapely.is_valid(self.b))
        self._need(True, True)
        if path == "echo":
            return {"a": geos_to_json(self.a), "b": geos_to_json(self.b)}
        if path == "relate":
            return str(shapely.relate(self.a, self.b))
        group, _, name = path.partition(".")
        if group == "predicates":
            return bool(_PRED[name](self.a, self.b))
        if group == "overlay":
            return geos_to_json(_OVERLAY[name](self.a, self.b))
        return None


def _build_v1(mp: list) -> Any:
    polys = [Polygon(p[0], p[1:]) for p in mp]
    return polys[0] if len(polys) == 1 else MultiPolygon(polys)


class SessionV1(Session):
    """The v1 fields, computed exactly as the v1 adapter did."""

    def __init__(self, case: dict[str, Any]) -> None:
        self.a, self.b = _build_v1(case["a"]), _build_v1(case["b"])

    def run(self, path: str) -> Any:
        a, b = self.a, self.b
        if path in ("valid_a", "valid_b"):
            return bool((a if path == "valid_a" else b).is_valid)
        if path in V1_PREDICATES:
            return bool(getattr(a, path)(b))
        if path == "covered_by":
            return bool(a.covered_by(b))
        fn = {"area_inter": a.intersection, "area_union": a.union, "area_diff": a.difference,
              "area_symdiff": a.symmetric_difference}[path]  # fmt: skip
        return float(fn(b).area)


class ShapelyLibrary(Library):
    lib = LIB
    timeout_env = "SHAPELY_ADAPTER_TIMEOUT"
    supports_v1 = True

    def session(self, case: dict[str, Any]) -> Session:
        return SessionV2(case)

    def session_v1(self, case: dict[str, Any]) -> Session:
        return SessionV1(case)


if __name__ == "__main__":
    sys.exit(main(ShapelyLibrary(), prog="shapely_adapter.py"))
