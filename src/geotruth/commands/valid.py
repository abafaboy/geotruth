"""Print the exact validity of a geometry, with every defect (DESIGN §5.1)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

HELP = "print the exact validity of a geometry (WKT or JSON) with every defect"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "geometry",
        metavar="A",
        help="WKT or typed-JSON geometry, a file holding one, or '-' for standard input",
    )
    parser.add_argument(
        "--operand",
        choices=("a", "b"),
        default="a",
        help="when the input is a case object {'a': ..., 'b': ...}, which operand to check "
        "(default: a)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print a JSON object: the expected-answer fields plus every defect with its "
        "exact location",
    )


def _read_text(arg: str) -> str:
    if arg == "-":
        return sys.stdin.read()
    if arg.lstrip()[:1] not in "{[" and len(arg) < 4096:
        path = Path(arg)
        try:
            if path.is_file():
                return path.read_text()
        except OSError:
            pass
    return arg


def load_geometry(text: str, operand: str = "a") -> Any:
    """A geometry from WKT, typed JSON (a geometry, a legacy MultiPolygon coordinate list
    or a case object with ``a``/``b``), or the first non-empty line of a JSONL file."""
    from geotruth.io import geometry_from_json, read_wkt
    from geotruth.numbers import json_loads

    stripped = text.strip()
    if stripped[:1] in "{[":
        try:
            obj = json_loads(stripped)
        except ValueError:
            first = next((ln for ln in stripped.splitlines() if ln.strip()), "")
            obj = json_loads(first)
        if isinstance(obj, dict) and "type" not in obj and operand in obj:
            obj = obj[operand]
        return geometry_from_json(obj)
    return read_wkt(stripped)


def run(args: argparse.Namespace) -> int:
    from geotruth.io import WKTError
    from geotruth.validity import validate

    try:
        geom = load_geometry(_read_text(args.geometry), args.operand)
    except (ValueError, TypeError, KeyError, WKTError) as exc:
        print(f"geotruth valid: cannot read the geometry: {exc}", file=sys.stderr)
        return 2
    report = validate(geom)
    if args.json:
        out = report.to_json(detail=True)
        out["geometry_type"] = geom.geom_type
        print(json.dumps(out, sort_keys=True))
        return 0
    print(f"{geom.geom_type}: {'valid' if report.valid else 'INVALID'}")
    if report.valid:
        return 0
    first = report.first
    assert first is not None
    note = {
        "precedence": "GEOS precedence",
        "geos-order": "GEOS precedence and noding order",
        "heuristic": "GEOS precedence; GEOS's pick depends on its noding order, one of "
        + ", ".join(report.first_alternatives),
    }[report.first_basis]
    print(f"first reason ({note}): {first.describe()}")
    print(f"defects ({len(report.defects)}):")
    for d in report.defects:
        print(f"  {d.code:24s} {d.describe()}")
    return 0
