"""Delta-debugging minimiser for library disagreements (DESIGN §5.5).

Given a case on which a library's answer for one field differs from the exact answer
(or on which the library raises), :func:`minimize` searches for a smaller case with the
same failure. It reduces, in passes that repeat until nothing changes:

1. **parts**: elements of GeometryCollections and multi-geometries (ddmin over parts);
2. **holes** of polygons (ddmin);
3. **vertices** of rings and lines (ddmin over all vertices at once; a ring keeps at
   least 3 distinct vertices, a line 2);
4. **decimals**: coordinates rounded to fewer significant digits, all at once or one
   distinct value at a time (a value is replaced everywhere it occurs, so shared vertices
   stay shared).

After every step each candidate is re-checked: both operands must stay valid (exact
validity: ``geotruth.validity`` or ``tests/reference/validity.py``), the exact answer is
recomputed (:mod:`geotruth.export.answers`), and the library must still disagree with it.
Every round collects all candidates of one step and runs the library **once** on all of
them, through the adapter's own run wrapper (the ``run`` command of its manifest
``adapters/<dir>/adapter.toml``): v2 adapters get typed case lines, v1 adapters FORMAT-v1
lines (polygons only).

Failure kinds (``kind``, detected from the original case unless given):

``value``
    a predicate, the relate matrix or a validity flag differs from the exact answer
    (convention-dependent predicates never count);
``area``
    an overlay area (v1 ``area_*`` field, or the area of a v2 ``overlay.<op>`` output)
    differs from the exact area by more than ``tol`` times the larger operand area
    (default 1e-6, as ``harness/compare.py``);
``error``
    the library reports an error for the field (the same message, digits ignored).
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import shlex
import struct
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from geotruth.export.answers import PREDICATES, ExactAnswer, exact_answer, geometry_area
from geotruth.geom import Geometry
from geotruth.io import geometry_from_json

__all__ = [
    "AdapterRunner",
    "MinimizeError",
    "MinimizeResult",
    "Target",
    "case_size",
    "find_target",
    "load_case",
    "minimize",
]

REPO = Path(__file__).resolve().parents[2]
V1_AREAS = {
    "area_inter": "intersection",
    "area_union": "union",
    "area_diff": "difference",
    "area_symdiff": "symdifference",
}
V2_AREAS = {v: k for k, v in V1_AREAS.items()}


class MinimizeError(RuntimeError):
    """The minimiser cannot start (unknown library, the case does not fail, ...)."""


# ============================================================================ adapters


@dataclass
class Target:
    """One library build from an adapter manifest."""

    id: str
    lib: str
    run: str
    contract: str
    manifest: Path


def _toml_load(path: Path) -> dict:
    try:
        import tomllib
    except ImportError:  # pragma: no cover - Python 3.10
        import tomli as tomllib
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def find_target(lib_id: str, root: Path = REPO) -> Target:
    """The ``[[target]]`` with ``id == lib_id`` in ``adapters/*/adapter.toml``."""
    known = []
    for path in sorted((root / "adapters").glob("*/adapter.toml")):
        m = _toml_load(path)
        for t in m.get("target", []):
            known.append(t["id"])
            if t["id"] == lib_id:
                contract = m.get("adapter", {}).get("contract", "v1")
                return Target(t["id"], t.get("lib", t["id"]), t["run"], contract, path)
    raise MinimizeError(f"unknown library {lib_id!r}; known: {', '.join(sorted(known))}")


class AdapterRunner:
    """Runs a library's adapter on a batch of cases: one process per :meth:`run`."""

    def __init__(
        self,
        target: Target,
        *,
        extra_args: Iterable[str] = (),
        timeout: float = 600.0,
        op_timeout: float | None = None,
        root: Path = REPO,
        env: dict[str, str] | None = None,
    ) -> None:
        self.target = target
        self.extra_args = list(extra_args)
        self.timeout = timeout
        self.root = root
        self.calls = 0
        self.cases_run = 0
        self.seconds = 0.0
        self.env = dict(os.environ)
        self.env.setdefault("GEOTRUTH_BUILD_DIR", str(Path.home() / ".cache" / "geotruth"))
        if op_timeout is not None:
            for var in ("JS_ADAPTER_TIMEOUT", "GEOS_ADAPTER_TIMEOUT", "BG_ADAPTER_TIMEOUT"):
                self.env[var] = str(op_timeout)
        if env:
            self.env.update(env)

    @property
    def v2(self) -> bool:
        return self.target.contract == "v2"

    def line(self, cid: str, a: dict, b: dict) -> dict:
        if self.v2:
            return {"id": cid, "family": "minimise", "tags": {}, "provenance": {}, "a": a, "b": b}
        return {"id": cid, "family": "minimise", "a": to_v1(a), "b": to_v1(b)}

    def run(self, lines: list[dict]) -> dict[str, dict]:
        """Results by case id (a case the adapter did not answer is missing)."""
        if not lines:
            return {}
        with tempfile.TemporaryDirectory(prefix="geotruth-min-") as tmp:
            path = Path(tmp) / "cases.jsonl"
            with open(path, "w", encoding="utf-8") as fh:
                for ln in lines:
                    fh.write(json.dumps(ln) + "\n")
            cmd = [*shlex.split(self.target.run), *self.extra_args, str(path)]
            t0 = time.perf_counter()
            proc = subprocess.run(
                cmd,
                cwd=self.root,
                env=self.env,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
            self.seconds += time.perf_counter() - t0
        self.calls += 1
        self.cases_run += len(lines)
        out: dict[str, dict] = {}
        for text in proc.stdout.splitlines():
            if text.strip():
                try:
                    rec = json.loads(text)
                except ValueError:
                    continue
                out[str(rec.get("id"))] = rec
        if not out and proc.returncode:
            raise MinimizeError(
                f"adapter {self.target.id} failed ({proc.returncode}): {proc.stderr[-800:]}"
            )
        return out


def to_v1(g: dict) -> list:
    """Typed Polygon/MultiPolygon JSON as FORMAT-v1 MultiPolygon coordinates."""
    if g["type"] == "Polygon":
        return [g["coordinates"]]
    if g["type"] == "MultiPolygon":
        return g["coordinates"]
    raise MinimizeError(f"a v1 adapter takes polygons only, not {g['type']}")


def to_typed(g: Any) -> dict:
    """A case operand (typed JSON or a FORMAT-v1 coordinate list) as typed JSON."""
    if isinstance(g, list):
        return (
            {"type": "Polygon", "coordinates": g[0]}
            if len(g) == 1
            else {"type": "MultiPolygon", "coordinates": g}
        )
    return g


# ============================================================================ fields


def field_for(fieldname: str, v2: bool) -> str:
    """A field path in the adapter's contract (v1 names and v2 paths both accepted)."""
    f = fieldname
    if v2:
        if f in PREDICATES:
            return f"predicates.{f}"
        if f in V1_AREAS:
            return f"overlay.{V1_AREAS[f]}"
        return f
    if f.startswith("predicates."):
        return f.split(".", 1)[1]
    if f.startswith("overlay."):
        return V2_AREAS.get(f.split(".", 1)[1], f)
    return f


def _get(res: dict, path: str) -> Any:
    if path.startswith("predicates."):
        return (res.get("predicates") or {}).get(path.split(".", 1)[1])
    if path.startswith("overlay."):
        return (res.get("overlay") or {}).get(path.split(".", 1)[1])
    return res.get(path)


_NUM = re.compile(r"-?[0-9][0-9.eE+-]*")


def error_signature(err: Any) -> str:
    """An error message with numbers masked (so the same failure at other coordinates
    compares equal); dict errors ({kind, message}) keep their kind."""
    if isinstance(err, dict):
        kind = err.get("kind", "")
        return f"{kind}: " + _NUM.sub("#", str(err.get("message", "")))[:80]
    if isinstance(err, list):
        return "list"
    return _NUM.sub("#", str(err))[:80]


def _error_of(res: dict, path: str) -> Any:
    errs = res.get("errors") or {}
    if path in errs:
        return errs[path]
    if path.startswith("overlay.") or path in V1_AREAS:
        # adapters list timeouts under "timeout" with the field names
        t = errs.get("timeout")
        if isinstance(t, list) and path in t:
            return "timeout"
    return None


@dataclass
class Check:
    """Decides whether a library result still shows the failure."""

    path: str
    kind: str
    tol: float = 1e-6
    signature: str | None = None

    def exact_needed(self) -> bool:
        return self.kind in ("value", "area")

    def failing(self, res: dict | None, exact: ExactAnswer | None) -> bool:
        if res is None:
            return False
        if self.kind == "error":
            err = _error_of(res, self.path)
            return err is not None and (
                self.signature is None or error_signature(err) == self.signature
            )
        got = _get(res, self.path)
        if got is None or got == "unsupported" or exact is None:
            return False
        if self.kind == "value":
            want = exact.field(self.path)
            name = self.path.split(".", 1)[-1]
            if f"predicates.{name}" in exact.conventions:
                return False
            return want is not None and got != want
        want = exact.field(self.path)
        if want is None or exact.areas is None:
            return False
        if isinstance(got, dict):
            try:
                got_area = geometry_area(geometry_from_json(got))
            except Exception:
                return False
        elif isinstance(got, (int, float)) and math.isfinite(got):
            got_area = Fraction(got)
        else:
            return False
        scale = max(exact.areas["a"], exact.areas["b"])
        if scale == 0:
            return got_area != want
        return abs(got_area - want) > Fraction(self.tol) * scale


# ============================================================================ geometry


def _children_key(g: dict) -> str | None:
    t = g["type"]
    if t == "GeometryCollection":
        return "geometries"
    if t in ("MultiPolygon", "MultiLineString", "MultiPoint"):
        return "coordinates"
    return None


def part_paths(g: dict, prefix: tuple = ()) -> list[tuple]:
    """Paths of the removable parts of a geometry (leaves of collections and multis)."""
    key = _children_key(g)
    if key is None:
        return []
    out: list[tuple] = []
    for i, child in enumerate(g[key]):
        if g["type"] == "GeometryCollection" and _children_key(child) is not None:
            sub = part_paths(child, (*prefix, i))
            out.extend(sub if sub else [(*prefix, i)])
        else:
            out.append((*prefix, i))
    return out


def remove_parts(g: dict, paths: set[tuple]) -> dict:
    """The geometry without the parts at ``paths`` (empty nested collections dropped)."""

    def rec(node: dict, prefix: tuple) -> dict:
        key = _children_key(node)
        if key is None:
            return node
        kept = []
        for i, child in enumerate(node[key]):
            p = (*prefix, i)
            if p in paths:
                continue
            if node["type"] == "GeometryCollection" and _children_key(child) is not None:
                child = rec(child, p)
                if not child[_children_key(child)] and part_paths(node[key][i], p):
                    continue
            kept.append(child)
        out = dict(node)
        out[key] = kept
        return out

    return rec(g, ())


def _polygons(g: dict, prefix: tuple = ()) -> list[tuple[tuple, list]]:
    """(path, rings) of every polygon (path: indices into collections/multis)."""
    t = g["type"]
    if t == "Polygon":
        return [(prefix, g["coordinates"])]
    if t == "MultiPolygon":
        return [((*prefix, i), p) for i, p in enumerate(g["coordinates"])]
    if t == "GeometryCollection":
        out = []
        for i, c in enumerate(g["geometries"]):
            out.extend(_polygons(c, (*prefix, i)))
        return out
    return []


def _sequences(g: dict) -> list[tuple[str, list]]:
    """Every ring ("ring") and line ("line") coordinate list, as live references."""
    t = g["type"]
    if t == "Polygon":
        return [("ring", r) for r in g["coordinates"] if r]
    if t == "MultiPolygon":
        return [("ring", r) for p in g["coordinates"] for r in p if r]
    if t == "LineString":
        return [("line", g["coordinates"])] if g["coordinates"] else []
    if t == "MultiLineString":
        return [("line", ln) for ln in g["coordinates"] if ln]
    if t == "GeometryCollection":
        return [s for c in g["geometries"] for s in _sequences(c)]
    return []


def _positions(g: dict) -> list[list]:
    """Every position (live references)."""
    t = g["type"]
    if t == "GeometryCollection":
        return [p for c in g["geometries"] for p in _positions(c)]
    c = g["coordinates"]
    if t == "Point":
        return [c] if c else []
    if t in ("LineString", "MultiPoint"):
        return [p for p in c if p]
    if t in ("Polygon", "MultiLineString"):
        return [p for r in c for p in r]
    if t == "MultiPolygon":
        return [p for poly in c for r in poly for p in r]
    return []


def _digits(v: float) -> int:
    s = repr(float(v))
    s = s[:-2] if s.endswith(".0") else s
    return len(s.lstrip("-"))


def _nodes(g: dict) -> int:
    """Number of geometry objects in the tree (collections, multis and their parts)."""
    t = g["type"]
    if t == "GeometryCollection":
        return 1 + sum(_nodes(c) for c in g["geometries"])
    if t.startswith("Multi"):
        return 1 + len(g["coordinates"])
    return 1


def case_size(a: dict, b: dict) -> tuple[int, int, int]:
    """(number of coordinates, total characters of their shortest round-trip forms,
    number of geometry objects): smaller is simpler, compared in that order."""
    pos = _positions(a) + _positions(b)
    return len(pos), sum(_digits(p[0]) + _digits(p[1]) for p in pos), _nodes(a) + _nodes(b)


def _structurally_ok(g: dict) -> bool:
    for kind, seq in _sequences(g):
        distinct = {(p[0], p[1]) for p in seq}
        if kind == "ring" and (len(seq) < 4 or len(distinct) < 3):
            return False
        if kind == "line" and len(distinct) < 2:
            return False
    return True


# ============================================================================ passes


_SINGLE = {"MultiPolygon": "Polygon", "MultiLineString": "LineString", "MultiPoint": "Point"}


def _unwrap(g: dict) -> list[dict]:
    """Simpler equivalents of g: a one-element collection or multi as its element, and
    g with one nested one-element collection unwrapped."""
    out = []
    t = g["type"]
    if t == "GeometryCollection":
        if len(g["geometries"]) == 1:
            out.append(g["geometries"][0])
        for i, c in enumerate(g["geometries"]):
            for u in _unwrap(c):
                gs = list(g["geometries"])
                gs[i] = u
                out.append({"type": t, "geometries": gs})
    elif t in _SINGLE and len(g["coordinates"]) == 1 and g["coordinates"][0] != []:
        out.append({"type": _SINGLE[t], "coordinates": g["coordinates"][0]})
    return out


def _cands_structure(state: tuple[dict, dict]) -> list:
    return [(u, state[1]) for u in _unwrap(state[0])] + [(state[0], u) for u in _unwrap(state[1])]


def _chunks(items: list, n: int) -> list[list]:
    k, r = divmod(len(items), n)
    out, i = [], 0
    for j in range(n):
        step = k + (1 if j < r else 0)
        out.append(items[i : i + step])
        i += step
    return [c for c in out if c]


def _cands_parts(state: tuple[dict, dict], n: int) -> tuple[list, int]:
    units = [(0, p) for p in part_paths(state[0])] + [(1, p) for p in part_paths(state[1])]
    cands = []
    for chunk in _chunks(units, min(n, len(units))) if units else []:
        drop = {0: set(), 1: set()}
        for op, p in chunk:
            drop[op].add(p)
        cand = (remove_parts(state[0], drop[0]), remove_parts(state[1], drop[1]))
        cands.append(cand)
    return cands, len(units)


def _cands_holes(state: tuple[dict, dict], n: int) -> tuple[list, int]:
    units = []
    for op in (0, 1):
        for pi, (_, rings) in enumerate(_polygons(state[op])):
            units.extend((op, pi, k) for k in range(1, len(rings)))
    cands = []
    for chunk in _chunks(units, min(n, len(units))) if units else []:
        cand = copy.deepcopy(state)
        drop = set(chunk)
        for op in (0, 1):
            for pi, (_, rings) in enumerate(_polygons(cand[op])):
                keep = [r for k, r in enumerate(rings) if (op, pi, k) not in drop]
                rings[:] = keep
        cands.append(cand)
    return cands, len(units)


def _cands_vertices(state: tuple[dict, dict], n: int) -> tuple[list, int]:
    units = []
    for op in (0, 1):
        for si, (kind, seq) in enumerate(_sequences(state[op])):
            m = len(seq) - 1 if kind == "ring" else len(seq)
            units.extend((op, si, k) for k in range(m))
    cands = []
    for chunk in _chunks(units, min(n, len(units))) if units else []:
        cand = copy.deepcopy(state)
        drop = set(chunk)
        for op in (0, 1):
            for si, (kind, seq) in enumerate(_sequences(cand[op])):
                if kind == "ring":
                    body = [p for k, p in enumerate(seq[:-1]) if (op, si, k) not in drop]
                    seq[:] = [*body, list(body[0])] if body else []
                else:
                    seq[:] = [p for k, p in enumerate(seq) if (op, si, k) not in drop]
        cands.append(cand)
    return cands, len(units)


def _round_sig(v: float, d: int) -> float:
    if v == 0 or not math.isfinite(v):
        return v
    return float(f"{v:.{d - 1}e}")


def _replace_values(state: tuple[dict, dict], fn: Callable[[float], float]) -> tuple:
    cand = copy.deepcopy(state)
    for g in cand:
        for p in _positions(g):
            p[0], p[1] = fn(p[0]), fn(p[1])
    return cand


#: Values whose magnitudes are within this many ulps form one cluster (rounded together,
#: keeping their ulp offsets, so an ulp-level near-degeneracy survives the rounding).
CLUSTER_ULPS = 1 << 12


def _ord(x: float) -> int:
    """The position of a non-negative double in the ordered sequence of doubles."""
    return struct.unpack("<q", struct.pack("<d", x))[0]


def _from_ord(k: int) -> float:
    return struct.unpack("<d", struct.pack("<q", k))[0]


def _clusters(values: Iterable[float]) -> list[list[float]]:
    """Distinct finite non-zero magnitudes grouped by ulp distance (sorted)."""
    mags = sorted({abs(v) for v in values if v and math.isfinite(v)})
    out: list[list[float]] = []
    for m in mags:
        if out and _ord(m) - _ord(out[-1][-1]) <= CLUSTER_ULPS:
            out[-1].append(m)
        else:
            out.append([m])
    return out


def _cluster_map(cluster: list[float], d: int) -> dict[float, float] | None:
    """Magnitudes of a cluster rounded to d significant digits (the shortest member is
    the anchor), each keeping its ulp offset from the anchor; None when nothing shrinks
    or the offsets do not fit."""
    anchor = min(cluster, key=lambda m: (_digits(m), m))
    r = _round_sig(anchor, d)
    if r == anchor or r <= 0 or not math.isfinite(r):
        return None
    base = _ord(r) - _ord(anchor)
    out = {}
    for m in cluster:
        k = _ord(m) + base
        if k <= 0 or k >= _ord(math.inf):
            return None
        out[m] = _from_ord(k)
    if sum(_digits(v) for v in out.values()) >= sum(_digits(m) for m in cluster):
        return None
    return out


def _apply_magnitudes(state: tuple[dict, dict], mapping: dict[float, float]) -> tuple:
    def fn(v: float) -> float:
        w = mapping.get(abs(v))
        return v if w is None else math.copysign(w, v)

    return _replace_values(state, fn)


def _cands_decimals(state: tuple[dict, dict]) -> list:
    """Rounding candidates: every cluster at once to d digits (d = 1..16), then one
    cluster at a time to each shorter length."""
    values = [v for g in state for p in _positions(g) for v in (p[0], p[1])]
    clusters = _clusters(values)
    cands = []
    for d in range(1, 17):
        mapping: dict[float, float] = {}
        for c in clusters:
            mapping.update(_cluster_map(c, d) or {})
        if mapping:
            cands.append(_apply_magnitudes(state, mapping))
    for c in clusters:
        nd = max(_digits(m) for m in c)
        for d in range(1, nd):
            mapping = _cluster_map(c, d)
            if mapping:
                cands.append(_apply_magnitudes(state, mapping))
    # one magnitude at a time, plainly rounded (breaks a cluster, which sometimes helps)
    for c in clusters:
        if len(c) == 1:
            continue
        for m in c:
            for d in range(1, _digits(m)):
                w = _round_sig(m, d)
                if w != m and w > 0:
                    cands.append(_apply_magnitudes(state, {m: w}))
    return cands


# ============================================================================ driver


@dataclass
class MinimizeResult:
    a: dict
    b: dict
    before: tuple[int, int, int]
    after: tuple[int, int, int]
    rounds: int
    adapter_calls: int
    candidates: int
    seconds: float
    kind: str
    field: str
    log: list[str] = field(default_factory=list)
    exact: ExactAnswer | None = None
    result: dict | None = None


class _Evaluator:
    def __init__(self, runner: AdapterRunner, check: Check, *, need_valid: bool) -> None:
        self.runner = runner
        self.check = check
        self.need_valid = need_valid
        self.cache: dict[str, tuple[bool, ExactAnswer | None, dict | None]] = {}
        self.candidates = 0

    @staticmethod
    def key(state: tuple) -> str:
        return json.dumps(state, sort_keys=True)

    def exact(self, state: tuple) -> ExactAnswer | None:
        ga: Geometry = geometry_from_json(state[0])
        gb: Geometry = geometry_from_json(state[1])
        is_area = self.check.kind == "area"
        ans = exact_answer(
            ga,
            gb,
            relate=self.check.kind == "value" and not self.check.path.startswith("valid"),
            areas=is_area,
        )
        if self.need_valid and not ans.valid:
            return None
        return ans

    def best(self, cands: list[tuple], current: tuple) -> tuple | None:
        """The smallest failing candidate (one adapter call for the new ones)."""
        cur_size = case_size(*current)
        todo: list[tuple[str, tuple, ExactAnswer | None]] = []
        seen = {self.key(current)}
        for c in cands:
            k = self.key(c)
            if k in seen:
                continue
            seen.add(k)
            if case_size(*c) >= cur_size:
                continue
            if k in self.cache:
                continue
            if not (_structurally_ok(c[0]) and _structurally_ok(c[1])):
                self.cache[k] = (False, None, None)
                continue
            if not self.runner.v2 and not all(g["type"] in ("Polygon", "MultiPolygon") for g in c):
                self.cache[k] = (False, None, None)
                continue
            try:
                ans = self.exact(c)
            except Exception:
                ans = None
            if ans is None or (self.check.exact_needed() and ans.field(self.check.path) is None):
                self.cache[k] = (False, None, None)
                continue
            todo.append((k, c, ans))
        if todo:
            lines = [self.runner.line(f"c{i}", c[0], c[1]) for i, (_, c, _) in enumerate(todo)]
            results = self.runner.run(lines)
            self.candidates += len(todo)
            for i, (k, _c, ans) in enumerate(todo):
                res = results.get(f"c{i}")
                self.cache[k] = (self.check.failing(res, ans), ans, res)
        failing = [
            c
            for c in cands
            if case_size(*c) < cur_size and self.cache.get(self.key(c), (False,))[0]
        ]
        if not failing:
            return None
        return min(failing, key=lambda c: case_size(*c))


def load_case(spec: str, case_id: str | None = None) -> dict:
    """A case from ``FILE``, ``FILE#ID`` (JSON lines or one JSON object), or inline JSON."""
    text_spec = spec.strip()
    if text_spec.startswith("{"):
        return json.loads(text_spec)
    path, _, frag = spec.partition("#")
    want = case_id or frag or None
    text = Path(path).read_text(encoding="utf-8")
    if text.lstrip().startswith("[") or (want is None and text.count("\n") <= 1):
        obj = json.loads(text)
        recs = obj if isinstance(obj, list) else [obj]
    else:
        recs = [json.loads(ln) for ln in text.splitlines() if ln.strip()]
    if want is None:
        if len(recs) != 1:
            raise MinimizeError(f"{path} holds {len(recs)} cases; name one with FILE#ID")
        return recs[0]
    for r in recs:
        if r.get("id") == want:
            return r
    raise MinimizeError(f"no case {want!r} in {path}")


def minimize(
    case: dict,
    runner: AdapterRunner,
    fieldname: str,
    *,
    kind: str | None = None,
    tol: float = 1e-6,
    decimals: bool = True,
    max_rounds: int = 200,
    log: Callable[[str], None] | None = None,
) -> MinimizeResult:
    """Minimise ``case`` while ``runner``'s library keeps failing on ``fieldname``."""
    t0 = time.perf_counter()
    path = field_for(fieldname, runner.v2)
    a, b = to_typed(case["a"]), to_typed(case["b"])
    state = (a, b)
    need_valid = not path.startswith("valid")
    msgs: list[str] = []

    def say(msg: str) -> None:
        msgs.append(msg)
        if log:
            log(msg)

    first = runner.run([runner.line("c0", a, b)]).get("c0")
    if first is None:
        raise MinimizeError("the adapter gave no result for the case")
    if kind is None:
        if _error_of(first, path) is not None:
            kind = "error"
        elif path.startswith("overlay.") or path in V1_AREAS:
            kind = "area"
        else:
            kind = "value"
    sig = error_signature(_error_of(first, path)) if kind == "error" else None
    check = Check(path, kind, tol, sig)
    ev = _Evaluator(runner, check, need_valid=need_valid)
    ans0 = ev.exact(state)
    if check.exact_needed() and (ans0 is None or ans0.field(path) is None):
        raise MinimizeError(f"no exact answer for {path} on this case (invalid input?)")
    if not check.failing(first, ans0):
        got = _error_of(first, path) if kind == "error" else _get(first, path)
        raise MinimizeError(
            f"{runner.target.id} does not fail on {path} for this case (library: {got!r}, "
            f"exact: {None if ans0 is None else ans0.field(path)!r})"
        )
    before = case_size(a, b)
    say(
        f"start: {before[0]} coordinates, {before[1]} digits, {before[2]} geometry objects; "
        f"kind {kind}; field {path}"
    )
    rounds = 0
    passes: list[tuple[str, Callable]] = [
        ("parts", _cands_parts),
        ("holes", _cands_holes),
        ("vertices", _cands_vertices),
    ]
    changed = True
    while changed and rounds < max_rounds:
        changed = False
        for name, gen in passes:
            n = 2
            while rounds < max_rounds:
                cands, units = gen(state, n)
                if not units:
                    break
                rounds += 1
                best = ev.best(cands, state)
                if best is not None:
                    state = best
                    changed = True
                    size = case_size(*state)
                    say(f"round {rounds}: {name} n={n}: {size[0]} coordinates, {size[1]} digits")
                    n = max(2, n - 1)
                    continue
                if n >= units:
                    break
                n = min(2 * n, units)
        while rounds < max_rounds:
            cands = _cands_structure(state)
            if not cands:
                break
            rounds += 1
            best = ev.best(cands, state)
            if best is None:
                break
            state = best
            changed = True
            say(f"round {rounds}: structure: {case_size(*state)}")
        if decimals:
            while rounds < max_rounds:
                rounds += 1
                best = ev.best(_cands_decimals(state), state)
                if best is None:
                    break
                state = best
                changed = True
                size = case_size(*state)
                say(f"round {rounds}: decimals: {size[0]} coordinates, {size[1]} digits")
    after = case_size(*state)
    final = ev.cache.get(ev.key(state))
    exact = final[1] if final else ans0
    res = final[2] if final else first
    say(
        f"done: {before} -> {after} (coordinates, digits) in {rounds} rounds, "
        f"{runner.calls} adapter calls, {ev.candidates} candidates"
    )
    return MinimizeResult(
        a=state[0],
        b=state[1],
        before=before,
        after=after,
        rounds=rounds,
        adapter_calls=runner.calls,
        candidates=ev.candidates,
        seconds=time.perf_counter() - t0,
        kind=kind,
        field=path,
        log=msgs,
        exact=exact,
        result=res,
    )


def minimised_record(
    case: dict, res: MinimizeResult, target: Target, *, new_id: str | None = None
) -> dict:
    """The minimised case as a v2 record, with provenance pointing at the original."""
    tags: dict[str, Any]
    try:
        gen = REPO / "corpus" / "generators"
        if str(gen) not in sys.path:
            sys.path.insert(0, str(gen))
        import casev2

        tags = casev2.compute_tags(
            geometry_from_json(res.a), geometry_from_json(res.b), flags=["minimised"]
        )
    except Exception:
        ga, gb = geometry_from_json(res.a), geometry_from_json(res.b)
        tags = {
            "n": ga.num_coords + gb.num_coords,
            "types": [ga.geom_type, gb.geom_type],
            "flags": ["minimised"],
        }
    lib = (res.result or {}).get("lib", target.lib)
    return {
        "id": new_id or f"{case.get('id', 'case')}.min",
        "family": case.get("family") or "minimised",
        "tags": tags,
        "provenance": {
            "source": "minimised",
            "parent": case.get("id", ""),
            "minimised_with": {
                "lib": lib,
                "target": target.id,
                "field": res.field,
                "kind": res.kind,
            },
            "size_before": {
                "coordinates": res.before[0],
                "digits": res.before[1],
                "objects": res.before[2],
            },
            "size_after": {
                "coordinates": res.after[0],
                "digits": res.after[1],
                "objects": res.after[2],
            },
        },
        "a": res.a,
        "b": res.b,
    }
