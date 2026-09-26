"""Shared support for the native-adapter tests (``test_native_*.py``), and its own tests.

The native adapters are the C / C++ programs under ``adapters/geos_main``,
``adapters/boost_geometry``, ``adapters/clipper2`` and ``adapters/cgal``. They answer
adapter contract v2 (DESIGN.md §4.1, ``schemas/result.v2.schema.json``) for typed input and
the unchanged v1 contract (``harness/FORMAT-v1.md``) for legacy input.

What lives here:

- :data:`TARGETS`: every library build of those four directories, read from their
  ``adapter.toml`` manifests, with :func:`require` to skip a test when that build is absent
  (builds live under ``$GEOTRUTH_BUILD_DIR``, default ``~/.cache/geotruth``);
- :func:`run_adapter`: run a target on a list of cases and parse its output lines;
- :data:`CANARY`: the parse-echo canary case (``schemas/examples/case.v2.valid.json``);
- :func:`exact_pair`: the exact answer for a polygon/polygon pair, behind an import shim.
  It uses the engine's documented API (DESIGN.md §2: ``geotruth.relate.relate(a, b)`` ->
  matrix / predicates / status, ``geotruth.overlay.overlay(a, b, op, variant)`` -> exact
  geometry + side-car + area) as soon as those modules exist, and falls back to the audited
  ``tests/reference/oracle.py`` until then. ``GEOTRUTH_EXACT_BACKEND=oracle|engine`` forces
  one backend (``auto``, the default, prefers the engine);
- :func:`area`: the exact (even-odd) area of a typed geometry with double ordinates.
"""

from __future__ import annotations

import dataclasses
import importlib
import itertools
import json
import os
import shlex
import subprocess
import sys
import warnings
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
NATIVE_DIRS = ("geos_main", "boost_geometry", "clipper2", "cgal")
OPS = ("intersection", "union", "difference", "symdifference")
PREDICATES = ("intersects", "disjoint", "touches", "crosses", "overlaps", "contains", "covers",
              "within", "covered_by", "equals")
V1_PREDICATES = tuple(p for p in PREDICATES if p != "crosses")
V1_FIELDS = ("valid_a", "valid_b", *V1_PREDICATES,
             "area_inter", "area_union", "area_diff", "area_symdiff")
V2_PATHS = ("echo", "relate", *(f"predicates.{p}" for p in PREDICATES), "valid_a", "valid_b",
            *(f"overlay.{op}" for op in OPS))
# fault-injection variables of the native adapters, per directory
FAULT_ENV = {"geos_main": "GEOS_ADAPTER_TEST_FAULT", "boost_geometry": "BG_ADAPTER_TEST_FAULT",
             "clipper2": "CLIPPER2_ADAPTER_TEST_FAULT", "cgal": "CGAL_ADAPTER_TEST_FAULT"}

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    tomllib = pytest.importorskip("tomli")


# ============================================================================ targets


@dataclass(frozen=True)
class Target:
    dir: str        # adapters/<dir>
    id: str         # manifest target id
    lib: str        # the lib string it reports
    run: str        # run command from the manifest (repo-relative)
    manifest: dict  # the [[target]] table

    def command(self, *flags: str) -> list[str]:
        words = shlex.split(self.run)
        return [str(REPO / words[0]), *words[1:], *flags]


def _load_targets() -> list[Target]:
    out = []
    for d in NATIVE_DIRS:
        with open(REPO / "adapters" / d / "adapter.toml", "rb") as fh:
            m = tomllib.load(fh)
        out += [Target(d, t["id"], t["lib"], t["run"], t) for t in m["target"]]
    return out


TARGETS: list[Target] = _load_targets()
TARGET_IDS = [t.id for t in TARGETS]


def target(tid: str) -> Target:
    return next(t for t in TARGETS if t.id == tid)


def built(t: Target) -> bool:
    """Is this target's binary built (its run wrapper answers --version)?"""
    try:
        out = subprocess.run(t.command("--version"), capture_output=True, text=True, timeout=30,
                             check=False)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return out.returncode == 0 and out.stdout.strip() == t.lib


def require(t: Target) -> None:
    """Skip unless the target is built (build it with its adapters/<dir>/build.sh)."""
    if not built(t):
        pytest.skip(f"{t.id} is not built under $GEOTRUTH_BUILD_DIR (adapters/{t.dir}/build.sh)")


def run_adapter(t: Target, cases: list[dict] | Path, *flags: str, env: dict | None = None,
                tmp: Path | None = None, timeout: float = 600) -> list[dict]:
    """Run ``t`` on the cases (a list of dicts, or a JSONL file) and parse every output line."""
    if isinstance(cases, Path):
        path = cases
    else:
        if tmp is None:
            raise ValueError("tmp is required for in-memory cases")
        path = tmp / f"cases-{t.id}.jsonl"
        path.write_text("".join(json.dumps(c) + "\n" for c in cases))
    full_env = {**os.environ, **(env or {})}
    out = subprocess.run(t.command(*flags, str(path)), capture_output=True, text=True,
                         timeout=timeout, env=full_env, check=False)
    assert out.returncode == 0, out.stderr[-2000:]
    return [json.loads(line) for line in out.stdout.splitlines()]


def by_id(records: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in records}


# ============================================================================ canary


def _canary() -> dict:
    cases = json.loads((REPO / "schemas" / "examples" / "case.v2.valid.json").read_text())
    (c,) = [c for c in cases if c.get("ops") == ["echo"]]
    return c


#: The parse-echo canary: 2^53+1 as an integer literal, subnormals, -0.0,
#: 0.30000000000000004 and the largest double (DESIGN.md §4.1).
CANARY: dict = _canary()


def positions(g: dict) -> list[tuple[float, float]]:
    """Every position of a typed geometry, in order, as the doubles float() gives."""
    out: list[tuple[float, float]] = []

    def walk(x: Any, depth: int) -> None:
        if depth == 0:
            if x:
                out.append((float(x[0]), float(x[1])))
            return
        for y in x:
            walk(y, depth - 1)

    t = g["type"]
    if t == "GeometryCollection":
        for e in g["geometries"]:
            out += positions(e)
        return out
    depth = {"Point": 0, "LineString": 1, "MultiPoint": 1, "Polygon": 2, "MultiLineString": 2,
             "MultiPolygon": 3}[t]
    walk(g["coordinates"], depth)
    return out


# ============================================================================ exact answers


def _rings(g: dict) -> list[list]:
    """Every ring of every polygonal element, grouped by polygon: [[shell, hole, ...], ...]."""
    t = g["type"]
    if t == "Polygon":
        return [g["coordinates"]] if g["coordinates"] else []
    if t == "MultiPolygon":
        return [p for p in g["coordinates"] if p]
    if t == "GeometryCollection":
        return [p for e in g["geometries"] for p in _rings(e)]
    return []


def _shoelace2(ring: list) -> Fraction:
    pts = [(Fraction(float(x)), Fraction(float(y))) for x, y, *_ in ring]
    return sum((p[0] * q[1] - q[0] * p[1] for p, q in itertools.pairwise(pts)), Fraction(0))


def even_odd_area(g: dict) -> Fraction:
    """Exact area of the even-odd point set of every ring of the output (the vertical slab
    decomposition of tests/reference/oracle.py, over the output's own edges)."""
    oracle = _oracle()
    edges = []
    for poly in _rings(g):
        for ring in poly:
            pts = [(oracle.num(x), oracle.num(y)) for x, y, *_ in ring]
            edges += [(p, q) for p, q in itertools.pairwise(pts) if p != q]
    _, inside, _ = oracle.overlay_areas(edges, [])
    return Fraction(int(inside.numerator), int(inside.denominator))


def area(g: dict | None) -> Fraction:
    """Exact area of a typed geometry with double ordinates, measured as DESIGN.md §4.3
    measures library output: the even-odd point set of all its rings (lines and points count
    0). Fast path: when the structural area (each shell minus its holes) equals the absolute
    orientation-signed sum over all rings, that is the even-odd area; otherwise (rings nested
    other than the structure says, as Clipper2's PolyTree does with a hole inscribed in its
    shell, or orientations mixed, as GEOS's union of disjoint inputs does) the even-odd area
    is computed exactly."""
    if g is None:
        return Fraction(0)
    polys = _rings(g)
    structural = sum((abs(_shoelace2(p[0])) - sum((abs(_shoelace2(h)) for h in p[1:]), Fraction(0))
                      for p in polys), Fraction(0)) / 2
    signed = abs(sum((_shoelace2(r) for p in polys for r in p), Fraction(0))) / 2
    if structural == signed:
        return structural
    return even_odd_area(g)


def legacy(g: dict | list) -> list:
    """A Polygon / MultiPolygon as FORMAT-v1 multipolygon coordinates (lists pass through)."""
    if isinstance(g, list):
        return g
    if g["type"] == "Polygon":
        return [g["coordinates"]] if g["coordinates"] else []
    if g["type"] == "MultiPolygon":
        return [p for p in g["coordinates"] if p]
    raise ValueError(f"not polygonal: {g['type']}")


@dataclass
class ExactPair:
    backend: str                       # "engine" or "oracle"
    valid_a: bool
    valid_b: bool
    relate: str | None                 # DE-9IM (engine only)
    predicates: dict[str, bool] | None  # None when an input is invalid
    areas: dict[str, Fraction] | None  # overlay op -> exact area (regularized areal)
    area_a: Fraction | None = None
    area_b: Fraction | None = None


def _field(obj: Any, *names: str) -> Any:
    for n in names:
        if isinstance(obj, dict) and n in obj:
            return obj[n]
        if hasattr(obj, n):
            return getattr(obj, n)
    return None


def _as_dict(v: Any) -> dict | None:
    if v is None:
        return None
    if isinstance(v, dict):
        return dict(v)
    if dataclasses.is_dataclass(v):
        return dataclasses.asdict(v)
    if hasattr(v, "_asdict"):
        return dict(v._asdict())
    return dict(vars(v))


def _as_fraction(v: Any) -> Fraction:
    if isinstance(v, str):
        return Fraction(v)
    if isinstance(v, float):
        return Fraction(v)
    return Fraction(int(v.numerator), int(v.denominator))


def _engine() -> tuple[Any, Any] | None:
    """The engine's relate and overlay modules, or None while they do not exist yet."""
    try:
        relate_mod = importlib.import_module("geotruth.relate")
        overlay_mod = importlib.import_module("geotruth.overlay")
    except ImportError:
        return None
    if not (hasattr(relate_mod, "relate") and hasattr(overlay_mod, "overlay")):
        return None
    return relate_mod, overlay_mod


def exact_backend() -> str:
    """The backend :func:`exact_pair` uses: "engine" once geotruth.relate and
    geotruth.overlay exist (DESIGN.md §2), else "oracle" (tests/reference/oracle.py)."""
    want = os.environ.get("GEOTRUTH_EXACT_BACKEND", "auto")
    if want not in ("auto", "engine", "oracle"):
        raise ValueError(f"GEOTRUTH_EXACT_BACKEND={want!r}: use auto, engine or oracle")
    if want == "oracle":
        return "oracle"
    if _engine() is not None:
        return "engine"
    if want == "engine":
        raise RuntimeError("GEOTRUTH_EXACT_BACKEND=engine, but geotruth.relate / geotruth.overlay "
                           "are not importable")
    return "oracle"


def _oracle() -> Any:
    ref = str(REPO / "tests" / "reference")
    if ref not in sys.path:
        sys.path.insert(0, ref)
    return importlib.import_module("oracle")


def _oracle_pair(a: Any, b: Any) -> ExactPair:
    oracle = _oracle()
    r = oracle.evaluate({"id": "pair", "a": legacy(a), "b": legacy(b)})
    if not (r["valid_a"] and r["valid_b"]):
        return ExactPair("oracle", r["valid_a"], r["valid_b"], None, None, None)
    ex = r["exact"]
    i, da, db = Fraction(ex["inter"]), Fraction(ex["diff_ab"]), Fraction(ex["diff_ba"])
    preds = {p: r[p] for p in V1_PREDICATES}
    preds["crosses"] = False  # areal/areal (DESIGN.md §1)
    areas = {"intersection": i, "union": i + da + db, "difference": da, "symdifference": da + db}
    return ExactPair("oracle", True, True, None, preds, areas, i + da, i + db)


def _engine_pair(a: Any, b: Any) -> ExactPair:
    from geotruth.io import geometry_from_json

    relate_mod, overlay_mod = _engine()
    ga = geometry_from_json(a if isinstance(a, dict) else _typed(a))
    gb = geometry_from_json(b if isinstance(b, dict) else _typed(b))
    r = relate_mod.relate(ga, gb)
    status = _field(r, "status") or "ok"
    if status != "ok":
        raise RuntimeError(f"engine abstained: {status}")
    matrix = r if isinstance(r, str) else _field(r, "matrix", "relate")
    preds = None if isinstance(r, str) else _field(r, "predicates")
    va = _field(r, "valid_a")
    vb = _field(r, "valid_b")
    areas = {}
    for op in OPS:
        o = overlay_mod.overlay(ga, gb, op, "areal")
        areas[op] = _as_fraction(_field(o, "area"))
    return ExactPair("engine", True if va is None else bool(va), True if vb is None else bool(vb),
                     matrix, _as_dict(preds), areas)


def _typed(mp: list) -> dict:
    return ({"type": "Polygon", "coordinates": mp[0]} if len(mp) == 1
            else {"type": "MultiPolygon", "coordinates": mp})


def exact_pair(a: Any, b: Any) -> ExactPair:
    """The exact answer for a polygon/polygon pair (typed geometries or FORMAT-v1 arrays).

    In ``auto`` mode an engine whose API does not match DESIGN.md §2 yet (it is being
    written) is reported with a warning and the oracle answers instead; with
    ``GEOTRUTH_EXACT_BACKEND=engine`` the error propagates."""
    if exact_backend() == "engine":
        try:
            return _engine_pair(a, b)
        except Exception as exc:  # the engine's API is not frozen yet
            if os.environ.get("GEOTRUTH_EXACT_BACKEND") == "engine":
                raise
            warnings.warn(f"geotruth engine did not answer ({exc!r}); using the oracle",
                          stacklevel=2)
    return _oracle_pair(a, b)


# ============================================================================ tests of the above


@pytest.mark.unit
def test_manifests_of_the_native_adapters_are_v2(repo):
    """Every native manifest validates against schemas/adapter.v2, declares contract v2 and
    lists each v1 field and each v2 field path exactly once."""
    from geotruth import schemas

    pytest.importorskip("jsonschema")
    for d in NATIVE_DIRS:
        with open(repo / "adapters" / d / "adapter.toml", "rb") as fh:
            m = tomllib.load(fh)
        schemas.validator("adapter").validate(m)
        assert m["adapter"]["contract"] == "v2", d
        for t in m["target"]:
            f = t["fields"]
            listed = [*f["supported"], *f.get("derived", {}), *f.get("unsupported", [])]
            assert len(listed) == len(set(listed)), (t["id"], "a field is listed twice")
            want = set(V1_FIELDS) | set(V2_PATHS)
            assert set(listed) == want, (t["id"], want ^ set(listed))
            for w in shlex.split(t["run"]) + shlex.split(t["version_command"]):
                if "/" in w:
                    assert (repo / w).is_file(), (t["id"], w)


@pytest.mark.unit
def test_native_target_ids():
    assert TARGET_IDS == ["geos-main", "geos-release", "boost-1.83", "boost-develop",
                          "boost-release", "clipper2", "cgal"]
    assert len({t.lib for t in TARGETS}) == len(TARGETS)


@pytest.mark.unit
def test_canary_case_has_the_required_values():
    vals = [v for p in positions(CANARY["a"]) + positions(CANARY["b"]) for v in p]
    assert 2.0**53 in vals            # 9007199254740993 read as a double
    assert 5e-324 in vals             # the smallest subnormal
    assert any(v == 0 and str(v) == "-0.0" for v in vals)
    assert 0.30000000000000004 in vals
    assert 1.7976931348623157e308 in vals
    raw = (REPO / "schemas" / "examples" / "case.v2.valid.json").read_text()
    assert "9007199254740993" in raw  # written as an integer literal


@pytest.mark.unit
def test_area_of_typed_geometries():
    sq = [[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]
    hole = [[0.5, 0.5], [0.5, 1], [1, 1], [1, 0.5], [0.5, 0.5]]
    assert area({"type": "Polygon", "coordinates": [sq, hole]}) == Fraction(15, 4)
    assert area({"type": "Polygon", "coordinates": [sq[::-1], hole[::-1]]}) == Fraction(15, 4)
    assert area({"type": "Polygon", "coordinates": []}) == 0
    tri = [[3, 0], [4, 0], [4, 1], [3, 0]]
    assert area({"type": "MultiPolygon", "coordinates": [[sq], [tri[::-1]]]}) == Fraction(9, 2)
    # even-odd, whatever the structure says: a copy cancels, a mis-nested hole still subtracts
    assert area({"type": "MultiPolygon", "coordinates": [[sq], [sq[::-1]]]}) == 0
    inscribed = [[1, 0], [2, 1], [1, 2], [0, 1], [1, 0]]  # touches the shell at 4 points
    assert area({"type": "MultiPolygon", "coordinates": [[sq], [inscribed[::-1]]]}) == 2
    assert even_odd_area({"type": "Polygon", "coordinates": [sq, hole]}) == Fraction(15, 4)
    gc = {"type": "GeometryCollection", "geometries": [
        {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
        {"type": "Polygon", "coordinates": [sq]}]}
    assert area(gc) == 4


@pytest.mark.unit
def test_exact_pair_shim():
    """The shim answers a polygon/polygon pair with whichever backend is available."""
    a = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
    b = {"type": "Polygon", "coordinates": [[[1, 1], [3, 1], [3, 3], [1, 3], [1, 1]]]}
    e = exact_pair(a, b)
    assert e.backend in ("engine", "oracle")
    assert e.valid_a and e.valid_b
    assert e.areas == {"intersection": 1, "union": 7, "difference": 3, "symdifference": 6}
    assert e.predicates["overlaps"] and not e.predicates["touches"]
    assert not e.predicates["crosses"]
    # legacy arrays give the same answer
    assert exact_pair(legacy(a), legacy(b)).areas == e.areas
    if e.backend == "engine":
        assert e.relate == "212101212"


@pytest.mark.unit
def test_exact_pair_oracle_fallback_is_forced(monkeypatch):
    monkeypatch.setenv("GEOTRUTH_EXACT_BACKEND", "oracle")
    a = [[[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]]
    b = [[[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]]]
    e = exact_pair(a, b)
    assert e.backend == "oracle"
    assert e.predicates["touches"] and e.areas["intersection"] == 0
    bow = [[[[0, 0], [1, 1], [1, 0], [0, 1], [0, 0]]]]  # invalid: self-crossing ring
    e = exact_pair(bow, a)
    assert e.valid_a is False and e.predicates is None and e.areas is None


@pytest.mark.unit
@pytest.mark.parametrize("t", TARGETS, ids=lambda t: t.id)
def test_run_wrappers_look_in_geotruth_build_dir(t, tmp_path):
    """With an empty $GEOTRUTH_BUILD_DIR every native run wrapper, the new release and CGAL
    wrappers included, fails with exit 2 and names the missing binary and build.sh."""
    env = {k: v for k, v in os.environ.items() if k != "BUILD_ROOT"}
    env["GEOTRUTH_BUILD_DIR"] = str(tmp_path)
    out = subprocess.run(t.command(str(REPO / "corpus" / "cases" / "seed.jsonl")), env=env,
                         capture_output=True, text=True, check=False)
    assert out.returncode == 2, out.stderr
    assert "build.sh" in out.stderr and str(tmp_path) in out.stderr


@pytest.mark.unit
def test_exact_pair_uses_the_engine_api_when_it_exists(monkeypatch):
    """Stand-in modules with the DESIGN.md §2 API (relate(a, b) -> matrix / predicates /
    status; overlay(a, b, op, variant) -> area) switch the shim to the engine."""
    import types

    calls = []

    @dataclasses.dataclass
    class Preds:
        intersects: bool = True
        touches: bool = False

    def relate(a, b):
        calls.append(("relate", type(a).__name__, type(b).__name__))
        return types.SimpleNamespace(matrix="212101212", predicates=Preds(), status="ok")

    def overlay(a, b, op, variant):
        calls.append((op, variant))
        return {"area": {"intersection": "1", "union": "7", "difference": "3",
                         "symdifference": "6"}[op]}

    monkeypatch.setitem(sys.modules, "geotruth.relate", types.SimpleNamespace(relate=relate))
    monkeypatch.setitem(sys.modules, "geotruth.overlay", types.SimpleNamespace(overlay=overlay))
    monkeypatch.delenv("GEOTRUTH_EXACT_BACKEND", raising=False)
    assert exact_backend() == "engine"
    a = {"type": "Polygon", "coordinates": [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]]]}
    e = exact_pair(a, a)
    assert e.backend == "engine" and e.relate == "212101212"
    assert e.predicates == {"intersects": True, "touches": False}
    assert e.areas == {"intersection": 1, "union": 7, "difference": 3, "symdifference": 6}
    assert calls[0][0] == "relate" and ("union", "areal") in calls
    # an engine that cannot answer falls back to the oracle in auto mode, not with "engine"
    monkeypatch.setitem(sys.modules, "geotruth.overlay",
                        types.SimpleNamespace(overlay=lambda *a: 1 / 0))
    with pytest.warns(UserWarning, match="using the oracle"):
        assert exact_pair(a, a).backend == "oracle"
    monkeypatch.setenv("GEOTRUTH_EXACT_BACKEND", "engine")
    with pytest.raises(ZeroDivisionError):
        exact_pair(a, a)
