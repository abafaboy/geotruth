"""Case format v2 (schemas/case.v2.schema.json): typed operands, tags and provenance.

Every generator family ends here. A family yields ``(variant, a, b)`` with the operands
either as FORMAT-v1 MultiPolygon coordinate lists (the ten legacy families) or as typed
JSON geometries (the families of ``families_v2.py``). :func:`make_case` turns that into a
v2 record::

    {"id", "family", "tags": {degeneracy, range, n, k, types, variant, flags},
     "provenance": {source, generator, generator_version, seed, n_per_family}, "a", "b"}

Tags are *computed from the geometry*, exactly, so they mean the same thing in every
family:

- ``degeneracy``: ``lattice`` when the two operands (or two different rings/elements of
  one operand) meet in an exact degenerate contact -- a vertex or point exactly on the
  other's segment or vertex, or a collinear overlap of positive length; otherwise ``ulp``
  when some vertex lies within ``ULP_NEAR`` (4096) ulps of the largest coordinate from a
  segment or vertex it does not touch; otherwise ``generic``. Proper crossings of two
  segment interiors are generic. Everything is decided in integer arithmetic after the
  per-case dyadic scaling (``geotruth.numbers.DyadicScale``).
- ``range``: ``extreme`` when some non-zero |coordinate| is below 1e-150 or above 1e150.
- ``n``: the number of coordinates of a and b (ring closing points included).
- ``k``: the number of distinct points where a meets b (crossings, touches, overlap
  endpoints, points on the other operand), or ``null`` when the pair count is over
  ``K_BUDGET``.
- ``types``: the two geometry types.
- ``variant``: the generator's variant label (also the last part of the id).
- ``flags``: free-form kebab-case flags (``convention``, ``empty``, ``zero-length-line``,
  ``invalid-input``, ``gc``, ``mod2``, ...).

Nothing here is a decision about the answer: tags only stratify the corpus.
"""

from __future__ import annotations

import bisect
import itertools
import math
import os
import sys
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
_SRC = os.path.join(ROOT, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from geotruth import exact as X  # noqa: E402
from geotruth.geom import Geometry, LineString, Point  # noqa: E402
from geotruth.io import geometry_from_json  # noqa: E402
from geotruth.numbers import DyadicScale  # noqa: E402

#: Version of the v2 corpus generators (bump when any generated case could change).
GENERATOR_VERSION = "2"
#: "ulp" degeneracy: a vertex within this many ulps (of the largest |coordinate|) of a
#: segment or vertex of the other operand that it does not touch.
ULP_NEAR = 4096
#: Above this many candidate segment pairs, ``k`` is not computed (null).
K_BUDGET = 400_000
EXTREME_LO, EXTREME_HI = 1e-150, 1e150


# ============================================================================ geometry


def legacy_to_typed(mp: list) -> dict[str, Any]:
    """A FORMAT-v1 MultiPolygon coordinate list as typed JSON (one part -> Polygon)."""
    if len(mp) == 1:
        return {"type": "Polygon", "coordinates": mp[0]}
    return {"type": "MultiPolygon", "coordinates": mp}


def as_geometry(obj: Any) -> Geometry:
    """A geometry from typed JSON, a legacy coordinate list, or a Geometry."""
    if isinstance(obj, Geometry):
        return obj
    return geometry_from_json(obj)


def _element_paths(geom: Geometry):
    """(element index, element) for every non-empty atomic element."""
    return [(i, e) for i, e in enumerate(geom.elements()) if not e.is_empty]


class _Parts:
    """Scaled integer segments and vertices of one operand, with owner ids.

    An *owner* is a ring or line (``(element, ring)``); contacts between different owners
    of one operand count as intra-operand degeneracies. Zero-length lines become points.
    """

    def __init__(self, geom: Geometry, scale: DyadicScale) -> None:
        self.segs: list[tuple[tuple[int, int], tuple[int, int], tuple[int, int]]] = []
        self.verts: list[tuple[tuple[int, int], tuple[int, int]]] = []
        for i, e in _element_paths(geom):
            if isinstance(e, Point):
                p = scale.to_point(*e.coord)
                self.verts.append((p, (i, -2)))
                continue
            rings = [e.coords] if isinstance(e, LineString) else list(e.rings)
            for r_i, ring in enumerate(rings):
                owner = (i, r_i if not isinstance(e, LineString) else -1)
                pts = [scale.to_point(x, y) for x, y in ring]
                if isinstance(e, LineString) and len(set(pts)) == 1:
                    self.verts.append((pts[0], (i, -2)))
                    continue
                for p in pts:
                    self.verts.append((p, owner))
                for p, q in itertools.pairwise(pts):
                    if p != q:
                        self.segs.append((p, q, owner))


def _bbox(p, q, pad=0):
    x0, x1 = sorted((p[0], q[0]))
    y0, y1 = sorted((p[1], q[1]))
    return (x0 - pad, y0 - pad, x1 + pad, y1 + pad)


def _pairs(boxes_a, boxes_b):
    """Index pairs (i, j) whose boxes overlap (boxes_b sorted by min x, then scanned)."""
    ev = sorted(range(len(boxes_b)), key=lambda j: boxes_b[j][0])
    xs = [boxes_b[j][0] for j in ev]
    for i, ba in enumerate(boxes_a):
        hi = bisect.bisect_right(xs, ba[2])
        for t in range(hi):
            j = ev[t]
            bb = boxes_b[j]
            if bb[2] >= ba[0] and bb[1] <= ba[3] and bb[3] >= ba[1]:
                yield i, j


def _is_endpoint(h, p, q) -> bool:
    return h[2] == 1 and ((h[0], h[1]) == p or (h[0], h[1]) == q)


def _near_threshold(scale_max: int) -> int:
    """log2 of ULP_NEAR ulps of the largest scaled |coordinate| (may be negative)."""
    return max(scale_max.bit_length(), 1) - 53 + int(math.log2(ULP_NEAR))


def _within(d2: tuple[int, int], t: int) -> bool:
    """Exact test: squared distance num/den <= (2^t)^2."""
    num, den = d2
    return num <= (den << (2 * t)) if t >= 0 else (num << (-2 * t)) <= den


class _Contacts:
    def __init__(self) -> None:
        self.lattice = False
        self.near = False
        self.points: set[tuple[int, int, int]] | None = set()


def _analyse(pa: _Parts, pb: _Parts, t: int, out: _Contacts, *, count: bool, intra: bool) -> None:
    """Contacts between the segments/vertices of pa and pb (pa is pb when intra)."""
    pad = 1 << t if t > 0 else 1
    ba = [_bbox(p, q) for p, q, _ in pa.segs]
    bb = [_bbox(p, q, pad) for p, q, _ in pb.segs]
    n_pairs = 0
    for i, j in _pairs(ba, bb):
        a0, a1, oa = pa.segs[i]
        b0, b1, ob = pb.segs[j]
        if intra and (oa == ob or j <= i):
            continue
        n_pairs += 1
        if count and n_pairs > K_BUDGET:
            out.points = None
            count = False
        r = X.intersect_segments(a0, a1, b0, b1)
        if r.kind == X.OVERLAP:
            out.lattice = True
        elif r.kind == X.POINT:
            h = r.points[0]
            if _is_endpoint(h, a0, a1) or _is_endpoint(h, b0, b1):
                out.lattice = True
        if r and count and out.points is not None:
            out.points.update(r.points)
        if not r and not out.near:
            for v, s0, s1 in ((a0, b0, b1), (a1, b0, b1), (b0, a0, a1), (b1, a0, a1)):
                if _within(X.sqdist_point_segment(v, s0, s1), t):
                    out.near = True
                    break
    # isolated points (point elements, zero-length lines) against segments and points
    for v, ov in pa.verts:
        if ov[1] != -2:
            continue
        for p, q, oq in pb.segs:
            if intra and oq == ov:
                continue
            d2 = X.sqdist_point_segment(v, p, q)
            if d2[0] == 0:
                out.lattice = True
                if count and out.points is not None:
                    out.points.add((v[0], v[1], 1))
            elif _within(d2, t):
                out.near = True
        for w, ow in pb.verts:
            if ow[1] != -2 or (intra and ow == ov):
                continue
            if w == v:
                out.lattice = True
                if count and out.points is not None:
                    out.points.add((v[0], v[1], 1))
            elif _within((X.sqdist(v, w), 1), t):
                out.near = True
    if not intra:
        for v, ov in pb.verts:
            if ov[1] != -2:
                continue
            for p, q, _ in pa.segs:
                d2 = X.sqdist_point_segment(v, p, q)
                if d2[0] == 0:
                    out.lattice = True
                    if count and out.points is not None:
                        out.points.add((v[0], v[1], 1))
                elif _within(d2, t):
                    out.near = True


def contact_tags(a: Geometry, b: Geometry) -> tuple[str, int | None]:
    """(degeneracy class, k) of an operand pair; see the module docstring."""
    values = [v for v in (*a.iter_values(), *b.iter_values()) if math.isfinite(v)]
    if not values:
        return "generic", 0
    scale = DyadicScale.for_values(values)
    pa, pb = _Parts(a, scale), _Parts(b, scale)
    m = max((abs(c) for p, _ in pa.verts + pb.verts for c in p), default=1)
    t = _near_threshold(m)
    out = _Contacts()
    _analyse(pa, pb, t, out, count=True, intra=False)
    k = None if out.points is None else len(out.points)
    if not out.lattice:
        inter = _Contacts()
        for p in (pa, pb):
            _analyse(p, p, t, inter, count=False, intra=True)
            if inter.lattice:
                break
        out.lattice = inter.lattice
        out.near = out.near or inter.near
    if out.lattice:
        return "lattice", k
    return ("ulp" if out.near else "generic"), k


def coordinate_range(a: Geometry, b: Geometry) -> str:
    for v in (*a.iter_values(), *b.iter_values()):
        if v and math.isfinite(v) and not (EXTREME_LO <= abs(v) <= EXTREME_HI):
            return "extreme"
    return "normal"


def compute_tags(
    a: Geometry, b: Geometry, *, variant: str | None = None, flags: tuple[str, ...] | list[str] = ()
) -> dict[str, Any]:
    """The ``tags`` object of a v2 case (see the module docstring)."""
    deg, k = contact_tags(a, b)
    fl = set(flags)
    if a.is_empty or b.is_empty or any(e.is_empty for g in (a, b) for e in g.elements()):
        fl.add("empty")
    if any(g.geom_type == "GeometryCollection" for g in (a, b)):
        fl.add("gc")
    if (
        a.is_zero_length_linear
        or b.is_zero_length_linear
        or any(
            isinstance(e, LineString) and e.coords and e.is_zero_length
            for g in (a, b)
            for e in g.elements()
        )
    ):
        fl.add("zero-length-line")
    if a.has_nonfinite or b.has_nonfinite:
        fl.add("nonfinite")
    tags: dict[str, Any] = {
        "degeneracy": deg,
        "range": coordinate_range(a, b),
        "n": a.num_coords + b.num_coords,
        "k": k,
        "types": [a.geom_type, b.geom_type],
    }
    if variant:
        tags["variant"] = variant
    if fl:
        tags["flags"] = sorted(fl)
    return tags


# ============================================================================ records


def provenance(
    generator: str, seed: int | None, n_per_family: int | None = None, **extra: Any
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "source": "generator",
        "generator": generator,
        "generator_version": GENERATOR_VERSION,
    }
    if seed is not None:
        out["seed"] = seed
    if n_per_family is not None:
        out["n_per_family"] = n_per_family
    out.update(extra)
    return out


def make_case(
    case_id: str,
    family: str,
    a: Any,
    b: Any,
    *,
    variant: str | None,
    prov: dict[str, Any],
    flags: tuple[str, ...] | list[str] = (),
    ops: list[str] | None = None,
) -> dict[str, Any]:
    """A v2 case record. ``a``/``b`` are typed JSON or legacy coordinate lists; legacy
    lists are written as typed JSON (Polygon or MultiPolygon)."""
    ja = legacy_to_typed(a) if isinstance(a, list) else a
    jb = legacy_to_typed(b) if isinstance(b, list) else b
    ga, gb = as_geometry(ja), as_geometry(jb)
    rec: dict[str, Any] = {
        "id": case_id,
        "family": family,
        "tags": compute_tags(ga, gb, variant=variant, flags=flags),
        "provenance": prov,
    }
    if ops:
        rec["ops"] = ops
    rec["a"] = ja
    rec["b"] = jb
    return rec
