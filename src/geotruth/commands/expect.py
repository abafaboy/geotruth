"""Compute the exact expected answers of a corpus tier (``corpus/expected/``).

``geotruth expect --tier core`` writes ``corpus/expected/core.jsonl`` (one ``expected.v2``
record per case) and its entry in ``corpus/expected/MANIFEST.json``. See
:mod:`geotruth.expect` for what a record holds, the checks behind it and the cache.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HELP = "compute the exact expected answers of a corpus tier (core, curated, full)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--tier",
        action="append",
        choices=("core", "curated", "full"),
        help="tier to compute (repeatable); the answers go to <out-dir>/<tier>.jsonl",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        help="compute the answers of this case file instead of a tier (no manifest entry)",
    )
    parser.add_argument(
        "-o", "--output", type=Path, help="with --cases: where to write (default: stdout)"
    )
    parser.add_argument("--jobs", type=int, default=1, help="worker processes (default 1)")
    parser.add_argument(
        "--corpus", type=Path, default=None, help="corpus directory (default: the repo's)"
    )
    parser.add_argument(
        "--out-dir", type=Path, default=None, help="answer directory (default: corpus/expected)"
    )
    parser.add_argument(
        "--cache",
        type=Path,
        default=None,
        help="cache root (default: $GEOTRUTH_CACHE_DIR, $XDG_CACHE_HOME/geotruth or "
        "~/.cache/geotruth)",
    )
    parser.add_argument("--no-cache", action="store_true", help="neither read nor write the cache")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compute and compare with the existing files; write nothing; exit 1 on a difference",
    )
    parser.add_argument(
        "--no-validate", action="store_true", help="skip the JSON Schema check of every record"
    )
    parser.add_argument("--quiet", action="store_true", help="print only the summary")


def _summary(name: str, stats, log) -> None:
    from geotruth.expect import STATUSES

    counts = ", ".join(f"{s} {stats.status.get(s, 0)}" for s in STATUSES)
    log(
        f"{name}: {stats.cases} cases: {counts}; {stats.cached} from the cache, "
        f"{stats.computed} computed in {stats.wall:.1f} s wall ({stats.cpu:.1f} s in the engine)"
    )
    if stats.computed:
        slow = ", ".join(f"{cid} {secs:.2f} s" for secs, cid in stats.slowest[:3])
        log(f"  slowest: {slow}")
    for cid, status, reason in stats.abstentions[:50]:
        log(f"  {status}: {cid}: {reason}")
    if len(stats.abstentions) > 50:
        log(f"  ... and {len(stats.abstentions) - 50} more abstentions")


def run(args: argparse.Namespace) -> int:
    from geotruth import expect as X
    from geotruth.numbers import require_gmpy2

    def err(msg: str) -> None:
        print(f"geotruth expect: {msg}", file=sys.stderr)

    if not args.tier and args.cases is None:
        err("give --tier core|curated|full (repeatable) or --cases FILE")
        return 2
    if args.tier and args.cases is not None:
        err("--tier and --cases are exclusive")
        return 2
    if args.cases is not None and (args.check or args.out_dir is not None):
        err("--check and --out-dir apply to tiers; with --cases use -o")
        return 2
    if args.output is not None and args.cases is None:
        err("-o applies to --cases; tier answers go to --out-dir")
        return 2
    if args.jobs < 1:
        err("--jobs must be at least 1")
        return 2
    try:
        require_gmpy2()
    except RuntimeError as exc:
        err(str(exc))
        return 2
    validate = not args.no_validate
    if validate:
        try:
            import jsonschema  # noqa: F401
        except ImportError:
            err("the schema check needs jsonschema (pip install 'geotruth[dev]'), or --no-validate")
            return 2

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    progress = None if args.quiet else log
    cache = None if args.no_cache else X.AnswerCache(args.cache or X.default_cache_dir())
    try:
        if args.cases is not None:
            lines, stats = X.compute_lines(
                X.read_case_lines([args.cases]),
                jobs=args.jobs,
                cache=cache,
                validate=validate,
                log=progress,
            )
            text = "".join(x + "\n" for x in lines)
            if args.output:
                args.output.write_text(text, encoding="ascii")
            else:
                sys.stdout.write(text)
            _summary(str(args.cases), stats, log)
            return 0
        status = 0
        for tier in dict.fromkeys(args.tier):
            try:
                res = X.write_tier(
                    tier,
                    corpus=args.corpus,
                    out_dir=args.out_dir,
                    jobs=args.jobs,
                    cache=cache,
                    validate=validate,
                    check_only=args.check,
                    log=progress,
                )
            except X.ExpectedChangedError as exc:
                err(str(exc))
                return 1
            except FileNotFoundError as exc:
                err(str(exc))
                return 2
            _summary(tier, res.stats, log)
            if args.check:
                if res.same_as_file:
                    log(f"  {res.path}: identical")
                else:
                    log(f"  {res.path}: DIFFERS from the computed answers")
                    status = 1
            else:
                log(f"  {res.path}: {'written' if res.written else 'unchanged'}")
        return status
    finally:
        if cache is not None:
            cache.close()
