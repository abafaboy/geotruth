"""Export cases with their exact answers to a library's own test format (DESIGN §5.6)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HELP = "export cases to JTS/GEOS XML, Boost, Clipper2, geo (Rust) or pytest tests"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    from geotruth.export import FORMATS

    parser.add_argument("--format", "-f", required=True, choices=sorted(FORMATS))
    parser.add_argument(
        "cases",
        metavar="CASES",
        nargs="*",
        help="case files (JSON lines, v2 or FORMAT-v1); FILE#ID selects one case",
    )
    parser.add_argument("--id", action="append", default=[], help="export only these ids")
    parser.add_argument("--family", default=None, help="export only this family")
    parser.add_argument("--limit", type=int, default=None, help="at most this many cases")
    parser.add_argument(
        "--rel",
        type=float,
        default=1e-6,
        help="relative area tolerance of the area checks (default 1e-6, as harness/compare.py)",
    )
    parser.add_argument("--comment", default="", help="an extra line for the file header")
    parser.add_argument(
        "--run",
        default="",
        help="jts-xml only: run the written files with these runners (comma-separated: jts, "
        "jts-old, geos) and print their summaries; exit 1 if any test fails",
    )
    parser.add_argument(
        "--build-runners",
        action="store_true",
        help="build the JTS TestRunner and GEOS xmltester under $GEOTRUTH_BUILD_DIR first",
    )
    parser.add_argument(
        "-o",
        "--out",
        type=Path,
        default=None,
        help="output file (several files get .partN before the extension); default stdout",
    )


def _read(spec: str) -> list[dict]:
    path, _, frag = spec.partition("#")
    recs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                recs.append(json.loads(line))
    if frag:
        recs = [r for r in recs if r.get("id") == frag]
        if not recs:
            raise ValueError(f"no case {frag!r} in {path}")
    return recs


def _run_runners(paths: list[Path], names: list[str]) -> int:
    from geotruth.export import runners

    bad = 0
    for path in paths:
        for name in names:
            try:
                if name == "geos":
                    res = runners.run_geos(path)
                elif name in ("jts", "jts-old"):
                    res = runners.run_jts(path, relate="old" if name == "jts-old" else "ng")
                else:
                    print(f"geotruth export: unknown runner {name!r}", file=sys.stderr)
                    return 2
            except RuntimeError as exc:
                print(f"geotruth export: {exc}", file=sys.stderr)
                return 2
            print(
                f"{path.name}: {res.runner}: {res.tests} tests, {res.passed} passed, "
                f"{res.failed} failed, {res.exceptions} exceptions"
            )
            for f in res.failures:
                print(f"    {f}")
            bad += not res.ok
    return 1 if bad else 0


def run(args: argparse.Namespace) -> int:
    from geotruth.export import export_records

    if args.build_runners:
        from geotruth.export import runners

        print(f"JTS TestRunner: {runners.build_jts_testrunner()}", file=sys.stderr)
        print(f"GEOS xmltester: {runners.build_geos_xmltester()}", file=sys.stderr)
        if not args.cases:
            return 0
    if not args.cases:
        print("geotruth export: no CASES given", file=sys.stderr)
        return 2

    try:
        records = [r for spec in args.cases for r in _read(spec)]
    except (OSError, ValueError) as exc:
        print(f"geotruth export: {exc}", file=sys.stderr)
        return 2
    if args.id:
        want = set(args.id)
        records = [r for r in records if r.get("id") in want]
    if args.family:
        records = [r for r in records if r.get("family") == args.family]
    if args.limit is not None:
        records = records[: args.limit]
    if not records:
        print("geotruth export: no cases selected", file=sys.stderr)
        return 2
    files = export_records(records, args.format, rel=args.rel, comment=args.comment)
    skipped = sorted({s for f in files for s in f.skipped})
    if args.out is None:
        if len(files) > 1:
            print(f"geotruth export: this export needs {len(files)} files; use -o", file=sys.stderr)
            return 2
        sys.stdout.write(files[0].text)
    else:
        written = []
        for f in files:
            path = args.out.with_name(args.out.stem + f.suffix + args.out.suffix)
            path.write_text(f.text, encoding="utf-8")
            written.append(path)
            print(f"wrote {path}", file=sys.stderr)
    if skipped:
        print(
            f"geotruth export: {len(skipped)} cases skipped (outside what the format "
            f"can express): {', '.join(skipped[:10])}{' ...' if len(skipped) > 10 else ''}",
            file=sys.stderr,
        )
    if args.run:
        if args.format != "jts-xml" or args.out is None:
            print("geotruth export: --run needs --format jts-xml and -o", file=sys.stderr)
            return 2
        return _run_runners(written, [r for r in args.run.split(",") if r])
    return 0
