"""Reading the inputs of the site: score files and the files ``geotruth run`` and
``geotruth score`` write next to them, the adapter manifests, the triage registry, and the
cases, library results and exact answers of the examples shown.

A results directory (``--scores DIR``) has the layout ``geotruth run`` and ``geotruth
score`` produce::

    DIR/<target>/<tier>.score.jsonl     score.v2 records (required)
    DIR/<target>/<tier>.jsonl           the library's result.v2 lines (for its answers)
    DIR/<target>/<tier>.stats.json      runner statistics, with the case files
    DIR/<target>/run.json               provenance (run.v2): versions, commits, dates
    DIR/_expected/*.jsonl               expected.v2 answers cached by the scorer

Only the score file is required; every other file makes the pages richer, and a page says
so when something is missing.
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gtsite.aggregate import LibraryStats

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - Python 3.10
    import tomli as tomllib

Log = Callable[[str], None]

_ID_RE = re.compile(r'"id"\s*:\s*"((?:[^"\\]|\\.)*)"')


class SiteInputError(RuntimeError):
    """The inputs cannot make a site (no score files, an unknown tier, ...)."""


@dataclass
class ScoreSet:
    """One library target's scores for one tier, with the files around them."""

    target_id: str
    tier: str
    score_path: Path
    root: Path  # the results directory holding <target>/
    stats: LibraryStats
    run: dict[str, Any] = field(default_factory=dict)
    run_stats: dict[str, Any] = field(default_factory=dict)
    target: Any = None  # geotruth.harness.manifest.Target, or None without a manifest
    results_path: Path | None = None

    @property
    def library(self) -> str:
        if self.target is not None:
            return str(self.target.table.get("library") or self.target_id)
        return self.target_id

    @property
    def lib(self) -> str:
        return str(self.run.get("lib") or self.stats.lib or self.target_id)

    @property
    def manifest(self) -> dict[str, Any]:
        return self.target.table if self.target is not None else {}

    @property
    def case_files(self) -> list[Path]:
        return [Path(p) for p in self.run_stats.get("case_files", [])]


def _read_json(path: Path) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def find_score_files(dirs: Iterable[Path]) -> list[tuple[str, str, Path, Path]]:
    """``(target, tier, score file, results root)`` for every ``*.score.jsonl`` directly in
    ``DIR/<target>/`` (or in ``DIR`` itself when ``DIR`` is a target's directory)."""
    out = []
    for d in dirs:
        d = Path(d)
        if not d.is_dir():
            raise SiteInputError(f"--scores {d}: not a directory")
        candidates = sorted(d.glob("*/*.score.jsonl"))
        roots = [(p, d) for p in candidates]
        if not candidates:
            roots = [(p, d.parent) for p in sorted(d.glob("*.score.jsonl"))]
        for path, root in roots:
            tier = path.name.removesuffix(".score.jsonl")
            out.append((path.parent.name, tier, path, root))
    return out


def choose_tier(found: list[tuple[str, str, Path, Path]], tier: str | None) -> str:
    tiers = sorted({t for _, t, _, _ in found})
    if not tiers:
        raise SiteInputError(
            "no score files (<target>/<tier>.score.jsonl) under the --scores directories; "
            "run `geotruth run` and `geotruth score` first"
        )
    if tier is not None:
        if tier not in tiers:
            raise SiteInputError(f"no scores for tier {tier!r} (tiers found: {', '.join(tiers)})")
        return tier
    if "core" in tiers:
        return "core"
    if len(tiers) == 1:
        return tiers[0]
    raise SiteInputError(f"several tiers found ({', '.join(tiers)}); choose one with --tier")


def _find_target(target_id: str) -> Any:
    try:
        from geotruth.harness.manifest import find_target, targets
    except ImportError:  # pragma: no cover - the site is built from a geotruth checkout
        return None
    for t in targets():
        if t.id == target_id:
            return t
    try:
        return find_target(target_id)
    except KeyError:
        return None


def load_scoreset(target_id: str, tier: str, path: Path, root: Path) -> ScoreSet:
    """Fold one score file into a :class:`ScoreSet`."""
    stats = LibraryStats(target_id)
    with open(path, encoding="utf-8") as fh:
        for n, line in enumerate(fh, 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError as exc:
                raise SiteInputError(f"{path}:{n}: not JSON ({exc})") from None
            if not isinstance(rec, dict) or "capability" not in rec or "verdict" not in rec:
                raise SiteInputError(f"{path}:{n}: not a score.v2 record")
            stats.add(rec)
    base = path.parent
    results = base / f"{tier}.jsonl"
    return ScoreSet(
        target_id=target_id,
        tier=tier,
        score_path=path,
        root=root,
        stats=stats,
        run=_read_json(base / "run.json"),
        run_stats=_read_json(base / f"{tier}.stats.json"),
        target=_find_target(target_id),
        results_path=results if results.is_file() else None,
    )


def load_scoresets(dirs: Iterable[Path], tier: str | None, log: Log) -> tuple[str, list[ScoreSet]]:
    found = find_score_files(dirs)
    chosen = choose_tier(found, tier)
    sets: dict[str, ScoreSet] = {}
    for target_id, t, path, root in found:
        if t != chosen:
            continue
        if target_id in sets:
            raise SiteInputError(
                f"two score files for {target_id} ({sets[target_id].score_path} and {path}); "
                "pass each library once"
            )
        log(f"reading {path}")
        sets[target_id] = load_scoreset(target_id, t, path, root)
    return chosen, [sets[k] for k in sorted(sets)]


# ============================================================================ registry


def load_registry(path: Path | None) -> tuple[list[dict[str, Any]], str | None]:
    """The entries of ``findings/registry.toml`` - its ``[[finding]]`` tables, then its
    ``[[lead]]`` tables (marked ``kind = "lead"``) - and a problem message (None when it
    was read)."""
    if path is None:
        return [], "no registry given"
    if not path.is_file():
        return [], f"{path} not found"
    try:
        with open(path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        return [], f"{path}: {exc}"
    out: list[dict[str, Any]] = []
    for table, kind in (("finding", "finding"), ("lead", "lead")):
        entries = data.get(table, [])
        if not isinstance(entries, list):
            return [], f"{path}: {table!r} is not an array of tables"
        out += [{**e, "kind": kind} for e in entries if isinstance(e, dict) and e.get("id")]
    return out, None


# ============================================================================ lookups


@dataclass
class CaseLine:
    """A case as read from its file: the raw line (for exact repro commands) and where."""

    id: str
    line: str
    path: Path
    obj: dict[str, Any]


def scan_jsonl(paths: Iterable[Path], wanted: set[str]) -> dict[str, tuple[str, Path]]:
    """``id -> (line, path)`` for the wanted ids, from JSON-lines files (the first
    occurrence wins). Only lines whose id is wanted are kept."""
    out: dict[str, tuple[str, Path]] = {}
    if not wanted:
        return out
    for p in paths:
        try:
            with open(p, encoding="utf-8") as fh:
                for line in fh:
                    m = _ID_RE.search(line, 0, 400)
                    if not m:
                        continue
                    cid = json.loads(f'"{m.group(1)}"')
                    if cid in wanted and cid not in out:
                        out[cid] = (line.rstrip("\n"), Path(p))
        except OSError:
            continue
        if len(out) == len(wanted):
            break
    return out


def corpus_case_files(tier: str) -> list[Path]:
    """The case files of a corpus tier from ``corpus/MANIFEST.json`` (present ones)."""
    try:
        from geotruth.harness.runner import corpus_dir
    except ImportError:  # pragma: no cover
        return []
    base = corpus_dir()
    try:
        man = json.loads((base / "MANIFEST.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    files = []
    for t in (tier, "core", "curated"):
        for rel in (man.get("tiers", {}).get(t, {}) or {}).get("files", {}):
            p = base / rel
            if p.is_file() and p not in files:
                files.append(p)
    return files


def find_cases(sets: list[ScoreSet], wanted: set[str], tier: str) -> dict[str, CaseLine]:
    """The wanted cases, from the case files the runs used (``stats.json``), falling back
    to files of the same name in the corpus, then to the corpus tier itself."""
    try:
        from geotruth.harness.runner import corpus_dir

        corpus = corpus_dir()
    except ImportError:  # pragma: no cover
        corpus = None
    files: list[Path] = []
    for ss in sets:
        for p in ss.case_files:
            cands = [p]
            if corpus is not None:
                cands += [corpus / "cases" / tier / p.name, corpus / "cases" / p.name]
            for c in cands:
                if c.is_file() and c not in files:
                    files.append(c)
                    break
    files += [p for p in corpus_case_files(tier) if p not in files]
    found = scan_jsonl(files, wanted)
    out = {}
    for cid, (line, path) in found.items():
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        out[cid] = CaseLine(cid, line, path, obj)
    return out


def find_results(ss: ScoreSet, wanted: set[str]) -> dict[str, dict[str, Any]]:
    """The library's result lines for the wanted ids."""
    if ss.results_path is None:
        return {}
    found = scan_jsonl([ss.results_path], wanted)
    out = {}
    for cid, (line, _) in found.items():
        try:
            out[cid] = json.loads(line)
        except ValueError:
            continue
    return out


def expected_files(roots: Iterable[Path]) -> list[Path]:
    """Where exact answers may be: the published answers (``corpus/expected/*.jsonl``),
    then the scorer's caches (``<root>/_expected/*.jsonl``, newest first)."""
    files: list[Path] = []
    try:
        from geotruth.harness.runner import corpus_dir

        pub = corpus_dir() / "expected"
        if pub.is_dir():
            files += sorted(pub.glob("*.jsonl"), key=lambda p: (p.name != "core.jsonl", p.name))
    except ImportError:  # pragma: no cover
        pass
    for r in roots:
        d = Path(r) / "_expected"
        if d.is_dir():
            files += sorted(d.glob("*.jsonl"), key=lambda p: -p.stat().st_mtime)
    return files


def find_expected(
    files: Iterable[Path],
    wanted: set[str],
    engine_version: str | None,
    expected_version: str | None,
) -> dict[str, dict[str, Any]]:
    """Exact answers for the wanted ids, preferring the records the scores were graded
    against: the same expected-answer version (``versions.expected`` of the score records;
    ``computed-<engine>`` for the scorer's own), else the same engine version, else any."""

    def rank(rec: dict[str, Any]) -> int:
        eng = rec.get("engine") or {}
        exp_v = eng.get("expected_version")
        if expected_version is not None:
            if exp_v is not None and str(exp_v) == expected_version:
                return 2
            if exp_v is None and expected_version == f"computed-{eng.get('version')}":
                return 2
        if engine_version is not None and eng.get("version") == engine_version:
            return 1
        return 0

    best: dict[str, dict[str, Any]] = {}
    if not wanted:
        return best
    for p in files:
        todo = {w for w in wanted if w not in best or rank(best[w]) < 2}
        if not todo:
            break
        for cid, (line, _) in scan_jsonl([p], todo).items():
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if cid not in best or rank(rec) > rank(best[cid]):
                best[cid] = rec
    return best
