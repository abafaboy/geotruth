"""Adapter manifests (``adapters/<dir>/adapter.toml``, DESIGN §4.2): discovery, targets,
derived fields and the displacement budget δ_lib.

The format is documented in ``adapters/README.md`` and validated by
``schemas/adapter.v2.schema.json``. A manifest has one ``[adapter]`` table and one
``[[target]]`` per library build; the runner and the scorer work on targets, found by
their ``id``.

δ_lib (``[target.precision].delta``) for a case whose largest absolute input ordinate is M:

========== ================================================================
kind       δ
========== ================================================================
relative   value × M
ulp        value × ulp(M)
absolute   value
grid       value × the grid step; the step is read from the ``grid`` text when it
           is a number or ``2^k`` expression, optionally times ``M``, ``ulp(M)`` or ``H``
           (the largest half-extent of the joint bounding box) (``"2^-28 * H"``,
           ``"1e-9"``), or Clipper2's ``2^-k, k the smallest integer ...``; a step that
           depends on the adapter's run-time choices cannot be computed, and δ is then
           undocumented
undocumented  none: overlay output is graded in tiers 1, 2, 4-6 only
========== ================================================================
"""

from __future__ import annotations

import hashlib
import math
import re
import sys
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    import tomli as tomllib

__all__ = [
    "V1_TO_V2",
    "Delta",
    "Target",
    "adapters_dir",
    "delta_for",
    "find_target",
    "load_manifests",
    "repo_root",
    "targets",
]

#: FORMAT-v1 field names and the v2 field paths they correspond to.
V1_TO_V2: dict[str, str] = {
    "valid_a": "valid_a",
    "valid_b": "valid_b",
    **{
        p: f"predicates.{p}"
        for p in (
            "intersects",
            "disjoint",
            "touches",
            "overlaps",
            "contains",
            "covers",
            "within",
            "covered_by",
            "equals",
        )
    },
    "area_inter": "overlay.intersection",
    "area_union": "overlay.union",
    "area_diff": "overlay.difference",
    "area_symdiff": "overlay.symdifference",
}


def repo_root() -> Path:
    """The source tree root (``src/geotruth/harness`` is three levels below it)."""
    return Path(__file__).resolve().parents[3]


def adapters_dir() -> Path:
    """``$GEOTRUTH_ADAPTERS_DIR`` if set, else ``adapters/`` of the source tree."""
    import os

    env = os.environ.get("GEOTRUTH_ADAPTERS_DIR")
    return Path(env) if env else repo_root() / "adapters"


@dataclass
class Target:
    """One ``[[target]]`` of a manifest, with its adapter table."""

    dir: str  # adapters/<dir>
    adapter: dict[str, Any]  # the [adapter] table
    table: dict[str, Any]  # the [[target]] table
    manifest_path: Path
    manifest_sha256: str

    @property
    def id(self) -> str:
        return self.table["id"]

    @property
    def lib(self) -> str:
        return self.table["lib"]

    @property
    def contract(self) -> str:
        return self.adapter.get("contract", "v1")

    @property
    def run(self) -> str:
        return self.table["run"]

    @property
    def version_command(self) -> str:
        return self.table["version_command"]

    @property
    def precision(self) -> dict[str, Any]:
        return self.table.get("precision", {})

    @property
    def tolerance_predicates(self) -> bool:
        return bool(self.precision.get("tolerance_predicates", False))

    def fields(self) -> tuple[set[str], dict[str, str], set[str]]:
        """(supported, derived, unsupported) as v2 field paths (v1 names translated)."""
        f = self.table.get("fields", {})
        sup = {V1_TO_V2.get(x, x) for x in f.get("supported", [])}
        der = {V1_TO_V2.get(k, k): v for k, v in (f.get("derived") or {}).items()}
        uns = {V1_TO_V2.get(x, x) for x in f.get("unsupported", [])}
        return sup, der, uns

    def derived_fields(self) -> dict[str, str]:
        """v2 field path -> how it is derived."""
        return self.fields()[1]


def _parse(path: Path) -> dict[str, Any]:
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def load_manifests(root: Path | None = None) -> dict[str, dict[str, Any]]:
    """Adapter directory name -> parsed manifest, for every ``adapters/*/adapter.toml``."""
    base = root or adapters_dir()
    return {p.parent.name: _parse(p) for p in sorted(base.glob("*/adapter.toml"))}


def targets(root: Path | None = None) -> list[Target]:
    """Every target of every manifest, in directory order."""
    base = root or adapters_dir()
    out = []
    for path in sorted(base.glob("*/adapter.toml")):
        raw = path.read_bytes()
        m = tomllib.loads(raw.decode("utf-8"))
        sha = hashlib.sha256(raw).hexdigest()
        for t in m.get("target", []):
            out.append(Target(path.parent.name, m.get("adapter", {}), t, path, sha))
    return out


def find_target(name: str, root: Path | None = None) -> Target:
    """The target whose id is ``name``; else the only target whose id starts with
    ``name`` or whose ``lib`` does. Raises KeyError (with the candidates) otherwise."""
    ts = targets(root)
    for t in ts:
        if t.id == name:
            return t
    cands = [t for t in ts if t.id.startswith(name) or t.lib.split("@")[0] == name]
    if len(cands) == 1:
        return cands[0]
    ids = ", ".join(t.id for t in (cands or ts))
    if cands:
        raise KeyError(f"--lib {name!r} is ambiguous: {ids}")
    raise KeyError(f"no adapter target {name!r}; known targets: {ids}")


# ============================================================================ delta


@dataclass
class Delta:
    """δ_lib of one case: ``delta2`` (δ² as an exact rational) or None when the budget is
    undocumented or cannot be computed (``note`` says why)."""

    kind: str
    delta2: Fraction | None
    delta: float | None
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


_GRID_RE = re.compile(
    r"^\s*(?:(?P<num>[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)"
    r"|2\s*\^\s*\(?\s*(?P<exp>[-+]?\d+)\s*\)?)"
    r"\s*(?:(?:\*|×|x|times|of)\s*(?P<unit>M|H|ulp\s*\(\s*M\s*\)))?\s*(?:$|[;,(:])",
    re.IGNORECASE,
)


_SMALLEST_K_RE = re.compile(
    r"^\s*2\s*\^\s*-\s*k\b.*smallest integer in (\d+)\s*\.\.\s*(\d+).*"
    r"every ordinate.*an integer",
    re.IGNORECASE | re.DOTALL,
)


def _smallest_k(values: list[float], lo: int, hi: int) -> int | None:
    """The smallest k in lo..hi such that every value times 2^k is an integer."""
    k = lo
    for v in values:
        if v == 0 or not math.isfinite(v):
            continue
        d = Fraction(v).denominator
        k = max(k, d.bit_length() - 1)
    return k if k <= hi else None


def grid_step(text: str, m: float, values: list[float] | None = None) -> Fraction | None:
    """The grid step described by a manifest ``grid`` string, or None if it is not a
    computable expression: a number or ``2^k``, optionally ``* M`` or ``* ulp(M)``; or
    ``2^-k, k the smallest integer in LO..HI that makes every ordinate ... an integer``
    (Clipper2's scaling), computed from the case's ordinates ``values`` (interleaved
    ``x0, y0, x1, y1, ...``); the unit ``H`` is the largest half-extent of their bounding
    box."""
    mk = _SMALLEST_K_RE.match(text or "")
    if mk and values is not None:
        k = _smallest_k(values, int(mk.group(1)), int(mk.group(2)))
        return None if k is None else Fraction(1, 2**k)
    mt = _GRID_RE.match(text or "")
    if not mt:
        return None
    if mt.group("num") is not None:
        step = Fraction(mt.group("num"))
    else:
        step = Fraction(2) ** int(mt.group("exp"))
    unit = (mt.group("unit") or "").replace(" ", "")
    if unit.lower().startswith("ulp"):
        step *= Fraction(math.ulp(m))
    elif unit == "H":
        if not values:
            return None
        step *= half_extent(values)
    elif unit:
        step *= Fraction(m)
    return step


def half_extent(values: list[float]) -> Fraction:
    """H: the largest half-extent of the bounding box of interleaved ordinates
    ``x0, y0, x1, y1, ...`` (non-finite ones ignored)."""
    xs = [v for v in values[0::2] if math.isfinite(v)]
    ys = [v for v in values[1::2] if math.isfinite(v)]
    if not xs or not ys:
        return Fraction(0)
    return max(Fraction(max(xs)) - Fraction(min(xs)), Fraction(max(ys)) - Fraction(min(ys))) / 2


def delta_for(
    target: Target | dict[str, Any], m: float, values: list[float] | None = None
) -> Delta:
    """δ_lib for a case whose largest absolute input ordinate is ``m`` (``values``: every
    input ordinate, for grids that depend on them)."""
    table = target.table if isinstance(target, Target) else target
    prec = table.get("precision", {})
    d = prec.get("delta", {"kind": "undocumented"})
    kind = d.get("kind", "undocumented")
    value = d.get("value")
    if kind == "undocumented" or value is None:
        return Delta(kind, None, None, "the library documents no displacement bound")
    v = Fraction(value)
    if kind == "relative":
        delta = v * Fraction(m)
    elif kind == "ulp":
        delta = v * Fraction(math.ulp(m))
    elif kind == "absolute":
        delta = v
    elif kind == "grid":
        step = grid_step(prec.get("grid", ""), m, values)
        if step is None:
            return Delta(
                kind, None, None, f"grid step not computable from {prec.get('grid', '')!r}"
            )
        delta = v * step
    else:
        return Delta(kind, None, None, f"unknown delta kind {kind!r}")
    return Delta(kind, delta * delta, float(delta))
