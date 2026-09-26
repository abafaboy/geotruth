"""Minimise a case on which a library disagrees with the exact answer (DESIGN §5.5)."""

from __future__ import annotations

import argparse
import json
import shlex
import sys
from fractions import Fraction
from pathlib import Path

HELP = "delta-debug a failing case down to a minimal one (one adapter call per round)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "case",
        metavar="CASE",
        help="a case file (JSON lines or one JSON object), FILE#ID, or an inline JSON case",
    )
    parser.add_argument("--lib", required=True, help="adapter target id (adapters/*/adapter.toml)")
    parser.add_argument(
        "--field",
        required=True,
        help="the failing field: relate, valid_a, predicates.<name> (or <name>), "
        "overlay.<op> (or area_inter/area_union/area_diff/area_symdiff)",
    )
    parser.add_argument("--id", dest="case_id", default=None, help="case id within CASE")
    parser.add_argument(
        "--kind",
        choices=("value", "area", "error"),
        default=None,
        help="failure kind (default: error if the library reports one for the field, else "
        "area for overlay fields, else value)",
    )
    parser.add_argument(
        "--tol",
        type=float,
        default=1e-6,
        help="area kind: relative area error that counts as a failure (default 1e-6)",
    )
    parser.add_argument("--no-decimals", action="store_true", help="skip decimal shortening")
    parser.add_argument("--max-rounds", type=int, default=200)
    parser.add_argument(
        "--op-timeout",
        type=float,
        default=None,
        help="per-operation timeout passed to adapters that read one (JS, GEOS, Boost)",
    )
    parser.add_argument("--timeout", type=float, default=600.0, help="per adapter call (s)")
    parser.add_argument(
        "--adapter-args", default="", help="extra arguments for the adapter's run wrapper"
    )
    parser.add_argument("-o", "--out", type=Path, default=None, help="write the minimal case")
    parser.add_argument("--new-id", default=None, help="id of the minimal case (ID.min)")
    parser.add_argument("--json", action="store_true", help="print a JSON report")
    parser.add_argument("--quiet", action="store_true")


def run(args: argparse.Namespace) -> int:
    from geotruth.export.answers import geometry_area
    from geotruth.io import geometry_from_json, to_wkt
    from geotruth.minimize import (
        AdapterRunner,
        MinimizeError,
        find_target,
        load_case,
        minimised_record,
        minimize,
    )

    try:
        case = load_case(args.case, args.case_id)
        target = find_target(args.lib)
        runner = AdapterRunner(
            target,
            extra_args=shlex.split(args.adapter_args),
            timeout=args.timeout,
            op_timeout=args.op_timeout,
        )
        log = None if args.quiet or args.json else (lambda s: print(s, file=sys.stderr))
        res = minimize(
            case,
            runner,
            args.field,
            kind=args.kind,
            tol=args.tol,
            decimals=not args.no_decimals,
            max_rounds=args.max_rounds,
            log=log,
        )
    except (MinimizeError, OSError, ValueError, KeyError) as exc:
        print(f"geotruth minimize: {exc}", file=sys.stderr)
        return 2
    rec = minimised_record(case, res, target, new_id=args.new_id)
    if args.out:
        args.out.write_text(json.dumps(rec, separators=(",", ":")) + "\n", encoding="utf-8")
    exact = res.exact.field(res.field) if res.exact else None
    got = None
    if res.result is not None:
        from geotruth.minimize import _error_of, _get

        got = (
            _error_of(res.result, res.field) if res.kind == "error" else _get(res.result, res.field)
        )
    if args.json:
        print(
            json.dumps(
                {
                    "case": rec,
                    "before": {
                        "coordinates": res.before[0],
                        "digits": res.before[1],
                        "objects": res.before[2],
                    },
                    "after": {
                        "coordinates": res.after[0],
                        "digits": res.after[1],
                        "objects": res.after[2],
                    },
                    "rounds": res.rounds,
                    "adapter_calls": res.adapter_calls,
                    "candidates": res.candidates,
                    "seconds": round(res.seconds, 2),
                    "kind": res.kind,
                    "field": res.field,
                    "exact": str(exact) if exact is not None else None,
                    "library": got if not isinstance(got, dict) else "geometry",
                }
            )
        )
        return 0
    print(f"minimal case {rec['id']} ({res.field}, {res.kind}):")
    print(f"  A: {to_wkt(geometry_from_json(res.a))}")
    print(f"  B: {to_wkt(geometry_from_json(res.b))}")
    print(
        f"  size: {res.before[0]} -> {res.after[0]} coordinates, "
        f"{res.before[1]} -> {res.after[1]} digits"
    )
    print(
        f"  {res.rounds} rounds, {res.adapter_calls} adapter calls, "
        f"{res.candidates} candidates, {res.seconds:.1f} s"
    )
    if exact is not None:
        print(f"  exact: {_show(exact)}")
    if isinstance(got, dict):
        try:
            got = f"area {float(geometry_area(geometry_from_json(got)))!r}"
        except Exception:
            got = "a geometry"
    if got is not None:
        print(f"  {target.id}: {got}")
    return 0


def _show(v: object) -> str:
    if isinstance(v, Fraction):
        text = f"{v.numerator}/{v.denominator}" if v.denominator != 1 else str(v.numerator)
        return f"{float(v)!r}" + (f" (= {text})" if len(text) <= 60 else " (rational)")
    return str(v)
