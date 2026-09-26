"""Print the exact overlay of two geometries (DESIGN §5.1, §2.5).

Operands are given as for ``geotruth relate``: WKT or typed JSON, inline, as ``@FILE``
(WKT, a typed JSON geometry, a case object ``{"a": ..., "b": ...}`` or a JSON-lines file of
cases picked with ``--id``), or ``-`` for standard input. With a single operand that is a
case, both geometries come from it. OP is ``intersection``, ``union``, ``difference``,
``symdifference`` (``symmetric_difference`` is accepted too) or ``all``::

    geotruth overlay "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))" "LINESTRING (-1 1, 3 1)" union
    geotruth overlay @a.wkt @b.json intersection --areal --json
    geotruth overlay @corpus/cases/seed.jsonl all --id tiny-rotation-1-000001 --certify

The result is the non-strict OverlayNG result by default (lines and points of boundary
touches kept; possibly a GeometryCollection), or its regularized polygonal part with
``--areal``. It is printed three ways: the display WKT (coordinates rounded to doubles:
never score against it), the exact rational side-car (typed JSON with ``"n/d"``
ordinates, canonical order) and the exact area. ``--certify`` runs the independent
certificate (DESIGN §2.6).

Exit status: 0 on success; 1 when the engine failed (``engine_error``) or a certificate
failed; 2 for unreadable input or input outside the engine's contract; 3 when the case is
over the engine's budget (``engine_skipped``).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

HELP = "print the exact overlay (intersection, union, difference, symdifference) of two geometries"

EXIT_OK, EXIT_FAILED, EXIT_INPUT, EXIT_SKIPPED = 0, 1, 2, 3

_OP_CHOICES = "intersection, union, difference, symdifference or all"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "a",
        metavar="A",
        help="WKT or typed-JSON geometry, @FILE, or '-' for standard input; a case "
        "object {'a': ..., 'b': ...} supplies both operands",
    )
    parser.add_argument("b", metavar="B", nargs="?", help="the second operand (same forms)")
    parser.add_argument("op", metavar="OP", nargs="?", help=f"the operation: {_OP_CHOICES}")
    parser.add_argument("--id", help="the case to use when a file holds JSON lines of cases")
    parser.add_argument(
        "--areal",
        action="store_true",
        help="the regularized polygonal result (polygon-only clippers) instead of the "
        "non-strict OverlayNG result",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print a JSON object: the result as an expected-answer OverlayResult "
        "(exact side-car, display WKT, area, vertex count); with OP 'all', the "
        "expected-answer 'overlay' block (both variants of every operation)",
    )
    parser.add_argument(
        "--certify",
        action="store_true",
        help="also run the independent certificate (DESIGN §2.6) on every result",
    )
    parser.add_argument("--max-size", type=int, help="budget: cap on n + k (default 200000)")
    parser.add_argument("--max-seconds", type=float, help="budget: wall-clock seconds")
    parser.add_argument("--no-budget", action="store_true", help="no resource limits")


def _split_operands(args: argparse.Namespace) -> tuple[str, str | None, str]:
    """``(A, B or None, OP)`` from the positionals ``A [B] OP``."""
    from geotruth.overlay import normalize_op

    a, b, op = args.a, args.b, args.op
    if op is None:
        if b is None:
            raise ValueError(f"OP is missing: give one of {_OP_CHOICES}")
        b, op = None, b  # "A OP" with a case operand
    if op.strip().lower() == "all":
        return a, b, "all"
    return a, b, normalize_op(op)


def _budget(args: argparse.Namespace) -> Any:
    from dataclasses import replace

    from geotruth.arrangement import DEFAULT_BUDGET

    if args.no_budget:
        return None
    budget = DEFAULT_BUDGET
    if args.max_size is not None:
        budget = replace(budget, max_size=args.max_size)
    if args.max_seconds is not None:
        budget = replace(budget, max_seconds=args.max_seconds)
    return budget


def _describe(geom: Any) -> str:
    n = geom.num_coords
    what = "empty" if geom.is_empty else f"{n} coordinate{'s' * (n != 1)}"
    return f"{geom.geom_type} ({what}; dimension {geom.dimension})"


def _status(results: list[Any]) -> int:
    if any(r.status == "engine_error" for r in results):
        return EXIT_FAILED
    if any(r.status == "engine_skipped" for r in results):
        return EXIT_SKIPPED
    return EXIT_OK


def _area_text(q: Any) -> str:
    from geotruth.numbers import format_rational, rational_to_float

    exact = format_rational(q)
    approx = repr(rational_to_float(q))
    return exact if exact == approx.removesuffix(".0") else f"{exact} (~{approx})"


def run(args: argparse.Namespace) -> int:
    from geotruth import ENGINE_VERSION
    from geotruth.arrangement import InvalidInputError
    from geotruth.commands.relate import InputError, load_operands
    from geotruth.numbers import get_backend
    from geotruth.overlay import OPS, VARIANTS, overlay_all
    from geotruth.validity import validate

    try:
        a_arg, b_arg, op = _split_operands(args)
        case_id, a, b = load_operands(a_arg, b_arg, args.id)
    except (InputError, ValueError) as exc:
        print(f"geotruth overlay: {exc}", file=sys.stderr)
        return EXIT_INPUT

    validity = {"a": validate(a), "b": validate(b)}
    for name, rep in validity.items():
        if not rep.valid:
            print(
                f"geotruth overlay: note: {name.upper()} is invalid ({rep.message}); overlay "
                "is defined for valid input only",
                file=sys.stderr,
            )
    ops = OPS if op == "all" else (op,)
    variant = "areal" if args.areal else "non_strict"
    variants = VARIANTS if op == "all" and args.json else (variant,)
    try:
        res = overlay_all(
            a, b, ops=ops, variants=variants, budget=_budget(args), certify=args.certify
        )
    except InvalidInputError as exc:
        print(f"geotruth overlay: input outside the engine's contract: {exc}", file=sys.stderr)
        return EXIT_INPUT
    results = [r for per in res.values() for r in per.values()]
    status = _status(results)

    if args.json:
        record: dict[str, Any] = {
            "id": case_id,
            "engine": {"version": ENGINE_VERSION, "backend": get_backend()},
            "dimensions": {
                "a": {"dimension": a.dimension, "real_dimension": a.real_dimension},
                "b": {"dimension": b.dimension, "real_dimension": b.real_dimension},
            },
            "validity": {k: v.to_json() for k, v in validity.items()},
        }
        if op == "all":
            record["status"] = next((r.status for r in results if not r.ok), "ok")
            bad = [f"{r.op} ({r.variant}): {r.reason}" for r in results if not r.ok]
            if bad:
                record["reason"] = "; ".join(bad)
            record["overlay"] = {
                o: {v: res[o][v].to_json() for v in VARIANTS}
                for o in OPS
                if all(res[o][v].ok for v in VARIANTS)
            }
        else:
            r = res[op][variant]
            record.update(op=op, variant=variant, status=r.status)
            if r.reason is not None:
                record["reason"] = r.reason
            if r.ok:
                record["result"] = r.to_json()
        if args.certify:
            record["certificates"] = {
                f"{r.op}/{r.variant}": r.certificate.to_json()
                for r in results
                if r.certificate is not None
            }
        print(json.dumps(record, sort_keys=True))
        return status

    print(f"A: {_describe(a)}")
    print(f"B: {_describe(b)}")
    label = "areal" if args.areal else "non-strict"
    for o in ops:
        r = res[o][variant]
        if not r.ok:
            print(f"{o} ({label}): {r.status}: {r.reason}")
            continue
        n = r.num_vertices
        print(f"{o} ({label}): {r.geom_type}, {n} {'vertex' if n == 1 else 'vertices'}")
        print(f"  wkt:   {r.wkt}")
        print(f"  exact: {json.dumps(r.exact)}")
        print(f"  area:  {_area_text(r.area)}")
        if r.certificate is not None:
            print(f"  certificate: {r.certificate.summary()}")
    return status
