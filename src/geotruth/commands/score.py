"""Score a library's results against the exact answers (DESIGN §4.3).

``geotruth score --lib geos-main [--tier core]`` reads ``<results>/<target>/<tier>.jsonl``
(from ``geotruth run``) with its ``stats.json`` (the case files) and ``run.json``
(versions), takes the expected answers from ``--expected`` or computes them with the
exact engine (cached under ``<results>/_expected/``), and writes
``<tier>.score.jsonl`` (score.v2 records), ``<tier>.summary.json`` and the summary table
``<tier>.summary.txt``, which it also prints.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

HELP = "grade a library's results against the exact answers (score.v2 records + summary)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lib", required=True, metavar="TARGET", help="adapter target id")
    parser.add_argument("--tier", default=None, help="tier name of the results file (core)")
    parser.add_argument(
        "--results", type=Path, default=None, help="results file (default from --lib/--tier)"
    )
    parser.add_argument(
        "--cases", nargs="+", type=Path, default=None, help="case files (default: stats.json)"
    )
    parser.add_argument(
        "--expected",
        type=Path,
        default=None,
        help="expected.v2 answers (default: computed with the engine and cached)",
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help="results directory (default $GEOTRUTH_RESULTS_DIR or ./results)",
    )
    parser.add_argument("--out", type=Path, default=None, help="score records file")
    parser.add_argument(
        "--jobs", type=int, default=min(2, os.cpu_count() or 1), help="worker processes (2)"
    )
    parser.add_argument("--no-overlay", action="store_true", help="skip overlay grading")
    parser.add_argument("--json", action="store_true", help="print the summary as JSON")


def _read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def run(args: argparse.Namespace) -> int:
    from geotruth import ENGINE_VERSION
    from geotruth.commands.run import results_dir
    from geotruth.harness import expected as E
    from geotruth.harness import manifest, runner, score
    from geotruth.numbers import json_loads

    def log(msg: str) -> None:
        print(f"geotruth score: {msg}", file=sys.stderr)

    try:
        target = manifest.find_target(args.lib)
    except KeyError as exc:
        log(exc.args[0])
        return 2
    base = results_dir(args.results_dir)
    tier = args.tier or "core"
    res_path = args.results or base / target.id / f"{tier}.jsonl"
    if not res_path.is_file():
        log(f"no results at {res_path}; run `geotruth run --lib {target.id}` first")
        return 2
    name = res_path.name.removesuffix(".jsonl")
    stats_path = res_path.with_name(f"{name}.stats.json")
    run_path = res_path.with_name("run.json")
    stats = _read_json(stats_path) if stats_path.is_file() else {}
    run_rec = _read_json(run_path) if run_path.is_file() else {}
    files = args.cases or [Path(p) for p in stats.get("case_files", [])]
    if not files:
        log("no case files: pass --cases (the results have no stats.json)")
        return 2
    cases = list(runner.load_cases(files))
    results: dict[str, dict[str, Any]] = {}
    with open(res_path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                rec = json_loads(line)
                results[rec.get("id")] = rec
    if args.expected:
        expected = E.load_expected(args.expected)
        expected_version = next(
            (r["engine"].get("expected_version") for r in expected.values() if r.get("engine")),
            None,
        ) or str(args.expected.name)
    else:
        wanted = [line for cid, line in cases if cid in results]
        expected = E.compute_expected(
            wanted, jobs=args.jobs, cache_dir=base / "_expected", log=log
        )
        expected_version = f"computed-{ENGINE_VERSION}"
    versions = {
        "corpus": str(run_rec.get("corpus_version") or runner.corpus_version(files)),
        "expected": expected_version,
        "engine": ENGINE_VERSION,
        "lib": str(run_rec.get("lib") or target.lib),
    }
    sha = (run_rec.get("adapter") or {}).get("git_sha")
    if sha:
        versions["adapter"] = sha
    ctx = score.ScoreContext(
        target=target, lib_id=target.id, versions=versions, overlay=not args.no_overlay
    )
    records = score.score_results(cases, expected, results, ctx, jobs=args.jobs)
    out = args.out or res_path.with_name(f"{name}.score.jsonl")
    with open(out, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec) + "\n")
    summary = score.summarize(records)
    summary["versions"] = versions
    summary["cases_total"] = len(cases)
    summary["cases_with_results"] = sum(1 for cid, _ in cases if cid in results)
    from geotruth.harness.engine import backends

    summary["exact_backends"] = backends()
    table = score.summary_table(summary)
    res_path.with_name(f"{name}.summary.json").write_text(
        json.dumps(summary, indent=1) + "\n", encoding="utf-8"
    )
    res_path.with_name(f"{name}.summary.txt").write_text(table, encoding="utf-8")
    print(json.dumps(summary, indent=1) if args.json else table, end="" if not args.json else "\n")
    log(f"score records: {out}")
    return 0
