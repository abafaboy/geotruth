"""gtsite: the static site generator behind ``geotruth site`` (DESIGN §6).

``build_site(SiteOptions(scores=[DIR], out=Path("site/_build")))`` reads the score files
that ``geotruth score`` wrote under DIR, with the run provenance, the library's result
lines, the scorer's cached exact answers, the adapter manifests and the triage registry,
and writes a self-contained static site: plain HTML with inline CSS, a few lines of inline
JavaScript (the theme switch only), inline SVG figures, and ``index.json``. It makes no
network requests and needs no server.

The package lives in the repository's ``site/`` directory, next to its templates and
static assets; ``geotruth site`` puts that directory on ``sys.path``. (It is not called
``site`` because that name belongs to Python's own start-up module.)
"""

from __future__ import annotations

import datetime as _dt
import json
import shutil
import sys
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

__all__ = ["BuildReport", "SiteOptions", "build_site"]

#: Written into every output directory; a directory without it is never cleaned.
MARKER = ".geotruth-site"


def _log_stderr(msg: str) -> None:
    print(f"geotruth site: {msg}", file=sys.stderr)


@dataclass
class SiteOptions:
    scores: list[Path]
    out: Path
    tier: str | None = None
    max_examples: int = 5
    registry: Path | None = None  # default: findings/registry.toml of the checkout
    repo_url: str = "https://github.com/abafaboy/geotruth"
    ref: str = "main"
    preview: bool = False
    generated: str | None = None  # the build date shown; fixed for reproducible builds
    verify: bool = True  # re-check every example's exact answer by a second route
    compute_missing: bool = True  # compute exact answers missing from the caches
    clean: bool = True  # empty the output directory first (only a previous site)


@dataclass
class BuildReport:
    out: Path
    tier: str = ""
    pages: int = 0
    libraries: int = 0
    clusters: int = 0
    examples: int = 0
    checks: Counter = field(default_factory=Counter)
    failed_checks: list[str] = field(default_factory=list)
    missing_cases: int = 0
    warnings: list[str] = field(default_factory=list)
    seconds: float = 0.0

    def to_json(self) -> dict[str, Any]:
        """The deterministic part (no timing), for index.json."""
        return {
            "libraries": self.libraries,
            "clusters": self.clusters,
            "examples": self.examples,
            "checks": dict(sorted(self.checks.items())),
            "failed_checks": list(self.failed_checks),
            "missing_cases": self.missing_cases,
            "warnings": list(self.warnings),
        }


def select_examples(records: list[dict[str, Any]], k: int) -> list[dict[str, Any]]:
    """Up to k records of a cluster, one per case: the smallest cases first, preferring a
    new generator variant over a second case of one already shown (deterministic)."""
    seen_ids: set[str] = set()
    uniq = []
    for r in records:
        if r["id"] not in seen_ids:
            seen_ids.add(r["id"])
            uniq.append(r)

    def key(r: dict[str, Any]) -> tuple:
        n = (r.get("tags") or {}).get("n")
        return (n if isinstance(n, int) else 10**9, len(r["id"]), r["id"])

    uniq.sort(key=key)
    out: list[dict[str, Any]] = []
    variants: set[str] = set()
    for r in uniq:
        v = str((r.get("tags") or {}).get("variant", "")).split(".")[0]
        if v not in variants:
            variants.add(v)
            out.append(r)
        if len(out) >= k:
            return out
    for r in uniq:
        if r not in out:
            out.append(r)
        if len(out) >= k:
            break
    return out


def _repro_available() -> bool:
    try:
        from geotruth.cli import discover

        cmd = discover().get("repro")
        return cmd is not None and cmd.error is None
    except Exception:
        return False


def _prepare_out(out: Path, clean: bool) -> None:
    if out.exists():
        if not out.is_dir():
            raise RuntimeError(f"--out {out} exists and is not a directory")
        entries = list(out.iterdir())
        if entries and not (out / MARKER).is_file():
            raise RuntimeError(
                f"--out {out} is not empty and does not hold a site built by geotruth site; "
                "choose an empty or new directory"
            )
        if clean:
            for p in entries:
                if p.is_dir() and not p.is_symlink():
                    shutil.rmtree(p)
                else:
                    p.unlink()
    out.mkdir(parents=True, exist_ok=True)
    (out / MARKER).write_text("built by geotruth site; this directory is emptied on rebuild\n")


def build_site(opts: SiteOptions, log: Callable[[str], None] = _log_stderr) -> BuildReport:
    """Build the site; returns what was built. Raises ``gtsite.load.SiteInputError`` for
    unusable inputs."""
    from geotruth import ENGINE_VERSION, __version__
    from geotruth.harness.manifest import repo_root
    from gtsite import load, pages, triage
    from gtsite.examples import ExampleContext, build_example

    t0 = time.monotonic()
    report = BuildReport(out=opts.out)
    tier, sets = load.load_scoresets(opts.scores, opts.tier, log)
    report.tier = tier
    report.libraries = len(sets)
    root = repo_root()
    reg_path = opts.registry or root / "findings" / "registry.toml"
    registry, reg_problem = load.load_registry(reg_path)
    if reg_problem:
        report.warnings.append(f"triage registry: {reg_problem}")
    try:
        reg_rel = str(reg_path.resolve().relative_to(root.resolve()))
    except ValueError:
        reg_rel = reg_path.name
    generated = opts.generated or _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ctx = pages.SiteContext(
        tier=tier,
        sets=sets,
        registry=registry,
        registry_problem=reg_problem,
        registry_rel=reg_rel,
        generated=generated,
        repo_url=opts.repo_url,
        ref=opts.ref,
        preview=opts.preview,
        max_examples=opts.max_examples,
        package_version=__version__,
        engine_version=ENGINE_VERSION,
        repro_available=_repro_available(),
    )
    for ss in sets:
        for cl in ss.stats.clusters.values():
            k = (ss.target_id, cl.key)
            ctx.cluster_path[k] = pages.cluster_file(cl)
            found = triage.matches(cl, registry)
            if found:
                ctx.cluster_matches[k] = found
    report.clusters = len(ctx.cluster_path)
    for ss in sets:
        if ss.stats.scorer_failures:
            report.warnings.append(f"{ss.target_id}: {ss.stats.scorer_failures} scorer failures")

    # ---------------------------------------------------------------- examples
    chosen: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for ss in sets:
        for cl in ss.stats.sorted_clusters():
            chosen[(ss.target_id, cl.key)] = select_examples(cl.records, opts.max_examples)
    wanted = {r["id"] for recs in chosen.values() for r in recs}
    log(f"{len(sets)} libraries, {report.clusters} failure clusters, {len(wanted)} example cases")
    cases = load.find_cases(sets, wanted, tier)
    report.missing_cases = len(wanted - set(cases))
    # the exact answers each library was graded against: grouped by (engine, expected) version
    files = load.expected_files(sorted({ss.root for ss in sets}))
    want_by_set: dict[str, set[str]] = {}
    group_of: dict[str, tuple[Any, Any]] = {}
    groups: dict[tuple[Any, Any], set[str]] = {}
    for ss in sets:
        vs = ss.stats.version_sets()
        v0 = vs[0] if vs else {}
        key = (v0.get("engine"), v0.get("expected"))
        want_by_set[ss.target_id] = {
            r["id"] for (t, _), recs in chosen.items() if t == ss.target_id for r in recs
        }
        group_of[ss.target_id] = key
        groups.setdefault(key, set()).update(want_by_set[ss.target_id])
    expected_by_group = {k: load.find_expected(files, ids, *k) for k, ids in groups.items()}
    done = 0
    for ss in sets:
        expected = expected_by_group[group_of[ss.target_id]]
        results = load.find_results(ss, want_by_set[ss.target_id])
        run_cmd = str(ss.manifest.get("run", "")) if ss.target is not None else ""
        for cl in ss.stats.sorted_clusters():
            k = (ss.target_id, cl.key)
            exs = []
            for i, rec in enumerate(chosen[k]):
                ectx = ExampleContext(
                    target_id=ss.target_id,
                    lib=ss.lib,
                    run_command=run_cmd,
                    repro_available=ctx.repro_available,
                    repo_root=root,
                    verify=opts.verify,
                    compute_missing=opts.compute_missing,
                    uid=f"ex{i + 1}",
                )
                ex = build_example(
                    ectx,
                    rec,
                    cases.get(rec["id"]),
                    results.get(rec["id"]),
                    expected.get(rec["id"]),
                    f"ex-{i + 1}",
                )
                for c in ex.checks:
                    report.checks[c.status] += 1
                    if c.status == "fail":
                        report.failed_checks.append(
                            f"{ctx.cluster_path[k]}#ex-{i + 1}: {rec['id']}"
                        )
                exs.append(ex)
            ctx.examples[k] = exs
            report.examples += len(exs)
            done += 1
            if done % 100 == 0:
                log(f"examples: {done}/{report.clusters} clusters")

    # ---------------------------------------------------------------- pages
    out_pages = [pages.index_page(ctx), pages.findings_page(ctx), pages.methodology_page(ctx)]
    for ss in sets:
        out_pages.append(pages.library_page(ctx, ss))
        for cl in ss.stats.sorted_clusters():
            out_pages.append(pages.cluster_page(ctx, ss, cl))
    _prepare_out(opts.out, opts.clean)
    pages.write_pages(opts.out, out_pages)
    index = pages.index_json(ctx, report.to_json())
    (opts.out / "index.json").write_text(
        json.dumps(index, indent=1, sort_keys=False) + "\n", encoding="utf-8"
    )
    (opts.out / ".nojekyll").write_text("")
    report.pages = len(out_pages)
    report.seconds = round(time.monotonic() - t0, 1)
    return report
