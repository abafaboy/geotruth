"""Run one adapter target over a corpus tier (DESIGN §4, §5.3).

``geotruth run --lib geos-main [--tier core|full|curated] [--prefix /path/to/build]``

Builds nothing: the target must already be built (its manifest's ``build`` recipe). Writes
``<out>/<target>/<tier>.jsonl`` (result.v2 lines), ``run.json`` (provenance, run.v2) and
``<tier>.stats.json``; see :mod:`geotruth.harness.runner`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HELP = "run one adapter target over a corpus tier (per-operation timeouts, provenance)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--lib",
        default=None,
        metavar="TARGET",
        help="adapter target id from adapters/*/adapter.toml (e.g. geos-main, shapely, "
        "engine-control); a unique prefix works",
    )
    parser.add_argument(
        "--tier",
        choices=("core", "full", "curated", "seed"),
        default=None,
        help="corpus tier from corpus/MANIFEST.json (default core; ignored with --cases)",
    )
    parser.add_argument(
        "--cases", nargs="+", type=Path, default=None, metavar="FILE", help="case files instead"
    )
    parser.add_argument(
        "--prefix",
        default=None,
        help="a maintainer's own build tree (exported as the adapter's build-root variable)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="results directory (default $GEOTRUTH_RESULTS_DIR or ./results)",
    )
    parser.add_argument(
        "--timeout", type=float, default=3.0, help="per-operation timeout in seconds (3)"
    )
    parser.add_argument(
        "--budget",
        type=float,
        default=3600.0,
        help="per-library wall budget in seconds (3600; 0 = none)",
    )
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases")
    parser.add_argument(
        "--no-validate", action="store_true", help="skip schema validation of result lines"
    )
    parser.add_argument("--list", action="store_true", help="list the adapter targets and exit")


def results_dir(arg: Path | None) -> Path:
    import os

    if arg is not None:
        return arg
    env = os.environ.get("GEOTRUTH_RESULTS_DIR")
    return Path(env) if env else Path("results")


def run(args: argparse.Namespace) -> int:
    from geotruth.harness import manifest, runner

    if args.list:
        for t in manifest.targets():
            print(f"{t.id:22s} {t.contract:3s} {t.lib:40s} adapters/{t.dir}")
        return 0
    if not args.lib:
        print("geotruth run: --lib TARGET is required (see --list)", file=sys.stderr)
        return 2
    try:
        target = manifest.find_target(args.lib)
    except KeyError as exc:
        print(f"geotruth run: {exc.args[0]}", file=sys.stderr)
        return 2
    tier = args.tier
    try:
        if args.cases:
            files = list(args.cases)
        else:
            tier = tier or "core"
            files = runner.resolve_tier(tier)
    except FileNotFoundError as exc:
        print(f"geotruth run: {exc}", file=sys.stderr)
        return 2
    opts = runner.RunOptions(
        target=target,
        files=files,
        tier=tier,
        out_dir=results_dir(args.out),
        prefix=args.prefix,
        op_timeout=args.timeout,
        budget_s=args.budget if args.budget and args.budget > 0 else None,
        limit=args.limit,
        validate=not args.no_validate,
    )

    def log(msg: str) -> None:
        print(f"geotruth run: {msg}", file=sys.stderr)

    try:
        report = runner.run_target(opts, log=log)
    except RuntimeError as exc:
        print(f"geotruth run: {exc}", file=sys.stderr)
        return 2
    s = report.stats
    budget = ", budget exhausted" if s["budget_exhausted"] else ""
    print(
        f"{target.id}: {s['cases_run']}/{s['cases_total']} cases in {s['elapsed_s']} s "
        f"({s['watchdog_timeouts']} watchdog timeouts, {s['early_exits']} early exits, "
        f"{s['invalid_lines']} invalid lines{budget})"
    )
    print(f"results: {report.results_path}")
    print(f"provenance: {report.run_path}")
    if s.get("aborted"):
        print(f"geotruth run: aborted: {s['aborted']}", file=sys.stderr)
        return 1
    return 0
