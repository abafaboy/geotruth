"""Expected answers: the exact answer to every case of a corpus tier (``geotruth expect``).

For each case the engine computes, in exact arithmetic on the exact input doubles:

- **validity** of both operands (:mod:`geotruth.validity`): the boolean, every defect
  kind and the reason GEOS would report first;
- **relate** (both operands valid): the DE-9IM matrix by *both* independent routes, the
  labelled arrangement (:mod:`geotruth.relate`, which also checks the transpose on a second
  arrangement built with the operands swapped) and the witness points
  (:mod:`geotruth.relate_witness`). They must agree; otherwise the case is an
  ``engine_error``. The named predicates and the fields decided by the empty-geometry
  convention table come with the matrix;
- **overlay** (both operands valid): intersection, union, difference and symmetric
  difference, each in the non-strict (OverlayNG default) and the regularized areal
  variant, as the exact rational side-car, a display WKT and the exact area. Every result
  is certified by the independent checker (:mod:`geotruth.overlay_certify`);
- **measures**: exact areas, certified lengths and centroids of each operand with finite
  coordinates, and the exact squared distance when both are valid (:mod:`geotruth.measures`).

Cross-checks between the parts
------------------------------
Besides the checks inside each module, every record passes consistency checks between
relate and overlay, which were computed from different arrangements. With ``S(op)`` the
(location in A, location in B) pairs an operation selects (a location is *in* X when it is
Interior or Boundary, DESIGN §1 "Overlay"):

- the dimension of the non-strict result is the largest matrix entry over ``S(op)``, and
  ``-1`` (empty) exactly when all of them are ``F``;
- the areal result is non-empty exactly when some entry of ``S(op)`` with both locations
  Interior or Exterior is ``2`` (faces are never on a boundary);
- both variants have the same area; ``|A u B| = |A n B| + |A xor B|``; and for
  polygonal operands ``|A| = |A n B| + |A - B|`` and ``|A u B| = |A| + |B| - |A n B|``,
  where ``|A|`` is the shoelace area of the input.

A failed check is an ``engine_error``, never a library failure.

Statuses
--------
``ok``; ``engine_skipped`` when a case is over the engine's budget; ``engine_error`` when
the engine raised or a check failed, with the reason. The budget is a size budget only
(:data:`EXPECT_BUDGET`: ``n + k`` of each arrangement, and the number of input coordinates
for the quadratic witness route), so whether a case is skipped never depends on the
machine. On an abstention the record keeps the validity and measures, which were computed
independently, and drops everything else.

Records and determinism
-----------------------
One ``expected.v2`` record per case (``schemas/expected.v2.schema.json``), one JSON line
each, in the order of the tier's case files. A record's ``engine`` object holds only the
engine version and the expected-answer series (:data:`EXPECTED_VERSION`), never a git
commit, a timestamp or the rational backend, so the same engine gives byte-identical files
on any machine, with any number of jobs and with either rational backend. Where the answers
were computed (commit, engine source digest, Python, gmpy2) is recorded once per file in
``corpus/expected/MANIFEST.json``.

The manifest also locks the answers: for a given engine version and the same case files, a
regenerated file must be byte-identical to the recorded one. :func:`write_tier` refuses
to replace it otherwise, since answers that change need a new ``geotruth.ENGINE_VERSION``
(the golden tests in ``tests/golden/`` check the same from the other side).

Cache
-----
Records are cached by ``(case sha256, engine version)``: the cache directory is named
after :data:`geotruth.ENGINE_VERSION` and a digest of the engine's source files
(:func:`engine_fingerprint`), so an edited engine never reuses stale answers even before
its version is bumped. The default location is ``$GEOTRUTH_CACHE_DIR``, else
``$XDG_CACHE_HOME/geotruth``, else ``~/.cache/geotruth``, under ``expected/``.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import time
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

from geotruth import ENGINE_VERSION
from geotruth.arrangement import Budget
from geotruth.geom import Geometry, LineString, MultiPolygon, Polygon
from geotruth.io import Case, case_from_json, case_sha256
from geotruth.numbers import format_rational, get_backend, json_loads, use_backend

__all__ = [
    "EXPECTED_VERSION",
    "EXPECT_BUDGET",
    "MANIFEST_NAME",
    "SCHEMA_ID",
    "STATUSES",
    "TIERS",
    "TIERS_IN_GIT",
    "WITNESS_MAX_COORDS",
    "AnswerCache",
    "ComputeStats",
    "ExpectedChangedError",
    "TierResult",
    "compute_lines",
    "consistency_problems",
    "corpus_dir",
    "default_cache_dir",
    "dumps_record",
    "engine_fingerprint",
    "expected_line",
    "expected_record",
    "load_manifest",
    "lock_violation",
    "read_case_lines",
    "sha256_file",
    "tier_case_files",
    "write_tier",
]

#: The expected-answer series: format ``expected.v2`` (``corpus/expected-v1/`` holds the
#: legacy oracle answers). Within the series, the answers are identified by the engine
#: version: one engine version gives one set of answers for one set of cases.
EXPECTED_VERSION = "2"

#: The tiers of ``corpus/cases/`` that have expected answers.
TIERS: tuple[str, ...] = ("core", "curated", "full")
#: Tiers whose case files, and so expected answers, are kept in git.
TIERS_IN_GIT: frozenset[str] = frozenset({"core", "curated"})

STATUS_OK, STATUS_SKIPPED, STATUS_ERROR = "ok", "engine_skipped", "engine_error"
STATUSES: tuple[str, ...] = (STATUS_OK, STATUS_SKIPPED, STATUS_ERROR)

#: The engine's budget for expected answers: the size limit of DESIGN §2.2 (``n + k`` of
#: each arrangement) and no wall-clock or memory limit, so that a skip is reproducible.
EXPECT_BUDGET = Budget(max_size=200_000, max_seconds=None, max_memory_mb=None)
#: The witness route is quadratic in the number of segments: above this many input
#: coordinates (both operands together) the case is ``engine_skipped``.
WITNESS_MAX_COORDS = 20_000

MANIFEST_NAME = "MANIFEST.json"
MANIFEST_VERSION = 1
SCHEMA_ID = "https://github.com/abafaboy/geotruth/schemas/expected.v2.schema.json"

_I, _B, _E = 0, 1, 2  # Location.INTERIOR, BOUNDARY, EXTERIOR: matrix rows and columns
_OPS: tuple[str, ...] = ("intersection", "union", "difference", "symdifference")
_VARIANTS: tuple[str, ...] = ("non_strict", "areal")
_SELECT: dict[str, Callable[[bool, bool], bool]] = {
    "intersection": lambda in_a, in_b: in_a and in_b,
    "union": lambda in_a, in_b: in_a or in_b,
    "difference": lambda in_a, in_b: in_a and not in_b,
    "symdifference": lambda in_a, in_b: in_a != in_b,
}


class _Abstain(Exception):
    """The engine abstains on a case: ``status`` is engine_skipped or engine_error."""

    def __init__(self, status: str, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


# ============================================================================ one case


def _dims(g: Geometry) -> dict[str, int]:
    return {"dimension": g.dimension, "real_dimension": g.real_dimension}


def _point_set_dimension(g: Geometry) -> int:
    """The dimension of the point set: the highest over non-empty elements (-1 if empty)."""
    dim = -1
    for e in g.elements():
        if e.is_empty:
            continue
        if isinstance(e, Polygon):
            d = 2
        elif isinstance(e, LineString):
            d = 0 if e.is_zero_length else 1
        else:
            d = 0
        dim = max(dim, d)
    return dim


def _num_coords(*geoms: Geometry) -> int:
    return sum(1 for g in geoms for _ in g.iter_coords())


def _is_polygonal(g: Geometry) -> bool:
    return isinstance(g, (Polygon, MultiPolygon))


def _relate(a: Geometry, b: Geometry, budget: Budget) -> Any:
    """The relate result by the arrangement route, confirmed by the witness route."""
    from geotruth.relate import relate
    from geotruth.relate_witness import relate_witness

    res = relate(a, b, budget=budget, check=True, transpose_check=True)
    if res.status == STATUS_SKIPPED:
        raise _Abstain(STATUS_SKIPPED, f"relate: {res.reason}")
    if res.status != STATUS_OK or res.matrix is None:
        raise _Abstain(STATUS_ERROR, f"relate (arrangement route): {res.reason}")
    n = _num_coords(a, b)
    if n > WITNESS_MAX_COORDS:
        raise _Abstain(
            STATUS_SKIPPED,
            f"relate (witness route) over budget: {n} input coordinates > {WITNESS_MAX_COORDS}",
        )
    witness = relate_witness(a, b, check=True).matrix
    if witness != res.matrix:
        raise _Abstain(
            STATUS_ERROR,
            f"relate: the two routes disagree: arrangement {res.matrix}, witness {witness}",
        )
    return res


def _overlays(a: Geometry, b: Geometry, budget: Budget) -> dict[str, dict[str, Any]]:
    """Every certified overlay result; abstains if any of them is not ok (an error
    before a skip)."""
    from geotruth.overlay import overlay_all

    res = overlay_all(a, b, ops=_OPS, variants=_VARIANTS, budget=budget, check=True, certify=True)
    bad = [(op, v, res[op][v]) for op in _OPS for v in _VARIANTS if not res[op][v].ok]
    if bad:
        errors = [x for x in bad if x[2].status == STATUS_ERROR]
        op, v, r = (errors or bad)[0]
        status = STATUS_ERROR if errors else STATUS_SKIPPED
        raise _Abstain(status, f"overlay {op} ({v}): {r.reason}")
    return res


def consistency_problems(
    matrix: str,
    overlays: dict[str, dict[str, Any]],
    a: Geometry,
    b: Geometry,
    area_a: Any,
    area_b: Any,
) -> list[str]:
    """Disagreements between the relate matrix, the overlay results and the operand areas
    (see the module docstring); ``overlays[op][variant]`` has ``geometry`` and ``area``."""
    problems: list[str] = []

    def entry(x: int, y: int) -> int:
        ch = matrix[3 * x + y]
        return -1 if ch == "F" else int(ch)

    for op in _OPS:
        pairs = [(x, y) for x in range(3) for y in range(3) if _SELECT[op](x != _E, y != _E)]
        want_dim = max(entry(x, y) for x, y in pairs)
        got_dim = _point_set_dimension(overlays[op]["non_strict"].geometry)
        if got_dim != want_dim:
            problems.append(
                f"{op}: the non-strict result has dimension {got_dim}, relate {matrix} "
                f"implies {want_dim}"
            )
        want_areal = any(entry(x, y) == 2 for x, y in pairs if _B not in (x, y))
        got_areal = not overlays[op]["areal"].geometry.is_empty
        if got_areal != want_areal:
            problems.append(
                f"{op}: the areal result is {'non-empty' if got_areal else 'empty'}, "
                f"relate {matrix} implies the opposite"
            )
        if overlays[op]["non_strict"].area != overlays[op]["areal"].area:
            problems.append(f"{op}: the two variants have different areas")

    area = {op: overlays[op]["areal"].area for op in _OPS}
    if area["union"] != area["intersection"] + area["symdifference"]:
        problems.append("area: |A u B| != |A n B| + |A xor B|")
    if _is_polygonal(a) and area_a != area["intersection"] + area["difference"]:
        problems.append("area: |A| != |A n B| + |A - B|")
    if (
        _is_polygonal(a)
        and _is_polygonal(b)
        and area["union"] != area_a + area_b - area["intersection"]
    ):
        problems.append("area: |A u B| != |A| + |B| - |A n B|")
    return problems


def _measures(
    a: Geometry, b: Geometry, finite_a: bool, finite_b: bool, both_valid: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """The ``measures`` object (key names as :func:`geotruth.measures.case_measures`) and
    the exact operand areas (for the consistency checks)."""
    from geotruth.measures import area, centroid, distance2, length

    out: dict[str, Any] = {}
    areas: dict[str, Any] = {}
    for tag, g, finite in (("a", a, finite_a), ("b", b, finite_b)):
        if not finite:
            continue
        areas[tag] = area(g)
        out[f"area_{tag}"] = format_rational(areas[tag])
        out[f"length_{tag}"] = length(g).to_json()
        c = centroid(g)
        if c is not None:
            out[f"centroid_{tag}_x"] = c[0].to_json()
            out[f"centroid_{tag}_y"] = c[1].to_json()
    if both_valid:
        d2 = distance2(a, b)
        if d2 is not None:
            out["distance2"] = format_rational(d2)
    return out, areas


def expected_record(case: Case, *, budget: Budget = EXPECT_BUDGET) -> dict[str, Any]:
    """The ``expected.v2`` record of one case (see the module docstring).

    Never raises for an engine failure: that is an ``engine_error`` record with the
    reason. ``budget`` bounds each arrangement (:data:`EXPECT_BUDGET`).
    """
    from geotruth.validity import INVALID_COORDINATE, validate

    a, b = case.a, case.b
    rec: dict[str, Any] = {
        "id": case.id,
        "case_sha256": case_sha256(case),
        "engine": {"version": ENGINE_VERSION, "expected_version": EXPECTED_VERSION},
        "status": STATUS_OK,
        "dimensions": {"a": _dims(a), "b": _dims(b)},
    }
    # the parts computed so far are kept on an abstention (they are independent answers)
    validity: dict[str, Any] | None = None
    measures: dict[str, Any] | None = None
    part = "validity"
    try:
        va, vb = validate(a), validate(b)
        validity = {"a": va.to_json(), "b": vb.to_json()}
        both_valid = va.valid and vb.valid
        part = "measures"
        finite_a = INVALID_COORDINATE not in va.reasons
        finite_b = INVALID_COORDINATE not in vb.reasons
        measures, areas = _measures(a, b, finite_a, finite_b, both_valid)
        if both_valid:
            part = "relate"
            rel = _relate(a, b, budget)
            part = "overlay"
            ovl = _overlays(a, b, budget)
            part = "consistency"
            problems = consistency_problems(rel.matrix, ovl, a, b, areas["a"], areas["b"])
            if problems:
                raise _Abstain(STATUS_ERROR, "relate/overlay/area check: " + "; ".join(problems))
            rec["relate"] = rel.matrix
            rec["predicates"] = dict(rel.predicates)
            if rel.conventions:
                rec["conventions"] = list(rel.conventions)
        rec["validity"] = validity
        if both_valid:
            rec["overlay"] = {op: {v: ovl[op][v].to_json() for v in _VARIANTS} for op in _OPS}
        if measures:
            rec["measures"] = measures
        return rec
    except _Abstain as exc:
        return _abstain(rec, exc.status, exc.reason, validity, measures)
    except MemoryError:
        return _abstain(rec, STATUS_SKIPPED, f"{part}: out of memory", validity, measures)
    except Exception as exc:  # an engine exception is an engine_error, never a crash
        return _abstain(
            rec, STATUS_ERROR, f"{part}: {type(exc).__name__}: {exc}", validity, measures
        )


def _abstain(
    rec: dict[str, Any],
    status: str,
    reason: str,
    validity: dict[str, Any] | None,
    measures: dict[str, Any] | None,
) -> dict[str, Any]:
    out = {k: rec[k] for k in ("id", "case_sha256", "engine")}
    out["status"] = status
    out["reason"] = reason[:2000]
    out["dimensions"] = rec["dimensions"]
    if validity is not None:
        out["validity"] = validity
    if measures:
        out["measures"] = measures
    return out


def dumps_record(rec: dict[str, Any]) -> str:
    """One record as its JSON line (compact, keys in construction order, ASCII)."""
    return json.dumps(rec, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


@cache
def _validator() -> Any:
    from geotruth import schemas

    return schemas.validator("expected")


def _schema_error(rec: dict[str, Any]) -> str | None:
    from jsonschema.exceptions import best_match

    err = best_match(_validator().iter_errors(rec))
    if err is None:
        return None
    where = "/".join(str(p) for p in err.absolute_path) or "(record)"
    return f"{where}: {err.message}"[:500]


@dataclass(frozen=True)
class _Job:
    line: str
    backend: str
    validate: bool
    budget: Budget


def expected_line(case_line: str, *, validate: bool = True, budget: Budget = EXPECT_BUDGET) -> str:
    """The expected-answer JSON line of one case line (a ``case.v2`` record).

    With ``validate`` the record is checked against ``schemas/expected.v2`` (needs
    jsonschema); a record that fails is replaced by an ``engine_error`` record that says
    why, which is itself schema-valid.
    """
    case = case_from_json(json_loads(case_line))
    rec = expected_record(case, budget=budget)
    if validate:
        err = _schema_error(rec)
        if err is not None:
            rec = _abstain(
                rec, STATUS_ERROR, f"the record failed schema validation: {err}", None, None
            )
    return dumps_record(rec)


def _work(job: _Job) -> tuple[str, float]:
    t0 = time.perf_counter()
    with use_backend(job.backend):
        text = expected_line(job.line, validate=job.validate, budget=job.budget)
    return text, time.perf_counter() - t0


# ============================================================================ cache


@cache
def engine_fingerprint() -> str:
    """SHA-256 of the engine's source files (every ``geotruth/*.py``; the ``commands``
    and ``harness`` subpackages are not part of the engine)."""
    h = hashlib.sha256()
    for p in sorted(Path(__file__).resolve().parent.glob("*.py")):
        h.update(p.name.encode() + b"\0")
        h.update(p.read_bytes())
        h.update(b"\0")
    return h.hexdigest()


def default_cache_dir() -> Path:
    """``$GEOTRUTH_CACHE_DIR``, else ``$XDG_CACHE_HOME/geotruth``, else
    ``~/.cache/geotruth``; expected answers are cached under ``expected/`` in it."""
    env = os.environ.get("GEOTRUTH_CACHE_DIR")
    if env:
        return Path(env)
    xdg = os.environ.get("XDG_CACHE_HOME")
    return (Path(xdg) if xdg else Path.home() / ".cache") / "geotruth"


class AnswerCache:
    """Expected-answer lines keyed by case sha256, for this engine version and source.

    One append-only JSON-lines file per (engine version, engine fingerprint); only the
    process that owns the cache object writes it. Unreadable lines (an interrupted write)
    are ignored.
    """

    def __init__(self, root: Path) -> None:
        key = f"engine-{ENGINE_VERSION}-{engine_fingerprint()[:16]}"
        self.path = Path(root) / "expected" / key / "answers.jsonl"
        self._lines: dict[str, str] = {}
        if self.path.is_file():
            with open(self.path, encoding="utf-8") as fh:
                for raw in fh:
                    line = raw.rstrip("\n")
                    try:
                        sha = json.loads(line)["case_sha256"]
                    except (ValueError, KeyError, TypeError):
                        continue
                    self._lines[sha] = line
        self._fh: Any = None

    def get(self, sha: str) -> str | None:
        return self._lines.get(sha)

    def put(self, sha: str, line: str) -> None:
        if self._lines.get(sha) == line:
            return
        self._lines[sha] = line
        if self._fh is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a", encoding="utf-8")  # noqa: SIM115
        self._fh.write(line + "\n")

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __len__(self) -> int:
        return len(self._lines)


# ============================================================================ many cases


@dataclass
class ComputeStats:
    """What :func:`compute_lines` did: counts, cache use and timings (seconds)."""

    cases: int = 0
    status: Counter = field(default_factory=Counter)
    cached: int = 0
    computed: int = 0
    wall: float = 0.0
    cpu: float = 0.0
    slowest: list[tuple[float, str]] = field(default_factory=list)
    abstentions: list[tuple[str, str, str]] = field(default_factory=list)  # id, status, why


def _status_of(line: str) -> tuple[str, str, str | None]:
    rec = json.loads(line)
    return rec["id"], rec["status"], rec.get("reason")


def compute_lines(
    case_lines: Sequence[str],
    *,
    jobs: int = 1,
    cache: AnswerCache | None = None,
    validate: bool = True,
    budget: Budget = EXPECT_BUDGET,
    backend: str | None = None,
    log: Callable[[str], None] | None = None,
) -> tuple[list[str], ComputeStats]:
    """The expected-answer line of every case line, in order, and statistics.

    Cases are looked up in ``cache`` first (by case sha256); the rest are computed, in
    ``jobs`` worker processes when ``jobs > 1``, and added to the cache.
    """
    backend = backend or get_backend()
    stats = ComputeStats(cases=len(case_lines))
    t0 = time.perf_counter()
    out: list[str | None] = [None] * len(case_lines)
    todo: list[tuple[int, str]] = []
    for i, line in enumerate(case_lines):
        sha = case_sha256(case_from_json(json_loads(line)))
        hit = cache.get(sha) if cache is not None else None
        if hit is not None:
            out[i] = hit
            stats.cached += 1
        else:
            todo.append((i, sha))
    if log and case_lines:
        log(f"  {stats.cached} cases from the cache, {len(todo)} to compute ({jobs} jobs)")
    jobs_list = [_Job(case_lines[i], backend, validate, budget) for i, _ in todo]
    times: list[tuple[float, str]] = []

    def results() -> Iterator[tuple[str, float]]:
        if jobs > 1 and len(jobs_list) > 1:
            with ProcessPoolExecutor(max_workers=jobs) as ex:
                yield from ex.map(_work, jobs_list, chunksize=4)
        else:
            yield from map(_work, jobs_list)

    for done, ((i, sha), (text, secs)) in enumerate(zip(todo, results(), strict=True), 1):
        out[i] = text
        if cache is not None:
            cache.put(sha, text)
        stats.cpu += secs
        times.append((secs, json.loads(text)["id"]))
        if log and done % 500 == 0:
            log(f"  {done}/{len(todo)} computed ({time.perf_counter() - t0:.0f} s)")
    stats.computed = len(todo)
    stats.wall = time.perf_counter() - t0
    stats.slowest = sorted(times, reverse=True)[:5]
    lines = [x for x in out if x is not None]
    assert len(lines) == len(case_lines)
    for line in lines:
        cid, status, reason = _status_of(line)
        stats.status[status] += 1
        if status != STATUS_OK:
            stats.abstentions.append((cid, status, reason or ""))
    return lines, stats


# ============================================================================ tiers


def corpus_dir() -> Path:
    """The repository's ``corpus/`` directory."""
    return Path(__file__).resolve().parents[2] / "corpus"


def tier_case_files(tier: str, corpus: Path | None = None) -> list[Path]:
    """The case files of a tier, in the order their answers are written."""
    cases = (corpus or corpus_dir()) / "cases"
    if tier == "core":
        return sorted((cases / "core").glob("*.jsonl"))
    if tier == "curated":
        p = cases / "curated.jsonl"
        return [p] if p.is_file() else []
    if tier == "full":
        return sorted((cases / "full").glob("*.jsonl"))
    raise ValueError(f"unknown tier {tier!r}; expected one of {TIERS}")


def read_case_lines(paths: Iterable[Path]) -> list[str]:
    """The non-blank lines of the case files, in order."""
    lines: list[str] = []
    for p in paths:
        with open(p, encoding="utf-8") as fh:
            lines += [ln.rstrip("\n") for ln in fh if ln.strip()]
    return lines


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_manifest(out_dir: Path) -> dict[str, Any] | None:
    """``corpus/expected/MANIFEST.json``, or None."""
    p = Path(out_dir) / MANIFEST_NAME
    if not p.is_file():
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def _git(root: Path, *args: str) -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def _provenance() -> dict[str, Any]:
    """Where the answers were computed (recorded in the manifest, never in records)."""
    root = Path(__file__).resolve().parents[2]
    info: dict[str, Any] = {}
    head = _git(root, "rev-parse", "HEAD")
    if head:
        info["engine_commit"] = head.strip()
        status = _git(root, "status", "--porcelain", "--", "src/geotruth")
        if status is not None:
            info["engine_worktree_clean"] = status.strip() == ""
    info["engine_source_sha256"] = engine_fingerprint()
    info["python"] = platform.python_version()
    try:
        import gmpy2

        info["gmpy2"] = gmpy2.version()
    except ImportError:  # pragma: no cover - gmpy2 is a dependency
        info["gmpy2"] = None
    info["rational_backend"] = get_backend()
    return info


def _corpus_version(corpus: Path) -> str | None:
    p = corpus / "MANIFEST.json"
    if not p.is_file():
        return None
    with open(p, encoding="utf-8") as fh:
        return json.load(fh).get("corpus_version")


class ExpectedChangedError(RuntimeError):
    """The answers for an unchanged engine version and case set differ from the ones the
    manifest records: the engine's answers changed without an ENGINE_VERSION bump."""


@dataclass
class TierResult:
    """The outcome of :func:`write_tier` for one tier."""

    tier: str
    path: Path
    stats: ComputeStats
    written: bool  # the answer file was (re)written
    changed: bool  # its content differs from the previous file (or there was none)
    same_as_file: bool | None = None  # --check: the computed answers equal the file


def lock_violation(old: dict[str, Any] | None, new: dict[str, Any]) -> bool:
    """True if two manifest entries of one answer file record different answers
    (``sha256``) for the same engine version and the same case files (``cases``): answers
    that changed without an ENGINE_VERSION bump."""
    return (
        old is not None
        and old.get("engine_version") == new.get("engine_version")
        and old.get("cases") == new.get("cases")
        and old.get("sha256") != new.get("sha256")
    )


def _cases_entry(files: list[Path], corpus: Path) -> dict[str, str]:
    return {p.relative_to(corpus).as_posix(): sha256_file(p) for p in files}


def write_tier(
    tier: str,
    *,
    corpus: Path | None = None,
    out_dir: Path | None = None,
    jobs: int = 1,
    cache: AnswerCache | None = None,
    validate: bool = True,
    check_only: bool = False,
    log: Callable[[str], None] | None = None,
) -> TierResult:
    """Compute the answers of a tier and write ``<out_dir>/<tier>.jsonl`` and its
    manifest entry (``out_dir`` defaults to ``corpus/expected``).

    The file and the manifest entry are left untouched when the content is unchanged.
    Raises :class:`ExpectedChangedError` if the content changed while the engine version
    and the case files are the ones the manifest records. With ``check_only`` nothing is
    written and ``same_as_file`` says whether the file holds exactly these answers.
    """
    corpus = Path(corpus) if corpus is not None else corpus_dir()
    out_dir = Path(out_dir) if out_dir is not None else corpus / "expected"
    files = tier_case_files(tier, corpus)
    if not files:
        raise FileNotFoundError(f"tier {tier!r} has no case files under {corpus / 'cases'}")
    case_lines = read_case_lines(files)
    if log:
        log(f"{tier}: {len(case_lines)} cases in {len(files)} file(s)")
    lines, stats = compute_lines(case_lines, jobs=jobs, cache=cache, validate=validate, log=log)
    text = "".join(x + "\n" for x in lines)
    data = text.encode("ascii")
    new_sha = hashlib.sha256(data).hexdigest()
    path = out_dir / f"{tier}.jsonl"
    old_sha = sha256_file(path) if path.is_file() else None
    changed = old_sha != new_sha
    if check_only:
        return TierResult(
            tier, path, stats, written=False, changed=changed, same_as_file=not changed
        )

    manifest = load_manifest(out_dir) or {}
    old_entry = (manifest.get("files") or {}).get(path.name)
    entry_now = {
        "sha256": new_sha,
        "engine_version": ENGINE_VERSION,
        "cases": _cases_entry(files, corpus),
    }
    if lock_violation(old_entry, entry_now):
        raise ExpectedChangedError(
            f"{path.name}: the answers changed for the same cases and the same engine "
            f"version {ENGINE_VERSION}; bump geotruth.ENGINE_VERSION (src/geotruth/__init__.py)"
            " and run `geotruth expect` again"
        )
    fresh = old_entry is None or any(old_entry.get(k) != v for k, v in entry_now.items())
    if changed:
        out_dir.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, path)
    if fresh:
        entry = {
            "tier": tier,
            "in_git": tier in TIERS_IN_GIT,
            "sha256": new_sha,
            "bytes": len(data),
            "records": len(lines),
            "status": {s: stats.status.get(s, 0) for s in STATUSES},
            "engine_version": ENGINE_VERSION,
            "expected_version": EXPECTED_VERSION,
            "corpus_version": _corpus_version(corpus),
            "cases": entry_now["cases"],
            "computed_with": _provenance(),
        }
        _write_manifest(out_dir, manifest, path.name, entry)
    return TierResult(tier, path, stats, written=changed, changed=changed)


def _write_manifest(
    out_dir: Path, manifest: dict[str, Any], name: str, entry: dict[str, Any]
) -> None:
    files = dict(manifest.get("files") or {})
    files[name] = entry
    new = {
        "manifest_version": MANIFEST_VERSION,
        "format": SCHEMA_ID,
        "expected_version": EXPECTED_VERSION,
        "licence": "CC0-1.0",
        "files": dict(sorted(files.items())),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / MANIFEST_NAME
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(new, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)
