"""Print the exact DE-9IM matrix and every named predicate of two geometries (DESIGN §5.1).

Operands are WKT or typed JSON, given inline, as ``@FILE`` (a file holding WKT, a typed
JSON geometry, a case object ``{"a": ..., "b": ...}``, or a JSON-lines file of cases
picked with ``--id``), or ``-`` for standard input. With a single operand that is a case,
both geometries come from it::

    geotruth relate "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))" "LINESTRING (1 1, 3 1)"
    geotruth relate @a.wkt @b.json --json
    geotruth relate @corpus/cases/seed.jsonl --id tiny-rotation-1-000001 --dual

Exit status: 0 on success; 1 when ``--dual`` finds the two exact routes disagreeing or
the engine failed (``engine_error``); 2 for unreadable input or input outside the
engine's contract; 3 when the case is over the engine's budget (``engine_skipped``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HELP = "print the exact DE-9IM matrix and named predicates of two geometries (WKT or JSON)"

EXIT_OK, EXIT_DISAGREE, EXIT_INPUT, EXIT_SKIPPED = 0, 1, 2, 3


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "a",
        metavar="A",
        help="WKT or typed-JSON geometry, @FILE, or '-' for standard input; a case "
        "object {'a': ..., 'b': ...} supplies both operands",
    )
    parser.add_argument("b", metavar="B", nargs="?", help="the second operand (same forms)")
    parser.add_argument("--id", help="the case to use when a file holds JSON lines of cases")
    parser.add_argument(
        "--json",
        action="store_true",
        help="print a JSON object: an expected-answer record (schemas/expected.v2) plus "
        "any --pattern/--dual/--explain results",
    )
    parser.add_argument("--pattern", help="also test the matrix against a DE-9IM pattern")
    parser.add_argument(
        "--dual",
        action="store_true",
        help="also compute the independent witness-point route (DESIGN §2.4) and compare",
    )
    parser.add_argument(
        "--explain",
        action="store_true",
        help="name a cell (vertex, edge or face, exact coordinates) realising each entry",
    )
    parser.add_argument("--max-size", type=int, help="budget: cap on n + k (default 200000)")
    parser.add_argument("--max-seconds", type=float, help="budget: wall-clock seconds")
    parser.add_argument("--no-budget", action="store_true", help="no resource limits")


# ============================================================================ input


class InputError(ValueError):
    """The operands could not be read."""


def _read_arg(arg: str, stdin_used: list[bool]) -> tuple[str, str]:
    """``(text, where)`` of an operand argument."""
    if arg == "-":
        if stdin_used[0]:
            raise InputError("standard input ('-') can be used for one operand only")
        stdin_used[0] = True
        return sys.stdin.read(), "standard input"
    if arg.startswith("@"):
        path = Path(arg[1:])
        try:
            return path.read_text(encoding="utf-8"), str(path)
        except OSError as exc:
            raise InputError(f"cannot read {path}: {exc.strerror or exc}") from None
    return arg, "the command line"


def _parse(text: str, where: str, case_id: str | None) -> Any:
    """A geometry, or a case (a dict with ``a`` and ``b`` geometries and an ``id``)."""
    from geotruth.io import GeometryFormatError, case_from_json, geometry_from_json, read_wkt
    from geotruth.numbers import json_loads

    stripped = text.strip()
    if not stripped:
        raise InputError(f"no geometry in {where}")
    if stripped[:1] not in "{[":
        try:
            return read_wkt(stripped)
        except ValueError as exc:
            raise InputError(f"bad WKT in {where}: {exc}") from None
    lines = [ln for ln in stripped.splitlines() if ln.strip()]
    try:
        objs = [json_loads(stripped)]
    except ValueError:
        try:
            objs = [json_loads(ln) for ln in lines]  # JSON lines
        except ValueError as exc:
            raise InputError(f"bad JSON in {where}: {exc}") from None
    if len(objs) > 1 or case_id is not None:
        cases = [o for o in objs if isinstance(o, dict) and "a" in o and "b" in o]
        if case_id is not None:
            cases = [o for o in cases if str(o.get("id")) == case_id]
            if not cases:
                raise InputError(f"no case with id {case_id!r} in {where}")
        elif len(cases) != 1:
            raise InputError(f"{where} holds {len(objs)} records: pick one with --id")
        objs = cases[:1]
    obj = objs[0]
    try:
        if isinstance(obj, dict) and "type" not in obj and "a" in obj and "b" in obj:
            case = case_from_json({"id": "cli", **obj})
            return {"id": case.id, "a": case.a, "b": case.b}
        return geometry_from_json(obj)
    except (GeometryFormatError, ValueError, TypeError) as exc:
        raise InputError(f"bad geometry in {where}: {exc}") from None


def load_operands(a: str, b: str | None, case_id: str | None = None) -> tuple[str, Any, Any]:
    """``(case id, A, B)`` from the command-line operands (see the module docstring)."""
    stdin_used = [False]
    first = _parse(*_read_arg(a, stdin_used), case_id)
    if b is None:
        if not isinstance(first, dict):
            raise InputError("B is missing (a single operand must be a case with 'a' and 'b')")
        return first["id"], first["a"], first["b"]
    if isinstance(first, dict):
        raise InputError("A is a case holding two operands; give it alone, without B")
    second = _parse(*_read_arg(b, stdin_used), case_id)
    if isinstance(second, dict):
        raise InputError("B is a case holding two operands, not a geometry")
    return "cli", first, second


# ============================================================================ output


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


def _grid(matrix: str) -> list[str]:
    rows = ["      I  B  E"]
    for i, r in enumerate("IBE"):
        rows.append(f"   {r}  " + "  ".join(matrix[3 * i : 3 * i + 3]))
    return rows


def _describe(geom: Any) -> str:
    n = geom.num_coords
    what = "empty" if geom.is_empty else f"{n} coordinate{'s' * (n != 1)}"
    return f"{geom.geom_type} ({what}; real dimension {geom.real_dimension})"


def run(args: argparse.Namespace) -> int:
    from geotruth import ENGINE_VERSION
    from geotruth.arrangement import InvalidInputError
    from geotruth.numbers import get_backend
    from geotruth.predicates import PREDICATE_NAMES, relate_pattern, validate_pattern
    from geotruth.relate import cell_realizers, describe_cell, relate
    from geotruth.validity import validate

    try:
        case_id, a, b = load_operands(args.a, args.b, args.id)
        if args.pattern is not None:
            validate_pattern(args.pattern)
    except (InputError, ValueError) as exc:
        print(f"geotruth relate: {exc}", file=sys.stderr)
        return EXIT_INPUT

    validity = {"a": validate(a), "b": validate(b)}
    for name, rep in validity.items():
        if not rep.valid:
            print(
                f"geotruth relate: note: {name.upper()} is invalid ({rep.message}); relate is "
                "defined for valid input only",
                file=sys.stderr,
            )
    try:
        res = relate(a, b, budget=_budget(args), keep_arrangement=args.explain)
    except InvalidInputError as exc:
        print(f"geotruth relate: input outside the engine's contract: {exc}", file=sys.stderr)
        return EXIT_INPUT

    status = EXIT_OK
    if res.status == "engine_skipped":
        status = EXIT_SKIPPED
    elif res.status != "ok":
        status = EXIT_DISAGREE

    witness = None
    if args.dual and res.ok:
        from geotruth.relate_witness import relate_witness

        witness = relate_witness(a, b).matrix
        if witness != res.matrix:
            status = EXIT_DISAGREE

    record: dict[str, Any] = {
        "id": case_id,
        "engine": {"version": ENGINE_VERSION, "backend": get_backend()},
        **res.to_json(),
        "validity": {k: v.to_json() for k, v in validity.items()},
    }
    if res.ok and args.pattern is not None:
        record["pattern"] = {
            "pattern": args.pattern,
            "matches": relate_pattern(res.matrix, args.pattern),
        }
    if witness is not None:
        record["witness"] = {"relate": witness, "agree": witness == res.matrix}
    if res.ok and args.explain and res.arrangement is not None:
        record["cells"] = {
            name: {"dim": c.dim, "cell": describe_cell(res.arrangement, c)}
            for name, c in cell_realizers(res.arrangement, res.matrix).items()
        }

    if args.json:
        print(json.dumps(record, sort_keys=True))
        return status

    print(f"A: {_describe(a)}")
    print(f"B: {_describe(b)}")
    if not res.ok:
        print(f"status: {res.status}: {res.reason}")
        return status
    print(f"relate: {res.matrix}")
    for line in _grid(res.matrix):
        print(line)
    if "cells" in record:
        for name, info in record["cells"].items():
            print(f"   {name} = {info['dim']}: {info['cell']}")
    if "pattern" in record:
        print(f"pattern {args.pattern}: {str(record['pattern']['matches']).lower()}")
    print("predicates:")
    values = res.predicate_values or {}
    for name in PREDICATE_NAMES:
        v = values[name]
        line = f"  {name:11s} {str(v.value).lower()}"
        if v.convention:
            line += f"   (convention; alternative {str(v.alternative).lower()}: {v.note})"
        print(line)
    if witness is not None:
        verdict = "agrees" if witness == res.matrix else "DISAGREES (an engine bug)"
        print(f"witness route: {witness} {verdict}")
    return status
