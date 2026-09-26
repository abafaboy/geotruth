"""Build the static results site (DESIGN §6) from score files.

``geotruth site --scores DIR [DIR ...] [--out site/_build]`` reads the score files that
``geotruth score`` wrote (``DIR/<target>/<tier>.score.jsonl``, with the ``run.json``,
``<tier>.stats.json``, result lines and cached exact answers around them), the adapter
manifests and ``findings/registry.toml``, and writes a self-contained static site: a
scoreboard, one page per library, one page per failure cluster with zoomed figures and
reproduction commands, the findings, the methodology, and ``index.json``. No server, no
trackers, no external requests; open ``index.html`` from disk or publish the directory.

The generator lives in the repository's ``site/`` directory (package ``gtsite``), so this
command needs a source checkout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HELP = "build the static results site from score files (scoreboard, clusters, findings)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--scores",
        nargs="+",
        type=Path,
        required=True,
        metavar="DIR",
        help="results directories holding <target>/<tier>.score.jsonl (from geotruth score)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="output directory (default site/_build of the checkout); emptied first if it "
        "holds a previous build, refused if it holds anything else",
    )
    parser.add_argument(
        "--tier", default=None, help="the tier to publish (default core, or the only one found)"
    )
    parser.add_argument(
        "--max-examples",
        type=int,
        default=5,
        metavar="N",
        help="examples per failure cluster (5)",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=None,
        help="triage registry (default findings/registry.toml of the checkout)",
    )
    parser.add_argument(
        "--repo-url",
        default="https://github.com/abafaboy/geotruth",
        help="repository URL for links to files",
    )
    parser.add_argument("--ref", default="main", help="branch or tag for links to files (main)")
    parser.add_argument(
        "--preview",
        action="store_true",
        help="mark every page as an unpublished preview (for maintainers before publication)",
    )
    parser.add_argument(
        "--date",
        default=None,
        help="the build date to print (default: now, UTC); fix it for reproducible output",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the second-route re-check of each example's exact answer (faster)",
    )
    parser.add_argument(
        "--no-compute",
        action="store_true",
        help="never run the engine for exact answers missing from the scorer's caches",
    )


def site_dir() -> Path:
    """The repository's ``site/`` directory (``$GEOTRUTH_SITE_DIR`` overrides)."""
    import os

    env = os.environ.get("GEOTRUTH_SITE_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3] / "site"


def run(args: argparse.Namespace) -> int:
    sdir = site_dir()
    if not (sdir / "gtsite" / "__init__.py").is_file():
        print(
            f"geotruth site: the site generator is not in {sdir} (a source checkout is needed)",
            file=sys.stderr,
        )
        return 2
    if str(sdir) not in sys.path:
        sys.path.insert(0, str(sdir))
    from gtsite import SiteOptions, build_site
    from gtsite.load import SiteInputError

    if args.max_examples < 0:
        print("geotruth site: --max-examples must be >= 0", file=sys.stderr)
        return 2
    opts = SiteOptions(
        scores=list(args.scores),
        out=args.out or sdir / "_build",
        tier=args.tier,
        max_examples=args.max_examples,
        registry=args.registry,
        repo_url=args.repo_url,
        ref=args.ref,
        preview=args.preview,
        generated=args.date,
        verify=not args.no_verify,
        compute_missing=not args.no_compute,
    )
    try:
        report = build_site(opts)
    except (SiteInputError, RuntimeError) as exc:
        print(f"geotruth site: {exc}", file=sys.stderr)
        return 2
    for w in report.warnings:
        print(f"geotruth site: warning: {w}", file=sys.stderr)
    checks = ", ".join(f"{n} {k}" for k, n in sorted(report.checks.items())) or "none"
    print(
        f"site: {report.pages} pages in {report.out} ({report.libraries} libraries, "
        f"{report.clusters} failure clusters, {report.examples} examples; tier {report.tier}; "
        f"{report.seconds} s)"
    )
    print(f"re-checks of the exact answers: {checks}")
    if report.missing_cases:
        print(
            f"geotruth site: {report.missing_cases} example cases not found in the case files",
            file=sys.stderr,
        )
    if report.failed_checks:
        print(
            "geotruth site: an exact answer failed its independent re-check (shown on the "
            "page as 'in doubt'):",
            file=sys.stderr,
        )
        for f in report.failed_checks:
            print(f"  {f}", file=sys.stderr)
        return 1
    return 0
