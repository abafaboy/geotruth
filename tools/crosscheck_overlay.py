#!/usr/bin/env python3
"""Overlay cross-check (DESIGN §0.2, §2.5, §2.6).

Every case is overlaid by :func:`geotruth.overlay.overlay_all` (the four operations in both
variants, read off one arrangement) and then checked by:

``certificate``
    :mod:`geotruth.overlay_certify` on every result: A, B and the result re-noded from
    scratch, every witness located in the original geometries by the standalone point
    locator, and the canonical-form checks. It shares only the §2.1 primitives with the
    overlay builder.
``oracle`` / ``indep``
    for valid polygon/polygon cases, the exact areas of ``tests/reference/oracle.py``
    (vertical slabs) and ``indep.py`` (Green's theorem on boundary pieces): intersection,
    union, difference and symmetric difference must be *equal* as rationals.
``validity``
    the polygonal part of every result must be valid under the audited reference rules
    R0-R6 (``tests/reference/validity.py``), and identical in both variants.
``properties``
    exact identities and invariances (engine against itself on other inputs):
    ``|A n B| + |A - B| = |A|``, ``|A n B| + |B - A| = |B|``,
    ``|A u B| = |A n B| + |A - B| + |B - A|``, ``|A x B| = |A - B| + |B - A|`` (point-set
    areas; ``|A|`` also equals the shoelace area for a Polygon/MultiPolygon); the
    symmetric operations commute exactly (same canonical geometry); ``A x B`` and
    ``(A u B) - (A n B)`` are the same point set; ``A u {} = A``, ``A n A = A`` as point
    sets and ``A - A = A x A = {}``; and exact transform invariance: translating by a
    dyadic vector, rotating by 90 degrees, reflecting, or scaling by ``2**k`` maps the
    canonical result exactly onto the result of the mapped operands. Point sets are
    compared with the exact relate (IE = BE = EI = EB = F).
``geos``
    GEOS (OverlayNG, through Shapely, in a separate restartable process) as a third
    opinion on small-integer lattice cases of GEOS-valid operands. Its output (doubles,
    converted exactly) is first certified as a *point set* (``structure=False``). Verdicts:

    - ``exact``: GEOS's canonical output equals the exact result;
    - ``same-point-set (...)``: the point sets agree; the reasons name the structural
      differences: ``collinear-vertices`` (GEOS keeps input vertices the exact result
      drops) or ``nodes`` (a different set of nodes or line splits), ``unnoded-lines``
      (overlapping or retraced line output), ``duplicate-points``, ``covered-parts``,
      ``invalid-polygons``, ``type`` (a less specific type), ``empty-type`` (another
      typed empty), after normalizing both (``normalize``: overlay with an empty
      geometry, which re-nodes and drops collinear non-node vertices);
    - ``rounding``: the point sets differ, but the exact result has coordinates that are
      not doubles, so GEOS must round its nodes;
    - ``gc-overlay (...)``: the point sets differ on a case with a GeometryCollection
      operand, which OverlayNG proper rejects and GEOS 3.13 overlays heuristically; the
      detail says whether GEOS drops or adds parts;
    - ``geos-error`` / ``geos-crash``: GEOS raised or crashed;
    - ``UNEXPLAINED``: anything else (the exit status is then 1).

Case sources (``--sources``) are those of ``tools/crosscheck_relate.py``: fixtures,
exhaustive, seed, review, lattice, adversarial, transformed, ulp, dense.

usage::

    python3 tools/crosscheck_overlay.py                          # everything
    python3 tools/crosscheck_overlay.py --sources seed,review --no-geos
    python3 tools/crosscheck_overlay.py --sources lattice --cases 2000 --jobs 2 --json r.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import random
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
for _p in (REPO / "src", REPO / "tests"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from geotruth.arrangement import InvalidInputError  # noqa: E402
from geotruth.geom import (  # noqa: E402
    Geometry,
    GeometryCollection,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
)
from geotruth.io import canonicalize, geometry_from_json, geometry_to_json, to_wkt  # noqa: E402
from geotruth.measures import area as shoelace_area  # noqa: E402
from geotruth.numbers import rational_to_float  # noqa: E402
from geotruth.overlay import OPS, VARIANTS, overlay, overlay_all  # noqa: E402
from geotruth.overlay_certify import Certificate, certify  # noqa: E402
from geotruth.relate import relate  # noqa: E402


def _load_relate_tool() -> Any:
    name = "crosscheck_relate"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / "crosscheck_relate.py")
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


R = _load_relate_tool()
XCase = R.XCase
SOURCES = R.SOURCES

EMPTY = GeometryCollection()
SYMMETRIC = ("intersection", "union", "symdifference")
SHAPELY_OPS = {
    "intersection": "intersection",
    "union": "union",
    "difference": "difference",
    "symdifference": "symmetric_difference",
}


# ============================================================================ helpers


def exact_json(g: Geometry) -> dict[str, Any]:
    return geometry_to_json(g, exact=True)


def same_point_set(x: Geometry, y: Geometry) -> bool:
    """Exact point-set equality (union semantics), from the exact relate."""
    if x.is_empty or y.is_empty:
        return x.is_empty == y.is_empty
    m = relate(x, y, transpose_check=False, strict=True).matrix
    assert m is not None
    return m[2] == m[5] == m[6] == m[7] == "F"


def polygon_part(g: Geometry) -> list[Polygon]:
    return [e for e in g.elements() if isinstance(e, Polygon) and not e.is_empty]


def doubles_only(g: Geometry) -> bool:
    """True if every coordinate of an exact result is a double."""
    for v in g.iter_values():
        f = q(v)
        if f.denominator & (f.denominator - 1):
            return False
        try:
            if Fraction(float(f)) != f:
                return False
        except OverflowError:
            return False
    return True


def parts_signature(g: Geometry) -> tuple:
    """Type and parts: the number of holes of each polygon, of lines and of points."""
    polys, lines, npts = [], 0, 0
    for e in g.elements():
        if e.is_empty:
            continue
        if isinstance(e, Polygon):
            polys.append(len(e.rings) - 1)
        elif isinstance(e, LineString):
            lines += 1
        else:
            npts += 1
    return (g.geom_type, tuple(sorted(polys)), lines, npts)


def point_set_area(g: Geometry) -> Any:
    """The area of the point set of ``g`` (overlapping GC polygons counted once)."""
    res = overlay(g, EMPTY, "union", "areal", strict=True)
    return res.area


def normalize(g: Geometry) -> Geometry | None:
    """A structure-independent form for comparing outputs: ``g`` overlaid with an empty
    geometry (re-noded, covered parts dropped, collinear non-node vertices removed,
    canonical order); None when ``g`` is outside the engine's contract (invalid)."""
    try:
        res = overlay(g, EMPTY, "union", strict=True)
    except (InvalidInputError, ValueError):
        return None
    return res.geometry


# ============================================================================ transforms


def q(v: Any) -> Fraction:
    """An exact coordinate (double, int, Fraction or mpq) as a Fraction."""
    if isinstance(v, (int, float, Fraction)):
        return Fraction(v)
    return Fraction(int(v.numerator), int(v.denominator))


def _exact_map(f: Callable[[Fraction, Fraction], tuple[Fraction, Fraction]]) -> Callable:
    def m(c: Any) -> tuple[Any, Any]:
        return f(q(c[0]), q(c[1]))

    return m


def transforms(rng: random.Random) -> tuple[str, Callable, Callable]:
    """A random exact similarity: ``(name, map on doubles, map on exact rationals)``."""
    kind = rng.choice(("translate", "rotate90", "reflect", "scale"))
    if kind == "translate":
        dx = Fraction(rng.randint(-64, 64), 2 ** rng.randint(0, 6))
        dy = Fraction(rng.randint(-64, 64), 2 ** rng.randint(0, 6))
        fx, fy = float(dx), float(dy)
        return (
            f"translate ({dx}, {dy})",
            lambda c: (c[0] + fx, c[1] + fy),
            _exact_map(lambda x, y: (x + dx, y + dy)),
        )
    if kind == "rotate90":
        return (
            "rotate 90",
            lambda c: (-c[1], c[0]),
            _exact_map(lambda x, y: (-y, x)),
        )
    if kind == "reflect":
        return "reflect x", lambda c: (-c[0], c[1]), _exact_map(lambda x, y: (-x, y))
    k = rng.choice((-40, -7, -1, 1, 3, 60))
    s = Fraction(2) ** k
    return (
        f"scale 2**{k}",
        lambda c: (math.ldexp(c[0], k), math.ldexp(c[1], k)),
        _exact_map(lambda x, y: (x * s, y * s)),
    )


def _mapped_exactly(g: Geometry, fd: Callable, fe: Callable) -> Geometry | None:
    """``g`` mapped by ``fd`` if that is exact on every coordinate, else None."""
    try:
        out = g.map_coords(fd)
    except OverflowError:
        return None
    for c, d in zip(g.iter_coords(), out.iter_coords(), strict=True):
        if not all(math.isfinite(v) for v in d):
            return None
        if fe(c) != (Fraction(d[0]), Fraction(d[1])):
            return None
    return out


# ============================================================================ GEOS

_GEOS_OVERLAY_SERVER = r"""
import json, sys
import shapely

def tj(g):
    t = g.geom_type
    if t == "GeometryCollection":
        return {"type": t, "geometries": [tj(x) for x in g.geoms]}
    if t == "LinearRing":
        t = "LineString"
    if g.is_empty:
        return {"type": t, "coordinates": []}
    if t == "Point":
        return {"type": t, "coordinates": [g.x, g.y]}
    if t == "LineString":
        return {"type": t, "coordinates": [list(c[:2]) for c in g.coords]}
    if t == "Polygon":
        rings = (g.exterior, *g.interiors)
        return {"type": t, "coordinates": [[list(c[:2]) for c in r.coords] for r in rings]}
    parts = [tj(x) for x in g.geoms]
    return {"type": t, "coordinates": [p["coordinates"] for p in parts]}

for line in sys.stdin:
    req = json.loads(line)
    try:
        if req["op"] == "overlay":
            a, b = shapely.from_wkt(req["a"]), shapely.from_wkt(req["b"])
            res = {}
            for op in req["ops"]:
                try:
                    res[op] = {"g": tj(getattr(shapely, op)(a, b))}
                except Exception as exc:
                    res[op] = {"error": f"{type(exc).__name__}: {exc}"}
            res = {"r": res}
        else:
            res = {"v": shapely.geos_version_string}
    except Exception as exc:
        res = {"error": f"{type(exc).__name__}: {exc}"}
    sys.stdout.write(json.dumps(res) + "\n")
    sys.stdout.flush()
"""


class GeosOverlayWorker(R.GeosWorker):
    """GEOS overlays in a separate, restartable process (a crash is recorded, not fatal)."""

    def _start(self) -> subprocess.Popen:
        if self.proc is None or self.proc.poll() is not None:
            self.proc = subprocess.Popen(
                [sys.executable, "-c", _GEOS_OVERLAY_SERVER],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        return self.proc

    def overlays(self, a: Geometry, b: Geometry) -> dict[str, Geometry | str]:
        """GEOS's result of every operation: a geometry, or the error text."""
        names = list(SHAPELY_OPS.values())
        out = self.call({"op": "overlay", "a": to_wkt(a), "b": to_wkt(b), "ops": names})["r"]
        res: dict[str, Geometry | str] = {}
        for op, name in SHAPELY_OPS.items():
            item = out[name]
            res[op] = item["error"] if "error" in item else geometry_from_json(item["g"])
        return res


_GEOS: GeosOverlayWorker | None = None


def geos() -> GeosOverlayWorker:
    global _GEOS
    if _GEOS is None:
        _GEOS = GeosOverlayWorker()
    return _GEOS


def _is_gc(g: Geometry) -> bool:
    return isinstance(g, GeometryCollection)


def _structure_reasons(cert: Certificate) -> list[str]:
    tags = []
    for p in cert.problems:
        if "not in canonical order" in p:
            continue
        if "empty result must be" in p:
            tags.append("empty-type")
        elif "lines overlap" in p:
            tags.append("unnoded-lines")
        elif "repeats a point" in p:
            tags.append("duplicate-points")
        elif "covered" in p or "lies on or in" in p:
            tags.append("covered-parts")
        elif "polygonal part is invalid" in p:
            tags.append("invalid-polygons")
        elif "its parts make" in p or "nests collections" in p:
            tags.append("type")
        elif "zero length" in p:
            tags.append("zero-length-line")
        else:
            tags.append(p)
    return tags


def geos_verdict(
    a: Geometry, b: Geometry, op: str, mine: Geometry, theirs: Geometry | str
) -> tuple[str, str]:
    """``(verdict, detail)`` for GEOS's result of ``op`` (see the module docstring)."""
    if isinstance(theirs, str):
        return "geos-error", theirs
    if exact_json(canonicalize(theirs)) == exact_json(mine):
        return "exact", ""
    ps = certify(a, b, op, theirs, "non_strict", structure=False)
    if ps.ok:
        full = certify(a, b, op, theirs, "non_strict", structure=True)
        tags = _structure_reasons(full)
        nm, nt = normalize(mine), normalize(theirs)
        if nm is None or nt is None or exact_json(nm) != exact_json(nt):
            tags.append("nodes")
        elif not tags:
            tags.append("collinear-vertices")
        return f"same-point-set ({', '.join(sorted(set(tags)))})", ""
    detail = ps.summary()
    gc = _is_gc(a) or _is_gc(b)
    if not doubles_only(mine):
        rounded = canonicalize(
            mine.map_coords(lambda c: (rational_to_float(c[0]), rational_to_float(c[1])))
        )
        if exact_json(canonicalize(theirs)) == exact_json(rounded):
            return "rounding (nearest)", ""
        if parts_signature(theirs) == parts_signature(mine):
            return "rounding (same parts)", ""
        if gc:
            return f"gc-overlay ({_how(ps)}; rounded nodes)", detail
        return "rounding (different parts)", detail
    if gc:
        return f"gc-overlay ({_how(ps)})", detail
    return "UNEXPLAINED", detail


def _how(ps: Certificate) -> str:
    """Whether a wrong point set misses selected cells, has extra ones, or both."""
    missing = any("E" not in m.expected and m.got == "E" for m in ps.mismatches)
    extra = any(m.expected == "E" and m.got != "E" for m in ps.mismatches)
    if missing and not extra:
        return "drops parts"
    if extra and not missing:
        return "adds parts"
    return "wrong parts"


# ============================================================================ checks


@dataclass
class Report:
    """The outcome of one case."""

    id: str
    source: str
    family: str
    types: tuple[str, str]
    status: str = "ok"
    invalid_input: str | None = None
    results: int = 0
    certified: int = 0
    oracle_agree: bool | None = None
    indep_agree: bool | None = None
    validity_agree: bool | None = None
    identities: bool | None = None
    transform: str | None = None
    transform_agree: bool | None = None
    geos: dict[str, str] = field(default_factory=dict)
    geos_detail: dict[str, str] = field(default_factory=dict)
    kinds: dict[str, str] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)
    t_overlay: float = 0.0
    t_certify: float = 0.0
    wkt: tuple[str, str] | None = None

    @property
    def failed(self) -> bool:
        return bool(self.problems)

    @property
    def geos_unexplained(self) -> int:
        return sum(v == "UNEXPLAINED" for v in self.geos.values())


def _references(rep: Report, a: Geometry, b: Geometry, areas: dict[str, Any]) -> None:
    from reference import indep, oracle

    la, lb = R.legacy(a), R.legacy(b)
    o = oracle.evaluate({"id": rep.id, "a": la, "b": lb})
    if not (o.get("valid_a") and o.get("valid_b")):
        return
    inter, dab, dba = (Fraction(str(o["exact"][k])) for k in ("inter", "diff_ab", "diff_ba"))
    want = {
        "intersection": inter,
        "union": inter + dab + dba,
        "difference": dab,
        "symdifference": dab + dba,
    }
    got = {op: q(v) for op, v in areas.items()}
    rep.oracle_agree = got == want
    if not rep.oracle_agree:
        rep.problems.append(f"areas differ from oracle.py: engine {got}, oracle {want}")
    i = indep.evaluate_geoms(la, lb)
    want_i = {
        "intersection": i["inter"],
        "union": i["union"],
        "difference": i["diff_ab"],
        "symdifference": i["diff_ab"] + i["diff_ba"],
    }
    rep.indep_agree = got == want_i
    if not rep.indep_agree:
        rep.problems.append(f"areas differ from indep.py: engine {got}, indep {want_i}")


def _reference_validity(polys: list[Polygon]) -> bool:
    from reference import validity

    if not polys:
        return True
    geom = [[[[q(x), q(y)] for x, y in r] for r in p.rings] for p in polys]
    return bool(validity.valid_geometry(geom))


def _identities(rep: Report, a: Geometry, b: Geometry, res: dict) -> None:
    """Exact area identities, commutativity and point-set identities."""
    ok = True

    def fail(msg: str) -> None:
        nonlocal ok
        ok = False
        rep.problems.append(f"identity: {msg}")

    area = {op: res[op]["areal"].area for op in OPS}
    ba = overlay(b, a, "difference", "areal", strict=True).area
    pa, pb = point_set_area(a), point_set_area(b)
    if area["intersection"] + area["difference"] != pa:
        fail(f"|AnB| + |A-B| = {area['intersection'] + area['difference']} != |A| = {pa}")
    if area["intersection"] + ba != pb:
        fail(f"|AnB| + |B-A| = {area['intersection'] + ba} != |B| = {pb}")
    if area["union"] != area["intersection"] + area["difference"] + ba:
        fail("|AuB| != |AnB| + |A-B| + |B-A|")
    if area["symdifference"] != area["difference"] + ba:
        fail("|AxB| != |A-B| + |B-A|")
    for g, p in ((a, pa), (b, pb)):
        if isinstance(g, (Polygon, MultiPolygon)) and shoelace_area(g) != p:
            fail(f"point-set area {p} != shoelace area {shoelace_area(g)}")
    swapped = overlay_all(b, a, ops=SYMMETRIC, strict=True)
    for op in SYMMETRIC:
        for v in VARIANTS:
            if exact_json(swapped[op][v].geometry) != exact_json(res[op][v].geometry):
                fail(f"{op} ({v}) does not commute")
    u, i, s = (res[op]["non_strict"].geometry for op in ("union", "intersection", "symdifference"))
    ui = overlay(u, i, "difference", strict=True).geometry
    if not same_point_set(ui, s):
        fail("(A u B) - (A n B) is not the point set of A x B")
    for g, name in ((a, "A"), (b, "B")):
        self_ = overlay_all(g, g, strict=True)
        if not same_point_set(self_["union"]["non_strict"].geometry, g):
            fail(f"{name} u {name} is not {name}")
        if not same_point_set(self_["intersection"]["non_strict"].geometry, g):
            fail(f"{name} n {name} is not {name}")
        for op in ("difference", "symdifference"):
            if not self_[op]["non_strict"].geometry.is_empty:
                fail(f"{name} {op} {name} is not empty")
        if not same_point_set(overlay(g, EMPTY, "union", strict=True).geometry, g):
            fail(f"{name} u EMPTY is not {name}")
    rep.identities = ok


def _transform(rep: Report, a: Geometry, b: Geometry, res: dict, rng: random.Random) -> None:
    name, fd, fe = transforms(rng)
    ta, tb = _mapped_exactly(a, fd, fe), _mapped_exactly(b, fd, fe)
    if ta is None or tb is None:
        return
    rep.transform = name
    tres = overlay_all(ta, tb, strict=True)
    ok = True
    for op in OPS:
        for v in VARIANTS:
            want = canonicalize(res[op][v].geometry.map_coords(fe))
            if exact_json(tres[op][v].geometry) != exact_json(want):
                ok = False
                rep.problems.append(f"{name} does not commute with {op} ({v})")
    rep.transform_agree = ok


def check_case(
    xc: Any,
    *,
    use_geos: bool = True,
    properties: bool = True,
    certify_results: bool = True,
) -> Report:
    """Overlay one case and run every applicable check. An unexpected exception is
    recorded as a failure of the case (it never ends a run)."""
    try:
        return _check_case(xc, use_geos, properties, certify_results)
    except Exception as exc:
        rep = Report(xc.id, xc.source, xc.family, (xc.a.geom_type, xc.b.geom_type))
        rep.problems.append(f"the check raised {type(exc).__name__}: {exc}")
        rep.wkt = (to_wkt(xc.a), to_wkt(xc.b))
        return rep


def _check_case(xc: Any, use_geos: bool, properties: bool, certify_results: bool) -> Report:
    a, b = xc.a, xc.b
    rep = Report(xc.id, xc.source, xc.family, (a.geom_type, b.geom_type))
    t = time.perf_counter()
    try:
        res = overlay_all(a, b)
    except InvalidInputError as exc:
        rep.invalid_input = str(exc)
        rep.problems.append(f"the engine refused the input: {exc}")
        rep.wkt = (to_wkt(a), to_wkt(b))
        return rep
    rep.t_overlay = time.perf_counter() - t
    results = [r for per in res.values() for r in per.values()]
    rep.results = len(results)
    bad = [r for r in results if not r.ok]
    if bad:
        rep.status = bad[0].status
        for r in bad:
            rep.problems.append(f"{r.op} ({r.variant}): {r.status}: {r.reason}")
        rep.wkt = (to_wkt(a), to_wkt(b))
        return rep
    for r in results:
        rep.kinds[f"{r.op}/{r.variant}"] = r.geometry.geom_type

    if certify_results:
        from geotruth.overlay_certify import certify_many

        t = time.perf_counter()
        certs = certify_many(a, b, [(r.op, r.variant, r.geometry) for r in results])
        rep.t_certify = time.perf_counter() - t
        for r, c in zip(results, certs, strict=True):
            if c.ok:
                rep.certified += 1
            else:
                rep.problems.append(f"certificate of {r.op} ({r.variant}): {c.summary()}")

    # both variants share the polygonal part; it is valid (reference rules)
    valid = True
    for op in OPS:
        p_ns = polygon_part(res[op]["non_strict"].geometry)
        p_ar = polygon_part(res[op]["areal"].geometry)
        if [exact_json(p) for p in p_ns] != [exact_json(p) for p in p_ar]:
            valid = False
            rep.problems.append(f"{op}: the variants have different polygonal parts")
        if res[op]["non_strict"].area != res[op]["areal"].area:
            valid = False
            rep.problems.append(f"{op}: the variants have different areas")
        if not _reference_validity(p_ar):
            valid = False
            rep.problems.append(f"{op}: the polygonal result is invalid (reference validity)")
    rep.validity_agree = valid

    areas = {op: res[op]["areal"].area for op in OPS}
    if R.polygonal(a) and R.polygonal(b) and R._float_coords(a) and R._float_coords(b):
        _references(rep, a, b, areas)

    if properties:
        rng = random.Random(xc.id)
        try:
            _identities(rep, a, b, res)
            _transform(rep, a, b, res, rng)
        except InvalidInputError as exc:
            rep.problems.append(f"property check: the engine refused a derived input: {exc}")

    if use_geos and R._shapely() is not None and R.geos_eligible(a, b):
        try:
            theirs = geos().overlays(a, b)
        except R.GeosCrash as exc:
            theirs = dict.fromkeys(OPS, f"crash: {exc}")
            rep.geos = dict.fromkeys(OPS, "geos-crash")
        else:
            for op in OPS:
                v, d = geos_verdict(a, b, op, res[op]["non_strict"].geometry, theirs[op])
                rep.geos[op] = v
                if d:
                    rep.geos_detail[op] = d
                if v == "UNEXPLAINED":
                    rep.problems.append(f"GEOS {op} unexplained: {d}")
    if rep.problems or any(v not in ("exact",) for v in rep.geos.values()):
        rep.wkt = (to_wkt(a), to_wkt(b))
    return rep


# ============================================================================ runs


def gather(sources: Iterable[str], args: argparse.Namespace) -> list[Any]:
    return R.gather(sources, args)


def _run_chunk(payload: tuple[list[Any], bool, bool]) -> list[Report]:
    chunk, use_geos, props = payload
    return [check_case(c, use_geos=use_geos, properties=props) for c in chunk]


def run(
    cases: list[Any], *, jobs: int = 1, use_geos: bool = True, properties: bool = True
) -> list[Report]:
    if jobs <= 1:
        return [check_case(c, use_geos=use_geos, properties=properties) for c in cases]
    from concurrent.futures import ProcessPoolExecutor

    size = max(1, min(100, len(cases) // (jobs * 8) or 1))
    chunks = [(cases[i : i + size], use_geos, properties) for i in range(0, len(cases), size)]
    out: list[Report] = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for reps in pool.map(_run_chunk, chunks):
            out += reps
    return out


def summarize(reports: list[Report]) -> dict[str, Any]:
    by_src: dict[str, list[Report]] = {}
    for r in reports:
        by_src.setdefault(r.source, []).append(r)

    def frac(rs: list[Report], attr: str) -> tuple[int, int]:
        vals = [getattr(r, attr) for r in rs if getattr(r, attr) is not None]
        return sum(bool(v) for v in vals), len(vals)

    def stats(rs: list[Report]) -> dict[str, Any]:
        verdicts = Counter(v for r in rs for v in r.geos.values())
        return {
            "cases": len(rs),
            "results": sum(r.results for r in rs),
            "certified": sum(r.certified for r in rs),
            "engine_not_ok": sum(r.status != "ok" for r in rs),
            "invalid_input": sum(r.invalid_input is not None for r in rs),
            "oracle": frac(rs, "oracle_agree"),
            "indep": frac(rs, "indep_agree"),
            "validity": frac(rs, "validity_agree"),
            "identities": frac(rs, "identities"),
            "transform": frac(rs, "transform_agree"),
            "geos_compared": sum(len(r.geos) for r in rs),
            "geos_verdicts": dict(sorted(verdicts.items())),
            "geos_unexplained": sum(r.geos_unexplained for r in rs),
            "failed": sum(r.failed for r in rs),
            "t_overlay_ms": round(1000 * sum(r.t_overlay for r in rs) / max(1, len(rs)), 3),
            "t_certify_ms": round(1000 * sum(r.t_certify for r in rs) / max(1, len(rs)), 3),
        }

    types = Counter(f"{r.types[0]}/{r.types[1]}" for r in reports)
    kinds = Counter(k for r in reports for k in r.kinds.values())
    examples: dict[str, list[dict[str, Any]]] = {}
    for r in reports:
        for op, v in r.geos.items():
            if v == "exact":
                continue
            lst = examples.setdefault(v, [])
            if len(lst) < 5:
                lst.append(
                    {
                        "id": r.id,
                        "op": op,
                        "a": r.wkt[0] if r.wkt else None,
                        "b": r.wkt[1] if r.wkt else None,
                        "detail": r.geos_detail.get(op, ""),
                    }
                )
    return {
        "sources": {s: stats(rs) for s, rs in by_src.items()},
        "total": stats(reports),
        "type_pairs": len(types),
        "result_types": dict(sorted(kinds.items())),
        "failures": [
            {
                "id": r.id,
                "family": r.family,
                "a": r.wkt[0] if r.wkt else None,
                "b": r.wkt[1] if r.wkt else None,
                "problems": r.problems,
            }
            for r in reports
            if r.failed
        ],
        "geos_examples": examples,
    }


def print_summary(summary: dict[str, Any], out: Any = None) -> None:
    out = out if out is not None else sys.stdout
    cols = ("cases", "certified", "oracle", "indep", "validity", "identities", "transform", "fail")
    print(f"{'source':12s} " + " ".join(f"{c:>12s}" for c in cols), file=out)

    def fr(t: tuple[int, int]) -> str:
        return f"{t[0]}/{t[1]}" if t[1] else "-"

    for name, s in [*summary["sources"].items(), ("TOTAL", summary["total"])]:
        cells = (
            str(s["cases"]),
            f"{s['certified']}/{s['results']}",
            fr(s["oracle"]),
            fr(s["indep"]),
            fr(s["validity"]),
            fr(s["identities"]),
            fr(s["transform"]),
            str(s["failed"]),
        )
        print(f"{name:12s} " + " ".join(f"{c:>12s}" for c in cells), file=out)
    tot = summary["total"]
    print(f"\ntype pairs covered: {summary['type_pairs']}", file=out)
    print(f"result types: {summary['result_types']}", file=out)
    print(f"GEOS results compared: {tot['geos_compared']}", file=out)
    for v, n in tot["geos_verdicts"].items():
        print(f"  {n:7d}  {v}", file=out)
    print(
        f"engine: {tot['engine_not_ok']} not ok, {tot['invalid_input']} refused inputs; "
        f"mean per case: overlay {tot['t_overlay_ms']} ms (4 ops x 2 variants), "
        f"certificate {tot['t_certify_ms']} ms",
        file=out,
    )
    for f in summary["failures"][:20]:
        print(f"\nFAIL {f['id']} ({f['family']})\n  A: {f['a']}\n  B: {f['b']}", file=out)
        for p in f["problems"][:8]:
            print(f"  - {p}", file=out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--sources", default=",".join(SOURCES), help=f"subset of {', '.join(SOURCES)}")
    p.add_argument("--cases", type=int, default=1000, help="random cases per random source")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--seed-step", type=int, default=1, help="use every k-th seed case")
    p.add_argument("--review-n", type=int, default=50, help="cases per review family")
    p.add_argument("--jobs", type=int, default=1, help="worker processes (at most 2 advised)")
    p.add_argument("--no-geos", action="store_true", help="skip the GEOS third opinion")
    p.add_argument("--no-properties", action="store_true", help="skip identities/transforms")
    p.add_argument("--json", metavar="PATH", help="write the full report as JSON")
    args = p.parse_args(argv)
    sources = [s.strip() for s in args.sources.split(",") if s.strip()]
    t0 = time.perf_counter()
    cases = gather(sources, args)
    reports = run(
        cases, jobs=args.jobs, use_geos=not args.no_geos, properties=not args.no_properties
    )
    summary = summarize(reports)
    summary["seconds"] = round(time.perf_counter() - t0, 1)
    summary["geos_version"] = None if R._shapely() is None or args.no_geos else geos().version()
    print_summary(summary)
    print(f"\n{len(cases)} cases in {summary['seconds']} s (GEOS {summary['geos_version']})")
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=1, default=str) + "\n")
    return 1 if summary["total"]["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
